"""Package the pinned chapter portraits and converted four-village resources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

import port_lumineos_resources as io

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'resource-packs/nanaimo-story-resource-kit.zip'
SCHEMA = 'openNanaimo.story-resource-kit.v1'
RECIPES = ('story_portrait_resources.json', 'monk_dialogue_resources.json',
           'monk_challenge_resources.json')


def inventory():
    rows = {}
    groups = {}
    for name in RECIPES:
        recipe = io.load(ROOT / 'manifest' / name)
        groups[name] = len(recipe['files'])
        for item in recipe['files']:
            row = dict(path=item['path'], size=item.get('output_size', item.get('size')),
                       sha256=item.get('output_sha256', item.get('sha256')))
            io.safe(ROOT, row['path'])
            if row['path'] in rows and rows[row['path']] != row:
                raise ValueError('Conflicting resource ownership: ' + row['path'])
            rows[row['path']] = row
    if len({p.lower() for p in rows}) != len(rows):
        raise ValueError('Case-colliding resource paths')
    return dict(schema=SCHEMA, runtime_acceptance=False, groups=groups,
                recipes={name: io.file_hash(ROOT / 'manifest' / name) for name in RECIPES},
                files=sorted(rows.values(), key=lambda r: r['path']))


def checked(raw, row):
    if len(raw) != row['size'] or io.digest(raw) != row['sha256']:
        raise ValueError('Resource identity differs: ' + row['path'])
    return raw


def read(archive=ARCHIVE):
    expected = inventory()
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        wanted = {'kit-manifest.json'} | {'payload/' + r['path'] for r in expected['files']}
        if len(names) != len(set(names)) or set(names) != wanted:
            raise ValueError('Story archive coverage differs')
        if json.loads(z.read('kit-manifest.json')) != expected:
            raise ValueError('Story archive does not match current recipes')
        data = {}
        for row in expected['files']:
            name = 'payload/' + row['path']
            if z.getinfo(name).file_size != row['size']:
                raise ValueError('Story archive size differs: ' + name)
            data[row['path']] = checked(z.read(name), row)
    return data


def build(source, output):
    source, output = io.clean_root(source), Path(output).absolute()
    if output.exists() or output.with_suffix('.zip.sha256').exists():
        raise ValueError('Output exists; preserve the previous archive')
    # Localized tables are deterministic repository outputs, not live-client inputs.
    import prepare_monk_resources as monk
    generated = monk.localized_resources(io.load(monk.LOCALIZATION))
    index = inventory()
    payload = {r['path']: checked(generated[r['path']] if r['path'] in generated
                                else io.safe(source, r['path']).read_bytes(), r)
               for r in index['files']}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, raw in sorted({'kit-manifest.json': io.encoded(index),
                                 **{'payload/' + p: b for p, b in payload.items()}}.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, raw)
    read(output)
    io.atomic(output.with_suffix('.zip.sha256'),
              (io.file_hash(output) + '  ' + output.name + '\n').encode('ascii'))
    return dict(status='built', files=len(payload), bytes=output.stat().st_size,
                sha256=io.file_hash(output), runtime_acceptance=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    b = commands.add_parser('build')
    b.add_argument('--source', type=Path, required=True)
    b.add_argument('--output', type=Path, default=ARCHIVE)
    v = commands.add_parser('verify')
    v.add_argument('--archive', type=Path, default=ARCHIVE)
    a = p.parse_args()
    result = build(a.source, a.output) if a.command == 'build' else dict(
        status='verified', files=len(read(a.archive)), runtime_acceptance=False)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
