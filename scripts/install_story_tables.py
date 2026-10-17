"""Transactional install of the candidate chapter QT/QS tables.

Both tables move together: QT alone makes the quest window reference texts that
do not exist, and QS alone installs dead text. The bundle is the output of
story_qt_patch.py and story_qs_patch.py, and their reports must prove they were
derived from the exact client state this installer is about to overwrite.

The transaction reuses the project's shared resource machinery in
port_lumineos_resources: the client-running guard, the exclusive client lock,
atomic replacement, the `.openNanaimo-resource-backups` journal layout and the
single rollback implementation. Nothing here enables chapter gameplay: the
reports stay inactive and the receipt keeps the previous bytes.
"""
import argparse
import json
from pathlib import Path
import re
import uuid

import port_lumineos_resources as io
from prepare_story_catalog import require

SCHEMA = 'openNanaimo.story-tables-install.v1'
TABLES = ('QT._D30', 'QS._D31')
REPORTS = {'QT._D30': 'patch-report.json', 'QS._D31': 'qs-patch-report.json'}
BACKUP_ROOT = '.openNanaimo-resource-backups'
RECEIPT_PREFIX = 'story-tables-'
MARKER = '.openNanaimo-story-tables.json'
RUNTIME_DATA = '资源/数据'


def runtime_row(bundle: Path, client: Path, runtime: Path, qt_output: dict) -> dict:
    """The adapter keeps its own copy of the quest table next to its exe.

    The server resolves chapter quests from that copy, so the same patched bytes
    must land there as well. It is inside the client root, so the shared journal
    can back it up and restore it like any other owned file.
    """
    client, runtime = io.clean_root(client), io.clean_root(runtime)
    require(runtime.is_relative_to(client), 'Adapter runtime must live inside the client root')
    relative = runtime.relative_to(client).as_posix() + '/' + RUNTIME_DATA + '/QT._D30'
    path = io.safe(client, relative)
    before = io.file_hash(path)
    require(before is not None, 'Adapter runtime is missing its quest table: ' + relative)
    baseline = {row['name']: row['sha256']
                for row in io.load(io.safe(bundle, REPORTS['QT._D30']))['inputs']}
    require(before == baseline['QT._D30'],
            'Adapter runtime quest table is not the shipped baseline: ' + relative)
    return dict(path=relative, source='QT._D30', before_sha256=before,
                sha256=qt_output['sha256'], size=qt_output['size'])


def validate_bundle(bundle, client, runtime=None):
    bundle, client = io.clean_root(bundle), io.clean_root(client)
    expected = set(TABLES) | set(REPORTS.values())
    actual = {path.name for path in bundle.iterdir() if path.is_file()}
    require(actual == expected, 'Bundle coverage differs: ' + repr(sorted(actual)))
    work = []
    for name in TABLES:
        report = io.load(io.safe(bundle, REPORTS[name]))
        require(report.get('schema', '').startswith('openNanaimo.story-'),
                'Report schema is not a story candidate: ' + REPORTS[name])
        require(report.get('status') == 'candidate-only'
                and report.get('activation_allowed') is False
                and report.get('runtime_acceptance') is False,
                'Bundle is not an inactive candidate: ' + REPORTS[name])
        raw = io.safe(bundle, name).read_bytes()
        output = report['output']
        require(output['name'] == name and output['size'] == len(raw)
                and output['sha256'] == io.digest(raw), 'Bundle payload differs from its report: ' + name)
        inputs = {row['name']: row for row in report['inputs']}
        require(name in inputs, 'Report does not record the client baseline: ' + name)
        before = io.file_hash(io.safe(client, name))
        require(before is not None, 'Client is missing ' + name)
        require(before == inputs[name]['sha256'], 'Bundle was not derived from this client: ' + name)
        work.append(dict(path=name, source=name, before_sha256=before,
                         sha256=output['sha256'], size=output['size']))
    qt_inputs = {row['name']: row['sha256'] for row in io.load(io.safe(bundle, REPORTS['QT._D30']))['inputs']}
    qs_inputs = {row['name']: row['sha256'] for row in io.load(io.safe(bundle, REPORTS['QS._D31']))['inputs']}
    shared = set(qt_inputs) & set(qs_inputs)
    require(shared, 'The two reports share no input identity to cross-check')
    for name in sorted(shared):
        require(qt_inputs[name] == qs_inputs[name],
                'The two reports disagree about a shared input: ' + name)
    if runtime is not None:
        work.append(runtime_row(bundle, client, runtime,
                                io.load(io.safe(bundle, REPORTS['QT._D30']))['output']))
    return bundle, work


def journal_body(client, receipt, work, status):
    return dict(schema=io.SCHEMA, overlay_schema=SCHEMA, client=str(client), receipt=receipt,
                status=status, activation_allowed=False, runtime_acceptance=False,
                files=[dict(row) for row in work])


def plan(bundle, client, runtime=None):
    bundle, work = validate_bundle(bundle, client, runtime)
    changes = [row for row in work if row['before_sha256'] != row['sha256']]
    return dict(status='plan', client=str(io.clean_root(client)), changed=len(changes),
                unchanged=len(work) - len(changes), files=[dict(row) for row in work],
                activation_allowed=False, runtime_acceptance=False)


def apply(bundle, client, runtime=None):
    client = io.clean_root(client)
    bundle, work = validate_bundle(bundle, client, runtime)
    with io.client_lock(client):
        backups = io.safe(client, BACKUP_ROOT)
        if backups.exists():
            for old in backups.glob('*/receipt.json'):
                if io.load(old).get('status') == 'applying':
                    raise ValueError('unfinished deployment; roll it back first: '
                                     + str(old.relative_to(client)))
        changes = [row for row in work if row['before_sha256'] != row['sha256']]
        if not changes:
            return dict(status='unchanged', files=0, activation_allowed=False,
                        runtime_acceptance=False)
        identifier = uuid.uuid4().hex
        folder = BACKUP_ROOT + '/' + RECEIPT_PREFIX + identifier
        receipt = folder + '/receipt.json'
        rows = []
        for row in work:
            if row['before_sha256'] == row['sha256']:
                rows.append(dict(row, backup=None))
            else:
                rows.append(dict(row, backup=folder + '/original/' + row['path']))
        io.atomic(io.safe(client, receipt), io.encoded(journal_body(client, receipt, rows, 'applying')))
        try:
            for row in rows:
                if row['backup'] is None:
                    continue
                original = io.safe(client, row['path']).read_bytes()
                require(io.digest(original) == row['before_sha256'],
                        'Client changed during install: ' + row['path'])
                io.atomic(io.safe(client, row['backup']), original)
                payload = io.safe(bundle, row.get('source', row['path'])).read_bytes()
                io.atomic(io.safe(client, row['path']), payload)
                require(io.file_hash(io.safe(client, row['path'])) == row['sha256'],
                        'Installed table differs from the bundle: ' + row['path'])
        except Exception:
            for row in rows:
                if row['backup'] is not None and io.safe(client, row['backup']).exists():
                    io.atomic(io.safe(client, row['path']),
                              io.safe(client, row['backup']).read_bytes())
            io.atomic(io.safe(client, receipt),
                      io.encoded(journal_body(client, receipt, rows, 'rolled-back')))
            raise
        io.atomic(io.safe(client, receipt), io.encoded(journal_body(client, receipt, rows, 'installed')))
        io.atomic(io.safe(client, MARKER), io.encoded(dict(
            schema=SCHEMA, receipt=receipt, files=[dict(row) for row in work],
            activation_allowed=False, runtime_acceptance=False)))
    return dict(status='installed', receipt=receipt, changed=len(changes),
                activation_allowed=False, runtime_acceptance=False)


def validate_receipt(client, receipt):
    client = io.clean_root(client)
    require(re.fullmatch(re.escape(BACKUP_ROOT) + '/' + re.escape(RECEIPT_PREFIX)
                         + r'[0-9a-f]{32}/receipt\.json', receipt) is not None, 'Invalid receipt path')
    journal = io.load(io.safe(client, receipt))
    require(journal.get('schema') == io.SCHEMA and journal.get('overlay_schema') == SCHEMA
            and journal.get('client') == str(client) and journal.get('receipt') == receipt
            and journal.get('status') in ('applying', 'installed', 'rolled-back')
            and journal.get('activation_allowed') is False
            and journal.get('runtime_acceptance') is False, 'Receipt ownership differs')
    entries = {row['path']: row for row in journal['files']}
    require(set(TABLES) <= set(entries) and len(entries) == len(journal['files']),
            'Receipt coverage differs')
    extra = set(entries) - set(TABLES)
    require(all(path.endswith('/' + RUNTIME_DATA + '/QT._D30') for path in extra),
            'Receipt owns an unexpected file: ' + repr(sorted(extra)))
    return journal


def verify(client, receipt):
    journal = validate_receipt(client, receipt)
    client = io.clean_root(client)
    for row in journal['files']:
        require(io.file_hash(io.safe(client, row['path'])) == row['sha256'],
                'Installed table differs: ' + row['path'])
    return dict(status='verified', receipt=receipt, files=len(journal['files']),
                activation_allowed=False, runtime_acceptance=False)


def rollback(client, receipt):
    client = io.clean_root(client)
    validate_receipt(client, receipt)
    with io.client_lock(client):
        result = io._rollback(client, receipt)
        marker = io.safe(client, MARKER)
        if marker.exists():
            marker.unlink()
    return dict(result, receipt=receipt, activation_allowed=False, runtime_acceptance=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'apply'):
        command = commands.add_parser(name)
        command.add_argument('--bundle', type=Path, required=True)
        command.add_argument('--client', type=Path, required=True)
        command.add_argument('--runtime', type=Path,
                           help='Adapter runtime directory that also needs the quest table')
    for name in ('verify', 'rollback'):
        command = commands.add_parser(name)
        command.add_argument('--client', type=Path, required=True)
        command.add_argument('--receipt', required=True)
    args = parser.parse_args(argv)
    if args.command == 'plan':
        result = plan(args.bundle, args.client, args.runtime)
    elif args.command == 'apply':
        result = apply(args.bundle, args.client, args.runtime)
    elif args.command == 'verify':
        result = verify(args.client, args.receipt)
    else:
        result = rollback(args.client, args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
