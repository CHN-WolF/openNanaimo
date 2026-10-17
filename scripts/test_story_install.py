"""Transactional portrait-preview tests; synthetic files are not client acceptance."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_story_portraits as install


class StoryInstallChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client, self.bundle = self.root / 'client', self.root / 'bundle'
        self.client.mkdir(); self.bundle.mkdir()
        self.files = {'effs/interface/NPC_6_0.eff': b'synthetic-effect',
                      'effs/interface/NPC_6.im3': b'synthetic-image'}
        self.rows = [dict(path=p, size=len(b), sha256=install.io.digest(b)) for p, b in self.files.items()]
        self.recipe = dict(schema='openNanaimo.story-portraits.v1', source_catalog_sha256='fixture',
                           activation_allowed=False, runtime_acceptance=False, npc_scope=[6],
                           effects=[dict(npc_uid=6, expression=0)], files=self.rows)
        self.recipe_path = self.root / 'recipe.json'
        self.package_path = self.root / 'package.json'
        self.write(self.recipe_path, self.recipe)
        self.write(self.package_path, dict(schema='openNanaimo.chapter-story.v1', source_catalog_sha256='fixture',
            activation_allowed=False, runtime_acceptance=False, chapters=[dict(dialogue=[dict(speeches=[dict(
                npc_uid=6, source_attributes=dict(expression='0'))])])]))
        self.manifest = dict(schema='openNanaimo.story-portraits.v1.bundle',
                             recipe_sha256=install.io.digest(install.io.encoded(self.recipe)),
                             status='prepared-not-installed', activation_allowed=False, runtime_acceptance=False,
                             files=[dict(row, disposition='additive-candidate') for row in self.rows])
        self.write(self.bundle / 'manifest.json', self.manifest)
        for rel, raw in self.files.items():
            p = self.bundle / 'payload' / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        for target, value in [('RECIPE', self.recipe_path), ('PACKAGE', self.package_path)]:
            context = patch.object(install, target, value); context.start(); self.addCleanup(context.stop)
        # Process enumeration is unrelated to these synthetic temporary directories.
        context = patch.object(install.io, 'assert_not_running'); context.start(); self.addCleanup(context.stop)
        self.guard = self.client / 'game.exe'; self.guard.write_bytes(b'do-not-change-client')
        (self.client / 'QS._D31').write_bytes(b'do-not-change-text')

    @staticmethod
    def write(path, obj):
        path.write_bytes(install.io.encoded(obj))

    def apply(self):
        return install.apply(self.bundle, self.client, allow_inactive_preview=True)

    def check_clean(self, reused=()):
        self.assertEqual(self.guard.read_bytes(), b'do-not-change-client')
        self.assertEqual((self.client / 'QS._D31').read_bytes(), b'do-not-change-text')
        self.assertFalse((self.client / install.MARKER).exists())
        for rel, raw in self.files.items():
            if rel in reused:
                self.assertEqual((self.client / rel).read_bytes(), raw)
            else:
                self.assertFalse((self.client / rel).exists())

    def receipt(self):
        return next((self.client / install.BACKUPS).glob('*/receipt.json')).relative_to(self.client).as_posix()

    def test_requires_explicit_preview(self):
        with self.assertRaisesRegex(ValueError, 'Explicit'):
            install.apply(self.bundle, self.client)
        self.check_clean()

    def test_add_verify_rollback(self):
        result = self.apply()
        self.assertEqual(result['status'], 'installed-inactive-preview')
        self.assertFalse(result['activation_allowed']); self.assertFalse(result['runtime_acceptance'])
        for rel, raw in self.files.items():
            self.assertEqual((self.client / rel).read_bytes(), raw)
        self.assertEqual(install.verify(self.client)['files'], 2)
        self.assertEqual(self.apply()['status'], 'already-installed-preview')
        self.assertEqual(install.rollback(self.client, result['receipt'])['status'], 'rolled-back')
        self.check_clean()
        self.assertEqual(install.rollback(self.client, result['receipt'])['status'], 'already-rolled-back')
        self.assertEqual(self.apply()['status'], 'installed-inactive-preview')

    def test_identical_resource_reused_not_removed(self):
        rel = next(iter(self.files))
        p = self.client / rel; p.parent.mkdir(parents=True); p.write_bytes(self.files[rel])
        self.manifest['files'][0]['disposition'] = 'reuse-identical'
        self.write(self.bundle / 'manifest.json', self.manifest)
        receipt = self.apply()['receipt']
        install.rollback(self.client, receipt)
        self.check_clean([rel])

    def test_existing_conflict_preserved(self):
        rel = next(iter(self.files)); p = self.client / rel
        p.parent.mkdir(parents=True); p.write_bytes(b'unrelated-existing')
        with self.assertRaisesRegex(ValueError, 'baseline'):
            self.apply()
        self.assertEqual(p.read_bytes(), b'unrelated-existing')
        self.assertFalse((self.client / install.BACKUPS).exists())

    def test_changed_baseline_refuses_even_identical_new_file(self):
        rel = next(iter(self.files)); p = self.client / rel
        p.parent.mkdir(parents=True); p.write_bytes(self.files[rel])
        with self.assertRaisesRegex(ValueError, 'baseline'):
            self.apply()

    def test_corrupt_payload_has_no_partial_writes(self):
        (self.bundle / 'payload' / list(self.files)[1]).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Corrupt payload'):
            self.apply()
        self.check_clean()

    def test_rejects_extra_payload(self):
        (self.bundle / 'payload' / 'game.exe').write_bytes(b'not-authorized')
        with self.assertRaisesRegex(ValueError, 'Unexpected bundle'):
            self.apply()
        self.check_clean()

    def test_duplicate_bundle_rows(self):
        self.manifest['files'].append(dict(self.manifest['files'][0]))
        self.write(self.bundle / 'manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'coverage'):
            self.apply()

    def test_stale_or_enabled_bundle(self):
        for key, value in [('recipe_sha256', '0' * 64), ('activation_allowed', True), ('runtime_acceptance', True)]:
            with self.subTest(key=key):
                doc = dict(self.manifest); doc[key] = value
                self.write(self.bundle / 'manifest.json', doc)
                with self.assertRaisesRegex(ValueError, 'Unmatched or enabled'):
                    self.apply()
                self.check_clean()

    def test_final_marker_failure_rolls_back_all_new_files(self):
        original = install.io.atomic
        def fail(path, data):
            if path == self.client / install.MARKER:
                raise OSError('injected-marker-write')
            return original(path, data)
        with patch.object(install.io, 'atomic', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.apply()
        self.check_clean()
        self.assertEqual(install.io.load(self.client / self.receipt())['status'], 'rolled-back')

    def test_interrupted_apply_requires_receipt_recovery(self):
        original = install.io.atomic
        class SimulatedPowerLoss(BaseException):
            pass
        def crash(path, data):
            if path == self.client / install.MARKER:
                raise SimulatedPowerLoss()
            return original(path, data)
        with patch.object(install.io, 'atomic', side_effect=crash):
            with self.assertRaises(SimulatedPowerLoss):
                self.apply()
        self.assertEqual(install.io.load(self.client / self.receipt())['status'], 'applying')
        with self.assertRaisesRegex(ValueError, 'Interrupted'):
            self.apply()
        install.rollback(self.client, self.receipt())
        self.check_clean()

    def test_rollback_conflict_full_preflight(self):
        receipt = self.apply()['receipt']
        rel = next(iter(self.files)); (self.client / rel).write_bytes(b'post-install-user-edit')
        with self.assertRaisesRegex(ValueError, 'Rollback conflict'):
            install.rollback(self.client, receipt)
        self.assertTrue((self.client / install.MARKER).exists())
        self.assertTrue((self.client / list(self.files)[1]).exists())
        self.assertEqual((self.client / rel).read_bytes(), b'post-install-user-edit')

    def test_receipt_path_and_ownership(self):
        receipt = self.apply()['receipt']
        for rel in ['../outside.json', '/absolute.json', receipt.replace('/', '\\')]:
            with self.assertRaises(ValueError):
                install.rollback(self.client, rel)
        path = self.client / receipt; original = install.io.load(path)
        for change in ['client', 'coverage', 'digest', 'before']:
            doc = json.loads(json.dumps(original))
            if change == 'client': doc['client'] = str(self.root)
            if change == 'coverage': doc['files'][0]['path'] = 'game.exe'
            if change == 'digest': doc['files'][0]['sha256'] = '0' * 64
            if change == 'before': doc['files'][0]['before_sha256'] = '0' * 64
            self.write(path, doc)
            with self.subTest(change=change), self.assertRaises(ValueError):
                install.rollback(self.client, receipt)
            self.assertTrue((self.client / install.MARKER).exists())
        self.write(path, original)
        install.rollback(self.client, receipt)
        self.check_clean()

    def test_overlapping_roots(self):
        with self.assertRaisesRegex(ValueError, 'overlap'):
            install.apply(self.client, self.client, True)

    def test_verify_detects_changes(self):
        self.apply()
        (self.client / next(iter(self.files))).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Installed portrait differs'):
            install.verify(self.client)

    def test_monk_portrait_recipe_not_owned(self):
        self.recipe['files'][0]['path'] = 'effs/interface/NPC_62_0.eff'
        self.write(self.recipe_path, self.recipe)
        with self.assertRaisesRegex(ValueError, 'ownership'):
            self.apply()


if __name__ == '__main__':
    unittest.main()
