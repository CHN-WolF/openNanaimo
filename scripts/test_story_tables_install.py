"""Checks for the transactional chapter table install.

The fixtures are synthetic bundles: the installer only reads hashes and report
fields, so no user-supplied client table is needed to exercise the transaction,
the refusal paths or the shared rollback.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_story_tables as install  # noqa: E402
import port_lumineos_resources as io  # noqa: E402


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_client(root: Path) -> tuple[Path, bytes, bytes]:
    client = root / 'client'
    qt = b'QUEST#20080625#357#' + b'0#' * 8
    qs = b'NANA_QUEST_TEXT#80625.01#633#' + b'0#' * 8
    write(client / 'QT._D30', qt)
    write(client / 'QS._D31', qs)
    return client, qt, qs


def report(name: str, payload: bytes, baseline: dict) -> dict:
    inputs = [dict(name=key, size=len(value), sha256=io.digest(value))
              for key, value in baseline.items()]
    return dict(schema='openNanaimo.story-qt-patch.v1', status='candidate-only',
                activation_allowed=False, runtime_acceptance=False, inputs=inputs,
                output=dict(name=name, size=len(payload), sha256=io.digest(payload)))


def make_bundle(root: Path, qt: bytes, qs: bytes, baseline_qt: bytes, baseline_qs: bytes,
                patch=None) -> Path:
    bundle = root / 'bundle'
    new_qt, new_qs = qt + b'chapter', qs + b'chapter'
    write(bundle / 'QT._D30', new_qt)
    write(bundle / 'QS._D31', new_qs)
    documents = {
        'patch-report.json': report('QT._D30', new_qt,
                                    {'QT._D30': baseline_qt, 'QS._D31': baseline_qs}),
        'qs-patch-report.json': report('QS._D31', new_qs,
                                       {'QS._D31': baseline_qs, 'catalog': b'{}'}),
    }
    if patch:
        patch(documents)
    for name, document in documents.items():
        write(bundle / name, io.encoded(document))
    return bundle


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client, self.qt, self.qs = make_client(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_reports_the_change_without_writing(self):
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        result = install.plan(bundle, self.client)
        self.assertEqual(result['changed'], 2)
        self.assertEqual((self.client / 'QT._D30').read_bytes(), self.qt)
        self.assertFalse(result['activation_allowed'])
        self.assertFalse((self.client / install.BACKUP_ROOT).exists())

    def test_apply_verify_rollback_round_trip(self):
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        installed = install.apply(bundle, self.client)
        self.assertEqual(installed['status'], 'installed')
        self.assertEqual(installed['changed'], 2)
        self.assertRegex(installed['receipt'],
                         r'^\.openNanaimo-resource-backups/story-tables-[0-9a-f]{32}/receipt\.json$')
        self.assertNotEqual((self.client / 'QT._D30').read_bytes(), self.qt)
        verified = install.verify(self.client, installed['receipt'])
        self.assertEqual(verified['files'], 2)
        rolled = install.rollback(self.client, installed['receipt'])
        self.assertEqual(rolled['status'], 'rolled-back')
        self.assertEqual((self.client / 'QT._D30').read_bytes(), self.qt)
        self.assertEqual((self.client / 'QS._D31').read_bytes(), self.qs)
        self.assertFalse((self.client / install.MARKER).exists())

    def test_bundle_from_another_client_is_refused(self):
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, b'other-client')
        with self.assertRaises(ValueError):
            install.apply(bundle, self.client)

    def test_enabled_candidate_is_refused(self):
        def enable(documents):
            documents['patch-report.json']['activation_allowed'] = True
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs, patch=enable)
        with self.assertRaises(ValueError):
            install.apply(bundle, self.client)

    def test_payload_must_match_its_report(self):
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        write(bundle / 'QT._D30', b'tampered')
        with self.assertRaises(ValueError):
            install.apply(bundle, self.client)

    def test_unrelated_edit_blocks_rollback(self):
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        installed = install.apply(bundle, self.client)
        write(self.client / 'QT._D30', b'someone else')
        with self.assertRaises(ValueError):
            install.rollback(self.client, installed['receipt'])

    def test_receipt_path_is_validated(self):
        for receipt in ('.openNanaimo-resource-backups/../../receipt.json',
                        '.openNanaimo-resource-backups/other-x/receipt.json'):
            with self.assertRaises(ValueError):
                install.verify(self.client, receipt)

    def test_unchanged_bundle_is_a_no_op(self):
        bundle = self.root / 'bundle'
        write(bundle / 'QT._D30', self.qt)
        write(bundle / 'QS._D31', self.qs)
        write(bundle / 'patch-report.json',
              io.encoded(report('QT._D30', self.qt, {'QT._D30': self.qt, 'QS._D31': self.qs})))
        write(bundle / 'qs-patch-report.json',
              io.encoded(report('QS._D31', self.qs, {'QS._D31': self.qs})))
        result = install.apply(bundle, self.client)
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual((self.client / 'QT._D30').read_bytes(), self.qt)

    def test_runtime_copy_is_installed_and_rolled_back_together(self):
        runtime = self.client / 'adapter_runtime'
        write(runtime / install.RUNTIME_DATA / 'QT._D30', self.qt)
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        planned = install.plan(bundle, self.client, runtime)
        self.assertEqual(planned['changed'], 3)
        installed = install.apply(bundle, self.client, runtime)
        runtime_table = runtime / install.RUNTIME_DATA / 'QT._D30'
        self.assertNotEqual(runtime_table.read_bytes(), self.qt)
        self.assertEqual(runtime_table.read_bytes(), (self.client / 'QT._D30').read_bytes())
        install.verify(self.client, installed['receipt'])
        install.rollback(self.client, installed['receipt'])
        self.assertEqual(runtime_table.read_bytes(), self.qt)

    def test_runtime_outside_the_client_is_refused(self):
        other = self.root / 'elsewhere'
        write(other / install.RUNTIME_DATA / 'QT._D30', self.qt)
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        with self.assertRaises(ValueError):
            install.plan(bundle, self.client, other)

    def test_runtime_table_must_be_the_shipped_baseline(self):
        runtime = self.client / 'adapter_runtime'
        write(runtime / install.RUNTIME_DATA / 'QT._D30', b'a different table')
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        with self.assertRaises(ValueError):
            install.plan(bundle, self.client, runtime)

    def test_unfinished_receipt_blocks_apply(self):
        bundle = make_bundle(self.root, self.qt, self.qs, self.qt, self.qs)
        install.apply(bundle, self.client)
        receipt = next((self.client / install.BACKUP_ROOT).glob('*/receipt.json'))
        journal = json.loads(receipt.read_text('utf-8'))
        journal['status'] = 'applying'
        receipt.write_bytes(io.encoded(journal))
        with self.assertRaises(ValueError):
            install.apply(bundle, self.client)


if __name__ == '__main__':
    unittest.main()
