"""Scene ownership, resource receipts, idempotence and exact rollback checks."""
from pathlib import Path
import json
import os
import struct
import tempfile
import unittest
from unittest.mock import patch
import prepare_monk_dialogue as d

BUNDLE=Path(os.environ.get('NANAIMO_MONK_DIALOGUE_BUNDLE',Path(__file__).resolve().parents[1]/'build/monk-dialogue-release'))


class FootDepthChecks(unittest.TestCase):
    def test_build_checks_explicit_previous_recipe_before_creating_output(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            recipe=root/'previous.json'; recipe.write_text('{"schema":"previous"}',encoding='utf8')
            output=root/'output'
            with patch.object(d.io,'verify',side_effect=ValueError('baseline rejected')) as verify:
                with self.assertRaisesRegex(ValueError,'baseline rejected'):
                    d.build(root/'source',root/'client',output,baseline_recipe=recipe)
                verify.assert_called_once_with(root/'client',dialogue_recipe={'schema':'previous'})
            self.assertFalse(output.exists())

    @staticmethod
    def effect():
        raw = bytearray(struct.pack('<5I', 2, 0, 0, 60, 3))
        for name, y in zip((d.scene.SHADOW, d.scene.SPRITE, d.scene.LABEL), (26., -17., 37.)):
            raw += struct.pack('<2I', 5, 6) + name.encode().ljust(260, b'\0')
            for track in range(12):
                value = y if track == 1 else 1. if track in (5, 6) else 255. if track in range(7, 11) else 0.
                raw += struct.pack('<IffII', 1, value, .22 if track == 11 else 0., 0, 60)
            raw += bytes(48)
        return bytes(raw)

    def test_only_y_constants_change_and_second_conversion_is_identical(self):
        old = self.effect(); new = d.foot_origin_effect(old)
        allowed = {at+i for at in (312, 868, 1424) for i in range(4)}
        self.assertTrue(all(a == b or i in allowed for i, (a, b) in enumerate(zip(old, new))))
        self.assertEqual(len(new), len(old))
        self.assertEqual([struct.unpack_from('<f', new, at)[0] for at in (312, 868, 1424)], [0., -43., 11.])
        self.assertEqual(d.foot_origin_effect(new), new)

    def test_all_children_keep_world_positions_at_every_animation_tick(self):
        old = self.effect(); new = d.foot_origin_effect(old)
        for _, _, _, center_y in d.dialogue.ENTRIES:
            foot_y = center_y + d.MONK_FOOT_Y_OFFSET
            for at in (312, 868, 1424):
                a, av, start, end = struct.unpack_from('<ffII', old, at)
                b, bv, _, _ = struct.unpack_from('<ffII', new, at)
                for tick in range(start, end):
                    self.assertEqual(center_y+a+tick*av, foot_y+b+tick*bv)
            # Body ground line and shadow centre now equal the sortable root Y.
            self.assertEqual(foot_y-43-50+93, foot_y)
            self.assertEqual(foot_y+struct.unpack_from('<f', new, 312)[0], foot_y)

    def test_front_back_switches_only_at_feet(self):
        for _, _, _, y in d.dialogue.ENTRIES:
            npc_foot = y + d.MONK_FOOT_Y_OFFSET
            for player_foot in (y-1, y+1, npc_foot-1, npc_foot, npc_foot+1):
                items = [('npc', npc_foot), ('player', player_foot)]
                ordered = sorted(items, key=lambda item:item[1])
                if player_foot < npc_foot:
                    self.assertEqual(ordered[-1][0], 'npc')
                elif player_foot > npc_foot:
                    self.assertEqual(ordered[-1][0], 'player')

    def test_unknown_mixed_or_animated_y_is_rejected(self):
        for at, value in ((312, 27.), (312, 0.), (316, .1)):
            raw = bytearray(self.effect()); struct.pack_into('<f', raw, at, value)
            with self.assertRaisesRegex(ValueError, 'Y (baseline|motion) differs'):
                d.foot_origin_effect(bytes(raw))

    def test_four_village_upgrade_preserves_grids_and_unrelated_objects(self):
        from test_monk_entry import scene, pack
        rows = []
        for i, (village, page, x, y) in enumerate(d.dialogue.ENTRIES):
            names = [(0, 'tree.eff'), (1, f'effs/village/openNanaimo_monk{i+1:02d}.eff')]
            layers = [[], [struct.pack('<I3f', 0, 10., 20., 0.)], [struct.pack('<I3f', 1, x, y, 0.)]]
            rows.append(((village+1)*10000+page, scene(textures=names,layers=layers)))
        rows.extend((50000+page, scene()) for page in range(30))
        raw=pack(rows); new=d.derive_pack(raw)
        self.assertEqual(d.derive_pack(new), new)
        before=dict(d.scene.scenes.records(raw)); after=dict(d.scene.scenes.records(new))
        for village,page,x,y in d.dialogue.ENTRIES:
            key=(village+1)*10000+page
            a,b=map(d.scene.VillageScene,(before[key][4:],after[key][4:]))
            self.assertEqual(a.raw[:a.grid_start+64800],b.raw[:b.grid_start+64800])
            self.assertEqual(a.layers[1],b.layers[1][:-1]);self.assertEqual(a.tail,b.tail)
            self.assertEqual(b.layers[2],[])
            self.assertEqual(struct.unpack('<I3f',b.layers[1][-1]),(1,float(x),float(y+26),0.))


@unittest.skipUnless((BUNDLE/'manifest.json').is_file(),'local resource bundle is a separate test input')
class ResourceChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.manifest=d.io.load(BUNDLE/'manifest.json'); self.recipe=d.io.load(BUNDLE/'recipe.json')
        self.baseline={}
        if self.manifest.get('previous_marker_sha256'):
            marker=d.io.safe(BUNDLE/'before',d.MARKER).read_bytes()
            self.assertEqual(d.io.digest(marker),self.manifest['previous_marker_sha256'])
            d.io.atomic(d.io.safe(self.root,d.MARKER),marker)
            self.baseline[d.MARKER]=marker
        for row in self.manifest['files']:
            rel=row['path']
            if row['before_sha256'] is not None:
                raw=d.io.safe(BUNDLE/'before',rel).read_bytes()
                self.assertEqual(d.io.digest(raw),row['before_sha256'])
                d.io.atomic(d.io.safe(self.root,rel),raw); self.baseline[rel]=raw
        for target,value in (('RECIPE',BUNDLE/'recipe.json'),):
            p=patch.object(d,target,value); p.start(); self.addCleanup(p.stop)

    def test_apply_repeat_verify_and_exact_restore(self):
        result=d.apply(BUNDLE,self.root)
        self.assertEqual(result['status'],'MONK_DIALOGUE_RESOURCES_PASS')
        self.assertEqual(d.apply(BUNDLE,self.root)['status'],result['status'])
        d.rollback(self.root,result['receipt'])
        for row in self.manifest['files']:
            path=d.io.safe(self.root,row['path'])
            if row['before_sha256'] is None: self.assertFalse(path.exists())
            else: self.assertEqual(path.read_bytes(),self.baseline[row['path']])
        if d.MARKER in self.baseline:
            self.assertEqual((self.root/d.MARKER).read_bytes(),self.baseline[d.MARKER])
        else:
            self.assertFalse((self.root/d.MARKER).exists())

    def test_edited_resource_blocks_restore_before_writes(self):
        result=d.apply(BUNDLE,self.root)
        path=d.io.safe(self.root,self.manifest['files'][-1]['path'])
        path.write_bytes(b'edited')
        with self.assertRaisesRegex(ValueError,'edited resource'): d.rollback(self.root,result['receipt'])
        self.assertEqual(path.read_bytes(),b'edited')
        self.assertTrue((self.root/d.MARKER).exists())

    def test_complete_scene_mapping_and_native_grid_preservation(self):
        old=dict(d.scene.scenes.records(self.baseline[d.PACK]))
        raw=d.io.safe(BUNDLE/'payload',d.PACK).read_bytes()
        new=dict(d.scene.scenes.records(raw))
        self.assertEqual(d.derive_pack(raw),raw)
        changed={10027,20026,30012,40006}|{50000+e['page'] for e in d.fifth.ENTRIES}
        for key,value in old.items():
            if key not in changed: self.assertEqual(value,new[key])
        for village,page,_,_ in d.dialogue.ENTRIES:
            key=(village+1)*10000+page
            a,b=map(d.scene.VillageScene,(old[key][4:],new[key][4:]))
            self.assertEqual(a.raw[a.grid_start:a.grid_start+64800],b.raw[b.grid_start:b.grid_start+64800])
            owned=f'effs/village/openNanaimo_monk{village+1:02d}.eff'.encode('ascii')
            ids={u for u,n in a.textures if n.split(b'\0',1)[0].replace(b'\\',b'/').lower()==owned.lower()}
            count=sum(1 for layer in a.layers for row in layer if int.from_bytes(row[:4],'little') in ids)
            self.assertEqual(sum(map(len,b.layers)),sum(map(len,a.layers))+1-count)

    def test_actor_layer_safe_positions_and_all_challenge_ui_images(self):
        rows=dict(d.scene.scenes.records(d.io.safe(BUNDLE/'payload',d.PACK).read_bytes()))
        import struct
        for village,page,x,y in d.dialogue.ENTRIES:
            value=d.scene.VillageScene(rows[(village+1)*10000+page][4:])
            path=f'effs/village/openNanaimo_monk{village+1:02d}.eff'.encode('ascii')
            ids={u for u,n in value.textures if n.split(b'\0',1)[0].replace(b'\\',b'/').lower()==path.lower()}
            placements=[(layer,struct.unpack('<I3f',row)[1:]) for layer,rr in enumerate(value.layers)
                        for row in rr if struct.unpack_from('<I',row)[0] in ids]
            self.assertEqual(placements,[(1,(float(x),float(y+d.MONK_FOOT_Y_OFFSET),0.))])
            if village in (0,2):
                for dx,dy in ((0,0),(-12,0),(12,0),(0,-12),(0,12)):
                    at=value.grid_start+(((x+dx)//16)*36+(y+dy)//16)*36+14
                    self.assertEqual(struct.unpack_from('<h',value.raw,at)[0],0)
            base='images/interface_images/shootingsky_inter_image/'
            for name in (f'dg_intro_hd0_ep{25+village:02d}.im3',f'ssky_hd0_ep{24+village:02d}_preview.im3',
                         f'ssky_mappreview_hd0_ep{24+village:02d}_dg00_st00.im3'):
                data=d.io.safe(BUNDLE/'payload',base+name).read_bytes()
                header=struct.unpack_from('<9I',data)
                self.assertEqual(header[:2],(0,2));self.assertEqual(header[7],8)
                self.assertEqual(header[2]+8,len(data))

    def test_modified_old_marker_blocks_upgrade_without_writes(self):
        if d.MARKER not in self.baseline:
            self.skipTest('upgrade bundle required')
        d.io.atomic(self.root/d.MARKER,b'edited marker')
        with self.assertRaisesRegex(ValueError,'baseline marker'):
            d.apply(BUNDLE,self.root)
        self.assertEqual((self.root/d.PACK).read_bytes(),self.baseline[d.PACK])

    def test_all_four_portraits_have_closed_dependencies_and_transaction_ownership(self):
        files={row['path']:row for row in self.recipe['files']}
        portraits=d.portrait_files(BUNDLE/'payload')
        self.assertEqual(len(portraits),12)
        self.assertTrue(set(portraits)<=set(files))
        for rel,raw in portraits.items():
            self.assertEqual(files[rel]['sha256'],d.io.digest(raw))
        result=d.apply(BUNDLE,self.root)
        self.assertEqual(d.portrait_files(self.root),portraits)
        d.rollback(self.root,result['receipt'])
        for rel in portraits:
            path=self.root/rel
            if rel in self.baseline:
                self.assertEqual(path.read_bytes(),self.baseline[rel])
            else:
                self.assertFalse(path.exists())

    def test_portrait_dependency_and_image_corruption_are_rejected(self):
        portraits=d.portrait_files(BUNDLE/'payload')
        for rel,raw in portraits.items():
            d.io.atomic(self.root/rel,raw)
        effect='effs/interface/NPC_62_0.eff'
        raw=portraits[effect]
        d.io.atomic(self.root/effect,raw.replace(b'NPC_62.im3',b'NPC_61.im3'))
        with self.assertRaisesRegex(ValueError,'portrait effect dependency'):
            d.portrait_files(self.root)
        d.io.atomic(self.root/effect,raw)
        image='effs/interface/NPC_62.im3'
        raw=bytearray(portraits[image]);struct.pack_into('<I',raw,12,229)
        d.io.atomic(self.root/image,raw)
        with self.assertRaisesRegex(ValueError,'portrait image layout'):
            d.portrait_files(self.root)

    def test_tampered_receipt_cannot_restore_an_unowned_file(self):
        result=d.apply(BUNDLE,self.root)
        path=d.io.safe(self.root,result['receipt']); journal=d.io.load(path)
        journal['files'][0]['path']='game.db'
        d.io.atomic(path,d.io.encoded(journal))
        with self.assertRaisesRegex(ValueError,'coverage differs'): d.rollback(self.root,result['receipt'])
        self.assertTrue((self.root/d.MARKER).exists())


if __name__=='__main__': unittest.main()
