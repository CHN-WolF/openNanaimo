"""Prepare, apply and revert the chapter acceptance window in one command.

The acceptance needs three things at once: the new managed binaries in the
adapter runtime, the candidate tables installed for both the client and that
runtime, and the two profile switches that make the adapter offer chapter quests
without changing the launcher's command line. Doing that by hand is where a
window gets expensive, so this tool does it as one reversible step:

  plan    report every change without writing anything
  apply   back up, deploy the binaries, install the tables, add the profile keys
  revert  restore the binaries, roll the tables back and remove the keys

The launcher keeps reading the same profile, so starting it afterwards is enough;
nothing here starts, stops or talks to a process.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_story_tables as tables  # noqa: E402
import story_qt_patch as shared  # noqa: E402

SCHEMA = 'openNanaimo.story-window-accept.v1'
MANAGED = ('Nanaimo.Adapter.exe', 'Nanaimo.Adapter.dll', 'Nanaimo.Adapter.pdb',
           'Nanaimo.Gameplay.dll', 'Nanaimo.Gameplay.pdb')
PROFILE_KEYS = {'story_chapters': '1', 'story_chapters_start': '1'}
BACKUPS = '.openNanaimo-story-window-backups'
# The L7/L8 resource ledger also pins the text table (it added monk-visible
# entries to it), so the launcher refuses to start until that row follows.
LUMINEOS = 'openNanaimo-l7-l8-resources.json'
LUMINEOS_TABLE = 'QS._D31'
LUMINEOS_DIGEST = re.compile(r'(?m)^[ \t]+"id": "([0-9a-f]{64})",\r?\n')


def lumineos_update(client: Path, receipt: str | None = None) -> tuple[bytes, bytes] | None:
    """Authorize a QS ledger update against the exact installed table transaction."""
    client = tables.io.clean_root(client)
    path = tables.io.safe(client, LUMINEOS)
    if not path.exists():
        return None
    before = path.read_bytes()
    text = before.decode('utf-8')
    document = json.loads(text)
    shared.require(document.get('schema') == tables.io.SCHEMA
                   and len(LUMINEOS_DIGEST.findall(text)) == 1
                   and document.get('id') == shared.digest(
                       LUMINEOS_DIGEST.sub('', text, count=1).encode('utf-8')),
                   'L7/L8 receipt digest mismatch')
    rows = document['files']
    shared.require(len({r['path'].lower() for r in rows}) == len(rows),
                   'Duplicate L7/L8 resource entry')
    matches = [row for row in rows if row['path'] == LUMINEOS_TABLE]
    if not matches:
        return None
    row = matches[0]
    raw = tables.io.safe(client, LUMINEOS_TABLE).read_bytes()
    size, digest = len(raw), shared.digest(raw)
    if row['size'] == size and row['sha256'] == digest:
        return None
    if receipt is None:
        receipt = tables.io.load(tables.io.safe(client, tables.MARKER))['receipt']
    journal = tables.validate_receipt(client, receipt)
    shared.require(journal['status'] == 'installed', 'Story tables are not installed')
    tables.verify(client, receipt)
    pin = next(r for r in journal['files'] if r['path'] == LUMINEOS_TABLE)
    shared.require(row['sha256'] == pin['before_sha256']
                   and pin['sha256'] == digest and pin['size'] == size,
                   'L7/L8 QS baseline differs from the installed story transaction')
    original = tables.io.safe(client, pin['backup']).read_bytes()
    shared.require(shared.digest(original) == row['sha256'] and len(original) == row['size'],
                   'Story QS backup differs from the L7/L8 baseline')
    row.update(size=size, sha256=digest)
    del document['id']
    document['id'] = tables.io.digest(tables.io.encoded(document))
    return before, tables.io.encoded(document)


def sync_lumineos_receipt(client: Path, receipt: str | None = None) -> bool:
    update = lumineos_update(client, receipt)
    if update is None:
        return False
    before, after = update
    path = tables.io.safe(client, LUMINEOS)
    shared.require(path.read_bytes() == before, 'L7/L8 receipt changed during preparation')
    tables.io.atomic(path, after)
    return True


def lumineos_needs_sync(client: Path) -> bool:
    return lumineos_update(client) is not None


def verify_launcher_resources(client: Path) -> list[dict]:
    tool = tables.io.safe(client, 'adapter_runtime/Nanaimo.Adapter.exe')
    checks = []
    for kind, marker in (('lumineos', LUMINEOS),
                         ('monk-dialogue', '.openNanaimo-monk-dialogue.json'),
                         ('hero', '.openNanaimo-hero-dragon.json'),
                         ('korean', '.openNanaimo-korean-pets.json')):
        if not tables.io.safe(client, marker).exists():
            continue
        command = [str(tool), '--tools', 'verify-resources', '--kind', kind,
                   '--root', str(client), '--client-root', str(client)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding='utf-8', errors='replace', timeout=120)
        checks.append(dict(kind=kind, command=command, returncode=result.returncode,
                           output=result.stdout))
        shared.require(result.returncode == 0,
                       'Launcher resource verification failed: ' + kind + '\n' + result.stdout)
    return checks


def repair_lumineos(client: Path, receipt: str) -> dict:
    """Repair only stale metadata; retain a digest-guarded rollback journal."""
    io = tables.io
    client = io.clean_root(client)
    with io.client_lock(client):
        update = lumineos_update(client, receipt)
        if update is None:
            return dict(status='unchanged', checks=verify_launcher_resources(client),
                        runtime_acceptance=False)
        for old in io.safe(client, tables.BACKUP_ROOT).glob('*/receipt.json'):
            shared.require(io.load(old).get('status') != 'applying',
                           'Unfinished resource deployment: ' + str(old))
        before, after = update
        folder = tables.BACKUP_ROOT + '/story-ledger-' + uuid.uuid4().hex
        backup = folder + '/original/' + LUMINEOS
        journal_path = folder + '/receipt.json'
        journal = dict(schema=io.SCHEMA, overlay_schema='openNanaimo.story-ledger-repair.v1',
                       client=str(client), status='applying', story_receipt=receipt,
                       runtime_acceptance=False, files=[dict(path=LUMINEOS, backup=backup,
                       before_sha256=io.digest(before), sha256=io.digest(after))])
        io.atomic(io.safe(client, backup), before)
        io.atomic(io.safe(client, journal_path), io.encoded(journal))
        try:
            path = io.safe(client, LUMINEOS)
            shared.require(path.read_bytes() == before, 'L7/L8 receipt changed during preparation')
            io.atomic(path, after)
            checks = verify_launcher_resources(client)
            journal.update(status='installed', checks=checks)
            io.atomic(io.safe(client, journal_path), io.encoded(journal))
        except Exception:
            io._rollback(client, journal_path)
            raise
        return dict(status='repaired', receipt=journal_path, checks=checks,
                    runtime_acceptance=False)


def profile_lines(path: Path) -> list[str]:
    return path.read_text('utf-8').splitlines() if path.exists() else []


def profile_missing(path: Path) -> list[str]:
    lines = profile_lines(path)
    settings = {}
    for line in lines:
        if '=' not in line or line.lstrip().startswith(('#', ';')):
            continue
        key, value = line.split('=', 1)
        settings[key.strip().lower()] = value.strip()
    return [key for key, wanted in PROFILE_KEYS.items() if settings.get(key) != wanted]


def with_profile_keys(lines: list[str]) -> list[str]:
    remaining = dict(PROFILE_KEYS)
    output = []
    for line in lines:
        if '=' in line and not line.lstrip().startswith(('#', ';')):
            key = line.split('=', 1)[0].strip().lower()
            if key in remaining:
                output.append('%s=%s' % (key, remaining.pop(key)))
                continue
        output.append(line)
    output.extend('%s=%s' % (key, value) for key, value in remaining.items())
    return output


def plan(client: Path, bundle: Path, build: Path, adapter: Path | None) -> dict:
    client = Path(client).absolute()
    runtime = client / 'adapter_runtime'
    preflight = tables.plan(bundle, client, runtime)
    rows = []
    for name in MANAGED:
        source = Path(build) / name
        target = runtime / name
        rows.append(dict(name=name, source_exists=source.is_file(), target_exists=target.is_file(),
                         source_sha256=shared.digest(source.read_bytes()) if source.is_file() else None,
                         target_sha256=shared.digest(target.read_bytes()) if target.is_file() else None))
    profile = client / 'nanaimo_launcher_profile.ini'
    return dict(schema=SCHEMA, mode='plan', client=str(client), bundle=str(Path(bundle).absolute()),
                tables=preflight, binaries=rows,
                profile=dict(path=str(profile), missing=profile_missing(profile)),
                activation_allowed=False, runtime_acceptance=False)


def apply(client: Path, bundle: Path, build: Path, adapter: Path | None) -> dict:
    client = Path(client).absolute()
    runtime = client / 'adapter_runtime'
    shared.require(runtime.is_dir(), 'Client has no adapter_runtime directory: ' + str(runtime))
    missing = [name for name in MANAGED if not (Path(build) / name).is_file()]
    shared.require(not missing, 'Build is missing: ' + ', '.join(missing))
    stamp = time.strftime('%Y%m%d-%H%M%S')
    folder = client / BACKUPS / stamp
    shared.require(not folder.exists(), 'Backup folder already exists: ' + str(folder))
    folder.mkdir(parents=True)
    binaries = []
    for name in MANAGED:
        target, source = runtime / name, Path(build) / name
        before = shared.digest(target.read_bytes()) if target.is_file() else None
        if target.is_file():
            (folder / 'runtime').mkdir(exist_ok=True)
            shutil.copy2(target, folder / 'runtime' / name)
        shutil.copy2(source, target)
        binaries.append(dict(name=name, before=before, after=shared.digest(target.read_bytes())))
    profile = client / 'nanaimo_launcher_profile.ini'
    profile_before = profile.read_bytes() if profile.exists() else None
    if profile_before is not None:
        shutil.copy2(profile, folder / 'nanaimo_launcher_profile.ini')
    wanted = profile_missing(profile)
    if wanted:
        lines = with_profile_keys(profile_lines(profile))
        profile.write_text('\n'.join(lines) + '\n', 'utf-8')
    installed = tables.apply(bundle, client, runtime)
    # The launcher verifies every runtime file against its own manifest, so the
    # manifest has to follow the new binaries or it refuses to start.
    manifest = runtime / 'adapter_manifest.json'
    manifest_saved = None
    if manifest.is_file():
        shutil.copy2(manifest, folder / 'adapter_manifest.json')
        manifest_saved = 'adapter_manifest.json'
    manifest_changed = sync_runtime_manifest(runtime)
    # The L7/L8 ledger pins the text table; without this the launcher refuses
    # to start with "Installed resource mismatch".
    ledger = client / LUMINEOS
    ledger_saved = None
    if ledger.is_file():
        shutil.copy2(ledger, folder / LUMINEOS)
        ledger_saved = (folder / LUMINEOS).name
    ledger_changed = sync_lumineos_receipt(client, installed.get('receipt'))
    receipt = dict(schema=SCHEMA, mode='apply', client=str(client), stamp=stamp,
                   binaries=binaries, profile_keys=wanted, tables=installed,
                   adapter_manifest=manifest_saved, adapter_manifest_synced=manifest_changed,
                   lumineos_ledger=ledger_saved, lumineos_synced=ledger_changed,
                   activation_allowed=False, runtime_acceptance=False)
    (folder / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    return dict(receipt, backup=str(folder), tables_receipt=installed.get('receipt'))


def runtime_manifest(runtime: Path) -> dict:
    """Describe the runtime exactly as the launcher manifest does."""
    path = runtime / 'adapter_manifest.json'
    document = {}
    if path.is_file():
        try:
            document = json.loads(path.read_text('utf-8'))
        except ValueError:
            document = {}
    rows = []
    for file in sorted(runtime.rglob('*')):
        if not file.is_file() or file.resolve() == path.resolve():
            continue
        rows.append(dict(name=file.relative_to(runtime).as_posix(), size=file.stat().st_size,
                         sha256=shared.digest(file.read_bytes())))
    document.setdefault('version', 1)
    document.setdefault('role', 'full Nanaimo adapter')
    document.setdefault('launcher_tools', 2)
    document.setdefault('state_storage', 'sqlite')
    document.setdefault('framework', 'net8.0/win-x64/self-contained')
    document.setdefault('sdk', '8.0.425')
    document['built_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    document['files'] = rows
    return document


def sync_runtime_manifest(runtime: Path) -> bool:
    """Rewrite the launcher manifest so its hashes match the deployed binaries."""
    path = runtime / 'adapter_manifest.json'
    document = runtime_manifest(runtime)
    text = json.dumps(document, ensure_ascii=False, indent=4) + '\n'
    if path.is_file() and path.read_text('utf-8') == text:
        return False
    path.write_text(text, 'utf-8')
    return True


def revert(client: Path, stamp: str) -> dict:
    client = Path(client).absolute()
    runtime = client / 'adapter_runtime'
    folder = client / BACKUPS / stamp
    receipt = json.loads((folder / 'receipt.json').read_text('utf-8'))
    shared.require(receipt.get('client') == str(client) and receipt.get('stamp') == stamp,
                   'Receipt ownership differs')
    rolled = tables.rollback(client, receipt['tables']['receipt'])
    restored = []
    for row in receipt['binaries']:
        target = runtime / row['name']
        saved = folder / 'runtime' / row['name']
        if row['before'] is None:
            if target.exists():
                target.unlink()
            restored.append(dict(name=row['name'], action='removed'))
            continue
        shared.require(saved.is_file(), 'Backup is missing: ' + str(saved))
        shutil.copy2(saved, target)
        shared.require(shared.digest(target.read_bytes()) == row['before'],
                       'Restored binary differs: ' + row['name'])
        restored.append(dict(name=row['name'], action='restored', sha256=row['before']))
    profile = client / 'nanaimo_launcher_profile.ini'
    saved_profile = folder / 'nanaimo_launcher_profile.ini'
    if saved_profile.is_file():
        shutil.copy2(saved_profile, profile)
    saved_ledger = folder / LUMINEOS
    ledger_restored = False
    if receipt.get('lumineos_ledger') and saved_ledger.is_file():
        shutil.copy2(saved_ledger, client / LUMINEOS)
        ledger_restored = True
    saved_manifest = folder / 'adapter_manifest.json'
    manifest_restored = False
    if receipt.get('adapter_manifest') and saved_manifest.is_file():
        shutil.copy2(saved_manifest, runtime / 'adapter_manifest.json')
        manifest_restored = True
    else:
        # No saved copy means the runtime gained a manifest; rebuild it from the
        # restored binaries so the launcher keeps accepting the runtime.
        manifest_restored = sync_runtime_manifest(runtime)
    return dict(schema=SCHEMA, mode='revert', client=str(client), stamp=stamp,
                tables=rolled, binaries=restored, profile_restored=saved_profile.is_file(),
                lumineos_ledger_restored=ledger_restored,
                adapter_manifest_restored=manifest_restored,
                activation_allowed=False, runtime_acceptance=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'apply'):
        command = commands.add_parser(name)
        command.add_argument('--client', type=Path, required=True)
        command.add_argument('--bundle', type=Path, required=True)
        command.add_argument('--build', type=Path, required=True)
        command.add_argument('--adapter', type=Path)
    revert_parser = commands.add_parser('revert')
    revert_parser.add_argument('--client', type=Path, required=True)
    revert_parser.add_argument('--stamp', required=True)
    repair_parser = commands.add_parser('repair-lumineos')
    repair_parser.add_argument('--client', type=Path, required=True)
    repair_parser.add_argument('--receipt', required=True, help='Installed story-table transaction')
    args = parser.parse_args(argv)
    if args.command == 'plan':
        result = plan(args.client, args.bundle, args.build, args.adapter)
    elif args.command == 'apply':
        result = apply(args.client, args.bundle, args.build, args.adapter)
    elif args.command == 'repair-lumineos':
        result = repair_lumineos(args.client, args.receipt)
    else:
        result = revert(args.client, args.stamp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
