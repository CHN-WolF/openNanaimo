"""Checks for the one-command acceptance window."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_story_tables as tables  # noqa: E402
import port_lumineos_resources as io  # noqa: E402
import story_window_accept as accept  # noqa: E402


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def report(name: str, payload: bytes, baseline: dict) -> dict:
    return dict(schema='openNanaimo.story-qt-patch.v1', status='candidate-only',
                activation_allowed=False, runtime_acceptance=False,
                inputs=[dict(name=key, size=len(value), sha256=io.digest(value))
                        for key, value in baseline.items()],
                output=dict(name=name, size=len(payload), sha256=io.digest(payload)))


class WindowFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = self.root / 'client'
        self.runtime = self.client / 'adapter_runtime'
        qt, qs = b'QUEST#20080625#357#' + b'0#' * 8, b'NANA_QUEST_TEXT#80625.01#633#' + b'0#' * 8
        write(self.client / 'QT._D30', qt)
        write(self.client / 'QS._D31', qs)
        write(self.runtime / '资源' / '数据' / 'QT._D30', qt)
        for name in accept.MANAGED:
            write(self.runtime / name, ('old-' + name).encode())
        self.profile = self.client / 'nanaimo_launcher_profile.ini'
        self.profile.write_text('version=2\nlaunch_mode=network\n', 'utf-8')
        self.build = self.root / 'build'
        for name in accept.MANAGED:
            write(self.build / name, ('new-' + name).encode())
        self.bundle = self.root / 'bundle'
        new_qt, new_qs = qt + b'chapter', qs + b'chapter'
        write(self.bundle / 'QT._D30', new_qt)
        write(self.bundle / 'QS._D31', new_qs)
        write(self.bundle / 'patch-report.json', io.encoded(report(
            'QT._D30', new_qt, {'QT._D30': qt, 'QS._D31': qs})))
        write(self.bundle / 'qs-patch-report.json', io.encoded(report(
            'QS._D31', new_qs, {'QS._D31': qs})))
        self.ledger = self.client / accept.LUMINEOS
        self.ledger.write_bytes(ledger_text(io.digest(qs), len(qs)).encode('utf-8'))
        self.ledger_before = self.ledger.read_bytes()
        self.manifest = self.runtime / 'adapter_manifest.json'
        self.manifest.write_text(json.dumps({
            'version': 1, 'role': 'full Nanaimo adapter', 'launcher_tools': 2,
            'state_storage': 'sqlite', 'framework': 'net8.0/win-x64/self-contained',
            'sdk': '8.0.425',
            'files': [{'name': 'Nanaimo.Adapter.dll', 'size': 3,
                       'sha256': 'F' * 64}]}, indent=4) + '\n', 'utf-8')

    def tearDown(self):
        self.temp.cleanup()


def ledger_text(digest: str, size: int) -> str:
    """A minimal L7/L8 ledger with one text-table row and its self digest."""
    import hashlib
    body = ('{\n'
            '    "files": [\n'
            '        {\n'
            '            "before_sha256": "%s",\n'
            '            "path": "%s",\n'
            '            "sha256": "%s",\n'
            '            "size": %d,\n'
            '            "transform": "monk-visible-additive"\n'
            '        }\n'
            '    ],\n'
            '    "id": "PLACEHOLDER",\n'
            '    "schema": "openNanaimo.l7-visual-l8-resources.v1"\n'
            '}\n') % (digest, accept.LUMINEOS_TABLE, digest, size)
    line = '    "id": "PLACEHOLDER",\n'
    stripped = body.replace(line, '', 1)
    return body.replace(line, '    "id": "%s",\n' % hashlib.sha256(
        stripped.encode('utf-8')).hexdigest(), 1)


class PlanTests(WindowFixture):
    def test_plan_reports_changes_without_writing(self):
        before = (self.runtime / 'Nanaimo.Gameplay.dll').read_bytes()
        result = accept.plan(self.client, self.bundle, self.build, None)
        self.assertEqual(result['tables']['changed'], 3)
        self.assertEqual(result['profile']['missing'], ['story_chapters', 'story_chapters_start'])
        self.assertTrue(all(row['source_exists'] for row in result['binaries']))
        self.assertEqual((self.runtime / 'Nanaimo.Gameplay.dll').read_bytes(), before)
        self.assertFalse((self.client / accept.BACKUPS).exists())


class ApplyRevertTests(WindowFixture):
    def test_apply_deploys_tables_and_profile(self):
        result = accept.apply(self.client, self.bundle, self.build, None)
        self.assertEqual((self.runtime / 'Nanaimo.Gameplay.dll').read_bytes(),
                         b'new-Nanaimo.Gameplay.dll')
        self.assertEqual((self.client / 'QT._D30').read_bytes(),
                         (self.bundle / 'QT._D30').read_bytes())
        self.assertEqual((self.runtime / '资源' / '数据' / 'QT._D30').read_bytes(),
                         (self.bundle / 'QT._D30').read_bytes())
        self.assertIn('story_chapters=1', self.profile.read_text('utf-8'))
        self.assertIn('story_chapters_start=1', self.profile.read_text('utf-8'))
        receipt = Path(result['backup']) / 'receipt.json'
        self.assertTrue(receipt.is_file())
        self.assertEqual(result['profile_keys'], ['story_chapters', 'story_chapters_start'])

    def test_existing_profile_keys_are_not_duplicated(self):
        self.profile.write_text('version=2\nstory_chapters=0\nstory_chapters_start=0\n', 'utf-8')
        accept.apply(self.client, self.bundle, self.build, None)
        text = self.profile.read_text('utf-8')
        self.assertEqual(text.count('story_chapters='), 1)
        self.assertIn('story_chapters=1', text)
        self.assertIn('story_chapters_start=1', text)

    def test_apply_syncs_the_l7_l8_ledger(self):
        result = accept.apply(self.client, self.bundle, self.build, None)
        patched = (self.client / 'QS._D31').read_bytes()
        ledger = self.ledger.read_bytes().decode('utf-8')
        self.assertIn('"sha256": "%s"' % io.digest(patched), ledger)
        self.assertIn('"size": %d' % len(patched), ledger)
        self.assertIn('"before_sha256": "%s"' % io.digest(
            self.bundle.joinpath('QS._D31').read_bytes()[:-len(b'chapter')]), ledger)
        self.assertTrue(result['lumineos_synced'])
        document = json.loads(ledger)
        import hashlib, re
        pattern = re.compile(r'(?m)^[ \t]+"id": "([0-9a-f]{64})",\r?\n')
        stripped = pattern.sub('', ledger, count=1)
        self.assertEqual(document['id'], hashlib.sha256(stripped.encode('utf-8')).hexdigest())

    def test_revert_restores_everything(self):
        applied = accept.apply(self.client, self.bundle, self.build, None)
        reverted = accept.revert(self.client, applied['stamp'])
        self.assertEqual((self.runtime / 'Nanaimo.Gameplay.dll').read_bytes(),
                         b'old-Nanaimo.Gameplay.dll')
        self.assertNotEqual((self.client / 'QT._D30').read_bytes(),
                            (self.bundle / 'QT._D30').read_bytes())
        self.assertNotIn('story_chapters', self.profile.read_text('utf-8'))
        self.assertTrue(reverted['profile_restored'])
        self.assertTrue(reverted['lumineos_ledger_restored'])
        self.assertEqual(self.ledger.read_bytes(), self.ledger_before)
        self.assertTrue(all(row['action'] == 'restored' for row in reverted['binaries']))


    def test_apply_syncs_the_runtime_manifest(self):
        stale = json.loads(self.manifest.read_text('utf-8'))
        self.assertEqual(stale['files'][0]['sha256'], 'F' * 64)
        result = accept.apply(self.client, self.bundle, self.build, None)
        document = json.loads(self.manifest.read_text('utf-8'))
        names = {row['name']: row['sha256'] for row in document['files']}
        self.assertEqual(names['Nanaimo.Adapter.dll'],
                         io.digest((self.runtime / 'Nanaimo.Adapter.dll').read_bytes()))
        self.assertIn('Nanaimo.Gameplay.dll', names)
        self.assertTrue(result['adapter_manifest_synced'])
        accept.revert(self.client, result['stamp'])
        self.assertEqual(json.loads(self.manifest.read_text('utf-8')), stale)
    def test_second_apply_requires_revert(self):
        accept.apply(self.client, self.bundle, self.build, None)
        with self.assertRaises(ValueError):
            accept.apply(self.client, self.bundle, self.build, None)

    def test_missing_build_file_is_refused(self):
        (self.build / 'Nanaimo.Gameplay.pdb').unlink()
        with self.assertRaises(ValueError):
            accept.apply(self.client, self.bundle, self.build, None)


class LedgerRepairTests(WindowFixture):
    def install_tables(self):
        return tables.apply(self.bundle, self.client, self.runtime)['receipt']

    def test_repair_verifies_all_layers_and_preserves_exact_backup(self):
        receipt = self.install_tables()
        with mock.patch.object(accept, 'verify_launcher_resources', return_value=[]) as verify:
            result = accept.repair_lumineos(self.client, receipt)
            verify.assert_called_once_with(self.client)
            self.assertEqual(result['status'], 'repaired')
            self.assertEqual(accept.repair_lumineos(self.client, receipt)['status'], 'unchanged')
        journal = io.load(self.client / result['receipt'])
        self.assertEqual((self.client / journal['files'][0]['backup']).read_bytes(), self.ledger_before)
        self.assertFalse(accept.lumineos_needs_sync(self.client))
        io.rollback(self.client, result['receipt'])
        self.assertEqual(self.ledger.read_bytes(), self.ledger_before)

    def test_failed_full_verification_restores_receipt(self):
        receipt = self.install_tables()
        with mock.patch.object(accept, 'verify_launcher_resources', side_effect=ValueError('other resource')):
            with self.assertRaisesRegex(ValueError, 'other resource'):
                accept.repair_lumineos(self.client, receipt)
        self.assertEqual(self.ledger.read_bytes(), self.ledger_before)
        journal = next((self.client / tables.BACKUP_ROOT).glob('story-ledger-*/receipt.json'))
        self.assertEqual(io.load(journal)['status'], 'rolled-back')

    def test_edited_table_cannot_be_blessed(self):
        receipt = self.install_tables()
        write(self.client / accept.LUMINEOS_TABLE, b'unregistered edit')
        with self.assertRaisesRegex(ValueError, 'Installed table differs'):
            accept.repair_lumineos(self.client, receipt)
        self.assertEqual(self.ledger.read_bytes(), self.ledger_before)

    def test_tampered_ledger_digest_is_rejected(self):
        receipt = self.install_tables()
        self.ledger.write_bytes(self.ledger_before.replace(b'monk-visible-additive', b'edited'))
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, 'receipt digest mismatch'):
            accept.repair_lumineos(self.client, receipt)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_unrelated_baseline_is_rejected(self):
        receipt = self.install_tables()
        self.ledger.write_bytes(ledger_text('f' * 64, 123).encode('utf-8'))
        with self.assertRaisesRegex(ValueError, 'QS baseline differs'):
            accept.repair_lumineos(self.client, receipt)

    def test_changed_backup_is_rejected(self):
        receipt = self.install_tables()
        row = next(r for r in io.load(self.client / receipt)['files'] if r['path'] == accept.LUMINEOS_TABLE)
        write(self.client / row['backup'], b'bad backup')
        with self.assertRaisesRegex(ValueError, 'QS backup differs'):
            accept.repair_lumineos(self.client, receipt)

    def test_launcher_checks_include_every_installed_layer(self):
        for marker in ('.openNanaimo-monk-dialogue.json', '.openNanaimo-hero-dragon.json',
                       '.openNanaimo-korean-pets.json'):
            write(self.client / marker, b'{}')
        with mock.patch.object(accept.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='PASS')):
            checks = accept.verify_launcher_resources(self.client)
        self.assertEqual([c['kind'] for c in checks], ['lumineos', 'monk-dialogue', 'hero', 'korean'])

    @unittest.skipUnless((accept.tables.io.ROOT / 'adapter_runtime/Nanaimo.Adapter.exe').is_file(),
                         'Managed runtime is a separate build input')
    def test_real_launcher_rejects_stale_qs_and_accepts_authorized_repair(self):
        receipt = self.install_tables()
        tool = accept.tables.io.ROOT / 'adapter_runtime/Nanaimo.Adapter.exe'
        command = [str(tool), '--tools', 'verify-resources', '--kind', 'lumineos',
                   '--client-root', str(self.client)]
        before = accept.subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(before.returncode, 0)
        self.assertIn('Installed resource mismatch: QS._D31', before.stderr)
        accept.sync_lumineos_receipt(self.client, receipt)
        after = accept.subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertIn('LUMINEOS_RESOURCES_PASS', after.stdout)


class ProfileTests(unittest.TestCase):
    def test_missing_keys_are_appended(self):
        lines = accept.with_profile_keys(['version=2', 'launch_mode=network'])
        self.assertEqual(lines[-2:], ['story_chapters=1', 'story_chapters_start=1'])

    def test_existing_keys_are_replaced_in_place(self):
        lines = accept.with_profile_keys(['story_chapters=0', 'version=2'])
        self.assertEqual(lines, ['story_chapters=1', 'version=2', 'story_chapters_start=1'])

    def test_reads_current_values(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'profile.ini'
            path.write_text('story_chapters=1\n', 'utf-8')
            self.assertEqual(accept.profile_missing(path), ['story_chapters_start'])


if __name__ == '__main__':
    unittest.main()
