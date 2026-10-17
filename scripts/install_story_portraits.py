"""Transactional, explicitly opted-in portrait preview; never enables chapter gameplay.

Only the current recipe's additive EFF/IM3 files are owned. Existing identical
files are reused. EXE, QS/QT, saved games, and adapter files are never modified.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import uuid

import port_lumineos_resources as io
import prepare_story_portraits as portraits
from prepare_story_catalog import require

RECIPE = portraits.RECIPE
PACKAGE = portraits.ROOT / 'release/components/story_chapters/chapters.json'
SCHEMA = 'openNanaimo.story-portrait-preview.v1'
MARKER = '.openNanaimo-story-portrait-preview.json'
BACKUPS = '.openNanaimo-story-portrait-receipts'


def recipe_rows():
    recipe = io.load(RECIPE)
    portraits.validate_story_scope(recipe, io.load(PACKAGE))
    require(recipe['activation_allowed'] is False and recipe['runtime_acceptance'] is False,
            'Preview recipe cannot authorize activation')
    rows = {r['path']: r for r in recipe['files']}
    require(len(rows) == len(recipe['files']) and rows, 'Duplicate or empty recipe')
    for rel, row in rows.items():
        path = PurePosixPath(rel)
        require(path.parent.as_posix() == 'effs/interface'
                and any(path.name in (f'NPC_{n}_0.eff', f'NPC_{n}.im3', f'NPC_{n}_b.im3')
                        for n in recipe['npc_scope'])
                and not any(path.name.startswith(f'NPC_{n}_') or path.name == f'NPC_{n}.im3'
                            for n in range(62, 66)), 'Resource outside portrait ownership')
        require(type(row['size']) is int and row['size'] > 0
                and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'Invalid recipe identity')
    return rows, io.digest(io.encoded(recipe))


def preview_marker(rows, recipe_hash):
    return dict(schema=SCHEMA, recipe_sha256=recipe_hash, activation_allowed=False,
                runtime_acceptance=False, status='portraits-only-not-playable',
                files=[dict(path=rel, size=row['size'], sha256=row['sha256'])
                       for rel, row in sorted(rows.items())])


def validated_bundle(bundle, client):
    rows, recipe_hash = recipe_rows()
    manifest = io.load(io.safe(bundle, 'manifest.json'))
    require(manifest.get('schema') == 'openNanaimo.story-portraits.v1.bundle'
            and manifest.get('recipe_sha256') == recipe_hash
            and manifest.get('status') == 'prepared-not-installed'
            and manifest.get('activation_allowed') is False
            and manifest.get('runtime_acceptance') is False, 'Unmatched or enabled bundle')
    entries = {r['path']: r for r in manifest['files']}
    require(len(entries) == len(manifest['files']) and set(entries) == set(rows), 'Bundle coverage differs')
    expected = {'manifest.json'} | {'payload/' + rel for rel in rows}
    require({p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()} == expected,
            'Unexpected bundle files')
    work = []
    for rel, row in sorted(rows.items()):
        entry = entries[rel]
        require(entry['size'] == row['size'] and entry['sha256'] == row['sha256'], 'Unmatched portrait identity')
        require(entry['disposition'] in ('reuse-identical', 'additive-candidate'), 'Unknown disposition')
        raw = io.safe(bundle, 'payload/' + rel).read_bytes()
        require(len(raw) == row['size'] and io.digest(raw) == row['sha256'], 'Corrupt payload: ' + rel)
        before = row['sha256'] if entry['disposition'] == 'reuse-identical' else None
        require(io.file_hash(io.safe(client, rel)) == before, 'Preview baseline differs: ' + rel)
        work.append((dict(path=rel, before_sha256=before, sha256=row['sha256'], size=row['size']), raw))
    marker = io.encoded(preview_marker(rows, recipe_hash))
    require(not io.safe(client, MARKER).exists(), 'Preview marker already exists')
    work.append((dict(path=MARKER, before_sha256=None, sha256=io.digest(marker), size=len(marker)), marker))
    return work, recipe_hash


def verify(client):
    client = io.clean_root(client)
    rows, recipe_hash = recipe_rows()
    require(io.load(io.safe(client, MARKER)) == preview_marker(rows, recipe_hash), 'Preview marker differs')
    for rel, row in rows.items():
        path = io.safe(client, rel)
        require(io.file_hash(path) == row['sha256'] and path.stat().st_size == row['size'], 'Installed portrait differs: ' + rel)
    return dict(status='preview-verified', files=len(rows), activation_allowed=False, runtime_acceptance=False)


def validate_receipt(client, receipt):
    require(re.fullmatch(re.escape(BACKUPS) + r'/[0-9a-f]{32}/receipt.json', receipt) is not None,
            'Invalid receipt path')
    journal = io.load(io.safe(client, receipt))
    require(journal.get('schema') == SCHEMA and journal.get('client') == str(client)
            and journal.get('receipt') == receipt
            and journal.get('status') in ('applying', 'installed', 'rolled-back')
            and journal.get('activation_allowed') is False and journal.get('runtime_acceptance') is False,
            'Receipt ownership differs')
    rows, recipe_hash = recipe_rows()
    require(journal.get('recipe_sha256') == recipe_hash, 'Receipt recipe differs; preserve original recipe for recovery')
    marker = io.encoded(preview_marker(rows, recipe_hash))
    expected = dict(rows)
    expected[MARKER] = dict(size=len(marker), sha256=io.digest(marker))
    entries = {r['path']: r for r in journal['files']}
    require(len(entries) == len(journal['files']) and set(entries) == set(expected), 'Receipt coverage differs')
    for rel, entry in entries.items():
        row = expected[rel]
        require(entry['sha256'] == row['sha256'] and entry['size'] == row['size']
                and entry['before_sha256'] in (None, row['sha256']), 'Receipt resource identity differs')
        if rel == MARKER:
            require(entry['before_sha256'] is None, 'Preview cannot replace a marker')
    return journal


def restore(client, receipt):
    journal = validate_receipt(client, receipt)
    # Full preflight before any removal. Reused files must still be identical;
    # unrelated edits and post-install replacements always block recovery.
    for row in journal['files']:
        current = io.file_hash(io.safe(client, row['path']))
        allowed = (row['before_sha256'],) if journal['status'] == 'rolled-back' else (row['before_sha256'], row['sha256'])
        require(current in allowed, 'Rollback conflict: ' + row['path'])
    if journal['status'] == 'rolled-back':
        return dict(status='already-rolled-back', receipt=receipt)
    for row in reversed(journal['files']):
        target = io.safe(client, row['path'])
        current = io.file_hash(target)
        require(current in (row['before_sha256'], row['sha256']), 'Rollback changed during recovery')
        if row['before_sha256'] is None and current is not None:
            target.unlink()  # Only an exact, pinned, newly created file. Never a directory.
    journal['status'] = 'rolled-back'
    io.atomic(io.safe(client, receipt), io.encoded(journal))
    return dict(status='rolled-back', receipt=receipt, activation_allowed=False, runtime_acceptance=False)


def rollback(client, receipt):
    client = io.clean_root(client)
    with io.client_lock(client):
        return restore(client, receipt)


def apply(bundle, client, allow_inactive_preview=False):
    require(allow_inactive_preview is True, 'Explicit --allow-inactive-preview required; this does not enable gameplay')
    bundle, client = io.clean_root(bundle), io.clean_root(client)
    require(bundle.is_dir() and client.is_dir() and not bundle.is_relative_to(client)
            and not client.is_relative_to(bundle), 'Bundle/client roots overlap or are missing')
    with io.client_lock(client):
        history = io.safe(client, BACKUPS)
        if history.exists():
            for path in history.glob('*/receipt.json'):
                old = validate_receipt(client, path.relative_to(client).as_posix())
                require(old['status'] != 'applying', 'Interrupted preview; rollback receipt first')
        if io.safe(client, MARKER).exists():
            # Installed bytes, not an incoming bundle, own idempotent verification.
            return dict(verify(client), status='already-installed-preview')
        work, recipe_hash = validated_bundle(bundle, client)
        receipt = BACKUPS + '/' + uuid.uuid4().hex + '/receipt.json'
        journal = dict(schema=SCHEMA, client=str(client), receipt=receipt, recipe_sha256=recipe_hash,
                       status='applying', activation_allowed=False, runtime_acceptance=False,
                       files=[row for row, raw in work])
        io.atomic(io.safe(client, receipt), io.encoded(journal))
        try:
            for row, raw in work:
                target = io.safe(client, row['path'])
                require(io.file_hash(target) == row['before_sha256'], 'Baseline changed during preview')
                if row['before_sha256'] is None:
                    io.atomic(target, raw)
            result = verify(client)
            journal['status'] = 'installed'
            io.atomic(io.safe(client, receipt), io.encoded(journal))
        except Exception:
            restore(client, receipt)
            raise
        return dict(result, status='installed-inactive-preview', receipt=receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('apply')
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--allow-inactive-preview', action='store_true')
    p = commands.add_parser('verify'); p.add_argument('--client', type=Path, required=True)
    p = commands.add_parser('rollback'); p.add_argument('--client', type=Path, required=True)
    p.add_argument('--receipt', required=True)
    args = vars(parser.parse_args()); command = args.pop('command')
    try:
        print(json.dumps(globals()[command](**args), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, 'STORY_PREVIEW_REFUSED: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
