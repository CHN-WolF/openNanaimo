"""Four-challenge deployment regression checks."""
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import generate_monk_combat as combat
import prepare_monk_challenges
import prepare_monk_resources as resources
import prepare_monk_village_entries as village
import prepare_client_compatibility as compatibility

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(os.environ.get('NANAIMO_CHALLENGE_BUNDLE', ROOT/'build/monk-expansion/bundle'))
ENTRY = Path(os.environ.get('NANAIMO_CHALLENGE_ENTRIES', ROOT/'build/monk-expansion/entries-release'))
CLIENT = Path(os.environ.get('NANAIMO_MONK_CN', ROOT.parent))


class CatalogTests(unittest.TestCase):
    def test_four_scopes_have_independent_slots_and_target_classes(self):
        report = json.loads((ROOT/'manifest/monk_challenge_combat.json').read_text())
        self.assertEqual(report['active_episodes'], [24,25,26,27])
        for row, targets, modes in zip(report['challenges'], [629,256,1034,518], [1,4,1,4]):
            self.assertEqual([s['slot'] for s in row['stages']], list(range(9)))
            self.assertTrue(all(s['targets'] == targets and s['boss_modes'] == modes for s in row['stages']))
        profiles = combat.tables.numeric_rows((ROOT/combat.tables.DATA).read_text(), 'hp_sync_profiles')
        selected = [p for p in profiles if p[1] == 0 and 24 <= p[0] <= 27]
        self.assertEqual(len(selected), 36)
        self.assertEqual(len({p[9] for p in selected}), 36)
        for section in combat.read_dcc((ROOT/combat.tables.CATALOG).read_bytes()):
            self.assertEqual({r[1] for r in section if r[0] == 0 and 24 <= r[1] <= 27}, {24,25,26,27})

    def test_resource_width_hazards_and_positive_target_boundaries(self):
        row = bytearray(700)
        row[4] = 4
        struct.pack_into('<i', row, 12, 99999)
        self.assertEqual(combat.checked_row(row), (0,99999))
        row[4] = 0
        with self.assertRaises(ValueError): combat.checked_row(row)
        row[4] = 4
        struct.pack_into('<i', row, 8, 1)
        with self.assertRaises(ValueError): combat.checked_row(row)


@unittest.skipUnless((BUNDLE/'manifest.json').is_file(), 'prepared resources required')
class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.saved = resources.RECIPE, resources.SCHEMA, resources.MARKER
        prepare_monk_challenges.configure()
        self.addCleanup(self.restore)

    def restore(self):
        resources.RECIPE, resources.SCHEMA, resources.MARKER = self.saved

    def test_every_dependency_resolves_and_each_stage_keeps_identity(self):
        manifest = resources.io.load(BUNDLE/'manifest.json')
        resources.validate_manifest(manifest)
        payload = BUNDLE/'payload'
        index = resources.ResourceIndex(payload)
        names = {r['path'] for r in manifest['files']}
        for row in manifest['files']:
            raw = resources.checked(payload/row['path'],row['sha256'],row['size'])
            if Path(row['path']).suffix.lower() in resources.EXTENSIONS:
                refs, _ = resources.parse_resource(raw,row['path'],payload,kr=False)
                for ref in refs:
                    if resources.reference(ref): self.assertIn(index.locate(ref),names)
        for episode in range(24,28):
            model = resources.codec_module().sstg((payload/f'flying/hd0_ep{episode}_dg00_st00.sstg').read_bytes())
            self.assertEqual(model['identity'],(0,episode,0,0))
            self.assertEqual(len(model['slots']),9)

    def test_full_transaction_repeat_and_exact_rollback(self):
        manifest = resources.io.load(BUNDLE/'manifest.json')
        with tempfile.TemporaryDirectory() as folder, patch.object(resources.io,'assert_not_running'):
            root = Path(folder)
            before = {}
            for row in manifest['files']:
                if row['before_sha256']:
                    before[row['path']] = resources.checked(BUNDLE/'payload'/row['path'],row['sha256'])
            for row in manifest['preserve_cn']:
                before[row['path']] = resources.checked(CLIENT/row['path'],row['sha256'])
            for rel, raw in before.items(): resources.io.atomic(root/rel,raw)
            result = resources.apply(BUNDLE,root)
            self.assertEqual(resources.apply(BUNDLE,root)['status'],'already-installed')
            self.assertEqual(resources.verify(root)['verified'],1154)
            resources.rollback(root,result['receipt'])
            for rel, raw in before.items(): self.assertEqual((root/rel).read_bytes(),raw)
            for row in manifest['files']:
                if row['before_sha256'] is None: self.assertFalse((root/row['path']).exists())


@unittest.skipUnless((ENTRY/village.PACK_REL).is_file(), 'prepared village required')
class RouteTests(unittest.TestCase):
    def test_center_reaches_all_action_cells_and_launcher_preserves_pack(self):
        raw = (ENTRY/village.PACK_REL).read_bytes()
        self.assertEqual(village.connected_entries(raw),{24:28,25:28,26:12,27:12})

    def test_existing_south_action_is_reachable_without_crossing_challenge(self):
        from collections import deque
        pack = village.FifthVillagePack((ENTRY/village.PACK_REL).read_bytes())
        queue = deque([(25,18)])
        seen = set(queue)
        actions = set()
        while queue:
            x,y = queue.popleft()
            action = pack.field(12,x,y,13)
            if action >= 0:
                actions.add(action)
                continue
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                cell = x+dx,y+dy
                if (cell not in seen and 0 <= cell[0] < 50 and 0 <= cell[1] < 36
                        and pack.field(12,*cell,7) == 0 and pack.field(12,*cell,10) == -1):
                    seen.add(cell);queue.append(cell)
        self.assertTrue({157,171}.issubset(actions))

    def test_launcher_keeps_current_map_identity(self):
        raw = (ENTRY/village.PACK_REL).read_bytes()
        self.assertEqual(compatibility.patch_village_pack(raw)[0],raw)
        self.assertEqual(village.derive(raw)[0],raw)

    def test_broken_interior_corridor_is_rejected(self):
        raw = bytearray((ENTRY/village.PACK_REL).read_bytes())
        pack = village.FifthVillagePack(raw)
        for x in range(22,28): struct.pack_into('<h',raw,pack.offset(19,x,5,7),1)
        with self.assertRaisesRegex(ValueError,'disconnected'): village.connected_entries(bytes(raw))

    def test_road_change_preserves_native_gate_actions_and_returns(self):
        before = village.FifthVillagePack((CLIENT/village.PACK_REL).read_bytes())
        after = village.FifthVillagePack((ENTRY/village.PACK_REL).read_bytes())
        for page in (18,19):
            for x in range(50):
                for y in range(36):
                    for field in (13,14): self.assertEqual(before.field(page,x,y,field),after.field(page,x,y,field))


if __name__ == '__main__': unittest.main(verbosity=2)
