"""Portrait preparation guards using synthetic EFF/IM3 fixtures."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import prepare_story_portraits as portraits


class PortraitChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.source=root/'source';self.client=root/'client'
        self.source.mkdir();self.client.mkdir()
        eff=b'effect-fixture';image=struct.pack('<9I',0,2,28,230,300,230,300,10,0)
        self.files={'effs/interface/NPC_6_0.eff':eff,'effs/interface/NPC_6.im3':image}
        rows=[]
        for name,raw in self.files.items():
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            row=dict(path=name,size=len(raw),sha256=portraits.io.digest(raw))
            if name.endswith('.im3'):row['image_header']=list(struct.unpack('<9I',raw))
            rows.append(row)
        self.recipe=dict(schema='openNanaimo.story-portraits.v1',runtime_acceptance=False,activation_allowed=False,
            npc_scope=[6],effects=[dict(npc_uid=6,expression=0,path='effs/interface/NPC_6_0.eff')],files=rows)
        self.model=dict(duration=60,refs=['NPC_6.im3'],rows=[(5,6)])
    def derive(self):
        with patch.object(portraits.codec,'eff2',return_value=self.model):
            return portraits.derive(self.source,self.client,self.recipe)
    def test_additive(self):
        f,m=self.derive();self.assertEqual(f,self.files)
        self.assertTrue(all(r['disposition']=='additive-candidate' for r in m['files']))
        self.assertEqual(list(self.client.iterdir()),[]);self.assertFalse(m['runtime_acceptance'])
    def test_reuse(self):
        for name,raw in self.files.items():
            p=self.client/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        _,m=self.derive();self.assertTrue(all(r['disposition']=='reuse-identical' for r in m['files']))
    def test_existing_conflict(self):
        p=self.client/'effs/interface/NPC_6.im3';p.parent.mkdir(parents=True);p.write_bytes(b'keep me')
        with self.assertRaisesRegex(ValueError,'refuse overwrite'):self.derive()
        self.assertEqual(p.read_bytes(),b'keep me')
    def test_source_digest(self):
        self.recipe['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source differs'):self.derive()
    def test_dependency_closure(self):
        self.model['refs'].append('missing.im3')
        with self.assertRaisesRegex(ValueError,'dependencies'):self.derive()
    def test_unsafe_reference(self):
        self.model['refs']=['../bad.im3']
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.derive()
    def test_monk_excluded(self):
        self.recipe['npc_scope'].append(62)
        with self.assertRaisesRegex(ValueError,'Monk'):self.derive()
    def test_duplicate_path(self):
        self.recipe['files'].append(self.recipe['files'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.derive()
    def test_image_layout(self):
        self.recipe['files'][1]['image_header'][3]=999
        with self.assertRaisesRegex(ValueError,'IM3'):self.derive()
    def test_effect_layout(self):
        self.model['duration']=0
        with self.assertRaisesRegex(ValueError,'EFF'):self.derive()
    def test_activation(self):
        self.recipe['activation_allowed']=True
        with self.assertRaisesRegex(ValueError,'activation'):self.derive()
    def test_owned_scope(self):
        self.recipe['files'][0]['path']='effs/interface/NPC_62_0.eff'
        with self.assertRaisesRegex(ValueError,'owned scope'):self.derive()
    def test_missing_npc_effect(self):
        self.recipe['npc_scope'].append(53)
        with self.assertRaisesRegex(ValueError,'Missing NPC'):self.derive()
    def test_duplicate_npc(self):
        self.recipe['npc_scope'].append(6)
        with self.assertRaisesRegex(ValueError,'Duplicate NPC'):self.derive()
    def test_full_story_coverage(self):
        root=Path(__file__).resolve().parents[1]
        recipe=json.loads((root/'manifest/story_portrait_resources.json').read_text('utf-8'))
        package=json.loads((root/'release/components/story_chapters/chapters.json').read_text('utf-8'))
        portraits.validate_story_scope(recipe,package)
        self.assertEqual(len(recipe['npc_scope']),18)
        self.assertEqual(len(recipe['files']),37)
        recipe['effects']=[e for e in recipe['effects'] if e['npc_uid']!=53]
        with self.assertRaisesRegex(ValueError,'coverage'):portraits.validate_story_scope(recipe,package)

if __name__=='__main__':unittest.main()
