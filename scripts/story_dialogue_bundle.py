'''Build the chapter dialogue data bundle the client payload would read.

The running client imports CreateFileA/ReadFile (verified in the recorded image),
so a future dialogue payload does not need the client's own text lookup: it can
read this file and draw the pages. This tool fixes that data contract now, while
it can still be verified:

  header   'SDLG', version, script count
  index    per script: uid, page count, reserved
  pages    fixed 256 bytes = 4 lines x 64 bytes, GBK, NUL padded

Wrapping matches the state helper: at most 48 GBK bytes per line and four lines
per page, so a long speech simply spans several pages. Nothing is installed and
no payload is generated; the report carries the same inactive flags as the other
candidates.
'''
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_qt_patch as shared  # noqa: E402

SCHEMA = 'openNanaimo.story-dialogue-bundle.v1'
MAGIC = b'SDLG'
VERSION = 1
LINE_BYTES = 48
SLOT_BYTES = 64
LINES_PER_PAGE = 4
PAGE_BYTES = SLOT_BYTES * LINES_PER_PAGE
HEADER = struct.Struct('<4sHH')
INDEX = struct.Struct('<IHH')
TEXTS = 'manifest/story_localization.json'
MONK_SCRIPT_FIRST = 10032  # 10032..10035 stay with the monk subsystem


def load_localization(path: Path) -> dict:
    data = json.loads(path.read_text('utf-8'))
    shared.require(data.get('schema') == 'openNanaimo.chapter-story-localization.v1',
                   'Invalid localization schema')
    shared.require(data.get('activation_allowed') is False
                   and data.get('runtime_acceptance') is False,
                   'Localization manifest must advertise inactive publication')
    return {int(row['qs_id']): row for row in data['texts']}


def load_catalog(path: Path) -> dict:
    data = json.loads(path.read_text('utf-8'))
    shared.require(data.get('schema') == 'openNanaimo.story-catalog.v1',
                   'Invalid story catalog schema')
    scripts = {row['uid']: row['actions'] for row in data['scripts']}
    shared.require(len(scripts) == 36, 'Story catalog script coverage differs')
    shared.require(data['bindings'], 'Story catalog bindings are empty')
    return dict(scripts=scripts, bindings=data['bindings'],
                chapters={row['id']: row for row in data['chapters']},
                sha256=shared.digest(path.read_bytes()))


def wrap(text: str) -> list[str]:
    lines = []
    for paragraph in text.replace('\r\n', '\n').split('^&'):
        line = ''
        for char in paragraph:
            if len((line + char).encode('gbk', errors='strict')) > LINE_BYTES:
                lines.append(line)
                line = ''
            line += char
        lines.append(line)
    return lines


def pages(lines: list[str]) -> list[list[str]]:
    return [lines[index:index + LINES_PER_PAGE] for index in range(0, len(lines), LINES_PER_PAGE)]


def page_bytes(page: list[str]) -> bytes:
    shared.require(0 < len(page) <= LINES_PER_PAGE, 'Page has too many lines')
    slot = bytearray(PAGE_BYTES)
    for index, line in enumerate(page):
        raw = line.encode('gbk', errors='strict')
        shared.require(len(raw) <= LINE_BYTES, 'Line exceeds the byte budget')
        start = index * SLOT_BYTES
        slot[start:start + len(raw)] = raw
    return bytes(slot)


def select_scripts(catalog: dict, chapters: list[int]) -> list[int]:
    wanted = []
    for episode in chapters:
        quest = 73_000_000 + episode - 1
        shared.require(quest in catalog['chapters'], 'Missing catalog chapter %d' % quest)
        for row in catalog['bindings']:
            if row['quest_id'] != quest or row['attributes'].get('type') != 'SPEECH':
                continue
            if row['script_uid'] >= MONK_SCRIPT_FIRST:
                continue  # the monk reference keeps its own dialogue owner
            if row['script_uid'] not in wanted:
                wanted.append(row['script_uid'])
    shared.require(wanted, 'The selected chapters bind no dialogue script')
    return sorted(wanted)


def build(catalog: dict, localization: dict, chapters: list[int],
          allow_unreviewed: bool) -> dict:
    scripts = []
    reviewed = True
    for uid in select_scripts(catalog, chapters):
        actions = catalog['scripts'].get(uid)
        shared.require(actions, 'Script %d is missing from the catalog' % uid)
        rendered = []
        for action in actions:
            if action.get('type') != 'SPEECH':
                continue
            text_id = shared.uint(action['string_uid'], 'speech text id')
            row = localization.get(text_id)
            shared.require(row is not None, 'No localization row for text %d' % text_id)
            reviewed = reviewed and bool(row['approved'])
            if not row['approved'] and not allow_unreviewed:
                raise ValueError('Unreviewed text %d; pass --allow-unreviewed' % text_id)
            rendered.extend(page_bytes(page) for page in pages(wrap(row['translation_zh'])))
        shared.require(rendered, 'Script %d has no speech to render' % uid)
        scripts.append(dict(uid=uid, pages=len(rendered), data=b''.join(rendered)))
    return dict(scripts=scripts, review_complete=reviewed)


def encode(built: dict) -> bytes:
    header = HEADER.pack(MAGIC, VERSION, len(built['scripts']))
    index, body = b'', b''
    for script in built['scripts']:
        index += INDEX.pack(script['uid'], script['pages'], 0)
    for script in built['scripts']:
        body += script['data']
    return header + index + body


def decode(raw: bytes) -> dict:
    shared.require(len(raw) >= HEADER.size, 'Bundle is truncated')
    magic, version, count = HEADER.unpack_from(raw, 0)
    shared.require(magic == MAGIC and version == VERSION, 'Bundle header differs')
    shared.require(len(raw) >= HEADER.size + count * INDEX.size, 'Bundle index is truncated')
    at = HEADER.size
    index = []
    for _ in range(count):
        uid, pages_count, reserved = INDEX.unpack_from(raw, at)
        at += INDEX.size
        index.append(dict(uid=uid, pages=pages_count, reserved=reserved))
    shared.require(at + sum(row['pages'] for row in index) * PAGE_BYTES == len(raw),
                   'Bundle body size differs')
    scripts = []
    for row in index:
        data = raw[at:at + row['pages'] * PAGE_BYTES]
        at += row['pages'] * PAGE_BYTES
        scripts.append(dict(uid=row['uid'], pages=row['pages'], data=data))
    return dict(scripts=scripts)


def page_text(bundle: dict, uid: int, page: int) -> list[str]:
    script = next((row for row in bundle['scripts'] if row['uid'] == uid), None)
    shared.require(script is not None, 'Script %d is not in the bundle' % uid)
    shared.require(0 <= page < script['pages'], 'Page %d is out of range' % page)
    start = page * PAGE_BYTES
    lines = []
    for index in range(LINES_PER_PAGE):
        slot = script['data'][start + index * SLOT_BYTES:start + (index + 1) * SLOT_BYTES]
        text = slot.split(b'\0', 1)[0].decode('gbk')
        if text:
            lines.append(text)
    return lines


def report(catalog_sha: str, built: dict, chapters: list[int], raw: bytes) -> dict:
    return dict(schema=SCHEMA, status='candidate-only', activation_allowed=False,
                runtime_acceptance=False, catalog_sha256=catalog_sha,
                chapter_range=[chapters[0], chapters[-1]],
                counts=dict(scripts=len(built['scripts']),
                            pages=sum(row['pages'] for row in built['scripts']),
                            bytes=len(raw)),
                page_bytes=PAGE_BYTES, lines_per_page=LINES_PER_PAGE, line_bytes=LINE_BYTES,
                review_complete=built['review_complete'],
                scripts=[dict(uid=row['uid'], pages=row['pages']) for row in built['scripts']],
                sha256=shared.digest(raw),
                consumer=dict(magic=MAGIC.decode(), version=VERSION,
                              imports=['CreateFileA', 'ReadFile', 'CloseHandle'],
                              page_address='base + 12 + 8*scripts + (script_slot*pages + page)*256'))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'verify'))
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--localization', type=Path, required=True)
    parser.add_argument('--chapters', default='1-4')
    parser.add_argument('--allow-unreviewed', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    chapters = shared.select_chapters(args.chapters)
    catalog = load_catalog(args.catalog)
    localization = load_localization(args.localization)
    built = build(catalog, localization, chapters, args.allow_unreviewed)
    raw = encode(built)
    decoded = decode(raw)
    shared.require([(row['uid'], row['pages']) for row in decoded['scripts']]
                   == [(row['uid'], row['pages']) for row in built['scripts']],
                   'Bundle index differs from the plan')
    shared.require(all(decoded['scripts'][index]['data'] == built['scripts'][index]['data']
                       for index in range(len(built['scripts']))), 'Bundle body differs from the plan')
    payload = {'story_dialogue.bin': raw,
               'dialogue-report.json': (json.dumps(report(catalog['sha256'], built, chapters, raw),
                                                   ensure_ascii=False, sort_keys=True, indent=2)
                                        + '\n').encode('utf-8')}
    if args.command == 'build':
        shared.require(not args.output.exists(), 'Output already exists; preserve prior results')
        args.output.mkdir(parents=True)
        for name, data in payload.items():
            (args.output / name).write_bytes(data)
        print(json.dumps(dict(output=str(args.output), status='candidate-only',
                              counts=json.loads(payload['dialogue-report.json'])['counts'],
                              review_complete=built['review_complete']), indent=2))
        return 0
    shared.require({path.name for path in args.output.iterdir()} == set(payload),
                   'Output coverage differs')
    for name, data in payload.items():
        shared.require((args.output / name).read_bytes() == data, 'Derived output differs: ' + name)
    print(json.dumps(dict(status='rederived-exact', activation_allowed=False,
                          runtime_acceptance=False), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
