"""Deterministic fifth-village entry and transaction construction checks."""
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import prepare_monk_village_entries as entry
from test_monk_entry import scene, pack


def fixture():
    raw = bytearray(scene())
    grid = entry.scene_preview.VillageScene(raw).grid_start
    for cell in range(1800):
        struct.pack_into('<h', raw, grid + cell * 36 + 14, 0)
    import prepare_client_compatibility as compatibility
    result = bytearray(pack([(50000 + page, bytes(raw)) for page in range(25)] + [(99999, b'preserved')]))
    parsed = entry.FifthVillagePack(result)
    for a, b in list(zip(compatibility.ROUTE, compatibility.ROUTE[1:])) + [(12, 11)]:
        for source, target in ((a, b), (b, a)):
            exits, arrivals = compatibility._strips(compatibility._side(source, target))
            for x, y in exits: struct.pack_into('<h', result, parsed.offset(source, x, y, 10), target)
            for x, y in arrivals: struct.pack_into('<h', result, parsed.offset(source, x, y, 11), target)
    return bytes(result)


class EntryTests(unittest.TestCase):
    def test_regions_are_four_disjoint_native_actions(self):
        self.assertEqual([r['action'] for r in entry.ENTRIES], [168, 169, 170, 171])
        self.assertEqual([r['episode'] for r in entry.ENTRIES], [24, 25, 26, 27])
        self.assertEqual([r['entry_index'] for r in entry.ENTRIES], [8, 9, 10, 11])
        cells = [(r['page'], *c) for r in entry.ENTRIES for c in r['cells']]
        self.assertEqual(len(cells), 80)
        self.assertEqual(len(set(cells)), 80)

    def test_only_action_words_and_four_markers_change(self):
        import prepare_client_compatibility as compatibility
        before = compatibility.patch_village_pack(fixture())[0]
        after, manifest = entry.derive(before)
        self.assertEqual(len(manifest['changes']), 80)
        a, b = entry.FifthVillagePack(before), entry.FifthVillagePack(after)
        old = dict(entry.scene_preview.scenes.records(before))
        new = dict(entry.scene_preview.scenes.records(after))
        selected = {50000 + r['page'] for r in entry.ENTRIES}
        for key in old.keys() - selected:
            self.assertEqual(old[key], new[key])
        for r in entry.ENTRIES:
            x = entry.scene_preview.VillageScene(a.record(r['page']))
            y = entry.scene_preview.VillageScene(b.record(r['page']))
            expected = bytearray(x.raw[:x.grid_start + 64800])
            for cx, cy in r['cells']:
                struct.pack_into('<h', expected, x.grid_start + (cx * 36 + cy) * 36 + 26, entry.action_value(r))
            self.assertEqual(bytes(expected), y.raw[:y.grid_start + 64800])
            self.assertEqual(x.tail, y.tail)
            self.assertEqual(x.layers[:2], y.layers[:2])
            self.assertEqual(x.layers[2], y.layers[2][:-1])
            self.assertEqual(x.textures, y.textures[:-1])
            self.assertEqual(struct.unpack('<I3f', y.layers[2][-1])[1:], tuple(r['placement']))
        self.assertEqual(entry.verify(after)['cells'], 80)
        self.assertEqual(entry.derive(after)[0], after)

    def test_installed_noncanonical_directory_is_idempotent(self):
        raw = bytearray(entry.derive(fixture())[0])
        raw[13:21], raw[21:29] = raw[21:29], raw[13:21]
        self.assertEqual(entry.derive(bytes(raw))[0], bytes(raw))

    def test_route_collision_and_action_conflicts_refused(self):
        for field, value in [(7, 1), (10, 9), (11, 0), (14, 168), (13, 166)]:
            raw = bytearray(fixture())
            p = entry.FifthVillagePack(raw)
            struct.pack_into('<h', raw, p.offset(9, 44, 14, field), value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                entry.derive(bytes(raw))

    def test_trailing_or_overlapping_pack_refused(self):
        raw = fixture()
        with self.assertRaises(ValueError): entry.derive(raw + b'x')
        changed = bytearray(raw)
        changed[25:29] = changed[17:21]
        with self.assertRaises(ValueError): entry.derive(bytes(changed))

    def test_missing_foreground_visual_refused(self):
        raw = entry.derive(fixture())[0]
        p = entry.FifthVillagePack(raw)
        record = p.record(9)
        v = entry.scene_preview.VillageScene(record)
        replacement = record[:v.grid_start + 64800] + struct.pack('<i3I', -1, 0, 0, 0) + v.tail
        raw = entry._replace_records(raw, {50009: replacement})
        with self.assertRaisesRegex(ValueError, 'visual resource'): entry.verify(raw)

    def install_fixture(self, root):
        source, bundle = root/'client', root/'bundle'
        entry.io.atomic(source/entry.PACK_REL, fixture())
        entry.io.atomic(source/entry.VISUAL_RESOURCE, b'fixture-effect')
        entry.build(source, bundle)
        return source, bundle

    def test_install_repeat_and_rollback_restore_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry.io, 'assert_not_running'):
            source, bundle = self.install_fixture(Path(temp))
            result = entry.apply(bundle, source)
            self.assertEqual(result['status'], 'installed')
            self.assertEqual(entry.apply(bundle, source)['status'], 'already-installed')
            result = entry.rollback(source, result['receipt'])
            self.assertEqual(result['status'], 'rolled-back')
            self.assertEqual((source/entry.PACK_REL).read_bytes(), fixture())
            self.assertFalse((source/entry.MARKER).exists())

    def test_missing_or_changed_visual_refused_before_install(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry.io, 'assert_not_running'):
            source, bundle = self.install_fixture(Path(temp))
            (source/entry.VISUAL_RESOURCE).write_bytes(b'wrong-effect')
            with self.assertRaisesRegex(ValueError, 'visual resource'): entry.apply(bundle, source)
            self.assertEqual((source/entry.PACK_REL).read_bytes(), fixture())
            self.assertFalse((source/entry.MARKER).exists())

    def test_repeated_install_rechecks_visual(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry.io, 'assert_not_running'):
            source, bundle = self.install_fixture(Path(temp))
            entry.apply(bundle, source)
            (source/entry.VISUAL_RESOURCE).write_bytes(b'wrong-effect')
            with self.assertRaisesRegex(ValueError, 'visual resource'): entry.apply(bundle, source)

    def test_receipt_failure_restores_pack_and_marker(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry.io, 'assert_not_running'):
            source, bundle = self.install_fixture(Path(temp))
            atomic = entry.io.atomic
            def fail_once(path, data):
                if path.name == 'receipt.json' and json.loads(data).get('status') == 'installed':
                    raise OSError('fixture receipt failure')
                atomic(path, data)
            with patch.object(entry.io, 'atomic', side_effect=fail_once), self.assertRaises(OSError):
                entry.apply(bundle, source)
            self.assertEqual((source/entry.PACK_REL).read_bytes(), fixture())
            self.assertFalse((source/entry.MARKER).exists())

    def test_foreign_receipt_and_changed_target_refused(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry.io, 'assert_not_running'):
            source, bundle = self.install_fixture(Path(temp))
            result = entry.apply(bundle, source)
            path = source/result['receipt']; original = path.read_bytes()
            receipt = json.loads(original); receipt['client'] = str(source/'other')
            path.write_bytes(entry.encoded(receipt))
            with self.assertRaisesRegex(ValueError, 'another client'): entry.rollback(source, result['receipt'])
            path.write_bytes(original)
            target = source/entry.PACK_REL; target.write_bytes(target.read_bytes() + b'x')
            with self.assertRaisesRegex(ValueError, 'changed after'): entry.rollback(source, result['receipt'])

    def test_changed_manifest_refused(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry.io, 'assert_not_running'):
            source, bundle = self.install_fixture(Path(temp))
            path = bundle/'manifest.json'; m = json.loads(path.read_bytes()); m['entries'][0]['episode'] = 25
            path.write_bytes(entry.encoded(m))
            with self.assertRaisesRegex(ValueError, 'contract differs'): entry.apply(bundle, source)

    def test_parent_resource_exception_is_exact_and_keeps_peer_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract = json.loads((entry.ROOT/'manifest/monk_village_entries.json').read_text('utf-8'))
            pack = root/entry.PACK_REL
            pack.parent.mkdir(parents=True)
            pack.write_bytes(b'installed')
            peer = root/'peer.bin'; peer.write_bytes(b'peer')
            contract.update(pack_size=9, pack_before_sha256='1'*64,
                            pack_after_sha256=entry.digest(b'installed'))
            recipe = root/'manifest/monk_village_entries.json'
            recipe.parent.mkdir(); recipe.write_bytes(entry.encoded(contract))
            m = dict(id='fixture', files=[dict(path=entry.PACK_REL, size=8, sha256='1'*64),
                                         dict(path='peer.bin', size=4, sha256=entry.digest(b'peer'))],
                     preserve_l7_combat=[])
            with patch.object(entry.io, 'ROOT', root), patch.object(entry.io, 'validate_manifest'):
                self.assertEqual(entry.io.verify(root, m)['verified'], 2)
                peer.write_bytes(b'edit')
                with self.assertRaisesRegex(ValueError, 'peer.bin'): entry.io.verify(root, m)
                peer.write_bytes(b'peer')
                m['files'][0]['sha256'] = '2'*64
                with self.assertRaisesRegex(ValueError, 'Village_map'): entry.io.verify(root, m)
                m['files'][0]['sha256'] = '1'*64
                pack.write_bytes(b'installed!')
                with self.assertRaisesRegex(ValueError, 'Village_map'): entry.io.verify(root, m)

    def test_configured_pack_matches_published_identity(self):
        name = os.environ.get('NANAIMO_MONK_VILLAGE_PACK')
        if not name: self.skipTest('optional installed resource identity')
        raw = Path(name).read_bytes()
        target, _ = entry.derive(raw)
        contract = json.loads((entry.ROOT/'manifest/monk_village_entries.json').read_text('utf-8'))
        self.assertEqual(entry.digest(target), contract['pack_after_sha256'].lower())
        self.assertEqual(len(target), contract['pack_size'])
        self.assertEqual(entry.derive(target)[0], target)


if __name__ == '__main__': unittest.main()
