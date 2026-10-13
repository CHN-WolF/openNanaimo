"""Install the fifth-village challenge entrance and four foreground positions.

The client already maps action 168..171 to native entry indexes 8..11 and
the existing resource selector resolves those indexes to episode 24..27.
The transaction updates VIL action WORDs and four foreground entry markers.
It preserves the executable, combat catalogs, target ledgers and account data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid

try:
    from . import port_lumineos_resources as io
    from . import prepare_monk_entry as scene_preview
except ImportError:
    import port_lumineos_resources as io
    import prepare_monk_entry as scene_preview


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'openNanaimo.monk-village-entry.v1'
PACK_REL = 'Village_map_image/Village_map_image.pack'
MARKER = '.openNanaimo-monk-village-entry.json'
ACTIVE_EPISODES = (24,)


def action_value(entry):
    return entry['action'] if entry['episode'] in ACTIVE_EPISODES else -1
VISUAL_RESOURCE = 'effs/village/village_inout_01.eff'

# The selected cells are existing walkable empty space.  Do not move a road,
# destination field, arrival marker, or collision boundary.
ENTRIES = (
    dict(page=9, action=168, entry_index=8, episode=24,
         cells=tuple((x, y) for x in range(44, 48) for y in range(14, 21)),
         placement=[720.0, 280.0, 0.0]),
    dict(page=10, action=169, entry_index=9, episode=25,
         cells=tuple((x, y) for x in range(44, 48) for y in range(14, 21)),
         placement=[720.0, 280.0, 0.0]),
    dict(page=11, action=170, entry_index=10, episode=26,
         cells=tuple((x, y) for x in range(22, 28) for y in range(3, 5)),
         placement=[400.0, 64.0, 0.0]),
    dict(page=12, action=171, entry_index=11, episode=27,
         cells=tuple((x, y) for x in range(22, 28) for y in range(2, 4)),
         placement=[400.0, 48.0, 0.0]),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def require(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


class FifthVillagePack:
    def __init__(self, data: bytes):
        self.data = bytes(data)
        scene_preview.scenes.records(self.data)
        require(self.data[:9] == b'NANA_PACK', 'invalid village pack signature')
        count = struct.unpack_from('<I', self.data, 9)[0]
        require(count >= 25 and 13 + count * 8 <= len(self.data), 'invalid village pack directory')
        self.records = {}
        self.directory = []
        for i in range(count):
            key, offset = struct.unpack_from('<II', self.data, 13 + i * 8)
            require(key not in self.records, 'duplicate village record')
            self.records[key] = offset
            self.directory.append((key, offset))
        self.pages = {}
        for page in range(25):
            offset = self.records.get(50000 + page)
            require(offset is not None, f'missing fifth-village page {page}')
            size = struct.unpack_from('<I', self.data, offset)[0]
            end = offset + 4 + size
            require(end <= len(self.data), f'truncated fifth-village page {page}')
            require(struct.unpack_from('<4I', self.data, offset + 20) == (16, 16, 50, 36),
                    f'unexpected page {page} dimensions')
            cursor = offset + 300
            for _ in range(64):
                require(cursor + 4 <= end, f'truncated page {page} texture table')
                texture = struct.unpack_from('<i', self.data, cursor)[0]
                cursor += 4
                if texture == -1:
                    break
                require(cursor + 260 <= end, f'truncated page {page} texture name')
                cursor += 260
            require(cursor + 50 * 36 * 36 <= end, f'truncated page {page} grid')
            self.pages[page] = cursor

    def offset(self, page: int, x: int, y: int, field: int) -> int:
        require(page in self.pages and 0 <= x < 50 and 0 <= y < 36 and 0 <= field < 18,
                'village cell out of range')
        return self.pages[page] + (x * 36 + y) * 36 + field * 2

    def field(self, page: int, x: int, y: int, field: int) -> int:
        return struct.unpack_from('<h', self.data, self.offset(page, x, y, field))[0]

    def record(self, page: int) -> bytes:
        offset = self.records[50000 + page]
        size = struct.unpack_from('<I', self.data, offset)[0]
        return self.data[offset + 4:offset + 4 + size]


def _scene_with_visual(raw: bytes, placement: list[float]) -> bytes:
    scene = scene_preview.VillageScene(raw)
    name = VISUAL_RESOURCE.encode('ascii').lower()
    matches = [uid for uid, value in scene.textures if value.split(b'\0', 1)[0].replace(b'\\', b'/').lower() == name]
    require(len(matches) <= 1, 'duplicate native village entry visual')
    textures = list(scene.textures)
    if matches:
        uid = matches[0]
    else:
        occupied = {value for value, _ in textures}
        require(len(textures) < 63, 'no native texture slot for village entry visual')
        uid = next(i for i in range(64) if i not in occupied)
        textures.append((uid, name.replace(b'/', b'\\').ljust(260, b'\0')))
    expected = struct.pack('<I3f', uid, *placement)
    layers = [list(rows) for rows in scene.layers]
    existing = [(layer, row) for layer, rows in enumerate(layers) for row in rows
               if struct.unpack_from('<I', row)[0] == uid]
    require(all(layer == 2 for layer, _ in existing), 'entry visual is used outside foreground layer')
    if expected not in layers[2]:
        layers[2].append(expected)
    output = bytearray(scene.raw[:scene.grid_start + 50 * 36 * 36])
    for index, value in textures:
        output += struct.pack('<i', index) + value
    output += struct.pack('<i', -1)
    for rows in layers:
        output += struct.pack('<I', len(rows)) + b''.join(rows)
    output += scene.tail
    return bytes(output)


def _replace_records(data: bytes, updates: dict[int, bytes]) -> bytes:
    pack = FifthVillagePack(data)
    rows = []
    for key, offset in pack.directory:
        size = struct.unpack_from('<I', data, offset)[0]
        body = updates.get(key, data[offset + 4:offset + 4 + size])
        rows.append((key, body))
    if all(body == data[offset + 4:offset + 4 + struct.unpack_from('<I', data, offset)[0]]
           for (_, body), (_, offset) in zip(rows, pack.directory)):
        return data
    header = 13 + len(rows) * 8
    output = bytearray(b'NANA_PACK' + struct.pack('<I', len(rows)))
    offset = header
    for key, body in rows:
        output += struct.pack('<II', key, offset)
        offset += 4 + len(body)
    for _, body in rows:
        output += struct.pack('<I', len(body)) + body
    return bytes(output)


def _row(entry):
    return dict(page=entry['page'], action=entry['action'], entry_index=entry['entry_index'],
                episode=entry['episode'], cells=[list(cell) for cell in entry['cells']],
                placement=entry['placement'])


def validate_entry_cells(pack: FifthVillagePack, data: bytes) -> None:
    for entry in ENTRIES:
        for x, y in entry['cells']:
            # field 7 is walkability/collision; fields 10/11 are destination
            # and arrival metadata; field 14 is the return marker.
            require(pack.field(entry['page'], x, y, 7) == 0,
                    f'entry cell is not walkable: page={entry["page"]} x={x} y={y}')
            require(pack.field(entry['page'], x, y, 10) == -1 and
                    pack.field(entry['page'], x, y, 11) == -1 and
                    pack.field(entry['page'], x, y, 14) == -1,
                    f'entry cell overlaps route metadata: page={entry["page"]} x={x} y={y}')
            action = pack.field(entry['page'], x, y, 13)
            require(action in (-1, entry['action']),
                    f'entry action conflict: page={entry["page"]} x={x} y={y} action={action}')


def derive(data: bytes) -> tuple[bytes, dict]:
    pack = FifthVillagePack(data)
    validate_entry_cells(pack, data)
    output = bytearray(data)
    changes = []
    for entry in ENTRIES:
        for x, y in entry['cells']:
            offset = pack.offset(entry['page'], x, y, 13)
            before = struct.unpack_from('<h', output, offset)[0]
            if before == action_value(entry):
                continue
            require(before == -1, f'unexpected action before patch at {entry["page"]},{x},{y}')
            struct.pack_into('<h', output, offset, action_value(entry))
            changes.append(dict(page=entry['page'], x=x, y=y, field=13,
                                before=before, after=entry['action']))
    result = bytes(output)
    visual_changes = []
    updates = {50000 + entry['page']: _scene_with_visual(FifthVillagePack(result).record(entry['page']), entry['placement'])
               for entry in ENTRIES}
    result = _replace_records(result, updates)
    for entry in ENTRIES:
        visual_changes.append(dict(page=entry['page'], resource=VISUAL_RESOURCE, placement=entry['placement']))
    verify(result)
    manifest = dict(
        schema=SCHEMA,
        runtime_accepted=False,
        status='native-action-bound-unverified',
        pack_path=PACK_REL,
        input_size=len(data),
        input_sha256=digest(data),
        output_size=len(result),
        output_sha256=digest(result),
        unchanged_file_size=len(data) == len(result),
        entry_chain=dict(action_range=[160, 182], setter_va='0xA74450',
                         resource_loader_va='0x66EC30',
                         selector_rule='entry8 -> local hd0/ep24/dg0/st0; entries9..11 reserved'),
        entries=[_row(entry) for entry in ENTRIES],
        active_episodes=list(ACTIVE_EPISODES),
        changes=changes,
        visual_resource=VISUAL_RESOURCE,
        visual_changes=visual_changes,
        combat_boundary=dict(
            combat_catalog='manifest/monk_combat.json',
            resource_identity=[0, 24, 0, 0],
            kind_hp_ledgers='preserved; no target KIND/HP/reward rows are rewritten by this transaction'),
    )
    manifest['id'] = digest(encoded(manifest))
    return result, manifest


def verify(data: bytes, manifest: dict | None = None, client_root: Path | None = None) -> dict:
    pack = FifthVillagePack(data)
    validate_entry_cells(pack, data)
    rows = []
    for entry in ENTRIES:
        scene = scene_preview.VillageScene(pack.record(entry['page']))
        matches = [uid for uid, name in scene.textures
                   if name.split(b'\0', 1)[0].replace(b'\\', b'/').lower()
                   == VISUAL_RESOURCE.encode('ascii')]
        require(len(matches) == 1, 'missing or duplicate entry visual resource')
        expected = struct.pack('<I3f', matches[0], *entry['placement'])
        require(scene.layers[2].count(expected) == 1, 'missing or duplicate entry foreground marker')
        require(all(struct.unpack_from('<I', row)[0] != matches[0]
                    for layer in scene.layers[:2] for row in layer), 'entry visual outside foreground layer')
        count = 0
        for x, y in entry['cells']:
            value = pack.field(entry['page'], x, y, 13)
            require(value == action_value(entry),
                    f'missing action {entry["action"]} at page={entry["page"]} x={x} y={y}')
            count += int(entry['episode'] in ACTIVE_EPISODES)
        rows.append(dict(page=entry['page'], action=action_value(entry), episode=entry['episode'], cells=count, active=entry['episode'] in ACTIVE_EPISODES))
    if manifest is not None:
        validate_manifest(manifest)
        require(manifest.get('output_sha256') == digest(data) and manifest.get('output_size') == len(data),
                'installed pack digest or size differs')
        if client_root is not None:
            resource = io.safe(client_root, manifest['visual_resource'])
            if (not resource.is_file() and client_root.name.lower() == 'client_compatibility_overlay'
                    and client_root.parent.name.lower() == 'adapter_data'):
                resource = io.safe(client_root.parent.parent, manifest['visual_resource'])
            require(resource.is_file() and resource.stat().st_size == manifest['visual_resource_size']
                    and digest(resource.read_bytes()) == manifest['visual_resource_sha256'],
                    'entry visual resource differs')
    return dict(schema=SCHEMA, verified=len(rows), cells=sum(row['cells'] for row in rows), entries=rows,
                size=len(data), sha256=digest(data), runtime_accepted=False)


def validate_manifest(manifest: dict) -> None:
    require(manifest.get('schema') == SCHEMA, 'unsupported monk entry manifest')
    require(manifest.get('pack_path') == PACK_REL and manifest.get('visual_resource') == VISUAL_RESOURCE,
            'unexpected entry resource path')
    require(manifest.get('entries') == [_row(entry) for entry in ENTRIES], 'entry contract differs')
    require(manifest.get('active_episodes') == list(ACTIVE_EPISODES), 'active entry scope differs')
    require(manifest.get('runtime_accepted') is False, 'unexpected entry acceptance status')
    require(manifest.get('id') == digest(encoded({k: v for k, v in manifest.items() if k != 'id'})),
            'entry manifest identity differs')
    for key in ('input_sha256', 'output_sha256', 'visual_resource_sha256'):
        value = manifest.get(key)
        require(isinstance(value, str) and len(value) == 64
                and all(c in '0123456789abcdef' for c in value), 'invalid resource digest')
    for key in ('input_size', 'output_size', 'visual_resource_size'):
        require(isinstance(manifest.get(key), int) and manifest[key] > 0, 'invalid resource size')


def build(source_root: Path, output_root: Path) -> dict:
    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    require(source_root != output_root and not output_root.exists(), 'source/output overlap or output exists')
    source = io.safe(source_root, PACK_REL)
    result, manifest = derive(source.read_bytes())
    visual = io.safe(source_root, VISUAL_RESOURCE).read_bytes()
    manifest['visual_resource_size'] = len(visual)
    manifest['visual_resource_sha256'] = digest(visual)
    manifest['id'] = digest(encoded({key: value for key, value in manifest.items() if key != 'id'}))
    output_root.mkdir(parents=True)
    io.atomic(io.safe(output_root, PACK_REL), result)
    io.atomic(output_root / 'manifest.json', encoded(manifest))
    return dict(status='built', bundle=str(output_root), id=manifest['id'],
                output_sha256=manifest['output_sha256'], cells=len(manifest['changes']))


def apply(bundle: Path, client_root: Path) -> dict:
    bundle, client_root = Path(bundle).resolve(), Path(client_root).resolve()
    manifest = io.load(io.safe(bundle, 'manifest.json'))
    validate_manifest(manifest)
    payload = io.safe(bundle, PACK_REL).read_bytes()
    require(digest(payload) == manifest['output_sha256'], 'bundle pack digest mismatch')
    target = io.safe(client_root, PACK_REL)
    with io.client_lock(client_root):
        verify(payload, manifest, client_root)
        marker = io.safe(client_root, MARKER)
        if marker.exists():
            installed = io.load(marker)
            require(installed == manifest, 'different monk entry overlay is already installed')
            return dict(status='already-installed', **verify(target.read_bytes(), manifest, client_root))
        before = target.read_bytes()
        require(digest(before) == manifest['input_sha256'] and len(before) == manifest['input_size'],
                'client pack baseline differs')
        prefix = f'.openNanaimo-resource-backups/monk-village-entry-{manifest["id"][:16]}-{uuid.uuid4().hex}'
        receipt = prefix + '/receipt.json'
        backup = io.safe(client_root, prefix + '/original/' + PACK_REL)
        io.atomic(backup, before)
        journal = dict(schema=SCHEMA, client=str(client_root), id=manifest['id'], manifest=manifest,
                       status='applying', files=[dict(path=PACK_REL, backup=prefix + '/original/' + PACK_REL,
                                                      before_sha256=digest(before), after_sha256=manifest['output_sha256'])])
        io.atomic(io.safe(client_root, receipt), encoded(journal))
        try:
            io.atomic(target, payload)
            verify(target.read_bytes(), manifest, client_root)
            io.atomic(marker, encoded(manifest))
            journal['status'] = 'installed'
            io.atomic(io.safe(client_root, receipt), encoded(journal))
        except Exception:
            io.atomic(target, before)
            if marker.exists():
                marker.unlink()
            journal['status'] = 'rolled-back'
            io.atomic(io.safe(client_root, receipt), encoded(journal))
            raise
    return dict(status='installed', receipt=receipt, **verify(payload, manifest))


def rollback(client_root: Path, receipt: str) -> dict:
    client_root = Path(client_root).resolve()
    with io.client_lock(client_root):
        receipt_path = io.safe(client_root, receipt)
        journal = io.load(receipt_path)
        require(journal.get('schema') == SCHEMA and journal.get('status') == 'installed', 'invalid monk entry receipt')
        require(journal.get('client') == str(client_root), 'receipt belongs to another client')
        manifest = journal['manifest']
        validate_manifest(manifest)
        require(journal.get('id') == manifest['id'], 'receipt transaction identity differs')
        marker = io.safe(client_root, MARKER)
        require(marker.is_file() and io.load(marker) == manifest, 'installed entry marker differs')
        require(len(journal.get('files', [])) == 1 and journal['files'][0]['path'] == PACK_REL,
                'receipt resource coverage differs')
        expected_backup = receipt_path.parent / 'original' / PACK_REL
        require(io.safe(client_root, journal['files'][0]['backup']) == expected_backup,
                'receipt backup ownership differs')
        target = io.safe(client_root, PACK_REL)
        require(digest(target.read_bytes()) == manifest['output_sha256'], 'client pack changed after install')
        backup = io.safe(client_root, journal['files'][0]['backup'])
        original = backup.read_bytes()
        require(digest(original) == manifest['input_sha256'], 'backup digest mismatch')
        io.atomic(target, original)
        marker = io.safe(client_root, MARKER)
        if marker.exists(): marker.unlink()
        journal['status'] = 'rolled-back'
        io.atomic(receipt_path, encoded(journal))
        return dict(status='rolled-back', receipt=receipt, sha256=digest(original), size=len(original))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('build'); p.add_argument('--source-root', type=Path, required=True); p.add_argument('--output-root', type=Path, required=True)
    p = commands.add_parser('apply'); p.add_argument('--bundle', type=Path, required=True); p.add_argument('--client-root', type=Path, required=True)
    p = commands.add_parser('verify'); p.add_argument('--client-root', type=Path, required=True)
    p = commands.add_parser('rollback'); p.add_argument('--client-root', type=Path, required=True); p.add_argument('--receipt', required=True)
    args = vars(parser.parse_args()); command = args.pop('command')
    if command == 'verify':
        root = Path(args['client_root']).resolve(); marker = io.load(io.safe(root, MARKER)); print(json.dumps(verify(io.safe(root, PACK_REL).read_bytes(), marker, root), indent=2))
    else:
        print(json.dumps(globals()[command](**args), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
