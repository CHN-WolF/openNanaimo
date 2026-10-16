import copy
import os
import json
from pathlib import Path
import unittest
from audit_story_localization import audit_translations, verify_authorities, TERMS


class StoryTerminologyChecks(unittest.TestCase):
    def setUp(self):
        self.terms=json.loads(TERMS.read_text('utf-8'))
        self.local=json.loads((TERMS.parent/'story_localization.json').read_text('utf-8'))

    def test_all_drafts_audited(self):
        self.assertEqual(audit_translations(self.local,self.terms),[])
        self.assertTrue(all(not r['approved'] for k in ('texts','titles','objective_names') for r in self.local[k]))

    def test_aliases_rejected(self):
        for term in self.terms['terms']:
            for alias in term['rejected_aliases']:
                with self.subTest(alias=alias):
                    local=copy.deepcopy(self.local)
                    local['texts'][0]['translation_zh']=alias
                    self.assertTrue(audit_translations(local,self.terms))

    def test_korean_residue(self):
        self.local['texts'][0]['translation_zh']='차차'
        self.assertEqual(audit_translations(self.local,self.terms)[0]['issue'],'untranslated-korean')

    def test_gold_suffix_not_duplicated(self):
        self.local['texts'][0]['translation_zh']='黄金粉末和黄金粉卡片'
        self.assertEqual(audit_translations(self.local,self.terms),[])
        self.local['texts'][0]['translation_zh']='黄金粉600g'
        self.assertTrue(audit_translations(self.local,self.terms))

    def test_local_authorities(self):
        supplied=os.environ.get('NANAIMO_STORY_TERM_RESOURCES')
        if not supplied:
            self.skipTest('Set NANAIMO_STORY_TERM_RESOURCES for resource-backed checks')
        resources=Path(supplied)
        self.assertTrue(verify_authorities(self.terms,resources))


if __name__=='__main__':unittest.main()
