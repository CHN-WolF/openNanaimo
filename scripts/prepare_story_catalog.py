'''Derive an isolated KR chapter catalog; never install or grant live quests.

QT layouts are deliberately separate. Unknown fields and all action attributes
survive in the output; unresolved CN consumers are release gates, not defaults.
'''
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import prepare_hero_dragon as crypto

SCHEMA = 'openNanaimo.story-catalog.v1'
KR_INPUTS = {
    'QT._D30': '430820a232659be7f18133ec06aad30272f8b037515df3a2bf9d73b3177161d8',
    'QS._D31': '2d8eec45112994591567fb6084579d99710f6957f3ddf08a5857b5a976b62e99',
    'action._S1': 'b2bbc61ad32425192bef5ee2783b64a64619778ab39fee1d11db5fd1cb4f3727',
    'NPC._D39': '3acf7acb56c73c7450dfabe1d1e1f886180d533fcb90a6cc5c1e5759ab850260',
}
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


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, label, signed=False):
    require(isinstance(value, str) and re.fullmatch(r'-?[0-9]+' if signed else r'[0-9]+', value),
            'Invalid integer: ' + label)
    result = int(value)
    require((-2147483648 if signed else 0) <= result <= (2147483647 if signed else 4294967295),
            'Integer out of range: ' + label)
    return result


class Fields:
    def __init__(self, text):
        self.values = text.split('#')
        self.at = 0

    def take(self, count):
        require(0 <= count <= len(self.values) - self.at, 'Truncated catalog')
        result = self.values[self.at:self.at + count]
        self.at += count
        return result

    def uint(self):
        return number(self.take(1)[0], 'catalog field')


def parse_qt(text, region):
    require(region in ('kr', 'cn'), 'Unknown QT region')
    f = Fields(text)
    header = f.take(3)
    require(header[0] == 'QUEST', 'Invalid QT header')
    width, head = (26, 24) if region == 'kr' else (27, 22)
    objectives = {}
    for _ in range(number(header[2], 'objective count')):
        row = f.take(width)
        uid = number(row[0], 'objective ID')
        require(uid not in objectives, 'Duplicate objective ID')
        for token in row[2:]:
            number(token, 'objective field', signed=True)
        objectives[uid] = row
    quests = {}
    for _ in range(f.uint()):
        h = f.take(head)
        uid = number(h[0], 'quest ID')
        require(uid not in quests, 'Duplicate quest ID')
        title_at = 5 if region == 'kr' else 4
        for i, token in enumerate(h):
            if i != title_at:
                number(token, 'quest header', signed=True)
        count = f.uint()
        ids = [number(v, 'linked objective') for v in f.take(count)]
        values = [number(v, 'parallel objective value', signed=True) for v in f.take(count)]
        require(ids and len(ids) == len(set(ids)) and all(v in objectives for v in ids),
                'Missing or duplicate linked objective')
        reward_text = f.uint()
        rewards = [[number(v, 'reward') for v in f.take(3)] for _ in range(f.uint())]
        tail, extras = [], []
        if region == 'kr':
            tail = f.take(2)
            number(tail[0], 'next quest')
            extras = [f.take(3) for _ in range(number(tail[1], 'extra count'))]
            # KR extra triples include resource paths and display names.
        quests[uid] = dict(id=uid, type=number(h[1], 'quest type'), header=h,
                          title=h[title_at], objective_ids=ids, objective_values=values,
                          reward_text_id=reward_text, rewards=rewards,
                          next_fields=tail, extra=extras)
    npc_bindings = {}
    if region == 'kr':
        for _ in range(f.uint()):
            objective, npc = f.uint(), f.uint()
            require(objective in objectives and objective not in npc_bindings, 'Invalid NPC binding')
            npc_bindings[objective] = npc
    require(f.take(1) == [''] and f.at == len(f.values), 'Unconsumed QT tail')
    return dict(header=header, objectives=objectives, quests=quests, npc_bindings=npc_bindings)


def parse_qs(text):
    f = Fields(text)
    header = f.take(3)
    require(header[0] == 'NANA_QUEST_TEXT', 'Invalid QS header')
    strings = {}
    for _ in range(number(header[2], 'QS count')):
        uid, value = f.take(2)
        uid = number(uid, 'QS ID')
        require(uid not in strings, 'Duplicate QS ID')
        strings[uid] = value
    require(f.take(1) == [''] and f.at == len(f.values), 'Unconsumed QS tail')
    return strings


def parse_actions(raw):
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'XML declarations forbidden')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError('Malformed action XML') from error
    require(root.tag == 'SCRIPTS', 'Invalid action root')
    scripts = {}
    for node in root:
        require(node.tag == 'SCRIPT' and set(node.attrib) == {'uid'}, 'Invalid script node')
        uid = number(node.get('uid'), 'script UID')
        require(uid not in scripts, 'Duplicate script UID')
        actions = []
        for action in node:
            require(action.tag == 'ACTION' and len(action) == 0 and not (action.text or '').strip(),
                    'Invalid action node')
            require(action.get('type') in ('SPEECH', 'COMPLETE', 'D_START', 'CONDITION'), 'Unknown action type')
            if action.get('type') == 'SPEECH':
                require({'npc_uid', 'string_uid', 'expression', 'value', 'close', 'face_count'}
                        <= set(action.attrib), 'Incomplete speech attributes')
                for key in ('npc_uid', 'string_uid', 'expression', 'value', 'close', 'face_count'):
                    number(action.get(key), 'speech ' + key)
            actions.append(dict(action.attrib))
        require(actions, 'Empty script')
        scripts[uid] = actions
    return dict(attributes=dict(root.attrib), scripts=scripts)


def make_catalog(kr, qs, actions, cn, cn_qs):
    chapters = [kr['quests'].get(uid) for uid in range(73000000, 73000016)]
    require(all(q is not None and q['type'] == 2 for q in chapters), 'Missing type2 chapter')
    require({q['id'] for q in kr['quests'].values() if q['type'] == 2}
            == set(range(73000000, 73000016)), 'Unexpected type2 chapter')
    require(len(kr['objectives']) == 409 and len(kr['quests']) == 233, 'KR catalog counts differ')
    require(set(actions['scripts']) == set(range(10000, 10036)), 'Script coverage differs')
    objective_ids, script_ids, speech_ids = [], [], []
    references, bindings, collisions = set(), [], []
    for index, quest in enumerate(chapters):
        require(number(quest['next_fields'][0], 'successor') == (73000001 + index if index < 15 else 0),
                'Chapter successor differs')
        ids = quest['objective_ids']
        expected_kinds = [39, 40, 39] + ([1] if index % 4 == 3 else [])
        require([number(kr['objectives'][uid][2], 'objective type') for uid in ids] == expected_kinds,
                'Chapter objective order differs')
        references.update((number(quest['header'][9], 'description QS'), quest['reward_text_id']))
        objective_ids.extend(ids)
        if quest['id'] in cn['quests']:
            collisions.append(dict(namespace='quest', id=quest['id']))
        for order, uid in enumerate(ids):
            row = kr['objectives'][uid]
            if uid in cn['objectives']:
                collisions.append(dict(namespace='objective', id=uid))
            script = number(row[19], 'script UID')
            if order == 1:
                require(script == 0, 'Gameplay objective unexpectedly has a script')
                continue
            expected = 10000 + 2 * index + (1 if order == 2 else 0) if order < 3 else 10032 + index // 4
            require(script == expected, 'Objective script binding differs')
            script_ids.append(script)
            if order == 3:
                require(kr['npc_bindings'].get(uid) == 62 + index // 4, 'Monk NPC binding differs')
            for action_order, attrs in enumerate(actions['scripts'][script]):
                bindings.append(dict(quest_id=quest['id'], objective_id=uid, objective_index=order,
                                     script_uid=script, action_order=action_order, attributes=attrs))
                if attrs['type'] == 'SPEECH':
                    text = number(attrs['string_uid'], 'speech QS')
                    speech_ids.append(text)
                    references.add(text)
    require(sorted(objective_ids) == list(range(75100000, 75100052)), 'Objective coverage differs')
    require(sorted(script_ids) == list(range(10000, 10036)), 'Script references differ')
    require(len(speech_ids) == len(set(speech_ids)) == 119, 'Speech coverage differs')
    story_speeches = sum(b['script_uid'] < 10032 and b['attributes']['type'] == 'SPEECH' for b in bindings)
    require(story_speeches == 107, 'Story speech coverage differs')
    require(references <= set(qs), 'Missing referenced QS string')
    for uid in sorted(references & set(cn_qs)):
        collisions.append(dict(namespace='qs', id=uid, same_source_text=qs[uid] == cn_qs[uid]))
    objectives = [dict(id=uid, raw_fields=kr['objectives'][uid]) for uid in objective_ids]
    return dict(schema=SCHEMA, status='preparation-only', runtime_acceptance=False,
                activation_allowed=False, unresolved_gates=list(GATES),
                counts=dict(chapters=16, objectives=52, scripts=36, speeches=119,
                            story_speeches=107, monk_speeches=12),
                source_qt_header=kr['header'], chapters=chapters, objectives=objectives,
                action_root_attributes=actions['attributes'],
                scripts=[dict(uid=uid, actions=actions['scripts'][uid]) for uid in sorted(actions['scripts'])],
                bindings=bindings, npc_bindings=kr['npc_bindings'],
                texts=[dict(qs_id=uid, source_ko=qs[uid]) for uid in sorted(references)],
                cn_collisions=collisions)


def reuse_monk(catalog, cn_qs, localization, existing_actions):
    scripts = {row['uid']: row['actions'] for row in catalog['scripts']}
    reuse = []
    for index in range(4):
        source_uid, target_uid = 10032 + index, 24000 + index
        expected = [dict(a) for a in scripts[source_uid]]
        starts = [a for a in expected if a['type'] == 'D_START']
        require(len(starts) == 1, 'Monk start action differs')
        require(starts[0] == dict(type='D_START', dtype='3', episode=str(index),
                                 dungeon='', level='', condition='1'), 'KR monk identity differs')
        starts[0].update(dtype='0', episode=str(24 + index), dungeon='0', level='0')
        require(existing_actions['scripts'].get(target_uid) == expected, 'Existing monk script differs')
        for uid in range(6000 + index * 3, 6003 + index * 3):
            translated = localization['quest_strings'].get(str(uid))
            require(translated, 'Existing monk translation missing')
            translated.encode('gbk', errors='strict')
            reuse.append(dict(qs_id=uid, source_script_uid=source_uid, existing_script_uid=target_uid,
                              npc_uid=62 + index, episode=24 + index,
                              owner='manifest/monk_localization.json', disposition='reuse-existing',
                              installed_qs_matches_owner=translated == cn_qs.get(uid),
                              text_consumer='monk_dialogue_compat embedded native pages',
                              runtime_acceptance=False))
    catalog['reused_monk'] = reuse
    reused = {row['qs_id'] for row in reuse}
    for collision in catalog['cn_collisions']:
        if collision['namespace'] == 'qs' and collision['id'] in reused:
            collision['resolution'] = 'reuse-existing-monk-localization'


def review_template(catalog):
    reused = catalog.get('reused_monk', [])
    ids = {row['qs_id'] for row in reused}
    return dict(schema=SCHEMA + '.localization', status='unreviewed',
                reused_texts=reused,
                texts=[dict(row, translation_zh='', approved=False) for row in catalog['texts'] if row['qs_id'] not in ids],
                titles=[dict(quest_id=q['id'], source_ko=q['title'], translation_zh='', approved=False)
                        for q in catalog['chapters']],
                objective_names=[dict(objective_id=o['id'], source_ko=o['raw_fields'][1],
                                      translation_zh='', approved=False) for o in catalog['objectives']])


def validate_translation(source, translated, byte_limit=None):
    require(isinstance(translated, str) and translated.strip(), 'Empty translation')
    require(not any(c in translated for c in ('#', '\0', '\r', '\n')), 'Unsafe catalog delimiter')
    # Keep formatting tokens exact; never feed arbitrary new printf directives to the client.
    tokens = lambda s: Counter(re.findall(r'%(?:[-+0 #]*[0-9]*(?:\.[0-9]+)?[sd]|%)', s))
    require(tokens(source) == tokens(translated), 'Formatting placeholders differ')
    stripped = re.sub(r'%(?:[-+0 #]*[0-9]*(?:\.[0-9]+)?[sd]|%)', '', translated)
    require('%' not in stripped, 'Unsupported formatting directive')
    require(source.count('^&') == translated.count('^&'), 'Explicit line breaks differ')
    raw = translated.encode('gbk', errors='strict')
    require(byte_limit is None or len(raw) <= byte_limit, 'Translation exceeds client byte limit')
    return raw


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def derive(source, client):
    inputs = []

    def read(root, name, region):
        raw = (root / name).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if region == 'kr':
            require(sha == KR_INPUTS[name], 'Unreviewed KR input: ' + name)
        inputs.append(dict(region=region, name=name, size=len(raw), sha256=sha))
        return crypto.decrypt(raw, crypto.SOURCE_KEY if region == 'kr' else crypto.CN_KEY)

    kr = parse_qt(read(source, 'QT._D30', 'kr').decode('cp949'), 'kr')
    qs = parse_qs(read(source, 'QS._D31', 'kr').decode('cp949'))
    actions = parse_actions(read(source, 'action._S1', 'kr'))
    # Pin the NPC source, but do not invent a CN record layout or copy its bytes.
    read(source, 'NPC._D39', 'kr')
    cn = parse_qt(read(client, 'QT._D30', 'cn').decode('gbk'), 'cn')
    cn_qs = parse_qs(read(client, 'QS._D31', 'cn').decode('gbk'))
    catalog = make_catalog(kr, qs, actions, cn, cn_qs)
    # The CN dialogue controller embeds the localization owner's text. A loose
    # QS difference is reported but must not force rebuilding an existing NPC.
    import prepare_monk_resources as monk
    local_raw = monk.LOCALIZATION.read_bytes()
    local = json.loads(local_raw)
    xml = monk.localized_resources(local)['.openNanaimo-monk/monk_action.xml']
    existing = parse_actions(ET.tostring(ET.fromstring(xml.decode('gbk')), encoding='utf-8'))
    try:
        reuse_monk(catalog, cn_qs, local, existing)
    except ValueError as error:
        catalog['monk_reuse_blocker'] = str(error)
    inputs.append(dict(region='project', name='manifest/monk_localization.json', size=len(local_raw),
                       sha256=hashlib.sha256(local_raw).hexdigest()))
    catalog['inputs'] = inputs
    payload = {'catalog.json': encoded(catalog), 'localization-review.json': encoded(review_template(catalog))}
    report = dict(schema=SCHEMA + '.build', runtime_acceptance=False, activation_allowed=False,
                  inputs=inputs, counts=catalog['counts'], unresolved_gates=list(GATES),
                  cn_collisions=catalog['cn_collisions'],
                  files=[dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                         for name, raw in payload.items()])
    payload['manifest.json'] = encoded(report)
    return payload


def build(source, client, output):
    source, client, output = source.resolve(), client.resolve(), output.resolve()
    require(not output.is_relative_to(source) and not output.is_relative_to(client),
            'Output must be outside client/source directories')
    require(not output.exists(), 'Output already exists; preserve prior results')
    payload = derive(source, client)
    output.mkdir(parents=True)
    for name, raw in payload.items():
        with (output / name).open('xb') as stream:
            stream.write(raw)
    return dict(output=str(output), status='preparation-only', runtime_acceptance=False)


def verify(source, client, output):
    payload = derive(source, client)
    require({p.name for p in output.iterdir()} == set(payload), 'Output coverage differs')
    for name, raw in payload.items():
        require((output / name).read_bytes() == raw, 'Derived output differs: ' + name)
    return dict(status='rederived-exact', runtime_acceptance=False, activation_allowed=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('build', 'verify'))
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = vars(p.parse_args())
    command = args.pop('command')
    print(json.dumps(globals()[command](**args), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
