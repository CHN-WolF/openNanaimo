"""Focused monk format, localization, closure and resource transaction tests.

These checks establish resource preparation; client entrance acceptance is an
independent validation item.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import prepare_monk_resources as monk
import lumineos_codec as codec

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(os.environ.get('NANAIMO_MONK_BUNDLE', ROOT / 'build/monk-prototype'))


def u32(value):
    return struct.pack('<I', value)


def name(value, size=260):
    return value.encode('ascii').ljust(size, b'\0')


def synthetic_sstg():
    plain = u32(6) + u32(1234) + u32(0) + bytes(524) + u32(0)
    plain += name('music.ogg') + bytes(260) + u32(1)
    plain += u32(1) + u32(0) + name('cloud_obj_00.mmo')
    for i in range(9):
        plain += name(f'slot{i}.smmo') + u32(80 + i) + name(str(i))
    plain += bytes(260) + u32(0)
    for i in range(9):
        plain += u32(2) + name('ep21_dg00_obj_sq_off_00.mmo') + name(f'extra{i}.mmo')
    plain += struct.pack('<4I', 2, 0, 0, 0)
    return codec.xor(plain, 40)


class FormatTests(unittest.TestCase):
    def test_mmo_and_pon_fixed_fields_rewrite_without_scalar_changes(self):
        old = 'ep21_dg00_obj_sq_off_00.mmo'
        new = 'monk_ep21_dg00_obj_sq_off_00.mmo'
        header = u32(200) + codec.xor(name('one.eff', 64))
        scalars = b''.join(bytes([7]) * size for _, size in codec.SCALARS)
        event0 = name(old, 64) + bytes([9]) * 8
        event8 = bytes([10]) * 8 + name(old, 64)
        body = scalars + codec.xor(name(old, 64)) * 3
        body += b'\x01' + codec.xor(event0) + b'\x01' + codec.xor(event8)
        body += bytes([11]) * 8 + codec.xor(name(old, 64)) * 2
        body += bytes([12]) * 4 + codec.xor(name(old, 64))
        for _ in range(3): body += bytes([13]) * 4 + codec.xor(name(old, 64))
        body += b'\x01' + codec.xor(event0)
        raw = header + body
        after, count = monk.rewrite_names(raw, 'a.mmo', {old: new})
        self.assertEqual(count, 12)
        _, fields, _ = monk.name_fields(raw, 'a.mmo')
        changed = {i for off, size, _ in fields for i in range(off, off + size)}
        self.assertTrue(all(raw[i] == after[i] for i in range(len(raw)) if i not in changed))
        self.assertEqual(len(raw), len(after))
        row = bytearray(1612)
        for off in (0, 280, 540, 800, 1060, 1340): row[off:off + 260] = name(old)
        pon = u32(106) + codec.xor(name('one.eff')) + codec.xor(bytes([15]) * 28)
        pon += codec.xor(row) + codec.xor(name(old))
        after, count = monk.rewrite_names(pon, 'a.pon', {old: new})
        self.assertEqual(count, 7)
        self.assertEqual(pon[264:292], after[264:292])
        self.assertEqual(len(pon), len(after))

    def test_sm2_and_eff_reference_fields_roundtrip(self):
        old, new = 'old.im3', 'new.im3'
        def scalar(value, key): return codec.xor(u32(value), key) + b'\0'
        raw = scalar(2, 40) + scalar(16, 40) + scalar(16, 19)
        raw += scalar(1, 31) + scalar(1, 163) + scalar(1, 33) + bytes(5)
        raw += codec.xor(name(old, 261), 89) + scalar(1, 40) + codec.xor(name(old, 261), 40) + scalar(0, 40)
        after, count = monk.rewrite_names(raw, 'a.sm2', {old: new})
        self.assertEqual(count, 2)
        self.assertEqual(codec.sm2(after)['refs'], [new, new])
        eff = struct.pack('<5I', 2, 0, 0, 1, 1) + bytes(8) + name(old) + bytes(12 * 4 + 48)
        after, count = monk.rewrite_names(eff, 'a.eff', {old: new})
        self.assertEqual(count, 1)
        self.assertEqual(codec.eff2(after)['refs'], [new])

    def test_standard_identity_nine_independent_slots_and_preloads(self):
        raw = synthetic_sstg()
        stage = codec.sstg(raw)
        renamed = {'cloud_obj_00.mmo': 'monk_cloud_obj_00.mmo',
                   'ep21_dg00_obj_sq_off_00.mmo': 'monk_ep21_dg00_obj_sq_off_00.mmo'}
        converted = codec.patch_sstg_identity(raw, (0, 24, 0, 0), ((2, 0, 0, 0),))
        converted, count = monk.rewrite_names(converted, 'flying/standard.sstg', renamed)
        after = codec.sstg(converted)
        self.assertEqual(after['identity'], (0, 24, 0, 0))
        self.assertEqual(after['slots'], stage['slots'])
        self.assertEqual(count, 10)
        self.assertEqual([v[1] for v in after['slots']], list(range(80, 89)))
        self.assertEqual([v[1] for v in after['extra']], [f'extra{i}.mmo' for i in range(9)])
        self.assertTrue(all(v[0] == 'monk_ep21_dg00_obj_sq_off_00.mmo' for v in after['extra']))
        self.assertEqual(len(raw), len(converted))

    def test_invalid_identity_and_truncation_refused(self):
        with self.assertRaisesRegex(ValueError, 'unexpected KR SSTG identity'):
            codec.patch_sstg_identity(synthetic_sstg(), (0, 24, 0, 0), ((9, 0, 0, 0),))
        with self.assertRaises(AssertionError):
            codec.sstg(synthetic_sstg()[:-1])

    def test_bmo_modes_children_bounded_and_rewritten(self):
        header = struct.pack('<11I', 2, 2500, 0, 0, 0, 0, 0, 0, 0, 0, 1)
        plain = header
        for children in (['flying\\mmo\\cloud_obj_00.mmo'], ['a.mmo', 'b.mmo']):
            plain += bytes(304) + u32(len(children)) + b''.join(name(s, 208) for s in children)
        raw = codec.xor(plain, 56)
        model, _ = monk.bmo_model(raw)
        self.assertEqual([len(mode['children']) for mode in model['modes']], [1, 2])
        after, count = monk.rewrite_names(raw, 'boss.bmo', {'cloud_obj_00.mmo': 'monk_cloud_obj_00.mmo'})
        self.assertEqual(count, 1)
        self.assertEqual(monk.bmo_model(after)[0]['modes'][0]['children'], ['flying\\mmo\\monk_cloud_obj_00.mmo'])
        with self.assertRaises(AssertionError): monk.bmo_model(raw[:-1])
        bad = bytearray(plain)
        struct.pack_into('<I', bad, 44 + 304, 101)
        with self.assertRaisesRegex(ValueError, 'child count'):
            monk.bmo_model(codec.xor(bad, 56))

    def test_crs_geometry_and_terminal_boundary(self):
        model = monk.crs_model(struct.pack('<2I', 61, 233) + bytes(8 * 233))
        self.assertEqual(model, dict(width=61, height=233, stride=8, refs=[]))
        for raw in (b'', struct.pack('<2I', 0, 1), struct.pack('<2I', 16, 16) + bytes(63)):
            with self.assertRaises(ValueError): monk.crs_model(raw)

    def test_smmo_boundary_and_tail_dependency(self):
        raw = codec.xor(u32(1) + struct.pack('<4I', 10, 11, 12, 13) + name('tail.eff'), 40)
        self.assertEqual(monk.smmo_model(raw), ([(10, 11, 12, 13)], ['tail.eff']))
        with self.assertRaises(AssertionError): monk.smmo_model(raw + b'x')

    def test_reference_rename_preserves_directory_separator(self):
        renames = {'cloud_obj_00.mmo': 'monk_cloud_obj_00.mmo'}
        self.assertEqual(monk.rename_value('flying\\mmo\\cloud_obj_00.mmo', renames), 'flying\\mmo\\monk_cloud_obj_00.mmo')
        with self.assertRaisesRegex(ValueError, 'capacity'):
            monk.rewrite_names(synthetic_sstg(), 'a.sstg', {'cloud_obj_00.mmo': 'x' * 260})


class LocalizationTests(unittest.TestCase):
    def test_gbk_json_and_complete_dialogue(self):
        raw = monk.LOCALIZATION.read_text('utf-8')
        self.assertEqual(json.loads(raw.encode('gbk').decode('gbk')), json.loads(raw))
        local = monk.io.load(monk.LOCALIZATION)
        self.assertEqual(len(local['quest_strings']), 20)
        self.assertEqual(len(local['game_strings']), 8)
        self.assertIn('16', local['quest_strings']['6000'])
        self.assertIn('\u5ba0\u7269', local['quest_strings']['6000'])
        self.assertIn('\u4e8c\u6b21\u6210\u957f', local['quest_strings']['6000'])

    def test_cn_encryption_catalog_structure_and_action_placeholders(self):
        from prepare_hero_dragon import decrypt
        local = monk.io.load(monk.LOCALIZATION)
        data = monk.localized_resources(local)
        prefix = '.openNanaimo-monk/'
        qfields = decrypt(data[prefix + 'monk_qs._D31'], monk.CN_KEY).decode('gbk').split('#')
        self.assertEqual(qfields[:3], ['NANA_QUEST_TEXT', '80625.01', '20'])
        self.assertEqual(dict(zip(qfields[3:-1:2], qfields[4:-1:2])), local['quest_strings'])
        gfields = decrypt(data[prefix + 'monk_gs._D20'], monk.CN_KEY).decode('gbk').split('#')
        self.assertEqual(gfields[:2], ['NANA_TEXT', 'CN00106.01'])
        self.assertEqual(dict(zip(gfields[2:-1:2], gfields[3:-1:2])), local['game_strings'])
        xml = data[prefix + 'monk_action.xml']
        self.assertEqual(decrypt(data[prefix + 'monk_action._S1'], monk.CN_KEY), xml)
        root = ET.fromstring(xml.decode('gbk').split('\n', 1)[1])
        self.assertEqual([s.get('uid') for s in root], ['24000', '24001', '24002', '24003'])
        for i, script in enumerate(root):
            self.assertEqual(script[1].attrib, dict(type='D_START', dtype='0', episode=str(24 + i), dungeon='0', level='0', condition='1'))
            self.assertEqual(script[3].get('string_uid'), str(6002 + 3 * i))
            self.assertEqual(script[5].get('string_uid'), str(6001 + 3 * i))

    def test_incomplete_or_invalid_catalog_refused(self):
        local = monk.io.load(monk.LOCALIZATION)
        del local['quest_strings']['6000']
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            monk.localized_resources(local)
        local = monk.io.load(monk.LOCALIZATION)
        local['quest_strings']['6000'] = 'a#b'
        with self.assertRaisesRegex(ValueError, 'text'):
            monk.localized_resources(local)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='monk-resources-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = self.root / 'client'
        self.bundle = self.root / 'bundle'
        self.client.mkdir()
        self.bundle.mkdir()
        self.recipe_path = self.root / 'recipe.json'
        self.manifest = dict(schema=monk.SCHEMA, runtime_accepted=False, entry_binding='placeholder-unbound', files=[], preserve_cn=[])
        pins = []
        for path, before, payload in [('images/a.im3', None, b'new-a'), ('images/b.im3', None, b'new-b'), ('images/shared.im3', b'CN', b'CN')]:
            if before is not None:
                monk.io.atomic(monk.io.safe(self.client, path), before)
            monk.io.atomic(monk.io.safe(self.bundle / 'payload', path), payload)
            sha = monk.io.digest(payload)
            self.manifest['files'].append(dict(path=path, before_sha256=monk.io.digest(before) if before is not None else None,
                                              sha256=sha, size=len(payload), transform='copy'))
            pins.append(dict(path=path, output_sha256=sha, output_size=len(payload), transform='copy'))
        self.manifest['localization_sha256'] = monk.io.digest(monk.LOCALIZATION.read_bytes())
        monk.io.atomic(self.client / 'images/original.im3', b'keep-original')
        self.manifest['preserve_cn'].append(dict(path='images/original.im3', sha256=monk.io.digest(b'keep-original'), size=len(b'keep-original')))
        monk.io.atomic(self.recipe_path, monk.io.encoded(dict(files=pins, preserve_cn=self.manifest['preserve_cn'])))
        self.manifest['recipe_sha256'] = monk.io.digest(self.recipe_path.read_bytes())
        self.sign()
        patch = mock.patch.object(monk, 'RECIPE', self.recipe_path)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(monk.io, 'assert_not_running')
        patch.start()
        self.addCleanup(patch.stop)

    def sign(self):
        self.manifest.pop('id', None)
        self.manifest['id'] = monk.io.digest(monk.io.encoded(self.manifest))
        monk.io.atomic(self.bundle / 'manifest.json', monk.io.encoded(self.manifest))

    def test_apply_verify_idempotence_and_exact_rollback(self):
        result = monk.apply(self.bundle, self.client)
        self.assertEqual(result['changed'], 2)
        self.assertEqual(monk.verify(self.client)['verified'], 3)
        self.assertEqual(monk.apply(self.bundle, self.client)['status'], 'already-installed')
        self.assertEqual(monk.rollback(self.client, result['receipt'])['status'], 'rolled-back')
        self.assertFalse((self.client / 'images/a.im3').exists())
        self.assertEqual((self.client / 'images/shared.im3').read_bytes(), b'CN')
        self.assertEqual((self.client / 'images/original.im3').read_bytes(), b'keep-original')
        self.assertEqual(monk.rollback(self.client, result['receipt'])['status'], 'already-rolled-back')

    def test_all_payloads_preflight_before_writing(self):
        (self.bundle / 'payload/images/b.im3').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            monk.apply(self.bundle, self.client)
        self.assertFalse((self.client / 'images/a.im3').exists())

    def test_install_and_preserved_cn_conflicts(self):
        (self.client / 'images/b.im3').write_bytes(b'user-edit')
        with self.assertRaisesRegex(ValueError, 'install conflict'):
            monk.apply(self.bundle, self.client)
        self.assertFalse((self.client / 'images/a.im3').exists())
        (self.client / 'images/b.im3').unlink()
        (self.client / 'images/original.im3').write_bytes(b'user-edit')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            monk.apply(self.bundle, self.client)

    def test_failure_restores_partial_transaction(self):
        atomic = monk.io.atomic
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path == self.client / 'images/b.im3' and not failed:
                failed = True
                raise OSError('simulated commit failure')
            atomic(path, data)
        with mock.patch.object(monk.io, 'atomic', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'simulated'):
                monk.apply(self.bundle, self.client)
        self.assertFalse((self.client / 'images/a.im3').exists())
        receipt = next((self.client / '.openNanaimo-resource-backups').glob('*/receipt.json'))
        self.assertEqual(monk.io.load(receipt)['status'], 'rolled-back')

    def test_rollback_preflights_all_rows_and_preserves_later_edits(self):
        result = monk.apply(self.bundle, self.client)
        (self.client / 'images/a.im3').write_bytes(b'later-edit')
        with self.assertRaisesRegex(ValueError, 'rollback conflict'):
            monk.rollback(self.client, result['receipt'])
        self.assertTrue((self.client / monk.MARKER).exists())
        self.assertEqual((self.client / 'images/b.im3').read_bytes(), b'new-b')

    def test_rollback_coverage_and_backup_paths_are_checked(self):
        result = monk.apply(self.bundle, self.client)
        path = monk.io.safe(self.client, result['receipt'])
        journal = monk.io.load(path)
        journal['files'][0]['backup'] = 'images/original.im3'
        monk.io.atomic(path, monk.io.encoded(journal))
        with self.assertRaisesRegex(ValueError, 'contract mismatch'):
            monk.rollback(self.client, result['receipt'])

    def test_shared_lock_and_interrupted_journal_block_apply(self):
        lock = self.client / '.openNanaimo-resource-port.lock'
        lock.write_bytes(b'other-owner')
        with self.assertRaises(FileExistsError): monk.apply(self.bundle, self.client)
        self.assertEqual(lock.read_bytes(), b'other-owner')
        lock.unlink()
        monk.io.atomic(self.client / '.openNanaimo-resource-backups/other/receipt.json', monk.io.encoded(dict(status='applying')))
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            monk.apply(self.bundle, self.client)

    def test_pinned_coverage_digest_and_additive_contract(self):
        tampered = copy.deepcopy(self.manifest)
        tampered['files'][0]['sha256'] = '0' * 64
        tampered.pop('id')
        tampered['id'] = monk.io.digest(monk.io.encoded(tampered))
        with self.assertRaisesRegex(ValueError, 'pinned recipe'):
            monk.validate_manifest(tampered)
        tampered = copy.deepcopy(self.manifest)
        tampered['files'][0]['before_sha256'] = '0' * 64
        tampered.pop('id')
        tampered['id'] = monk.io.digest(monk.io.encoded(tampered))
        with self.assertRaisesRegex(ValueError, 'non-additive'):
            monk.validate_manifest(tampered)

    def test_preservation_manifest_coverage_is_pinned(self):
        self.manifest['preserve_cn'] = []
        self.sign()
        with self.assertRaisesRegex(ValueError, 'preservation recipe coverage'):
            monk.apply(self.bundle, self.client)
        self.assertFalse((self.client / 'images/a.im3').exists())

    def test_concurrent_edit_preserved_and_interrupted_receipt_retained(self):
        atomic = monk.io.atomic
        changed = False
        def edit_later_target(path, data):
            nonlocal changed
            atomic(path, data)
            if path == self.client / 'images/a.im3' and not changed:
                changed = True
                atomic(self.client / 'images/b.im3', b'concurrent-user-edit')
        with mock.patch.object(monk.io, 'atomic', side_effect=edit_later_target):
            with self.assertRaisesRegex(ValueError, 'rollback conflict'):
                monk.apply(self.bundle, self.client)
        self.assertEqual((self.client / 'images/b.im3').read_bytes(), b'concurrent-user-edit')
        receipt = next((self.client / '.openNanaimo-resource-backups').glob('*/receipt.json'))
        self.assertEqual(monk.io.load(receipt)['status'], 'applying')
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            monk.apply(self.bundle, self.client)

    def test_unsafe_paths_and_wrong_receipt_refused(self):
        for path in ('../other', 'images/../bad', 'images\\bad', 'C' + ':/bad', 'images/CON.im3', 'images/a. '):
            with self.assertRaises(ValueError): monk.io.safe(self.client, path)
        with self.assertRaisesRegex(ValueError, 'monk transaction'):
            monk.rollback(self.client, 'images/original.im3')


@unittest.skipUnless((BUNDLE / 'manifest.json').exists(), 'local monk bundle is a separate preparation input')
class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = monk.io.load(BUNDLE / 'manifest.json')
        cls.payload = BUNDLE / 'payload'

    def test_every_output_pin_and_recursive_reference_resolves(self):
        monk.validate_manifest(self.manifest)
        index = monk.ResourceIndex(self.payload)
        paths = {row['path'] for row in self.manifest['files']}
        for row in self.manifest['files']:
            raw = monk.checked(monk.io.safe(self.payload, row['path']), row['sha256'], row['size'])
            if Path(row['path']).suffix.lower() not in monk.EXTENSIONS: continue
            refs, _ = monk.parse_resource(raw, row['path'], self.payload, kr=False)
            for ref in refs:
                if monk.reference(ref): self.assertIn(index.locate(ref), paths, (row['path'], ref))

    def test_first_stage_actual_nine_slots_preload_and_boss(self):
        model = codec.sstg((self.payload / 'flying/hd0_ep24_dg00_st00.sstg').read_bytes())
        self.assertEqual(model['identity'], (0, 24, 0, 0))
        self.assertEqual(len(model['slots']), 9)
        self.assertEqual([len(slot) for slot in model['extra']], [61] * 9)
        self.assertTrue(all(slot[:2] == ['hu00_dg00_00.smmo', 100] for slot in model['slots']))
        summary = self.manifest['dependency_report']['summary']
        self.assertEqual(summary['slots'][0]['ordinary_rows'], 629)
        self.assertEqual(summary['slots'][0]['positive_hp_rows'], 413)
        self.assertEqual(len(summary['slots'][0]['ordinary_resources']), 29)
        bmo, _ = monk.bmo_model((self.payload / 'flying/mmo/hu00_dg00_bbm.bmo').read_bytes())
        self.assertEqual(len(bmo['modes']), 1)
        self.assertEqual(len(bmo['modes'][0]['children']), 1)
        _, rows, _ = codec.mmo_model((self.payload / 'flying/mmo/hu00_dg00_bbm.mmo').read_bytes(), self.payload, False)
        self.assertEqual(len(rows), 25)
        self.assertEqual([(mem[4], struct.unpack_from('<i', mem, 8)[0], struct.unpack_from('<i', mem, 408)[0]) for mem, _ in rows[:24]], [(4, 0, 24)] * 24)
        self.assertEqual(struct.unpack_from('<i', rows[24][0], 8)[0], 80000)

    def test_two_conflict_aliases_are_in_recipe_and_used_when_reachable(self):
        recipe = monk.io.load(monk.RECIPE)
        self.assertEqual(len(recipe['renames']), 2)
        paths = {row['path'] for row in recipe['files']}
        for old, new in recipe['renames'].items():
            self.assertNotIn(old, paths)
            if new not in paths: continue
            for edge in self.manifest['dependency_report']['edges']:
                if edge['target'] == old: self.assertEqual(edge['output_target'], new)

    def test_complete_bundle_apply_verify_and_rollback_in_isolated_client(self):
        with tempfile.TemporaryDirectory(prefix='monk-full-transaction-') as folder:
            client = Path(folder) / 'client'
            client.mkdir()
            originals = {}
            for row in self.manifest['files']:
                if row['before_sha256'] is not None:
                    originals[row['path']] = (self.payload / row['path']).read_bytes()
            for row in self.manifest['preserve_cn']:
                candidates = list(self.payload.rglob(Path(row['path']).name))
                matches = [p for p in candidates if monk.io.file_hash(p) == row['sha256']]
                if matches:
                    originals[row['path']] = matches[0].read_bytes()
                else:
                    source_client = Path(os.environ.get('NANAIMO_MONK_CN', '.'))
                    originals[row['path']] = monk.checked(monk.io.safe(source_client, row['path']), row['sha256'], row['size'])
            for path, raw in originals.items(): monk.io.atomic(monk.io.safe(client, path), raw)
            with mock.patch.object(monk.io, 'assert_not_running'):
                installed = monk.apply(BUNDLE, client)
                self.assertEqual(monk.verify(client)['verified'], len(self.manifest['files']))
                monk.rollback(client, installed['receipt'])
            self.assertFalse((client / monk.MARKER).exists())
            for row in self.manifest['files']:
                path = client / row['path']
                if row['before_sha256'] is None: self.assertFalse(path.exists())
            for path, raw in originals.items(): self.assertEqual((client / path).read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
