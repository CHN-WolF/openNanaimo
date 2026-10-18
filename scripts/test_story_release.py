"""Chapter delivery integrity, transactions and optional real-file deployment."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import deploy_story_release as deploy
import package_story_resource_kit as kit

io = deploy.io


class ArchiveTests(unittest.TestCase):
    def test_published_archive_contains_all_three_resource_groups(self):
        data = kit.read()
        self.assertEqual(len(data), 1228)
        self.assertEqual(sorted(kit.inventory()['groups'].values()), [37, 37, 1154])
        self.assertNotIn('game.exe', data)
        sidecar = kit.ARCHIVE.with_suffix('.zip.sha256').read_text('ascii').split()
        self.assertEqual(sidecar, [io.file_hash(kit.ARCHIVE), kit.ARCHIVE.name])

    def test_extra_and_duplicate_archive_members_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../game.exe', b'bad')
            with self.assertRaisesRegex(ValueError, 'coverage'):
                kit.read(archive)

    def test_corrupt_resource_refused(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            kit.checked(b'bad', dict(path='test', size=3, sha256=io.digest(b'new')))

    def test_upgrade_baselines_pin_existing_outputs(self):
        baseline = io.load(deploy.ROOT / 'manifest/story_deployment_baselines.json')
        self.assertEqual(baseline['recipe_sha256'], io.file_hash(io.RECIPE))
        rows = {r['path']: r for r in io.load(io.RECIPE)['files']}
        self.assertEqual(len({r['path'] for r in baseline['files']}), 197)
        for row in baseline['files']:
            self.assertEqual((row['size'], row['sha256']),
                             (rows[row['path']]['output_size'], rows[row['path']]['output_sha256']))
            self.assertNotEqual(row['before_sha256'], row['sha256'])


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = Path(self.temp.name)
        io.atomic(self.client / 'game.exe', b'original')
        io.atomic(self.client / 'adapter_data/save.db', b'private')
        self.data = {'game.exe': b'patched', 'effs/new.eff': b'asset'}
        self.guard = patch.object(io, 'assert_not_running')
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.preparer = patch.object(deploy, 'prepare', return_value=self.data)
        self.preparer.start()
        self.addCleanup(self.preparer.stop)
        self.verifier = patch.object(deploy, 'verify', return_value={'status': 'verified'})
        self.mock_verify = self.verifier.start()
        self.addCleanup(self.verifier.stop)

    def test_plan_apply_repeat_and_exact_rollback(self):
        self.assertEqual(deploy.install(self.client)['changed'], 2)
        self.assertEqual((self.client / 'game.exe').read_bytes(), b'original')
        self.assertFalse((self.client / '.openNanaimo-resource-backups').exists())
        result = deploy.install(self.client, apply=True)
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(deploy.install(self.client, apply=True)['status'], 'already-installed')
        deploy.restore(self.client, result['receipt'])
        self.assertEqual((self.client / 'game.exe').read_bytes(), b'original')
        self.assertFalse((self.client / 'effs/new.eff').exists())
        self.assertEqual((self.client / 'adapter_data/save.db').read_bytes(), b'private')

    def test_verification_failure_rolls_back_all_files(self):
        self.mock_verify.side_effect = ValueError('injected failure')
        with self.assertRaisesRegex(ValueError, 'injected failure'):
            deploy.install(self.client, apply=True)
        self.assertEqual((self.client / 'game.exe').read_bytes(), b'original')
        self.assertFalse((self.client / 'effs/new.eff').exists())
        journals = list(self.client.glob(deploy.PREFIX + '*/receipt.json'))
        self.assertEqual(io.load(journals[0])['status'], 'rolled-back')

    def test_post_install_edit_refuses_rollback_before_any_write(self):
        result = deploy.install(self.client, apply=True)
        io.atomic(self.client / 'effs/new.eff', b'user edit')
        with self.assertRaisesRegex(ValueError, 'Edited deployment'):
            deploy.restore(self.client, result['receipt'])
        self.assertEqual((self.client / 'game.exe').read_bytes(), b'patched')

    def test_damaged_backup_refuses_rollback(self):
        result = deploy.install(self.client, apply=True)
        journal = io.load(self.client / result['receipt'])
        io.atomic(self.client / journal['files'][0]['backup'], b'damaged')
        with self.assertRaisesRegex(ValueError, 'Damaged'):
            deploy.restore(self.client, result['receipt'])

    def test_running_target_refused(self):
        with patch.object(io, 'assert_not_running', side_effect=ValueError('running')):
            with self.assertRaisesRegex(ValueError, 'running'):
                deploy.install(self.client, apply=True)
        self.assertEqual((self.client / 'game.exe').read_bytes(), b'original')

    def test_concurrent_preparation_edit_is_preserved(self):
        def prepare(client, archive, enable, review, snapshot):
            snapshot.update({n: io.file_hash(client / n) for n in self.data})
            io.atomic(client / 'game.exe', b'concurrent user edit')
            return self.data
        with patch.object(deploy, 'prepare', side_effect=prepare):
            with self.assertRaisesRegex(ValueError, 'Concurrent edit before backup'):
                deploy.install(self.client, apply=True)
        self.assertEqual((self.client / 'game.exe').read_bytes(), b'concurrent user edit')

    def test_mid_install_failure_restores_partial_writes(self):
        atomic = io.atomic
        def fail_asset(path, raw):
            if path == self.client / 'effs/new.eff' and raw == b'asset':
                raise OSError('injected write failure')
            atomic(path, raw)
        with patch.object(io, 'atomic', side_effect=fail_asset):
            with self.assertRaisesRegex(OSError, 'injected write failure'):
                deploy.install(self.client, apply=True)
        self.assertEqual((self.client / 'game.exe').read_bytes(), b'original')
        self.assertFalse((self.client / 'effs/new.eff').exists())

    def test_unsafe_receipt_refused(self):
        with self.assertRaisesRegex(ValueError, 'receipt path'):
            deploy.restore(self.client, '../receipt.json')

    def test_interrupted_install_blocks_new_deployment(self):
        result = deploy.install(self.client, apply=True)
        path = self.client / result['receipt']
        journal = io.load(path)
        journal['status'] = 'applying'
        io.atomic(path, io.encoded(journal))
        with self.assertRaisesRegex(ValueError, 'Unfinished'):
            deploy.install(self.client, apply=True)


class TableTests(unittest.TestCase):
    def test_chapter_only_baseline_accepted_and_original_rows_protected(self):
        path = deploy.ROOT / (deploy.DATA + 'QT._D30')
        target = path.read_bytes()
        table = deploy.qt.parse_qt(deploy.qt.decrypt_qt(target))
        chapters = [r for r in table['quests'] if 73000000 <= int(r['header'][0]) < 73000016]
        owned = {int(n) for r in chapters for n in r['objective_ids']}
        table['quests'] = [r for r in table['quests'] if r not in chapters]
        table['objectives'] = [r for r in table['objectives'] if int(r[0]) not in owned]
        before = deploy.qt.encrypt_qt(deploy.qt.serialize_qt(table))
        deploy.checked_table('QT._D30', before, target)
        table['objectives'][0][1] = 'edited'
        with self.assertRaisesRegex(ValueError, 'Non-chapter'):
            deploy.checked_table('QT._D30', deploy.qt.encrypt_qt(deploy.qt.serialize_qt(table)), target)

    def test_nonchapter_qs_edit_refused(self):
        target = (deploy.ROOT / (deploy.DATA + 'QS._D31')).read_bytes()
        table = deploy.qs.parse_qs(deploy.qt.decrypt_qt(target))
        key, value = table['entries'][0]
        table['entries'][0] = key, value + 'edit'
        with self.assertRaisesRegex(ValueError, 'Non-chapter'):
            deploy.checked_table('QS._D31', deploy.qt.encrypt_qt(deploy.qs.serialize_qs(table)), target)


class RewardTests(unittest.TestCase):
    def test_review_id_length_matches_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deploy.reward_review(root, None, False)
            template = root / 'reward-template.json'
            document = io.load(template)
            document['reviews'][0]['review_id'] = 'x' + ' ' * 128
            io.atomic(template, io.encoded(document))
            with tempfile.TemporaryDirectory() as other:
                with self.assertRaisesRegex(ValueError, 'identifier length'):
                    deploy.reward_review(Path(other), template, False)

    def test_boolean_reward_number_is_not_an_integer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deploy.reward_review(root, None, False)
            template = root / 'reward-template.json'
            document = io.load(template)
            document['reviews'][0]['source_rewards'][0][0] = True
            io.atomic(template, io.encoded(document))
            with tempfile.TemporaryDirectory() as other:
                with self.assertRaisesRegex(ValueError, 'triples or durations'):
                    deploy.reward_review(Path(other), template, False)

    def test_embedded_current_template_and_no_implicit_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(deploy.reward_review(root, None, False))
            template = io.load(root / 'reward-template.json')
            self.assertEqual(len(template['reviews']), 16)
            self.assertFalse(any(r['approved'] for r in template['reviews']))
            with tempfile.TemporaryDirectory() as other:
                with self.assertRaisesRegex(ValueError, 'not reviewed'):
                    deploy.reward_review(Path(other), root / 'reward-template.json', True)

    def test_enable_without_review_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'requires --reward-review'):
                deploy.reward_review(Path(tmp), None, True)


@unittest.skipUnless(os.environ.get('NANAIMO_STORY_BASELINE'), 'set NANAIMO_STORY_BASELINE for real-file deployment')
class DeploymentTests(unittest.TestCase):
    def test_fresh_install_repeat_verification_and_rollback(self):
        baseline = Path(os.environ['NANAIMO_STORY_BASELINE'])
        with tempfile.TemporaryDirectory(prefix='nanaimo-story-accept-') as tmp:
            client = Path(tmp)
            shutil.copytree(baseline, client, dirs_exist_ok=True)
            before = {p.relative_to(client).as_posix(): io.file_hash(p)
                      for p in client.rglob('*') if p.is_file()}
            plan = deploy.install(client)
            self.assertGreater(plan['changed'], 1228)
            # This approval exists only in an isolated test and is never published.
            with tempfile.TemporaryDirectory(prefix='nanaimo-test-review-') as review_dir:
                review = Path(review_dir) / 'reward-template.json'
                deploy.reward_review(Path(review_dir), None, False)
                document = io.load(review)
                for row in document['reviews']:
                    row.update(approved=True, review_id='synthetic-deployment-test')
                io.atomic(review, io.encoded(document))
                result = deploy.install(client, apply=True, enable=True, review=review)
            self.assertEqual(result['status'], 'installed')
            self.assertTrue(deploy.chapters_enabled(client))
            self.assertEqual(deploy.install(client, apply=True)['status'], 'already-installed')
            self.assertEqual(deploy.verify(client)['resource_files'], 1228)
            deploy.restore(client, result['receipt'])
            after = {p.relative_to(client).as_posix(): io.file_hash(p)
                     for p in client.rglob('*') if p.is_file()
                     and not p.relative_to(client).as_posix().startswith('.openNanaimo-resource-backups/')}
            self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main(verbosity=2)
