"""Scene ownership, resource receipts, idempotence and exact rollback checks."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import prepare_monk_dialogue as d

BUNDLE=Path(os.environ.get('NANAIMO_MONK_DIALOGUE_BUNDLE',Path(__file__).resolve().parents[1]/'build/monk-dialogue-release'))


@unittest.skipUnless((BUNDLE/'manifest.json').is_file(),'local resource bundle is a separate test input')
class ResourceChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.manifest=d.io.load(BUNDLE/'manifest.json'); self.recipe=d.io.load(BUNDLE/'recipe.json')
        self.baseline={}
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
            self.assertEqual(len(b.layers[2]),len(a.layers[2])+(0 if village==0 else 1))

    def test_tampered_receipt_cannot_restore_an_unowned_file(self):
        result=d.apply(BUNDLE,self.root)
        path=d.io.safe(self.root,result['receipt']); journal=d.io.load(path)
        journal['files'][0]['path']='game.db'
        d.io.atomic(path,d.io.encoded(journal))
        with self.assertRaisesRegex(ValueError,'coverage differs'): d.rollback(self.root,result['receipt'])
        self.assertTrue((self.root/d.MARKER).exists())


if __name__=='__main__': unittest.main()
