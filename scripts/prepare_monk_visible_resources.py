"""Build a verified L7/L8 resource upgrade that only makes the first monk visible."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import port_lumineos_resources as port

SCHEMA = 'openNanaimo.monk-visible-upgrade.v1'
PARENT_MARKER = 'openNanaimo-l7-l8-resources.json'

def build(client: Path, candidate: Path, output: Path):
    client = port.clean_root(client); candidate = port.clean_root(candidate)
    if output.exists(): raise ValueError('output already exists; use a fresh bundle directory')
    parent = port.load(port.safe(client, PARENT_MARKER)); port.validate_manifest(parent)
    preview = port.load(port.safe(candidate, 'manifest.json'))
    if preview.get('schema') != 'openNanaimo.monk-entry-preview.v1' or preview.get('runtime_accepted') is not False:
        raise ValueError('invalid monk preview manifest')
    if preview.get('entry', {}).get('scene_key') != 10027 or preview.get('entry', {}).get('position') != [293, 157]:
        raise ValueError('preview is not the first-village monk scene')
    preview_rows = {row['path']: row for row in preview['files']}
    required = {'Village_map_image/Village_map_image.pack','QS._D31','GS._D20',
        'effs/village/openNanaimo_monk01.eff','effs/village/openNanaimo_monk01.im3',
        'effs/village/openNanaimo_monk_shadow.im3','effs/village/openNanaimo_monk_name.im3'}
    if set(preview_rows) != required: raise ValueError('preview file coverage differs')
    parent_rows = {row['path']: row for row in parent['files']}
    parent_files = {path: row['sha256'] for path, row in parent_rows.items()}
    rows = [dict(row, before_sha256=row['sha256']) for row in parent['files']]; by_path = {row['path']: row for row in rows}
    for path, preview_row in preview_rows.items():
        payload = port.safe(candidate / 'payload', path).read_bytes()
        if port.digest(payload) != preview_row['sha256'] or len(payload) != preview_row['size']:
            raise ValueError('preview payload identity mismatch: ' + path)
        before = port.file_hash(port.safe(client, path))
        if before != preview_row['before_sha256']:
            if not (preview_row['before_sha256'] is None and before == preview_row['sha256']):
                raise ValueError('preview baseline differs from client: ' + path)
        row = dict(path=path, before_sha256=before, sha256=preview_row['sha256'], size=preview_row['size'],
                   transform='monk-visible-village-pages' if path == 'Village_map_image/Village_map_image.pack' else 'monk-visible-additive')
        if path in by_path: by_path[path] = row
        else: rows.append(row)
    rows = [by_path.get(row['path'], row) for row in rows]
    recipe_paths = {row['path'] for row in port.load(port.RECIPE)['files']}
    additional = sorted((set(parent_rows) | required) - recipe_paths)
    manifest = dict(parent); manifest['files'] = rows; manifest['runtime_accepted'] = False
    manifest['monk_visible'] = dict(schema=SCHEMA, parent_manifest_id=parent['id'], parent_files=parent_files,
        additional_paths=additional, additional_before={path: next(row['before_sha256'] for row in rows if row['path'] == path) for path in additional},
        village_sha256=preview_rows['Village_map_image/Village_map_image.pack']['sha256'],
        scene_key=10027, position=[293, 157], interactive=False)
    identity = dict(manifest); identity.pop('id', None); manifest['id'] = port.digest(port.encoded(identity))
    port.validate_manifest(manifest); output.mkdir(parents=True)
    for row in rows:
        path = row['path']
        source = port.safe(candidate / 'payload', path) if path in required else port.safe(client, path)
        port.atomic(port.safe(output / 'payload', path), source.read_bytes())
    port.atomic(port.safe(output, 'manifest.json'), port.encoded(manifest))
    return dict(bundle=str(output), id=manifest['id'], files=len(required), runtime_accepted=False,
                entry_status='scene-visible-unbound', interactive=False)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True); parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    print(json.dumps(build(args.client, args.candidate, args.output), ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
