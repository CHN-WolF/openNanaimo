'''Derive the candidate chapter action-script table (the third data package).

The KR client loads `action._S1` and builds one action record per SCRIPT UID; the
CN client has no such loader at all (no `_S1`, no SCRIPTS/SPEECH vocabulary in
game.exe), so this package is the reviewed data a future executor — or a patched
dialogue controller — would consume. It is emitted as readable XML plus the same
encrypted container the monk resources use, and it never touches a client.

Every selected script is checked against the derived catalog before it is
written: the script must exist, its actions must use known types, a SPEECH must
carry the six attributes the native loader reads, its text id must be a catalog
text, and the catalog binding must agree on quest, objective and script.
'''
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_qt_patch as shared  # noqa: E402  (AES container and validation helpers)

SCHEMA = 'openNanaimo.story-action-patch.v1'
PREFIX = '.openNanaimo-story'
XML_NAME = 'story_action.xml'
BINARY_NAME = 'story_action._S1'
REPORT_NAME = 'action-report.json'
ACTION_TYPES = ('SPEECH', 'COMPLETE', 'D_START', 'CONDITION')
SPEECH_ATTRIBUTES = ('npc_uid', 'string_uid', 'expression', 'value', 'close', 'face_count')
NUMERIC_ATTRIBUTES = ('npc_uid', 'string_uid', 'expression', 'value', 'close', 'face_count',
                      'dtype', 'episode', 'dungeon', 'level', 'condition', 'step_clear')
STORY_SCRIPTS_PER_EPISODE = 2
MONK_SCRIPT_FIRST, MONK_SCRIPT_LAST = 10032, 10035
GATES = shared.GATES
FOLLOWUPS = (
    'the CN client has no action-script loader; this package cannot fire a dialogue on its own',
    'a future executor must read SCRIPT 10000..10031 for the story speeches',
    'the monk scripts 10032..10035 stay with the existing monk subsystem (24000..24003)',
)


def load_catalog(path: Path) -> dict:
    data = json.loads(path.read_text('utf-8'))
    shared.require(data.get('schema') == 'openNanaimo.story-catalog.v1',
                   'Invalid story catalog schema')
    scripts = {row['uid']: row['actions'] for row in data['scripts']}
    texts = {row['qs_id'] for row in data['texts']}
    root = data.get('action_root_attributes') or {}
    shared.require(len(scripts) == 36 and len(texts) == 151, 'Story catalog script/text coverage differs')
    shared.require(set(scripts) == set(range(10000, 10036)), 'Story catalog script range differs')
    shared.require(set(root) == {'target', 'version'}, 'Action root attributes differ')
    return dict(scripts=scripts, texts=texts, root=root, bindings=data['bindings'],
                chapters={row['id']: row for row in data['chapters']},
                sha256=shared.digest(path.read_bytes()))


def select_chapters(range_text: str) -> list[int]:
    return shared.select_chapters(range_text)


def required_scripts(chapters: list[int]) -> list[int]:
    return sorted({10000 + STORY_SCRIPTS_PER_EPISODE * (episode - 1) + offset
                   for episode in chapters for offset in range(STORY_SCRIPTS_PER_EPISODE)})


def check_script(catalog: dict, uid: int, expected_quest: int, expected_objective: int) -> dict:
    actions = catalog['scripts'].get(uid)
    shared.require(actions is not None, 'Script %d is missing from the catalog' % uid)
    shared.require(actions, 'Script %d has no actions' % uid)
    for action in actions:
        kind = action.get('type')
        shared.require(kind in ACTION_TYPES, 'Script %d has an unknown action %r' % (uid, kind))
        if kind == 'SPEECH':
            shared.require(set(SPEECH_ATTRIBUTES) <= set(action),
                           'Script %d speech is incomplete' % uid)
            text = shared.uint(action['string_uid'], 'speech text id')
            shared.require(text in catalog['texts'],
                           'Script %d speaks text %d that the catalog does not carry' % (uid, text))
        for name, value in action.items():
            if name in NUMERIC_ATTRIBUTES:
                shared.sint(value, 'action attribute ' + name)
            else:
                shared.require(isinstance(value, str) and value, 'Empty action attribute ' + name)
    binding = [row for row in catalog['bindings'] if row['script_uid'] == uid]
    shared.require(binding, 'Script %d has no catalog binding' % uid)
    shared.require(all(row['quest_id'] == expected_quest and row['objective_id'] == expected_objective
                       for row in binding), 'Script %d binding differs from its chapter' % uid)
    return dict(script_uid=uid, actions=[dict(action) for action in actions])


def escape(value: str) -> str:
    return (value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def render(root: dict, scripts: list[dict]) -> bytes:
    shared.require(set(root) == {'target', 'version'}, 'Action root attributes differ')
    lines = ['<SCRIPTS target="%s" version="%s">' % (escape(root['target']), escape(root['version']))]
    for script in scripts:
        lines.append('  <SCRIPT uid="%d">' % script['script_uid'])
        for action in script['actions']:
            order = ['type'] + sorted(name for name in action if name != 'type')
            attributes = ' '.join('%s="%s"' % (name, escape(action[name])) for name in order)
            lines.append('    <ACTION %s/>' % attributes)
        lines.append('  </SCRIPT>')
    lines.append('</SCRIPTS>')
    return ('\n'.join(lines) + '\n').encode('gbk')


def plan(catalog: dict, chapters: list[int]) -> dict:
    required = required_scripts(chapters)
    shared.require(all(uid < MONK_SCRIPT_FIRST for uid in required),
                   'The selected chapters reach into the monk scripts')
    shared.require(MONK_SCRIPT_LAST < 10036, 'Monk script range differs')
    scripts = []
    for episode in chapters:
        quest = 73_000_000 + episode - 1
        chapter = catalog['chapters'].get(quest)
        shared.require(chapter is not None, 'Missing catalog chapter %d' % quest)
        dialogue = [row for row in catalog['bindings']
                    if row['quest_id'] == quest and row['attributes']['type'] == 'SPEECH']
        by_script = {}
        for row in dialogue:
            by_script.setdefault(row['script_uid'], row['objective_id'])
        for offset in range(STORY_SCRIPTS_PER_EPISODE):
            uid = 10000 + STORY_SCRIPTS_PER_EPISODE * (episode - 1) + offset
            shared.require(uid in by_script, 'Chapter %d does not bind script %d' % (episode, uid))
            scripts.append(check_script(catalog, uid, quest, by_script[uid]))
    shared.require([row['script_uid'] for row in scripts] == required, 'Script order differs')
    return dict(scripts=scripts, required=required)


def build_report(inputs: list[dict], planned: dict, chapters: list[int], xml: bytes,
                 encrypted: bytes) -> dict:
    speeches = [action['string_uid'] for script in planned['scripts']
                for action in script['actions'] if action['type'] == 'SPEECH']
    return dict(schema=SCHEMA, status='candidate-only', kind='build',
                activation_allowed=False, runtime_acceptance=False,
                unresolved_gates=list(GATES), inputs=inputs,
                chapter_range=[chapters[0], chapters[-1]],
                counts=dict(scripts=len(planned['scripts']), speeches=len(speeches),
                            unique_texts=len({int(value) for value in speeches})),
                scripts=[dict(script_uid=script['script_uid'],
                              actions=len(script['actions']),
                              speeches=[action['string_uid'] for action in script['actions']
                                        if action['type'] == 'SPEECH'])
                         for script in planned['scripts']],
                container=PREFIX,
                outputs=[dict(name=PREFIX + '/' + XML_NAME, size=len(xml), sha256=shared.digest(xml)),
                         dict(name=PREFIX + '/' + BINARY_NAME, size=len(encrypted),
                              sha256=shared.digest(encrypted))],
                required_followups=list(FOLLOWUPS))


def derive(catalog_path: Path, chapters: list[int]) -> dict:
    catalog = load_catalog(catalog_path)
    planned = plan(catalog, chapters)
    xml = render(catalog['root'], planned['scripts'])
    encrypted = shared.encrypt_qt(xml.decode('gbk'))
    shared.require(shared.decrypt_qt(encrypted) == xml.decode('gbk'),
                   'Encrypted container does not round trip')
    inputs = [dict(name='catalog', size=catalog_path.stat().st_size, sha256=catalog['sha256'])]
    report = (json.dumps(build_report(inputs, planned, chapters, xml, encrypted),
                         ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    return {XML_NAME: xml, BINARY_NAME: encrypted, REPORT_NAME: report}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'verify'))
    parser.add_argument('--catalog', type=Path, required=True, help='Derived KR story catalog.json')
    parser.add_argument('--chapters', default='1-4', help='Episode range FIRST-LAST, must start at 1')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    chapters = select_chapters(args.chapters)
    payload = derive(args.catalog, chapters)
    if args.command == 'build':
        shared.require(not args.output.exists(), 'Output already exists; preserve prior results')
        shared.require(args.output.resolve() != args.catalog.parent.resolve(),
                       'Output must not be the directory holding the catalog')
        args.output.mkdir(parents=True)
        for name, raw in payload.items():
            (args.output / name).write_bytes(raw)
        built = json.loads(payload[REPORT_NAME].decode('utf-8'))
        print(json.dumps(dict(output=str(args.output), status='candidate-only',
                              activation_allowed=False, runtime_acceptance=False,
                              counts=built['counts']), indent=2))
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
