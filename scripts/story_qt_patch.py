'''Derive a candidate CN QT table carrying the first story chapters.

The KR chapter rows come from an isolated, already derived catalog; the CN
table is read from the user-owned client. Nothing is installed: the outputs are
a fresh QT._D30 candidate and a provenance report. Slots this tool cannot prove
are copied from an explicit reference quest or left at the shipped CN default,
never invented, and every one of them is listed in the report. Both
`activation_allowed` and `runtime_acceptance` stay false.

Layout evidence:
  CN objective row = 27 fields. Fields 0..16 are read by the adapter parser
  (manifest/QuestCatalog.cs); fields 17..26 are zero in all 357 shipped rows.
  CN quest header = 22 fields. Id, type, title and description-QS positions are
  proven by the same parser; the remaining positions are not.

KR -> CN mapping this tool applies (everything else is refused):
  objective  0,1,2..16 from the KR row (name replaced by the reviewed CN text)
  objective 17..26  '0', plus the action script UID placed in --script-slot
  quest      0 id, 1 type, 4 title, 7 description QS, 8/9/10 from KR 10/11/12,
             11..21 from KR 13..23
  quest      2 next catalogue index, 3/5/6 from --reference-quest
'''
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_hero_dragon as crypto  # noqa: E402  (shared AES container)

SCHEMA = 'openNanaimo.story-qt-patch.v1'
CN_QT_NAME = 'QT._D30'
CN_ENCODING = 'gbk'
CN_OBJECTIVE_WIDTH = 27
CN_OBJECTIVE_COUNT = 357
CN_QUEST_HEAD = 22
CN_QUEST_COUNT = 217
KR_OBJECTIVE_WIDTH = 26
KR_QUEST_HEAD = 24
TAIL_FIRST, TAIL_LAST = 17, 26
SCRIPT_SLOT_MIN, SCRIPT_SLOT_MAX = 17, 26
OBJECTIVE_TYPE_DIALOGUE, OBJECTIVE_TYPE_DUNGEON, OBJECTIVE_TYPE_MONK = 39, 40, 1
EXPECTED_KINDS = ((39, 40, 39), (39, 40, 39, 1))
# CN quest header positions taken verbatim from --reference-quest.
TEMPLATE_QUEST_SLOTS = (3, 5, 6)
# KR quest header positions that the CN header does not consume.
UNUSED_KR_SLOTS = (2, 3, 4, 6, 7, 8)
KR_DESC_SLOT = 9
GATES = (
    'cn-story-executor-and-scene-trigger',
    'cn-dialogue-confirmation-protocol',
    'type40-settlement-condition',
    'first-grant-and-legacy-save-policy',
    'cn-reward-mapping-and-atomic-transaction',
    'npc-portrait-resource-mapping',
    'reviewed-gbk-localization',
    'transactional-client-install-and-rollback',
    'original-client-first-chapter-acceptance',
)
FOLLOWUPS = (
    'QS patch must install the referenced description, reward and objective texts',
    'action._S1 patch must install SCRIPT 10000..10007 before any dialogue can fire',
    'the adapter OfficialObjectiveCount/OfficialQuestCount constants must accept the new totals',
    'the CN client needs C5A1/C5A2 handling before a dialogue confirmation can complete',
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def uint(value, label):
    require(isinstance(value, str) and value.isdigit(), 'Not an unsigned integer: ' + label)
    require(int(value) <= 0xFFFFFFFF, 'Integer out of range: ' + label)
    return int(value)


def sint(value, label):
    require(isinstance(value, str) and value.lstrip('-').isdigit() and value != '-',
            'Not a signed integer: ' + label)
    return int(value)


def gbk(value, label):
    require(isinstance(value, str) and value.strip(), 'Empty text: ' + label)
    require(not any(c in value for c in ('#', '\0', '\r', '\n')), 'Unsafe QT delimiter: ' + label)
    return value.encode(CN_ENCODING, errors='strict').decode(CN_ENCODING)


def decrypt_qt(raw: bytes) -> str:
    return crypto.decrypt(raw, crypto.CN_KEY).decode(CN_ENCODING)


def encrypt_qt(text: str) -> bytes:
    from Crypto.Cipher import AES
    raw = text.encode(CN_ENCODING)
    padding = 16 - len(raw) % 16
    return AES.new(crypto.CN_KEY, AES.MODE_CBC, bytes(16)).encrypt(raw + bytes([padding]) * padding)


def parse_qt(text: str) -> dict:
    fields = text.split('#')
    require(len(fields) >= 4 and fields[0] == 'QUEST', 'Invalid QT header')
    at = 3
    objectives = []
    for _ in range(uint(fields[2], 'QT objective count')):
        require(at + CN_OBJECTIVE_WIDTH <= len(fields), 'Truncated QT objective table')
        objectives.append(fields[at:at + CN_OBJECTIVE_WIDTH])
        at += CN_OBJECTIVE_WIDTH
    require(at < len(fields), 'Missing QT quest count')
    quests = []
    quest_count = uint(fields[at], 'QT quest count')
    at += 1
    for _ in range(quest_count):
        require(at + CN_QUEST_HEAD <= len(fields), 'Truncated QT quest header')
        header = fields[at:at + CN_QUEST_HEAD]
        at += CN_QUEST_HEAD
        require(at < len(fields), 'Truncated QT linked objective count')
        linked = uint(fields[at], 'QT linked objective count')
        at += 1
        require(at + linked * 2 + 2 <= len(fields), 'Truncated QT linked objective arrays')
        ids = fields[at:at + linked]
        values = fields[at + linked:at + 2 * linked]
        at += 2 * linked
        reward_text = fields[at]
        at += 1
        reward_count = uint(fields[at], 'QT reward count')
        at += 1
        require(at + reward_count * 3 <= len(fields), 'Truncated QT rewards')
        rewards = [fields[at + 3 * i:at + 3 * i + 3] for i in range(reward_count)]
        at += reward_count * 3
        quests.append(dict(header=header, objective_ids=ids, objective_values=values,
                           reward_text_id=reward_text, rewards=rewards))
    require(fields[at:] == [''], 'Unconsumed QT tail')
    return dict(header=fields[:3], objectives=objectives, quests=quests)


def serialize_qt(table: dict) -> str:
    fields = list(table['header'])
    fields[2] = str(len(table['objectives']))
    for row in table['objectives']:
        require(len(row) == CN_OBJECTIVE_WIDTH, 'Objective row width differs')
        fields.extend(row)
    fields.append(str(len(table['quests'])))
    for quest in table['quests']:
        require(len(quest['header']) == CN_QUEST_HEAD, 'Quest header width differs')
        fields.extend(quest['header'])
        fields.append(str(len(quest['objective_ids'])))
        fields.extend(quest['objective_ids'])
        fields.extend(quest['objective_values'])
        fields.append(quest['reward_text_id'])
        fields.append(str(len(quest['rewards'])))
        for reward in quest['rewards']:
            require(len(reward) == 3, 'Reward triple width differs')
            fields.extend(reward)
    fields.append('')
    return '#'.join(fields)


def load_localization(path: Path) -> dict:
    data = json.loads(path.read_text('utf-8'))
    require(data.get('schema') == 'openNanaimo.chapter-story-localization.v1',
            'Invalid localization schema')
    require(data.get('activation_allowed') is False and data.get('runtime_acceptance') is False,
            'Localization manifest must advertise inactive publication')
    titles = {row['quest_id']: row for row in data['titles']}
    names = {row['objective_id']: row for row in data['objective_names']}
    require(len(titles) == 16 and len(names) == 52, 'Localization coverage differs')
    return dict(titles=titles, names=names, sha256=digest(path.read_bytes()))


def load_catalog(path: Path) -> dict:
    data = json.loads(path.read_text('utf-8'))
    require(data.get('schema') == 'openNanaimo.story-catalog.v1', 'Invalid story catalog schema')
    chapters = {row['id']: row for row in data['chapters']}
    objectives = {row['id']: row['raw_fields'] for row in data['objectives']}
    require(len(chapters) == 16 and len(objectives) == 52, 'Story catalog coverage differs')
    require(data['counts']['chapters'] == 16 and data['counts']['objectives'] == 52,
            'Story catalog counts differ')
    return dict(chapters=chapters, objectives=objectives, sha256=digest(path.read_bytes()))


def select_chapters(range_text: str) -> list[int]:
    require(range_text.count('-') == 1, 'Chapter range must be FIRST-LAST')
    first, last = (uint(part.strip(), 'chapter range') for part in range_text.split('-'))
    require(first == 1, 'Candidate patches must start at episode 1')
    require(first <= last <= 16, 'Chapter range out of bounds')
    return list(range(first, last + 1))


def chapter_objective_count(episode: int) -> int:
    return 4 if episode % 4 == 0 else 3


def objective_row(kr: list[str], name: str, script_slot: int, provenance: list[dict]) -> list[str]:
    require(len(kr) == KR_OBJECTIVE_WIDTH, 'KR objective row width differs')
    kind = uint(kr[2], 'KR objective type')
    require(kind in (OBJECTIVE_TYPE_DIALOGUE, OBJECTIVE_TYPE_DUNGEON, OBJECTIVE_TYPE_MONK),
            'Unexpected chapter objective type')
    row = ['0'] * CN_OBJECTIVE_WIDTH
    row[0] = kr[0]
    row[1] = gbk(name, 'objective name')
    for index in range(2, TAIL_FIRST):
        sint(kr[index], 'KR objective field %d' % index)
        row[index] = kr[index]
    script = sint(kr[19], 'KR objective script')
    if kind == OBJECTIVE_TYPE_DIALOGUE:
        require(10000 <= script < 10032, 'Chapter dialogue script differs')
        row[script_slot] = kr[19]
    elif kind == OBJECTIVE_TYPE_MONK:
        # The CN monk subsystem owns 24000..24003; never project the KR script id.
        require(10032 <= script < 10036, 'KR monk reference script differs')
        script = 0
    else:
        require(script == 0, 'Dungeon objective must not carry a script')
    provenance.append(dict(objective_id=int(kr[0]), objective_type=kind, script_uid=script,
                           script_slot=script_slot if script else None,
                           tail_defaulted=[TAIL_FIRST, TAIL_LAST]))
    return row


def quest_row(chapter: dict, template: list[str], index: int, title: str,
              provenance: list[dict]) -> dict:
    header = chapter['header']
    require(len(header) == KR_QUEST_HEAD, 'KR quest header width differs')
    require(uint(header[0], 'quest id') == chapter['id'], 'Catalog quest id differs from header')
    require(uint(header[1], 'quest type') == 2, 'Chapter is not type 2')
    row = ['0'] * CN_QUEST_HEAD
    row[0] = header[0]
    row[1] = header[1]
    row[2] = str(index)
    row[4] = gbk(title, 'quest title')
    row[7] = header[KR_DESC_SLOT]
    row[8] = header[10]
    row[9] = header[11]
    row[10] = header[12]
    for slot in TEMPLATE_QUEST_SLOTS:
        row[slot] = template[slot]
    for slot in range(11, CN_QUEST_HEAD):
        row[slot] = header[slot + 2]
    for slot in (0, 7):
        require(row[slot].isdigit(), 'Quest header slot must stay numeric')
    require(uint(row[7], 'description QS') > 0, 'Missing description QS')
    provenance.append(dict(quest_id=chapter['id'], template_slots=list(TEMPLATE_QUEST_SLOTS),
                           unused_kr_slots=list(UNUSED_KR_SLOTS), catalog_index=index))
    return dict(header=row,
                objective_ids=[str(value) for value in chapter['objective_ids']],
                objective_values=[str(value) for value in chapter['objective_values']],
                reward_text_id=str(chapter['reward_text_id']),
                rewards=[[str(part) for part in triple] for triple in chapter['rewards']])


def plan(cn_text: str, catalog: dict, localization: dict, chapters: list[int],
         script_slot: int, reference_quest: int, allow_unreviewed: bool) -> dict:
    require(SCRIPT_SLOT_MIN <= script_slot <= SCRIPT_SLOT_MAX, 'Script slot outside the CN tail')
    table = parse_qt(cn_text)
    require(len(table['objectives']) == CN_OBJECTIVE_COUNT, 'CN objective count differs')
    require(len(table['quests']) == CN_QUEST_COUNT, 'CN quest count differs')
    for row in table['objectives']:
        require(all(value == '0' for value in row[TAIL_FIRST:]),
                'Shipped CN objective tail is not zero; refusing to assume the slot layout')
    shipped_objectives = {uint(row[0], 'CN objective id') for row in table['objectives']}
    shipped_quests = {uint(quest['header'][0], 'CN quest id') for quest in table['quests']}
    require(len(shipped_objectives) == CN_OBJECTIVE_COUNT, 'CN objective ids repeat')
    require(len(shipped_quests) == CN_QUEST_COUNT, 'CN quest ids repeat')

    templates = {uint(quest['header'][0], 'CN quest id'): quest['header']
                 for quest in table['quests']}
    require(reference_quest in templates, 'Reference quest is not in the CN table')
    template = templates[reference_quest]
    require(not any(int(template[slot]) for slot in TEMPLATE_QUEST_SLOTS),
            'Reference quest does not expose zero-valued template slots')
    next_index = max(uint(quest['header'][2], 'CN catalogue index') for quest in table['quests']) + 1

    new_objectives, new_quests, provenance = [], [], []
    reviewed = True
    for episode in chapters:
        quest_id = 73_000_000 + episode - 1
        chapter = catalog['chapters'].get(quest_id)
        require(chapter is not None, 'Missing catalog chapter %d' % quest_id)
        kinds = [uint(catalog['objectives'][objective_id][2], 'objective type')
                 for objective_id in chapter['objective_ids']]
        require(any(tuple(kinds) == expected for expected in EXPECTED_KINDS),
                'Chapter objective order differs')
        require(len(kinds) == chapter_objective_count(episode), 'Chapter objective count differs')
        title = localization['titles'][quest_id]
        reviewed = reviewed and bool(title['approved'])
        if not title['approved'] and not allow_unreviewed:
            raise ValueError('Unreviewed title for %d; pass --allow-unreviewed' % quest_id)
        quest = quest_row(chapter, template, next_index, title['translation_zh'], provenance)
        for objective_id in chapter['objective_ids']:
            require(objective_id not in shipped_objectives,
                    'Objective %d already exists in the CN table' % objective_id)
            named = localization['names'][objective_id]
            reviewed = reviewed and bool(named['approved'])
            if not named['approved'] and not allow_unreviewed:
                raise ValueError('Unreviewed objective name %d' % objective_id)
            new_objectives.append(objective_row(catalog['objectives'][objective_id],
                                                named['translation_zh'], script_slot, provenance))
        require(quest_id not in shipped_quests, 'Quest %d already exists in the CN table' % quest_id)
        new_quests.append(quest)
        next_index += 1

    candidate = dict(header=list(table['header']),
                     objectives=list(table['objectives']) + new_objectives,
                     quests=list(table['quests']) + new_quests)
    return dict(table=table, candidate=candidate, provenance=provenance, review_complete=reviewed,
                reference_quest=reference_quest, script_slot=script_slot)


def verify_appended(candidate: dict, table: dict, chapters: list[int], script_slot: int) -> None:
    expected_objectives = sum(chapter_objective_count(episode) for episode in chapters)
    require(len(candidate['objectives']) == len(table['objectives']) + expected_objectives,
            'Objective growth differs')
    require(len(candidate['quests']) == len(table['quests']) + len(chapters), 'Quest growth differs')
    require(candidate['objectives'][:len(table['objectives'])] == table['objectives'],
            'Existing objective row changed')
    require(candidate['quests'][:len(table['quests'])] == table['quests'],
            'Existing quest row changed')
    index_of = {}
    for position, row in enumerate(candidate['objectives'][CN_OBJECTIVE_COUNT:]):
        index_of[row[0]] = CN_OBJECTIVE_COUNT + position
    offset = 0
    for episode in chapters:
        quest = candidate['quests'][CN_QUEST_COUNT + episode - 1]
        require(uint(quest['header'][0], 'quest id') == 73_000_000 + episode - 1, 'Quest order differs')
        require(uint(quest['header'][1], 'quest type') == 2, 'Appended quest is not type 2')
        kinds = [uint(candidate['objectives'][index_of[objective_id]][2], 'objective type')
                 for objective_id in quest['objective_ids']]
        require(any(tuple(kinds) == expected for expected in EXPECTED_KINDS), 'Objective kinds differ')
        for objective_id in quest['objective_ids']:
            row = candidate['objectives'][index_of[objective_id]]
            require(all(row[slot] == '0' for slot in range(TAIL_FIRST, TAIL_LAST + 1)
                        if slot != script_slot), 'CN tail slot must stay zero')
        first, second, third = quest['objective_ids'][:3]
        require(candidate['objectives'][index_of[first]][script_slot].isdigit(), 'Script slot differs')
        require(candidate['objectives'][index_of[second]][script_slot] == '0',
                'Dungeon objective must stay script-free')
        require(uint(candidate['objectives'][index_of[third]][script_slot],
                     'exit script') == 10001 + 2 * (episode - 1), 'Exit script differs')
        if len(quest['objective_ids']) == 4:
            require(candidate['objectives'][index_of[quest['objective_ids'][3]]][script_slot] == '0',
                    'Monk reference must not carry the KR script')
        offset += len(quest['objective_ids'])
    require(offset == expected_objectives, 'Objective coverage differs')


def build_report(kind: str, inputs: list[dict], planned: dict, chapters: list[int],
                 candidate_bytes: bytes) -> dict:
    return dict(schema=SCHEMA, status='candidate-only', kind=kind,
                activation_allowed=False, runtime_acceptance=False,
                unresolved_gates=list(GATES), inputs=inputs,
                chapter_range=[chapters[0], chapters[-1]],
                counts=dict(chapters=len(chapters),
                            objectives=sum(chapter_objective_count(e) for e in chapters),
                            quests=len(chapters)),
                script_slot=planned['script_slot'],
                script_slot_provenance='unproven: all 357 shipped CN rows keep fields 17..26 at zero',
                reference_quest=planned['reference_quest'],
                template_quest_slots=list(TEMPLATE_QUEST_SLOTS),
                review_complete=planned['review_complete'],
                provenance=planned['provenance'],
                output=dict(name=CN_QT_NAME, size=len(candidate_bytes),
                            sha256=digest(candidate_bytes)),
                required_followups=list(FOLLOWUPS))


def derive(client: Path, catalog_path: Path, localization_path: Path, chapters: list[int],
           script_slot: int, reference_quest: int, allow_unreviewed: bool) -> dict:
    raw = (client / CN_QT_NAME).read_bytes()
    catalog = load_catalog(catalog_path)
    localization = load_localization(localization_path)
    planned = plan(decrypt_qt(raw), catalog, localization, chapters, script_slot, reference_quest,
                   allow_unreviewed)
    verify_appended(planned['candidate'], planned['table'], chapters, script_slot)
    candidate_bytes = encrypt_qt(serialize_qt(planned['candidate']))
    reparsed = parse_qt(decrypt_qt(candidate_bytes))
    require(reparsed['objectives'] == planned['candidate']['objectives'],
            'Candidate objectives differ after re-read')
    require(reparsed['quests'] == planned['candidate']['quests'],
            'Candidate quests differ after re-read')
    inputs = [dict(name=CN_QT_NAME, size=len(raw), sha256=digest(raw)),
              dict(name='catalog', size=catalog_path.stat().st_size, sha256=catalog['sha256']),
              dict(name='localization', size=localization_path.stat().st_size,
                   sha256=localization['sha256'])]
    report = (json.dumps(build_report('build', inputs, planned, chapters, candidate_bytes),
                         ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    return {CN_QT_NAME: candidate_bytes, 'patch-report.json': report}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'verify'))
    parser.add_argument('--client', type=Path, required=True, help='Client root containing QT._D30')
    parser.add_argument('--catalog', type=Path, required=True, help='Derived KR story catalog.json')
    parser.add_argument('--localization', type=Path, required=True,
                        help='manifest/story_localization.json')
    parser.add_argument('--chapters', default='1-4', help='Episode range FIRST-LAST, must start at 1')
    parser.add_argument('--script-slot', type=int, default=19,
                        help='CN objective tail slot for the action script UID (unproven)')
    parser.add_argument('--reference-quest', type=int, default=71000000,
                        help='CN quest whose unproven header slots are copied')
    parser.add_argument('--allow-unreviewed', action='store_true',
                        help='Permit unreviewed translations; the report records the gap')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    chapters = select_chapters(args.chapters)
    payload = derive(args.client, args.catalog, args.localization, chapters, args.script_slot,
                     args.reference_quest, args.allow_unreviewed)
    if args.command == 'build':
        require(not args.output.exists(), 'Output already exists; preserve prior results')
        require(args.output.resolve() != args.client.resolve(),
                'Output must not be the client root')
        for guarded in (args.catalog.parent, args.localization.parent):
            require(args.output.resolve() != guarded.resolve(),
                    'Output must not be the directory holding the inputs')
        args.output.mkdir(parents=True)
        for name, raw in payload.items():
            (args.output / name).write_bytes(raw)
        built = json.loads(payload['patch-report.json'].decode('utf-8'))
        print(json.dumps(dict(output=str(args.output), status='candidate-only',
                              activation_allowed=False, runtime_acceptance=False,
                              review_complete=built['review_complete'],
                              counts=built['counts']), indent=2))
        return 0
    require({path.name for path in args.output.iterdir()} == set(payload), 'Output coverage differs')
    for name, raw in payload.items():
        require((args.output / name).read_bytes() == raw, 'Derived output differs: ' + name)
    print(json.dumps(dict(status='rederived-exact', activation_allowed=False,
                          runtime_acceptance=False), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
