"""Host construction checks only; never original-client entry acceptance."""
import json
import os
from pathlib import Path
import struct
import unittest

import prepare_monk_entry as entry

BUNDLE = Path(os.environ['NANAIMO_MONK_ENTRY_BUNDLE']) if os.environ.get('NANAIMO_MONK_ENTRY_BUNDLE') else Path('__missing_monk_entry_bundle__')
FONT = Path(os.environ.get("WINDIR", "__missing_windows_font__")) / "Fonts/simsun.ttc"


def table(rows):
    return b''.join(struct.pack('<i', uid) + name.encode('ascii').ljust(260, b'\0')
                    for uid, name in rows) + struct.pack('<i', -1)


def scene(*, mode=1, textures=None, layers=None, tail=b'opaque-tail'):
    prefix = struct.pack('<8I', 5, mode, 2, 0, 16, 16, 50, 36) + b'H' * 264
    floor = table([(0, 'images/Village_images/floor.im3')])
    grid = b''.join(struct.pack('<18h', *([0, 1] + [-1] * 16)) for _ in range(1800))
    textures = textures if textures is not None else [(0, 'effs/village/tree.eff')]
    layers = layers if layers is not None else [[], [struct.pack('<I3f', 0, 10., 20., 0.)], []]
    return prefix + floor + grid + table(textures) + b''.join(
        struct.pack('<I', len(rows)) + b''.join(rows) for rows in layers) + tail


def pack(rows):
    offset = 13 + len(rows) * 8
    head = bytearray(b'NANA_PACK' + struct.pack('<I', len(rows)))
    bodies = []
    for key, raw in rows:
        body = struct.pack('<I', len(raw)) + raw
        head += struct.pack('<II', key, offset)
        offset += len(body)
        bodies.append(body)
    return bytes(head) + b''.join(bodies)


def catalog(name, rows):
    head = ['NANA_QUEST_TEXT', '80625.01', str(len(rows))] if name == 'QS._D31' else ['NANA_TEXT', 'CN00106.01']
    return entry.monk.encrypt_cn(('#'.join(head + [x for pair in rows for x in pair]) + '#').encode('gbk'))


class SceneTests(unittest.TestCase):
    def test_only_selected_record_and_decoration_change(self):
        base = scene()
        raw = pack([(50018, b'unrelated-L7'), (10027, base), (50019, b'unrelated-L8')])
        changed = entry.derive_pack(raw)
        before, after = dict(entry.scenes.records(raw)), dict(entry.scenes.records(changed))
        self.assertEqual(before[50018], after[50018])
        self.assertEqual(before[50019], after[50019])
        a, b = entry.VillageScene(base), entry.VillageScene(after[10027][4:])
        self.assertEqual(a.raw[:a.grid_start + 64800], b.raw[:b.grid_start + 64800])
        self.assertEqual(a.tail, b.tail)
        self.assertEqual(a.layers[0], b.layers[0])
        self.assertEqual(a.layers[1], b.layers[1])
        self.assertEqual(a.layers[2], b.layers[2][:-1])
        self.assertEqual(struct.unpack('<I3f', b.layers[2][-1])[1:], (293., 157., 0.))
        self.assertEqual(entry.derive_pack(changed), changed)

    def test_foreground_monk_moves_to_actor_layer_once(self):
        placement = struct.pack('<I3f', 1, 293., 157., 0.)
        tree = struct.pack('<I3f', 0, 10., 20., 0.)
        for old_layers in ([[], [tree], [placement]], [[], [tree, placement], [placement]]):
            raw = scene(textures=[(0, 'tree.eff'), (1, 'effs/village/' + entry.EFFECT)], layers=old_layers)
            changed = entry.VillageScene(raw).derive()
            self.assertEqual(entry.VillageScene(changed).layers, [[], [tree], [placement]])
            self.assertEqual(entry.VillageScene(changed).derive(), changed)

    def test_noncanonical_pack_directory_order_preserved_when_idempotent(self):
        raw = entry.derive_pack(pack([(10027, scene()), (50018, b'unrelated')]))
        swapped = bytearray(raw)
        swapped[13:21], swapped[21:29] = raw[21:29], raw[13:21]
        self.assertEqual(entry.derive_pack(bytes(swapped)), bytes(swapped))

    def test_no_foreign_page_fallback(self):
        with self.assertRaisesRegex(ValueError, 'missing first-village'):
            entry.derive_pack(pack([(50018, scene())]))

    def test_zero_layer_mode_refused(self):
        with self.assertRaisesRegex(ValueError, 'unsupported VIL'):
            entry.VillageScene(scene(mode=0))

    def test_dimensions_refused(self):
        raw = bytearray(scene())
        struct.pack_into('<I', raw, 24, 51)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            entry.VillageScene(raw)

    def test_truncated_grid_and_objects_refused(self):
        raw = scene(tail=b'')
        for size in (10, 500, len(raw) - 1):
            with self.subTest(size=size), self.assertRaises(ValueError):
                entry.VillageScene(raw[:size])

    def test_unknown_and_nonfinite_placement_refused(self):
        for placement in [struct.pack('<I3f', 9, 1., 2., 0.), struct.pack('<I3f', 0, float('nan'), 2., 0.)]:
            with self.assertRaises(ValueError):
                entry.VillageScene(scene(layers=[[], [placement], []]))

    def test_duplicate_or_out_of_range_native_index_refused(self):
        for textures in [[(0, 'a'), (0, 'b')], [(64, 'a')], [(-2, 'a')]]:
            with self.assertRaisesRegex(ValueError, 'texture index'):
                entry.VillageScene(scene(textures=textures))

    def test_native_table_sentinel_capacity(self):
        textures = [(i, 'a' + str(i)) for i in range(64)]
        with self.assertRaisesRegex(ValueError, 'sentinel'):
            entry.VillageScene(scene(textures=textures))
        textures.pop()
        with self.assertRaisesRegex(ValueError, 'slot'):
            entry.VillageScene(scene(textures=textures)).derive()

    def test_conflicting_placement_not_silently_replaced(self):
        raw = scene(textures=[(0, 'effs/village/' + entry.EFFECT)])
        with self.assertRaisesRegex(ValueError, 'conflicting monk'):
            entry.VillageScene(raw).derive()

    def test_duplicate_normalized_resource_refused(self):
        names = [(0, 'effs/village/' + entry.EFFECT), (1, 'EFFS\\VILLAGE\\' + entry.EFFECT.upper())]
        with self.assertRaisesRegex(ValueError, 'duplicate monk texture'):
            entry.VillageScene(scene(textures=names)).derive()

    def test_pack_overlap_and_trailer_not_dropped(self):
        raw = pack([(10027, scene()), (50018, b'unrelated')])
        with self.assertRaisesRegex(ValueError, 'trailing'):
            entry.derive_pack(raw + b'unknown')
        broken = bytearray(raw)
        broken[25:29] = broken[17:21]
        with self.assertRaises(ValueError):
            entry.derive_pack(broken)


class CatalogTests(unittest.TestCase):
    def test_existing_pairs_order_preserved_and_count_updated(self):
        for name, start in [('QS._D31', 3), ('GS._D20', 2)]:
            raw = catalog(name, [('2', 'two'), ('1', 'one')])
            result = entry.merge_catalog(raw, name, {'6000': 'trial'})
            fields = entry.crypto.decrypt(result, entry.crypto.CN_KEY).decode('gbk').split('#')
            self.assertEqual(fields[start:], ['2', 'two', '1', 'one', '6000', 'trial', ''])
            if start == 3:
                self.assertEqual(fields[2], '3')
            self.assertEqual(entry.merge_catalog(result, name, {'6000': 'trial'}), result)

    def test_conflicting_text_refused(self):
        with self.assertRaisesRegex(ValueError, 'collision'):
            entry.merge_catalog(catalog('GS._D20', [('2504', 'old')]), 'GS._D20', {'2504': 'new'})

    def test_duplicate_numeric_uid_refused(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            entry.merge_catalog(catalog('QS._D31', [('1', 'a'), ('01', 'b')]), 'QS._D31', {})

    def test_malformed_count_refused(self):
        raw = entry.monk.encrypt_cn(b'NANA_QUEST_TEXT#80625.01#9#1#a#')
        with self.assertRaisesRegex(ValueError, 'count'):
            entry.merge_catalog(raw, 'QS._D31', {})

    def test_empty_delimiter_nul_and_non_gbk_refused(self):
        for text in ['', 'a#b', 'a\0b', '\U0001f600']:
            with self.assertRaises((ValueError, UnicodeEncodeError)):
                entry.merge_catalog(catalog('GS._D20', []), 'GS._D20', {'2504': text})

    def test_non_numeric_added_uid_refused(self):
        for uid in ['x', '-1', '01']:
            with self.assertRaises(ValueError):
                entry.merge_catalog(catalog('GS._D20', []), 'GS._D20', {uid: 'trial'})


class LocalCandidateTests(unittest.TestCase):
    @unittest.skipUnless((BUNDLE / 'manifest.json').exists(), 'separate local candidate input')
    def test_real_candidate_hashes_and_acceptance_boundaries(self):
        root = BUNDLE
        manifest = json.loads((root / 'manifest.json').read_text('utf8'))
        identifier = manifest.pop('id')
        self.assertEqual(identifier, entry.monk.io.digest(entry.monk.io.encoded(manifest)))
        self.assertFalse(manifest['runtime_accepted'])
        self.assertFalse(manifest['entry']['interactive'])
        self.assertEqual(manifest['entry']['status'], 'scene-preview-unbound')
        self.assertEqual(manifest['entry']['layer'], 2)
        self.assertEqual(manifest['entry']['name_font_size'], 13)
        self.assertEqual(len(manifest['files']), 7)
        for row in manifest['files']:
            raw = entry.monk.io.safe(root / 'payload', row['path']).read_bytes()
            self.assertEqual(len(raw), row['size'])
            self.assertEqual(entry.monk.io.digest(raw), row['sha256'])
        raw = (root / 'payload' / entry.PACK).read_bytes()
        self.assertEqual(entry.derive_pack(raw), raw)
        refs = entry.monk.codec_module().eff2((root / 'payload/effs/village' / entry.EFFECT).read_bytes())['refs']
        self.assertEqual(set(refs), {entry.SPRITE, entry.SHADOW, entry.LABEL})

    @unittest.skipUnless(FONT.exists(), 'local user-owned font')
    def test_generated_chinese_name_image_native_header(self):
        template = struct.pack('<9I2f', 0, 2, 120, 39, 19, 39, 19, 8, 0, 19.5, 9.5)
        template += b''.join(struct.pack('<Hh', 2, 0) for _ in range(14))
        template += b''.join(struct.pack('<HhHHH', 5, 1, 19, 1, 0xFFE0) for _ in range(5))
        text = ''.join(map(chr, (0x4FEE, 0x9053, 0x50E7)))
        image, raw = entry.name_image(FONT, text, template)
        self.assertEqual(entry.MONK_NAME_FONT_SIZE, 13)
        self.assertEqual(image.size, (45, 21))
        self.assertEqual(struct.unpack_from('<2f', raw, 36), (22.5, 10.5))
        self.assertEqual(struct.unpack_from('<9I', raw), (0, 2, len(raw) - 8, 45, 21, 45, 21, 8, 0))
        self.assertEqual(sum(image.getpixel((x, 14))[3] != 0 for x in range(45)), 0)
        self.assertEqual(sum(image.getpixel((x, 15))[3] != 0 for x in range(45)), 0)
        for y in range(16, 21):
            self.assertEqual(image.getpixel((22, y)), (255, 255, 0, 255))
            self.assertEqual(sum(image.getpixel((x, y))[3] != 0 for x in range(45)), 1)
        top = image.crop((0, 0, 45, 14))
        self.assertEqual(top.getbbox(), (2, 0, 42, 14))


if __name__ == '__main__':
    unittest.main(verbosity=2)
