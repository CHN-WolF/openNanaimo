'''Derive a candidate CN QS table carrying the first story chapters' texts.

QT references a description text, a reward text and, through the action script,
one text per dialogue line. None of them exist in the shipped CN table, so the
chapter rows stay blank until this candidate is installed alongside the QT one.
Nothing is installed here: the outputs are a fresh QS._D31 candidate and a
provenance report, and both `activation_allowed` and `runtime_acceptance` stay
false.

Inputs:
  client QS._D31        shipped table, read through the shared AES container
  catalog.json          isolated KR derivation (quest texts, chapter order)
  story_localization    reviewed CN text for every referenced id
  sibling story_terms.json  optional bounded task-panel display projections

Rules:
  - an id already present in the shipped table is never overwritten; it is
    recorded as reused (the monk texts 6000..6011 belong to their own owner)
  - every added text must pass the project's own QS validator: GBK encodable,
    no delimiter or line break, identical format tokens, identical '^&' count
  - unreviewed translations are refused unless --allow-unreviewed is passed
'''
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_story_catalog as catalog_validator  # noqa: E402
import story_qt_patch as shared  # noqa: E402  (AES container and field helpers)

SCHEMA = 'openNanaimo.story-qs-patch.v1'
CN_QS_NAME = 'QS._D31'
CN_ENCODING = 'gbk'
QS_FIRST, QS_LAST = 3000, 3138
# sub_A5D9A0 copies each task-panel line with strcpy_s(dst, 31, text).
TASK_LINE_BYTES = 30
GATES = shared.GATES
FOLLOWUPS = (
    'the QT candidate must reference exactly these description and reward ids',
    'action._S1 must reference the speech ids installed here',
    'the client keeps its own copy of QS; install both tables in one transaction',
    'rewards stay unmapped: 12 source triples still await review',
)


def parse_qs(text: str) -> dict:
    fields = text.split('#')
    shared.require(len(fields) >= 4 and fields[0] == 'NANA_QUEST_TEXT', 'Invalid QS header')
    count = shared.uint(fields[2], 'QS entry count')
    at = 3
    entries = []
    seen = set()
    for _ in range(count):
        shared.require(at + 2 <= len(fields), 'Truncated QS table')
        entry_id = shared.uint(fields[at], 'QS id')
        shared.require(entry_id not in seen, 'Duplicate QS id %d' % entry_id)
        seen.add(entry_id)
        entries.append((entry_id, fields[at + 1]))
        at += 2
    shared.require(fields[at:] == [''], 'Unconsumed QS tail')
    return dict(header=fields[:3], entries=entries)


def serialize_qs(table: dict) -> str:
    fields = list(table['header'])
    fields[2] = str(len(table['entries']))
    for entry_id, value in table['entries']:
        fields.append(str(entry_id))
        fields.append(value)
    fields.append('')
    return '#'.join(fields)


def load_localization(path: Path) -> dict:
    data = json.loads(path.read_text('utf-8'))
    shared.require(data.get('schema') == 'openNanaimo.chapter-story-localization.v1',
                   'Invalid localization schema')
    shared.require(data.get('activation_allowed') is False
                   and data.get('runtime_acceptance') is False,
                   'Localization manifest must advertise inactive publication')
    texts = {int(row['qs_id']): row for row in data['texts']}
    shared.require(len(texts) >= 1 and len(texts) == len(data['texts']),
                   'Localization text ids are missing or repeated')
    terms_path = path.with_name('story_terms.json')
    terms = json.loads(terms_path.read_text('utf-8')) if terms_path.exists() else {}
    panel = {int(uid): text for uid, text in terms.get('task_panel_texts', {}).items()}
    shared.require(set(panel) <= set(texts), 'Task panel projection has no source text')
    return dict(texts=texts, task_panel_texts=panel, sha256=shared.digest(path.read_bytes()),
                task_panel_input=dict(name='story_terms', size=terms_path.stat().st_size,
                    sha256=shared.digest(terms_path.read_bytes())) if terms_path.exists() else None)


def task_panel_text(text_id: int, text: str, origin: dict, chapter: dict,
                    projections: dict) -> str:
    if origin['kind'] == 'speech':
        shared.require(text_id not in projections, 'Task panel projection cannot replace speech')
        return text
    display = projections.get(text_id, text)
    shared.require(isinstance(display, str) and display
                   and not any(c in display for c in ('#', '\0', '\r', '\n', '%')),
                   'Unsafe task panel text %d' % text_id)
    lines = display.split('^&')
    shared.require(all(line and len(line.encode(CN_ENCODING)) <= TASK_LINE_BYTES for line in lines),
                   'Task panel text %d exceeds 30 GBK bytes per line' % text_id)
    if origin['kind'] == 'reward':
        # sub_A5C310 stops after QT reward_count, even if QS has more lines.
        shared.require(len(lines) <= len(chapter['rewards']),
                       'Task panel text %d exceeds QT reward line count' % text_id)
    return display


def load_catalog(path: Path) -> dict:
    data = json.loads(path.read_text('utf-8'))
    shared.require(data.get('schema') == 'openNanaimo.story-catalog.v1',
                   'Invalid story catalog schema')
    chapters = {row['id']: row for row in data['chapters']}
    bindings = data['bindings']
    shared.require(len(chapters) == 16, 'Story catalog chapter coverage differs')
    shared.require(isinstance(bindings, list) and bindings, 'Story catalog bindings are empty')
    return dict(chapters=chapters, bindings=bindings, sha256=shared.digest(path.read_bytes()))


def select_chapters(range_text: str) -> list[int]:
    return shared.select_chapters(range_text)


def chapter_ids(chapter: dict) -> tuple[int, int]:
    description = int(chapter['header'][9])
    reward = int(chapter['reward_text_id'])
    shared.require(QS_FIRST <= description <= QS_LAST and QS_FIRST <= reward <= QS_LAST,
                   'Chapter text id outside the candidate range')
    return description, reward


def collect_references(catalog: dict, chapters: list[int]) -> dict:
    needed = {}
    for episode in chapters:
        quest_id = 73_000_000 + episode - 1
        chapter = catalog['chapters'].get(quest_id)
        shared.require(chapter is not None, 'Missing catalog chapter %d' % quest_id)
        description, reward = chapter_ids(chapter)
        needed[description] = dict(kind='description', quest_id=quest_id)
        needed[reward] = dict(kind='reward', quest_id=quest_id)
        linked = {int(value) for value in chapter['objective_ids']}
        for binding in catalog['bindings']:
            if binding['quest_id'] != quest_id:
                continue
            shared.require(int(binding['objective_id']) in linked,
                           'Binding references an unlinked objective')
            attributes = binding['attributes']
            if attributes.get('type') != 'SPEECH':
                continue
            text_id = shared.uint(attributes['string_uid'], 'speech text id')
            needed.setdefault(text_id, dict(kind='speech', quest_id=quest_id))
    return needed


def plan(qs_text: str, catalog: dict, localization: dict, chapters: list[int],
         allow_unreviewed: bool) -> dict:
    table = parse_qs(qs_text)
    shipped = {entry_id for entry_id, _ in table['entries']}
    needed = collect_references(catalog, chapters)
    ids = sorted(needed)
    to_add = [text_id for text_id in ids if text_id not in shipped]
    shared.require(all(QS_FIRST <= text_id <= QS_LAST for text_id in to_add),
                   'Text id outside the candidate range')

    added, reused, provenance = [], [], []
    reviewed = True
    for text_id in ids:
        origin = needed[text_id]
        row = localization['texts'].get(text_id)
        if text_id in shipped:
            # Shipped ids keep their owner: the monk texts 6000..6011 are
            # localized elsewhere and must never be rewritten from here.
            reused.append(text_id)
            provenance.append(dict(qs_id=text_id, kind=origin['kind'], quest_id=origin['quest_id'],
                                   disposition='reuse-shipped',
                                   localized_elsewhere=row is None))
            continue
        shared.require(row is not None, 'No localization row for text %d' % text_id)
        reviewed = reviewed and bool(row['approved'])
        if not row['approved'] and not allow_unreviewed:
            raise ValueError('Unreviewed text %d; pass --allow-unreviewed' % text_id)
        raw = catalog_validator.validate_translation(row['source_ko'], row['translation_zh'])
        shared.require(raw.decode(CN_ENCODING) == row['translation_zh'],
                       'Text %d does not survive a GBK round trip' % text_id)
        display = task_panel_text(text_id, row['translation_zh'], origin,
                                  catalog['chapters'][origin['quest_id']],
                                  localization.get('task_panel_texts', {}))
        added.append((text_id, display))
        provenance.append(dict(qs_id=text_id, kind=origin['kind'], quest_id=origin['quest_id'],
                               disposition='add', approved=bool(row['approved']),
                               bytes=len(display.encode(CN_ENCODING)),
                               task_panel_projection=display != row['translation_zh']))

    entries = list(table['entries']) + added
    candidate = dict(header=[table['header'][0], table['header'][1], str(len(entries))],
                     entries=entries)
    shipped_bytes = [len(value.encode(CN_ENCODING)) for _, value in table['entries']]
    added_bytes = [item for item in provenance if item['disposition'] == 'add']
    by_kind = {}
    for item in added_bytes:
        by_kind[item['kind']] = max(by_kind.get(item['kind'], 0), item['bytes'])
    return dict(table=table, candidate=candidate, added=added, reused=reused,
                provenance=provenance, review_complete=reviewed,
                size_profile=dict(max_added=max((item['bytes'] for item in added_bytes), default=0),
                                  max_shipped=max(shipped_bytes),
                                  by_kind=by_kind,
                                  total_added=sum(item['bytes'] for item in added_bytes)))


def verify_appended(candidate: dict, table: dict, added: list[tuple[int, str]]) -> None:
    shared.require(len(candidate['entries']) == len(table['entries']) + len(added),
                   'QS entry growth differs')
    shared.require(candidate['entries'][:len(table['entries'])] == table['entries'],
                   'Existing QS entry changed')
    shared.require([entry_id for entry_id, _ in candidate['entries'][len(table['entries']):]]
                   == [entry_id for entry_id, _ in added], 'Appended id order differs')
    for entry_id, value in candidate['entries']:
        shared.require(isinstance(value, str) and value, 'Empty QS text')
        value.encode(CN_ENCODING, errors='strict')
        shared.require('#' not in value and not any(c in value for c in ('\r', '\n', '\0')),
                       'Unsafe QS text %d' % entry_id)


def build_report(inputs: list[dict], planned: dict, chapters: list[int],
                 candidate_bytes: bytes) -> dict:
    return dict(schema=SCHEMA, status='candidate-only', kind='build',
                activation_allowed=False, runtime_acceptance=False,
                unresolved_gates=list(GATES), inputs=inputs,
                chapter_range=[chapters[0], chapters[-1]],
                counts=dict(added=len(planned['added']), reused=len(planned['reused']),
                            entries=len(planned['candidate']['entries'])),
                review_complete=planned['review_complete'],
                size_profile=planned['size_profile'],
                provenance=planned['provenance'],
                output=dict(name=CN_QS_NAME, size=len(candidate_bytes),
                            sha256=shared.digest(candidate_bytes)),
                required_followups=list(FOLLOWUPS))


def derive(client: Path, catalog_path: Path, localization_path: Path, chapters: list[int],
           allow_unreviewed: bool) -> dict:
    raw = (client / CN_QS_NAME).read_bytes()
    catalog = load_catalog(catalog_path)
    localization = load_localization(localization_path)
    planned = plan(shared.decrypt_qt(raw), catalog, localization, chapters, allow_unreviewed)
    verify_appended(planned['candidate'], planned['table'], planned['added'])
    candidate_bytes = shared.encrypt_qt(serialize_qs(planned['candidate']))
    reparsed = parse_qs(shared.decrypt_qt(candidate_bytes))
    shared.require(reparsed['entries'] == planned['candidate']['entries'],
                   'Candidate entries differ after re-read')
    shared.require(reparsed['header'] == planned['candidate']['header'],
                   'Candidate header differs after re-read')
    inputs = [dict(name=CN_QS_NAME, size=len(raw), sha256=shared.digest(raw)),
              dict(name='catalog', size=catalog_path.stat().st_size, sha256=catalog['sha256']),
              dict(name='localization', size=localization_path.stat().st_size,
                   sha256=localization['sha256'])]
    if localization['task_panel_input'] is not None:
        inputs.append(localization['task_panel_input'])
    report = (json.dumps(build_report(inputs, planned, chapters, candidate_bytes),
                         ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    return {CN_QS_NAME: candidate_bytes, 'qs-patch-report.json': report}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'verify'))
    parser.add_argument('--client', type=Path, required=True, help='Client root containing QS._D31')
    parser.add_argument('--catalog', type=Path, required=True, help='Derived KR story catalog.json')
    parser.add_argument('--localization', type=Path, required=True,
                        help='manifest/story_localization.json')
    parser.add_argument('--chapters', default='1-4', help='Episode range FIRST-LAST, must start at 1')
    parser.add_argument('--allow-unreviewed', action='store_true',
                        help='Permit unreviewed text; the report records the gap')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    chapters = select_chapters(args.chapters)
    payload = derive(args.client, args.catalog, args.localization, chapters, args.allow_unreviewed)
    if args.command == 'build':
        shared.require(not args.output.exists(), 'Output already exists; preserve prior results')
        shared.require(args.output.resolve() != args.client.resolve(),
                       'Output must not be the client root')
        for guarded in (args.catalog.parent, args.localization.parent):
            shared.require(args.output.resolve() != guarded.resolve(),
                           'Output must not be the directory holding the inputs')
        args.output.mkdir(parents=True)
        for name, raw in payload.items():
            (args.output / name).write_bytes(raw)
        built = json.loads(payload['qs-patch-report.json'].decode('utf-8'))
        print(json.dumps(dict(output=str(args.output), status='candidate-only',
                              activation_allowed=False, runtime_acceptance=False,
                              counts=built['counts'], review_complete=built['review_complete']),
                         indent=2))
        return 0
    shared.require({path.name for path in args.output.iterdir()} == set(payload),
                   'Output coverage differs')
    for name, raw in payload.items():
        shared.require((args.output / name).read_bytes() == raw, 'Derived output differs: ' + name)
    print(json.dumps(dict(status='rederived-exact', activation_allowed=False,
                          runtime_acceptance=False), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
