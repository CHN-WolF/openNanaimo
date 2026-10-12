"""Build additive first-challenge combat catalogs from converted client resources."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import struct
import subprocess

import generate_lumineos_combat as tables
import generate_preloaded_targets as preload
import generate_boss_contact_resources as contact
import generate_scene_hazard_catalog as hazard
import generate_scene_hazard_resources as hazard_resources
import lumineos_codec as codec
import normalize_combat_score_resources as scores

ROOT = Path(__file__).resolve().parents[1]
TAG = '/* MONK GENERATED APPEND */'
END = '/* END MONK GENERATED APPEND */'
SCOPE = (0, 24, 0, 0)
STAGE = 'flying/hd0_ep24_dg00_st00.sstg'
PRELOAD = Path('release/components/target_resources/preloaded_target_catalog.json')
SCORE = Path('release/components/combat_economy/combat_score_resource_data.inc')
BOSS_CONTACT = Path('release/components/stage_damage/boss_contact_catalog.inc')
MONSTER_CONTACT = Path('release/components/stage_damage/monster_contact_catalog.inc')
HAZARD = Path('release/components/stage_damage/scene_hazard_registry.json')


def clean(text):
    return re.sub(re.escape(TAG) + r'.*?' + re.escape(END) + r'\n', '', text, flags=re.S)


def append(text, name, lines, boundary=None):
    if not lines:
        return text
    match = tables.array(text, name)
    at = match.end(1) + 1
    if boundary:
        split = re.search(boundary, match[1], re.M)
        if split is None:
            raise ValueError('Missing ordered catalog boundary: ' + name)
        at = match.start(1) + split.start()
    block = TAG + '\n' + '\n'.join(lines) + '\n' + END + '\n'
    return text[:at] + block + text[at:]


def resize(text, name, macro, count):
    text = re.sub(r'(\b' + name + r'\[)\d+(\])', lambda m: m[1] + str(count) + m[2], text)
    return tables.define(text, macro, count)


def unique(keys, label, ordered=False):
    if len(set(keys)) != len(keys) or (ordered and keys != sorted(keys)):
        raise ValueError('Duplicate or unordered ' + label)


def read_dcc(data):
    sections = [[row for _, row in section] for section in scores.split_catalog(data)]
    for index, section in enumerate(sections):
        keys = [struct.unpack_from('<5BH', row) +
                (struct.unpack_from('<BBi', row, 7) if index == 2 else ()) for row in section]
        unique(keys, 'DCC7 section ' + str(index))
    return sections


def merge_dcc(original, added):
    if len(added) != 4:
        raise ValueError('DCC7 requires four sections')
    merged = []
    for rows, replacement in zip(read_dcc(original), added):
        indices = [i for i, row in enumerate(rows) if tuple(row[:4]) == SCOPE]
        at = indices[0] if indices else len(rows)
        if indices != list(range(at, at + len(indices))):
            raise ValueError('Noncontiguous first-challenge DCC7 section')
        merged.append(rows[:at] + replacement + rows[at + len(indices):])
    result = b'DCC7' + b''.join(struct.pack('<I', len(rows)) + b''.join(rows) for rows in merged)
    read_dcc(result)
    return result


class Resources(tables.Resources):
    def __init__(self, root):
        super().__init__(Path(root))
        self.bmos = {}
        self.bmo_effects = {}

    def path(self, name):
        path = super().path(name)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Resource path escapes client directory')
        return path

    def boss_names(self, name):
        # The bounded BMO2 reader consumes every mode and child record.
        modes = scores.Resources.boss(self, name)
        if name not in self.bmo_effects:
            raw = codec.xor(self.read(name), 56)
            pos, effects = 44, []
            for children in modes:
                mode_effects = []
                for relative in (0, 104, 204):
                    field = raw[pos+relative:pos+relative+100]
                    value = field.split(b'\0', 1)[0]
                    if b'\0' not in field or (value and not value.lower().endswith(b'.eff')):
                        raise ValueError('Unreviewed BMO2 effect field')
                    if value:
                        effect = value.decode('ascii')
                        codec.eff2(self.read(effect))
                        mode_effects.append(effect)
                effects.append(mode_effects)
                pos += 308 + 208 * len(children)
            if pos != len(raw):
                raise ValueError('BMO2 effect boundary')
            self.bmo_effects[name] = effects
        return modes

    def projectiles(self, names):
        queue = list(names)
        seen, result = set(), {}
        while queue:
            name = queue.pop()
            key = Path(name.replace('\\', '/')).name.lower()
            if key in seen:
                continue
            seen.add(key)
            if key.endswith('.mmo'):
                _, refs = self.mmo(name)
                queue.extend(r.decode('ascii') for r in refs if r.lower().endswith((b'.mmo', b'.pon', b'.bmo')))
            elif key.endswith('.bmo'):
                queue.extend(child for mode in self.boss_names(name) for child in mode)
            elif key.endswith('.pon'):
                eff, prefix, rows, _, refs = codec.pon_model(self.read(name), self.root, False)
                self.read('effs/game/shootinggamebasic/' + eff.decode('ascii'))
                owner = tables.u32(prefix, 24)
                if owner > 65535:
                    raise ValueError('PON owner exceeds unsigned16')
                result[key] = (owner, [tables.u32(row, 0x114) for row in rows])
                queue.extend(r.decode('ascii') for r in refs if r.lower().endswith((b'.mmo', b'.pon', b'.bmo')))
        return result


def checked_row(mem):
    raw, attack, score, _ = struct.unpack_from('<4i', mem, 8)
    if raw < 0 or not 0 <= attack <= 65535 or score < 0:
        raise ValueError('Unsupported MMO numeric fields')
    return raw, attack


def merge_preloads(previous, resources, model, profiles):
    result = copy.deepcopy(previous)
    if result['schema'] != 3:
        raise ValueError('Unsupported preload catalog')
    old_scopes = [s for s in result['scopes'] if (s['hd'], s['episode'], s['dungeon'], s['stage']) == SCOPE]
    old_rows = {s['profile_row'] for s in old_scopes}
    result['rows'] = [r for r in result['rows'] if r[0] not in old_rows]
    result['scopes'] = [s for s in result['scopes'] if s not in old_scopes]
    unique(result['resources'], 'preload resource names')
    for slot, profile in enumerate(profiles):
        selector = profile[10]
        for name in model['extra'][slot]:
            if name not in result['resources']:
                result['resources'].append(name)
            ri = result['resources'].index(name)
            rows, _ = resources.mmo(name)
            start = selector
            for ordinal, (mem, _) in enumerate(rows):
                raw, attack = checked_row(mem)
                if selector > 65535:
                    raise ValueError('Preload selector exceeds unsigned16')
                result['rows'].append([profile[9], selector, mem[4], raw, raw * profile[7] // 100,
                                       tables.i32(mem, 20), mem[26], ri, attack, tables.i32(mem, 408), start])
                selector += 1
        result['scopes'].append(dict(hd=0, episode=24, dungeon=0, stage=0, slot=slot,
                                     profile_row=profile[9], static_count=profile[10], preload_count=selector-profile[10]))
    result['rows'].sort(key=lambda r: (r[0], r[1]))
    result['scopes'].sort(key=lambda s: (s['hd'], s['episode'], s['dungeon'], s['stage'], s['slot']))
    result['inputs'].update(resources.inputs)
    unique([(s['hd'], s['episode'], s['dungeon'], s['stage'], s['slot']) for s in result['scopes']], 'preload scopes')
    return result


def merge_boss_contacts(previous, resources, boss_uid, modes):
    result = copy.deepcopy(previous)
    if result['schema'] != 1:
        raise ValueError('Unsupported Boss contact registry')
    result['scopes'] = [s for s in result['scopes'] if tuple(s['key'][:4]) != SCOPE]
    definitions = {r['resource']: r for r in result['resources']}
    unique([r['resource'] for r in result['resources']], 'Boss contact resources')
    parts = []
    for mode, children in enumerate(modes):
        for child, name in enumerate(children):
            key = Path(name.replace('\\', '/')).name
            rows, _ = resources.mmo(name)
            definition = dict(resource=key, sha256=tables.sha(resources.read(name)),
                              rows=[[tables.i32(m, 8), m[4], checked_row(m)[1]] for m, _ in rows])
            if key in definitions and definitions[key] != definition:
                raise ValueError('Conflicting Boss contact identity: ' + key)
            definitions[key] = definition
            parts.append([mode, child, key])
    result['resources'] = [definitions[k] for k in sorted(definitions)]
    result['scopes'].extend(dict(key=[*SCOPE, slot], boss_uid=boss_uid, parts=parts) for slot in range(9))
    result['scopes'].sort(key=lambda s: s['key'])
    contact.rows(result)
    return result


def merge_hazards(previous, resources, profiles, targets, resource_rows, attacks):
    result = copy.deepcopy(previous)
    if result['schema'] != 2:
        raise ValueError('Unsupported scene hazard registry')
    policies = {p['resource']: p for p in result['policies']}
    unique([p['resource'] for p in result['policies']], 'hazard resources')
    # Counts follow the three selected stage scopes, not all nine alternatives.
    for profile in profiles:
        if profile[5] != 0:
            continue
        for target in targets[profile[9]:profile[9]+profile[10]]:
            raw, scaled, basis, association, ri, placement, selector, start, kind, reward, segment, _ = target
            if kind != 4:
                continue
            parent_selector = start + association if association >= 0 else selector
            if 0 <= parent_selector < profile[10]:
                parent = targets[profile[9]+parent_selector]
                if (parent[1] > 0 and parent[5] == placement and parent[4] == ri and
                        parent[10] == segment and attacks[(profile[6], parent_selector)] > 0):
                    continue
            name, digest, count = resource_rows[ri]
            mem = resources.mmo(name)[0][selector-start][0]
            attack = checked_row(mem)[1]
            if raw != 0 or scaled != 0 or reward != 0 or attack == 0:
                continue
            if name not in policies:
                policies[name] = dict(resource=name, sha256=digest, mmo_record_count=count,
                                      damage=attack, expected_selected_rows=0, scopes=[], rows=[])
            policy = policies[name]
            if (policy['sha256'], policy['mmo_record_count']) != (digest, count):
                raise ValueError('Conflicting scene contact identity')
            scope = dict(hd=0, episode=24, dungeon=0, stage=0, difficulty_mask=7)
            if scope not in policy['scopes']:
                policy['scopes'].append(scope)
            entry = dict(row=selector-start, basis=basis, association=association, damage=attack)
            if entry not in policy['rows']:
                policy['rows'].append(entry)
            policy['expected_selected_rows'] += 1
    result['policies'] = [policies[name] for name in sorted(policies)]
    for policy in result['policies']:
        policy['rows'].sort(key=lambda r: r['row'])
    return result


def generate(client, output, source_root=ROOT):
    client, output, source_root = Path(client).resolve(), Path(output).resolve(), Path(source_root).resolve()
    if not output.is_relative_to(ROOT / 'build') or output == source_root or output == client:
        raise ValueError('Output must be an isolated directory under build')
    resources = Resources(client)
    stage = codec.sstg(resources.read(STAGE))
    if tuple(stage['identity']) != SCOPE or len(stage['slots']) != 9:
        raise ValueError('First-challenge SSTG identity')
    if any(len(pool) != 61 for pool in stage['extra']):
        raise ValueError('First-challenge requires 61 independent preload resources per slot')
    monsters = {uid: (kind, name) for uid, kind, name in stage['monsters']}
    if len(monsters) != len(stage['monsters']) or any(not 0 <= uid <= 65535 for uid in monsters):
        raise ValueError('Invalid SSTG UID')
    bosses = [(uid, name) for uid, (kind, name) in monsters.items() if kind == 3]
    if len(bosses) != 1:
        raise ValueError('First-challenge requires one Boss')
    boss_uid, boss_name = bosses[0]
    modes = resources.boss_names(boss_name)
    if len(modes) != 1 or len(modes[0]) != 1:
        raise ValueError('Unreviewed first-challenge Boss structure')
    boss_rows = resources.mmo(modes[0][0])[0]
    shape = [(m[4], tables.i32(m, 8), tables.i32(m, 408)) for m, _ in boss_rows]
    if shape != [(4, 0, 24)] * 24 + [(3, 80000, -1)]:
        raise ValueError('First-challenge Boss component shape differs')
    hp = clean((source_root/tables.DATA).read_text('utf8'))
    boss = clean((source_root/tables.BOSS).read_text('utf8'))
    damage = clean((source_root/tables.DAMAGE).read_text('utf8'))
    terminal = clean((source_root/tables.TERMINAL_ITEMS).read_text('utf8'))
    profiles = tables.numeric_rows(hp, 'hp_sync_profiles')
    targets = tables.numeric_rows(hp, 'hp_sync_target_defs')
    resource_rows = [(n, h, int(c)) for n, h, c in re.findall(r'\{"([^"]+)","([A-F0-9]{64})",(\d+)u\}', tables.array(hp, 'hp_sync_resources')[1])]
    unique([n.lower() for n, _, _ in resource_rows], 'HP resource names')
    unique([(p[1], p[0], p[2], p[3], p[4], p[5]) for p in profiles], 'HP profiles', True)
    if any((p[1], p[0], p[2], p[3]) == SCOPE for p in profiles):
        raise ValueError('Existing first-challenge HP rows lack append ownership')
    resource_index = {(n.lower(), h): i for i, (n, h, _) in enumerate(resource_rows)}
    def register(name, count):
        name = Path(name.replace('\\', '/')).name
        digest = tables.sha(resources.read(name))
        key = (name.lower(), digest)
        if key not in resource_index:
            if any(n.lower() == name.lower() for n, _, _ in resource_rows):
                raise ValueError('Conflicting MMO resource name: ' + name)
            resource_index[key] = len(resource_rows)
            resource_rows.append((name, digest, count))
        if resource_rows[resource_index[key]][2] != count:
            raise ValueError('MMO record count differs')
        return resource_index[key]
    old_resource_count, old_target_count = len(resource_rows), len(targets)
    bp = tables.numeric_rows(boss, 'boss_component_boss_profiles')
    bm = tables.numeric_rows(boss, 'boss_component_boss_modes')
    bc = tables.numeric_rows(boss, 'boss_component_boss_components')
    new_profiles, new_targets, new_bp, new_bm, new_bc, terminal_rows = [], [], [], [], [], []
    added = [[], [], [], []]
    summary, attacks, contact_ranges = [], {}, []
    for slot, (smmo, percent, _) in enumerate(stage['slots']):
        if percent != 100:
            raise ValueError('First-challenge HP percent differs')
        placements = resources.placements(smmo)
        if len(placements) != 299 or any(p[2] not in monsters for p in placements):
            raise ValueError('First-challenge placement table differs')
        scheduled = {p[2] for p in placements}
        key = lambda uid: struct.pack('<5BH', *SCOPE, slot, uid)
        for uid, (kind, name) in monsters.items():
            if kind != 0:
                continue
            rows, _ = resources.mmo(name)
            first = next((m for m, _ in rows if tables.i32(m, 8) > 0), None)
            if first is not None:
                checked_row(first)
                added[0].append(key(uid) + struct.pack('<iB4i', *tables.template(first)))
        start, selector = old_target_count + len(new_targets), 0
        for placement, (_, _, uid, _) in enumerate(placements):
            kind, name = monsters[uid]
            if kind != 0:
                continue
            rows, _ = resources.mmo(name)
            ri, placement_start = register(name, len(rows)), selector
            for mem, _ in rows:
                raw, attack = checked_row(mem)
                scaled = raw * percent // 100
                new_targets.append((raw, scaled, tables.i32(mem, 20), tables.i32(mem, 408),
                                    ri, placement, selector, placement_start, mem[4], mem[24], slot % 3, percent))
                attacks[(slot, selector)] = attack
                if raw > 0 and scaled > 0:
                    added[3].append(key(selector) + struct.pack('<H', uid) + struct.pack('<iB4i', *tables.template(mem, min(raw, scaled))))
                    if contact_ranges and contact_ranges[-1][:5] == (*SCOPE, slot) and contact_ranges[-1][6] + 1 == selector and contact_ranges[-1][7] == attack:
                        contact_ranges[-1] = (*contact_ranges[-1][:6], selector, attack)
                    else:
                        contact_ranges.append((*SCOPE, slot, selector, selector, attack))
                if mem[26] == 5 and mem[24] != 5 and raw > 0 and scaled > 0 and mem[4] != 4:
                    terminal_rows.append(old_target_count + len(new_targets) - 1)
                selector += 1
        if selector != 629:
            raise ValueError('First-challenge ordinary row count differs')
        new_profiles.append((24, 0, 0, 0, slot//3, slot%3, slot, percent, 0, start, selector))
        first_mode, total_hp, total_score = len(bm)+len(new_bm), 0, 0
        for mode, children in enumerate(modes):
            first_component, mode_hp, component_count = len(bc)+len(new_bc), 0, 0
            for child, name in enumerate(children):
                for ordinal, (mem, _) in enumerate(resources.mmo(name)[0]):
                    raw, _ = checked_row(mem)
                    scaled = raw * percent // 100
                    new_bc.append((scaled, tables.i32(mem, 20), child, ordinal, mem[4], 0))
                    component_count += 1
                    mode_hp += scaled
                    if scaled > 0:
                        template = tables.template(mem, scaled)
                        total_hp += scaled
                        total_score += template[4]
                        added[2].append(key(boss_uid) + struct.pack('<BBi', mode, child, ordinal) + struct.pack('<iB4i', *template))
            new_bm.append((first_component, mode_hp, component_count, 0))
        new_bp.append((*SCOPE, slot, len(modes), 0, 0, first_mode, 0))
        added[1].append(key(boss_uid) + struct.pack('<iiB', total_hp, total_score, boss_uid in scheduled))
        summary.append(dict(stage=0, slot=slot, smmo=smmo, percent=percent, placements=len(placements),
                            targets=selector, positive_hp=sum(t[0] > 0 for t in new_targets[-selector:]),
                            preload_resources=len(stage['extra'][slot]), boss_modes=len(modes),
                            boss_children=list(map(len, modes)), boss_components=component_count,
                            boss_hp=total_hp, boss_score=total_score,
                            boss_effects=resources.bmo_effects[boss_name]))
    pons = resources.projectiles([name for kind, name in monsters.values() if kind in (0, 3)] +
                                [name for pool in stage['extra'] for name in pool])
    values = [int(v) for v in re.findall(r'(\d+)u', tables.array(damage, 'stage_damage_stage_attack_values')[1])]
    dr_count = len(re.findall(r'^\s*\{', tables.array(damage, 'stage_damage_stage_attack_resources')[1], re.M))
    ds_count = len(re.findall(r'^\s*\{', tables.array(damage, 'stage_damage_stage_attack_scopes')[1], re.M))
    new_values, new_dr, new_ds = [], [], []
    grouped = {}
    for name, (owner, damage_values) in sorted(pons.items()):
        grouped.setdefault(owner, []).append((name, damage_values))
    for difficulty in range(3):
        first = dr_count + len(new_dr)
        for owner, entries in sorted(grouped.items()):
            name, attack_values = entries[0]
            ambiguous = len({tuple(v) for _, v in entries}) > 1
            at = len(values) + len(new_values)
            new_values.extend(attack_values)
            new_dr.append('    {' + f'{owner}u,{len(attack_values)}u,{at}u,{int(ambiguous)}u,"{name}"' + '},')
        new_ds.append('    {' + f'0u,0u,0u,{difficulty}u,0u,24u,{len(grouped)}u,{first}u,"{stage["slots"][difficulty*3][0]}"' + '},')
    hp = append(hp, 'hp_sync_profiles', [tables.hp_profile_row(p) for p in new_profiles], r'^[ \t]*\{0,1,')
    hp = append(hp, 'hp_sync_target_defs', [tables.row(t) for t in new_targets])
    hp = append(hp, 'hp_sync_resources', [f'    {{"{n}","{h}",{c}u}},' for n, h, c in resource_rows[old_resource_count:]])
    for macro, count in [('PROFILE_COUNT', len(profiles)+len(new_profiles)), ('TARGET_DEF_COUNT', len(targets)+len(new_targets)),
                         ('RESOURCE_COUNT', len(resource_rows)), ('MAX_PROFILE_TARGETS', max(p[10] for p in profiles+new_profiles))]:
        hp = tables.define(hp, 'HP_SYNC_' + macro, count)
    unique([(p[1], p[0], p[2], p[3], p[4], p[5]) for p in tables.numeric_rows(hp, 'hp_sync_profiles')], 'merged HP profiles', True)
    for name, entries in [('profiles', new_bp), ('modes', new_bm), ('components', new_bc)]:
        boss = append(boss, 'boss_component_boss_' + name, [tables.row(e) for e in entries])
    all_bp, all_bm, all_bc = bp+new_bp, bm+new_bm, bc+new_bc
    unique([p[:5] for p in all_bp], 'Boss profiles')
    for macro, count in [('STAGE_COUNT', len({p[:4] for p in all_bp})), ('PROFILE_COUNT', len(all_bp)), ('MODE_COUNT', len(all_bm)),
                         ('COMPONENT_COUNT', len(all_bc)), ('CHILD_COUNT', sum(len({c[2] for c in all_bc[m[0]:m[0]+m[2]]}) for m in all_bm)),
                         ('MAX_MODE_COUNT', max(p[5] for p in all_bp)), ('MAX_MODE_COMPONENTS', max(m[2] for m in all_bm))]:
        boss = tables.define(boss, 'BOSS_COMPONENT_BOSS_' + macro, count)
    digest = tables.sha(json.dumps(all_bp).encode()+json.dumps(all_bm).encode()+json.dumps(all_bc).encode())
    boss = re.sub(r'(#define BOSS_COMPONENT_BOSS_LEDGER_SHA256 )"[A-F0-9]+"', lambda m: m[1]+'"'+digest+'"', boss)
    for name, lines, count in [('values', [str(v)+'u,' for v in new_values], len(values)+len(new_values)),
                               ('resources', new_dr, dr_count+len(new_dr)), ('scopes', new_ds, ds_count+len(new_ds))]:
        array = 'stage_damage_stage_attack_' + name
        damage = append(damage, array, lines, r'^[ \t]*\{1u,' if name == 'scopes' else None)
        damage = resize(damage, array, 'STAGE_DAMAGE_STAGE_ATTACK_' + {'values':'VALUE', 'resources':'RESOURCE', 'scopes':'SCOPE'}[name] + '_COUNT', count)
    scope_rows = [tuple(map(int, m.groups())) for m in re.finditer(
        r'\{(\d+)u,(\d+)u,(\d+)u,(\d+)u,(\d+)u,(\d+)u,',
        tables.array(damage, 'stage_damage_stage_attack_scopes')[1])]
    unique([(s[0], s[5], s[1], s[2], s[3]) for s in scope_rows], 'PON scopes', True)
    terminal_count = len(re.findall(r'\d+u', tables.array(terminal, 'terminal_item_drop_rows')[1]))
    terminal = append(terminal, 'terminal_item_drop_rows', [f'    {i}u,' for i in terminal_rows])
    terminal = tables.define(terminal, 'TERMINAL_ITEM_DROP_ROW_COUNT', terminal_count+len(terminal_rows))
    dcc = merge_dcc((source_root/tables.CATALOG).read_bytes(), added)
    preloaded = merge_preloads(json.loads((source_root/PRELOAD).read_text('utf8')), resources, stage, new_profiles)
    boss_contacts = merge_boss_contacts(json.loads((source_root/contact.REGISTRY).read_text('utf8')), resources, boss_uid, modes)
    outputs = {tables.DATA: hp.encode(), tables.BOSS: boss.encode(), tables.DAMAGE: damage.encode(),
               tables.TERMINAL_ITEMS: terminal.encode(), tables.CATALOG: dcc,
               PRELOAD: (json.dumps(preloaded, indent=2)+'\n').encode(), PRELOAD.with_suffix('.inc'): preload.render(preloaded).encode(),
               contact.REGISTRY: contact.render(boss_contacts).encode()}
    for path, array, macro, entries in [
        (BOSS_CONTACT, 'boss_contact_rows', 'BOSS_CONTACT_ROW_COUNT', [r for r in contact.rows(boss_contacts) if r[:4] == SCOPE]),
        (MONSTER_CONTACT, 'monster_contact_rows', 'MONSTER_CONTACT_ROW_COUNT', contact_ranges)]:
        text = clean((source_root/path).read_text('utf8'))
        count = len(tables.numeric_rows(text, array))
        text = append(text, array, [tables.row(r) for r in entries], r'^[ \t]*\{1u,')
        keys = [r[:8] if path == BOSS_CONTACT else r[:6] for r in tables.numeric_rows(text, array)]
        unique(keys, 'contact keys', True)
        outputs[path] = tables.define(text, macro, count+len(entries)).encode()
    old_hazards = json.loads((source_root/HAZARD).read_text('utf8'))
    for policy in old_hazards['policies']:
        matching = [s for s in policy['scopes'] if (s['hd'], s['episode'], s['dungeon'], s['stage']) == SCOPE]
        if matching and len(policy['scopes']) != len(matching):
            raise ValueError('Mixed first-challenge hazard ownership')
    old_hazards['policies'] = [p for p in old_hazards['policies'] if not any((s['hd'], s['episode'], s['dungeon'], s['stage']) == SCOPE for s in p['scopes'])]
    hazards = merge_hazards(old_hazards, resources, new_profiles, targets+new_targets, resource_rows, attacks)
    outputs[HAZARD] = hazard_resources.render_registry(hazards).encode()
    counts = dict(registered_hazards=sum(p['expected_selected_rows'] for p in hazards['policies']))
    outputs[HAZARD.with_name('scene_hazard_catalog.inc')] = hazard.render(hazards, counts).encode()
    for path, data in outputs.items():
        destination = output/path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    dotnet = ROOT/'.dotnet/dotnet.exe'
    command = [str(dotnet) if dotnet.is_file() else 'dotnet', 'run', '--configuration', 'Release',
               '--artifacts-path', str(output/'.combat-score-tool'),
               '--project', str(ROOT/'scripts/combat-score-generator/CombatScoreGenerator.csproj'),
               '--', str(output/tables.CATALOG), str(output/tables.DATA), str(output/SCORE)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors='replace', timeout=180)
    if completed.returncode:
        raise ValueError('Combat score generation failed: ' + completed.stdout + completed.stderr)
    outputs[SCORE] = (output/SCORE).read_bytes()
    report = dict(schema=1, resource_identity=list(SCOPE), runtime_accepted=False,
                  score_policy='floor(MMO Score / 10); existing DCC7 scores retained',
                  bmo_schema='BMO2 flag0, 308-byte mode header, 208-byte child; complete boundary checked',
                  stages=summary, dcc_added=list(map(len, added)), terminal_item_rows_added=len(terminal_rows),
                  preload_rows_added=sum(s['preload_count'] for s in preloaded['scopes'] if s['episode'] == 24),
                  pon_resources=len(pons), inputs=resources.inputs,
                  outputs={p.as_posix(): dict(size=len(b), sha256=tables.sha(b)) for p, b in outputs.items()})
    for summary_row, scope in zip(summary, [s for s in preloaded['scopes']
                                          if (s['hd'], s['episode'], s['dungeon'], s['stage']) == SCOPE]):
        summary_row['preload_targets'] = scope['preload_count']
    (output/'monk-combat-generation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8', newline='\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    report = generate(args.client, args.output, args.source_root)
    if args.manifest:
        if args.manifest.resolve() != ROOT/'manifest/monk_combat.json':
            raise ValueError('Manifest destination must be manifest/monk_combat.json')
        args.manifest.write_text(json.dumps(report, indent=2)+'\n', encoding='utf8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('inputs', 'stages')}, indent=2))


if __name__ == '__main__':
    main()
