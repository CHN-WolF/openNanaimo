"""Build a review-only Korean L7 resource candidate from a client overlay."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from pathlib import Path
import json
import struct

import lumineos_codec as codec
import port_lumineos_resources as port

EXTENSIONS = {'.sstg', '.smmo', '.mmo', '.pon', '.bmo', '.eff', '.im3', '.crs', '.wav', '.ogg'}

def text_refs(values):
    result = []
    for value in values:
        if isinstance(value, bytes):
            if not any(value.lower().endswith(ext.encode('ascii')) for ext in EXTENSIONS):
                continue
            value = value.decode('ascii')
        result.append(value)
    return result


def find(root, name, by_name, source_path):
    name = name.replace('\\', '/')
    direct = root / name
    if direct.is_file():
        return direct
    local = source_path.parent / Path(name).name
    if local.is_file():
        return local
    if source_path.suffix.lower() in ('.sstg', '.sm2'):
        folder = ('images/game_images/shootinggamebasic/shootingimages'
                  if Path(name).suffix.lower() == '.im3' else 'effs/game/shootinggamebasic/map')
        mapped = root / folder / Path(name).name
        if mapped.is_file():
            return mapped
    choices = by_name.get(Path(name).name.lower(), [])
    if len(choices) != 1:
        raise ValueError(f'missing/ambiguous resource: {name}')
    return choices[0]


def combat_closure(root):
    root = port.clean_root(root)
    by_name = defaultdict(list)
    for folder in ('flying', 'effs', 'images', 'sounds'):
        for path in (root / folder).rglob('*'):
            if path.is_file():
                by_name[path.name.lower()].append(path)
    queue = deque([root / f'flying/hd0_ep22_dg00_st{stage:02}.sstg' for stage in (0, 1)])
    nodes, edges = {}, []
    while queue:
        path = queue.popleft()
        rel = path.relative_to(root).as_posix()
        if rel in nodes:
            continue
        raw = path.read_bytes()
        ext = path.suffix.lower()
        refs = []
        if ext == '.sstg':
            model = codec.sstg(raw)
            refs = [name for _, kind, name in model['monsters'] if kind in (0, 3)]
            refs += [slot[0] for slot in model['slots']]
        elif ext == '.smmo':
            plain = codec.xor(raw, 40)
            count = struct.unpack_from('<I', plain)[0]
            if len(plain) != 4 + count * 16 + 260:
                raise ValueError('invalid SMMO: ' + rel)
        elif ext == '.mmo' and raw[:4] != b'\x3a\x38\x38\x38':
            model = codec.mmo_model(raw, root, True)
            refs = text_refs(model[2])
        elif ext == '.mmo' or ext == '.bmo':
            plain = codec.xor(raw, 56)
            if struct.unpack_from('<I', plain)[0] != 2 or (len(plain) - 44) % 516:
                raise ValueError('invalid BMO2: ' + rel)
            for off in range(44, len(plain), 516):
                refs.append(plain[off + 308:off + 516].split(b'\0', 1)[0].decode('ascii'))
        elif ext == '.pon':
            model = codec.pon_model(raw, root, True)
            refs = text_refs(model[4])
        elif ext == '.eff':
            refs = codec.eff2(raw)['refs']
        elif ext == '.sm2':
            refs = codec.sm2(raw)['refs'] + ['images/game_images/shootinggamebasic/coll/tile_16_16.crs']
        nodes[rel] = dict(size=len(raw), sha256=port.digest(raw))
        for name in sorted(set(refs)):
            if Path(name).suffix.lower() not in EXTENSIONS:
                continue
            target = find(root, name, by_name, path)
            target_rel = target.relative_to(root).as_posix()
            edges.append(dict(source=rel, reference=name, target=target_rel))
            queue.append(target)
    return nodes, edges


def convert(source, current, rel):
    raw = (source / rel).read_bytes()
    ext = Path(rel).suffix.lower()
    if ext == '.mmo' and raw[:4] != b'\x3a\x38\x38\x38':
        return codec.convert_mmo(raw, source)[0], 'mmo200'
    if ext == '.pon':
        return codec.convert_pon(raw, source)[0], 'pon106'
    if ext == '.sstg':
        stage = int(Path(rel).stem[-2:])
        accepted = ((0, 0, 0, 0),) if stage == 0 else ((0, 100, 6, 1),)
        return codec.patch_sstg_identity(raw, (0, 100, 6, stage), accepted), 'sstg-l7'
    return raw, 'copy'


def review(source, client, output):
    source, client, output = map(port.clean_root, (source, client, output))
    if output.exists() or output.is_relative_to(source):
        raise ValueError('review output must be fresh and independent')
    port.verify(client)
    nodes, edges = combat_closure(source)
    old = port.load(port.RECIPE)
    installed = port.load(port.safe(client, port.MARKER))
    installed_by_path = {row['path']: row['sha256'] for row in installed['files'] + installed['preserve_l7_combat']}
    rows = {row['path']: row for row in old['files']}
    preserved = {row['path']: row for row in old['preserve_l7_combat']}
    current_rows = rows | preserved
    reviewed = []
    for rel, source_identity in sorted(nodes.items()):
        target = port.safe(client, rel)
        if not target.is_file() and rel in current_rows:
            raise ValueError('CN target missing: ' + rel)
        data, transform = convert(source, client, rel)
        before = port.digest(target.read_bytes()) if target.is_file() else None
        episode_owned = 'ep22' in Path(rel).name.lower()
        if Path(rel).suffix.lower() == '.mmo' and not episode_owned:
            if codec.mmo_model((source / rel).read_bytes(), source, True) == codec.mmo_model(target.read_bytes(), client, False):
                continue
        if Path(rel).suffix.lower() == '.pon' and not episode_owned:
            if codec.pon_model((source / rel).read_bytes(), source, True) == codec.pon_model(target.read_bytes(), client, False):
                continue
        if rel.endswith('.sstg') or episode_owned or before != source_identity['sha256']:
            expected_before = installed_by_path.get(rel, current_rows.get(rel, {}).get('baseline_sha256', current_rows.get(rel, {}).get('sha256')))
            if expected_before is not None and expected_before != before:
                raise ValueError('CN baseline changed: ' + rel)
            rows[rel] = dict(path=rel, source_sha256=source_identity['sha256'],
                             source_size=source_identity['size'], baseline_sha256=before,
                             transform=transform, output_sha256=port.digest(data), output_size=len(data))
            preserved.pop(rel, None)
            port.atomic(output / 'payload' / rel, data)
            reviewed.append(dict(path=rel, transform=transform, before_sha256=before,
                                 output_sha256=port.digest(data), output_size=len(data)))
        else:
            continue
    alias = 'flying/hd0_ep22_dg01_st01.sstg'
    source_rel = 'flying/hd0_ep22_dg00_st01.sstg'
    alias_source = nodes[source_rel]
    alias_target = port.safe(client, alias)
    alias_before = port.digest(alias_target.read_bytes()) if alias_target.is_file() else None
    alias_data, alias_transform = convert(source, client, source_rel)
    expected_alias = installed_by_path.get(alias, current_rows.get(alias, {}).get('baseline_sha256', current_rows.get(alias, {}).get('sha256')))
    if expected_alias is not None and expected_alias != alias_before:
        raise ValueError('CN baseline changed: ' + alias)
    rows[alias] = dict(path=alias, source_path=source_rel, source_sha256=alias_source['sha256'],
                       source_size=alias_source['size'], baseline_sha256=alias_before,
                       transform=alias_transform, output_sha256=port.digest(alias_data),
                       output_size=len(alias_data))
    preserved.pop(alias, None)
    port.atomic(output / 'payload' / alias, alias_data)
    reviewed.append(dict(path=alias, transform=alias_transform, before_sha256=alias_before,
                         output_sha256=port.digest(alias_data), output_size=len(alias_data)))
    alias = 'flying/pon/mis_ep22_dg01_m_196_02.pon'
    source_rel = 'flying/pon/mis_ep22_dg01_m_196.pon'
    alias_source = nodes.get(source_rel, {'sha256': port.digest((source / source_rel).read_bytes()), 'size': (source / source_rel).stat().st_size})
    alias_target = port.safe(client, alias)
    alias_before = port.digest(alias_target.read_bytes()) if alias_target.is_file() else None
    alias_data, alias_transform = convert(source, client, source_rel)
    expected_alias = installed_by_path.get(alias, current_rows.get(alias, {}).get('baseline_sha256', current_rows.get(alias, {}).get('sha256')))
    if expected_alias is not None and expected_alias != alias_before:
        raise ValueError('CN baseline changed: ' + alias)
    rows[alias] = dict(path=alias, source_path=source_rel, source_sha256=alias_source['sha256'],
                       source_size=alias_source['size'], baseline_sha256=alias_before,
                       transform=alias_transform, output_sha256=port.digest(alias_data),
                       output_size=len(alias_data))
    preserved.pop(alias, None)
    port.atomic(output / 'payload' / alias, alias_data)
    reviewed.append(dict(path=alias, transform=alias_transform, before_sha256=alias_before,
                         output_sha256=port.digest(alias_data), output_size=len(alias_data)))
    recipe = dict(old, scope='KR L7 combat resource closure; preserve unrelated CN resources',
                  files=[rows[key] for key in sorted(rows)],
                  preserve_l7_combat=[preserved[key] for key in sorted(preserved)],
                  compatible_recipe_sha256s=[])
    recipe['upgrade_from_manifest_ids'] = sorted(set(recipe.get('upgrade_from_manifest_ids', []) + [installed['id']]))
    for row in recipe['files']:
        if row['path'] in installed_by_path:
            row['baseline_sha256'] = installed_by_path[row['path']]
    for row in recipe['preserve_l7_combat']:
        if row['path'] in installed_by_path:
            row['sha256'] = installed_by_path[row['path']]
    manifest = dict(schema=port.SCHEMA, recipe_sha256=port.digest(port.encoded(recipe)),
                    scope=recipe['scope'], runtime_accepted=False, files=reviewed,
                    preserve_l7_combat=recipe['preserve_l7_combat'])
    manifest['id'] = port.digest(port.encoded(manifest))
    port.atomic(output / 'recipe.json', port.encoded(recipe))
    port.atomic(output / 'manifest.json', port.encoded(manifest))
    report = dict(runtime_accepted=False, nodes=len(nodes), edges=len(edges), files=len(reviewed),
                  preserved=len(preserved), transforms={})
    for row in reviewed:
        report['transforms'][row['transform']] = report['transforms'].get(row['transform'], 0) + 1
    port.atomic(output / 'review.json', port.encoded(dict(report=report, nodes=nodes, edges=edges)))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(review(**vars(parser.parse_args())), ensure_ascii=False, indent=2))
