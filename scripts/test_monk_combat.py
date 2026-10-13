"""First-challenge additive catalogs, independent selectors and resource boundaries."""
from pathlib import Path
import json
import os
import re
import struct
import subprocess
import tempfile
import unittest

import generate_monk_combat as gen

ROOT = gen.ROOT
CLIENT = Path(os.environ.get('NANAIMO_MONK_CLIENT', ROOT/'build/monk-prototype/payload'))
BASELINE = Path(os.environ.get('NANAIMO_MONK_SOURCE', ROOT))


def encode_dcc(sections):
    return b'DCC7' + b''.join(struct.pack('<I', len(s)) + b''.join(s) for s in sections)


def dcc_row(index, episode, uid=1, score=123):
    key = struct.pack('<5BH', 0, episode, 0, 0, 0, uid)
    template = struct.pack('<iB4i', 7, 0, 100, 90, score, 0)
    return key + (template if index == 0 else struct.pack('<iiB', 100, score, 1) if index == 1
                  else struct.pack('<BBi', 0, 0, 24) + template if index == 2
                  else struct.pack('<H', 5) + template)


class CatalogBoundaryTests(unittest.TestCase):
    def test_dcc_merge_is_idempotent_and_preserves_peer_bytes(self):
        original = [[dcc_row(i, 1), dcc_row(i, 24), dcc_row(i, 23)] for i in range(4)]
        replacement = [[dcc_row(i, 24, 2, 17)] for i in range(4)]
        expected = encode_dcc([[s[0], *r, s[2]] for s, r in zip(original, replacement)])
        actual = gen.merge_dcc(encode_dcc(original), replacement)
        self.assertEqual(actual, expected)
        self.assertEqual(gen.merge_dcc(actual, replacement), expected)
        self.assertEqual([struct.unpack_from('<i', s[0], offset)[0] for s, offset in
                          zip(gen.read_dcc(actual), (20, 11, 26, 22))], [123]*4)

    def test_dcc_rejects_truncation_duplicate_keys_and_trailing_data(self):
        original = encode_dcc([[dcc_row(i, 1)] for i in range(4)])
        for invalid in (original[:-1], original+b'x', b'BAD7'+original[4:]):
            with self.assertRaises(ValueError):
                gen.read_dcc(invalid)
        with self.assertRaises(ValueError):
            gen.read_dcc(encode_dcc([[dcc_row(i, 1)]*2 for i in range(4)]))
        with self.assertRaises(ValueError):
            gen.merge_dcc(original, [[], [], []])

    def test_append_cleanup_retains_original_text(self):
        text = 'static const unsigned table[2] = {\n    {0u,1u},\n    {1u,2u},\n};\n'
        for boundary in (None, r'^[ \t]*\{1u,'):
            generated = gen.append(text, 'table', ['    {0u,24u},'], boundary)
            self.assertEqual(gen.clean(generated), text)
            self.assertEqual(gen.append(gen.clean(generated), 'table', ['    {0u,24u},'], boundary), generated)

    def test_bmo_consumes_entire_mode_and_child_layout(self):
        header = bytearray(44)
        struct.pack_into('<I', header, 0, 2)
        mode = bytearray(308)
        struct.pack_into('<I', mode, 304, 1)
        raw = bytes(header+mode) + b'hu00_dg00_bbm.mmo\0'.ljust(208, b'\0')
        with tempfile.TemporaryDirectory(dir=ROOT/'build', prefix='monk-bmo-test-') as temp:
            root = Path(temp)
            (root/'flying').mkdir()
            path = root/'flying/boss.bmo'
            for invalid in (raw[:-1], raw+b'x', raw[:44]+b'\1'+raw[45:]):
                path.write_bytes(gen.codec.xor(invalid, 56))
                with self.assertRaises(ValueError):
                    gen.Resources(root).boss_names('boss.bmo')
            path.write_bytes(gen.codec.xor(raw, 56))
            self.assertEqual(gen.Resources(root).boss_names('boss.bmo'), [['hu00_dg00_bbm.mmo']])

    def test_preload_selectors_do_not_mix_alternative_slots(self):
        class Resources:
            inputs = {}
            def mmo(self, name):
                mem = bytearray(688)
                struct.pack_into('<4i', mem, 8, 10 if name == 'a.mmo' else 20, 3, 100, 0)
                struct.pack_into('<i', mem, 408, -1)
                return [(bytes(mem), [])], []
        profiles = [(24, 0, 0, 0, s//3, s%3, s, 100, 0, 1000+s*629, 629) for s in range(9)]
        model = {'extra': [['a.mmo' if s % 2 == 0 else 'b.mmo']*61 for s in range(9)]}
        baseline = dict(schema=3, resources=[], rows=[], scopes=[], inputs={})
        result = gen.merge_preloads(baseline, Resources(), model, profiles)
        self.assertEqual(len(result['rows']), 9*61)
        for slot, scope in enumerate(result['scopes']):
            rows = [r for r in result['rows'] if r[0] == scope['profile_row']]
            self.assertEqual([r[1] for r in rows], list(range(629, 690)))
            self.assertEqual({r[4] for r in rows}, {10 if slot % 2 == 0 else 20})
        self.assertEqual(gen.merge_preloads(result, Resources(), model, profiles), result)

    def test_pon_consumes_all_rows_preserves_zero_and_bounds_owner(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build', prefix='monk-pon-test-') as temp:
            root = Path(temp)
            (root/'flying').mkdir()
            eff_dir = root/'effs/game/shootinggamebasic'
            eff_dir.mkdir(parents=True)
            (eff_dir/'test.eff').write_bytes(struct.pack('<5I', 2, 0, 0, 1, 2))
            prefix = bytearray(28)
            rows = [bytearray(1612), bytearray(1612)]
            struct.pack_into('<I', rows[1], 0x114, 219)
            path = root/'flying/test.pon'
            def write(owner):
                struct.pack_into('<I', prefix, 24, owner)
                path.write_bytes(struct.pack('<I', 106) + gen.codec.xor(b'test.eff\0'.ljust(260, b'\0')) +
                                 gen.codec.xor(prefix) + gen.codec.xor(b''.join(rows)) + gen.codec.xor(bytes(260)))
            write(4200)
            resources = gen.Resources(root)
            self.assertEqual(resources.projectiles(['test.pon']), {'test.pon': (4200, [0, 219])})
            self.assertEqual(set(resources.inputs), {'flying/test.pon', 'effs/game/shootinggamebasic/test.eff'})
            write(65536)
            with self.assertRaisesRegex(ValueError, 'owner'):
                gen.Resources(root).projectiles(['test.pon'])

    def test_output_cannot_target_production_or_client(self):
        for output in (ROOT, CLIENT, ROOT/'release'):
            with self.assertRaisesRegex(ValueError, 'isolated directory'):
                gen.generate(CLIENT, output)


class MonkCombatGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (CLIENT/gen.STAGE).is_file():
            raise FileNotFoundError('Converted first-challenge resources required; set NANAIMO_MONK_CLIENT')
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT/'build', prefix='monk-combat-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name)/'first'
        cls.baseline = Path(cls.temp.name)/'baseline'
        gen.prepare_baseline(BASELINE, cls.baseline)
        cls.report = gen.generate(CLIENT, cls.output, cls.baseline)
        cls.hp = (cls.output/gen.tables.DATA).read_text('utf8')
        cls.profiles = gen.tables.numeric_rows(cls.hp, 'hp_sync_profiles')
        cls.targets = gen.tables.numeric_rows(cls.hp, 'hp_sync_target_defs')
        cls.new_profiles = [p for p in cls.profiles if (p[1], p[0], p[2], p[3]) == gen.SCOPE]

    def test_repeat_generation_and_additive_source_are_byte_identical(self):
        expected = {p: (self.output/p).read_bytes() for p in self.report['outputs']}
        again = gen.generate(CLIENT, self.output, self.baseline)
        self.assertEqual(again, self.report)
        for path, data in expected.items():
            self.assertEqual((self.output/path).read_bytes(), data, path)
        repeated = Path(self.temp.name)/'repeated'
        report = gen.generate(CLIENT, repeated, self.output)
        self.assertEqual(report, self.report)
        for path, data in expected.items():
            self.assertEqual((repeated/path).read_bytes(), data, path)

    def test_old_hp_boss_damage_terminal_and_contact_rows_are_retained(self):
        arrays = [(gen.tables.DATA, ('hp_sync_profiles', 'hp_sync_target_defs', 'hp_sync_resources')),
                  (gen.tables.BOSS, ('boss_component_boss_profiles', 'boss_component_boss_modes', 'boss_component_boss_components')),
                  (gen.tables.DAMAGE, ('stage_damage_stage_attack_values', 'stage_damage_stage_attack_resources', 'stage_damage_stage_attack_scopes')),
                  (gen.tables.TERMINAL_ITEMS, ('terminal_item_drop_rows',)),
                  (gen.BOSS_CONTACT, ('boss_contact_rows',)), (gen.MONSTER_CONTACT, ('monster_contact_rows',))]
        for path, names in arrays:
            before, after = gen.clean((self.baseline/path).read_text('utf8')), gen.clean((self.output/path).read_text('utf8'))
            for name in names:
                self.assertEqual(gen.tables.array(before, name)[1], gen.tables.array(after, name)[1], name)
        original = [[row for row in section if tuple(row[:4]) != gen.SCOPE]
                    for section in gen.read_dcc((self.baseline/gen.tables.CATALOG).read_bytes())]
        generated = gen.read_dcc((self.output/gen.tables.CATALOG).read_bytes())
        for before, after in zip(original, generated):
            self.assertEqual(before, [r for r in after if tuple(r[:4]) != gen.SCOPE])

    def test_unique_sorted_profiles_and_nine_independent_ordinary_tables(self):
        keys = [(p[1], p[0], p[2], p[3], p[4], p[5]) for p in self.profiles]
        self.assertEqual(keys, sorted(set(keys)))
        self.assertEqual(len(self.new_profiles), 9)
        for slot, profile in enumerate(self.new_profiles):
            self.assertEqual(profile[6:8], (slot, 100))
            self.assertEqual(profile[10], 629)
            rows = self.targets[profile[9]:profile[9]+profile[10]]
            self.assertEqual([r[6] for r in rows], list(range(629)))
            self.assertEqual(sum(r[0] > 0 for r in rows), 413)
            self.assertEqual({r[10] for r in rows}, {slot % 3})
        ranges = sorted((p[9], p[9]+p[10]) for p in self.profiles)
        self.assertEqual([r[1] for r in ranges[:-1]], [r[0] for r in ranges[1:]])
        self.assertEqual(ranges[-1][1], len(self.targets))

    def test_preloads_are_separate_and_legacy_catalog_is_unchanged(self):
        old = json.loads((self.baseline/gen.PRELOAD).read_text('utf8'))
        old_profile_rows = {s['profile_row'] for s in old['scopes']
                            if not (s['hd'] == 0 and 24 <= s['episode'] <= 27)}
        old = dict(old,
                   rows=[r for r in old['rows'] if r[0] in old_profile_rows],
                   scopes=[s for s in old['scopes'] if s['profile_row'] in old_profile_rows])
        new = json.loads((self.output/gen.PRELOAD).read_text('utf8'))
        old_rows = {s['profile_row'] for s in old['scopes']}
        self.assertEqual([r for r in new['rows'] if r[0] in old_rows], old['rows'])
        self.assertEqual(new['resources'][:len(old['resources'])], old['resources'])
        self.assertEqual([s for s in new['scopes'] if s['episode'] != 24], old['scopes'])
        stage = gen.codec.sstg((CLIENT/gen.STAGE).read_bytes())
        resources = gen.Resources(CLIENT)
        for slot, profile in enumerate(self.new_profiles):
            rows = [r for r in new['rows'] if r[0] == profile[9]]
            count = sum(len(resources.mmo(n)[0]) for n in stage['extra'][slot])
            self.assertEqual(len(stage['extra'][slot]), 61)
            self.assertEqual(len(rows), count)
            self.assertEqual([r[1] for r in rows], list(range(629, 629+count)))
        self.assertEqual((self.output/gen.PRELOAD.with_suffix('.inc')).read_text('utf8'), gen.preload.render(new))

    def test_boss_zero_hp_parts_modes_and_children_are_preserved(self):
        text = (self.output/gen.tables.BOSS).read_text('utf8')
        profiles = gen.tables.numeric_rows(text, 'boss_component_boss_profiles')
        modes = gen.tables.numeric_rows(text, 'boss_component_boss_modes')
        components = gen.tables.numeric_rows(text, 'boss_component_boss_components')
        selected = [p for p in profiles if p[:4] == gen.SCOPE]
        self.assertEqual(len(selected), 9)
        for slot, profile in enumerate(selected):
            self.assertEqual(profile[4:6], (slot, 1))
            mode = modes[profile[8]]
            self.assertEqual(mode[1:3], (80000, 25))
            rows = components[mode[0]:mode[0]+mode[2]]
            self.assertEqual([(r[0], r[2], r[3], r[4]) for r in rows],
                             [(0, 0, i, 4) for i in range(24)] + [(80000, 0, 24, 3)])
        registry = json.loads((self.output/gen.contact.REGISTRY).read_text('utf8'))
        rows = [r for r in gen.contact.rows(registry) if r[:4] == gen.SCOPE]
        self.assertEqual(len(rows), 225)
        for slot in range(9):
            self.assertEqual([r[7] for r in rows if r[4] == slot], list(range(25)))

    def test_score_uses_resource_values_once_and_dcc_has_four_sections(self):
        sections = gen.read_dcc((self.output/gen.tables.CATALOG).read_bytes())
        selected = [[r for r in s if tuple(r[:4]) == gen.SCOPE] for s in sections]
        self.assertEqual(list(map(len, selected)), self.report['dcc_added'])
        self.assertEqual(list(map(len, selected))[1:], [9, 9, 413*9])
        resource_rows = re.findall(r'\{"([^"]+)","([A-F0-9]{64})",(\d+)u\}', gen.tables.array(self.hp, 'hp_sync_resources')[1])
        resources = gen.Resources(CLIENT)
        by_profile = {p[6]: p for p in self.new_profiles}
        for row in selected[3]:
            key = struct.unpack_from('<5BH', row)
            profile = by_profile[key[4]]
            target = self.targets[profile[9]+key[5]]
            mem = resources.mmo(resource_rows[target[4]][0])[0][key[5]-target[7]][0]
            self.assertEqual(struct.unpack_from('<i', row, 22)[0], gen.tables.i32(mem, 16)//10)
        for aggregate, component in zip(selected[1], selected[2]):
            self.assertEqual(struct.unpack_from('<i', aggregate, 11)[0], struct.unpack_from('<i', component, 26)[0])
        old_score = (ROOT/gen.SCORE).read_text('utf8')
        new_score = (self.output/gen.SCORE).read_text('utf8')
        old_values = re.findall(r'(\d+)u', gen.tables.array(old_score, 'combat_score_target_scores')[1])
        baseline_count = len(gen.tables.numeric_rows((self.baseline/gen.tables.DATA).read_text('utf8'), 'hp_sync_target_defs'))
        old_values = old_values[:baseline_count]
        new_values = re.findall(r'(\d+)u', gen.tables.array(new_score, 'combat_score_target_scores')[1])
        self.assertEqual(new_values[:len(old_values)], old_values)
        self.assertEqual(len(new_values), len(self.targets))

    def test_pon_scopes_and_hazards_preserve_old_policies(self):
        text = (self.output/gen.tables.DAMAGE).read_text('utf8')
        body = gen.tables.array(text, 'stage_damage_stage_attack_scopes')[1]
        scopes = [tuple(map(int, m.groups())) for m in re.finditer(r'\{(\d+)u,(\d+)u,(\d+)u,(\d+)u,(\d+)u,(\d+)u,', body)]
        keys = [(s[0], s[5], s[1], s[2], s[3]) for s in scopes]
        self.assertEqual(keys, sorted(set(keys)))
        self.assertEqual([s[3] for s in scopes if s[5] == 24], [0, 1, 2])
        old = json.loads((self.baseline/gen.HAZARD).read_text('utf8'))
        new = json.loads((self.output/gen.HAZARD).read_text('utf8'))
        names = {p['resource'] for p in old['policies']}
        self.assertEqual([p for p in new['policies'] if p['resource'] in names], old['policies'])
        self.assertEqual(new['negative_samples'], old['negative_samples'])

    def test_generated_headers_compile_and_preload_lookup_is_exact(self):
        source = r'''
#include <assert.h>
#include "release/components/targets/hp_resource_global_data.inc"
#include "release/components/boss/component_data.inc"
#include "release/components/target_resources/preloaded_target_catalog.inc"
#include "release/components/combat_economy/combat_score_resource_data.inc"
#include "release/components/stage_damage/boss_contact_catalog.inc"
#include "release/components/stage_damage/monster_contact_catalog.inc"
#include "release/components/stage_damage/scene_hazard_catalog.inc"
#include "release/components/stage_damage/stage_damage_catalog.inc"
#include "release/components/targets/terminal_item_drop_data.inc"
int main(void){unsigned i,j,seen=0;
 for(i=0;i<HP_SYNC_PROFILE_COUNT;i++){
  const struct hp_sync_profile_def *p=&hp_sync_profiles[i];
  if(p->stage_id!=24||p->hd_id!=0)continue;
  assert(p->target_count==629);assert(!preloaded_target_find(p->first_row,628));
  for(j=0;j<PRELOADED_TARGET_COUNT;j++)if(preloaded_targets[j].profile_row==p->first_row){
   assert(preloaded_target_find(p->first_row,preloaded_targets[j].selector)==&preloaded_targets[j]);
   assert(preloaded_targets[j].selector>=629);
  }
  seen++;
 }
 assert(seen==9);assert(COMBAT_SCORE_TARGET_COUNT==HP_SYNC_TARGET_DEF_COUNT);return 0;
}
'''
        path = self.output/'catalog-check.c'
        path.write_text(source, encoding='ascii')
        executable = self.output/'catalog-check.exe'
        for command in ([str(ROOT/'tools/tcc/tcc.exe'), '-I', str(self.output), str(path), '-o', str(executable)], [str(executable)]):
            result = subprocess.run(command, cwd=self.output, capture_output=True, text=True, errors='replace', timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
