"""Synthetic compiler checks plus attributable local-candidate checks when present."""
import copy
import os
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import prepare_story_catalog as catalog
import prepare_story_port as port
from test_story_catalog import catalog_fixture


def fixture():
    kr,qs,actions,cn,cnqs=catalog_fixture()
    for index in range(4):
        speeches=[a for a in actions['scripts'][10032+index] if a['type']=='SPEECH']
        for action,uid in zip(speeches,[6000+3*index,6002+3*index,6001+3*index]):
            qs[uid]=qs.pop(int(action['string_uid']))
            action['string_uid']=str(uid)
            action['npc_uid']=str(62+index)
    for q in kr['quests'].values():
        if q['type']!=2:continue
        ep=q['id']-73000000+1
        for i,oid in enumerate(q['objective_ids']):
            kr['objectives'][oid][4]=str(ep*2-1 if i in (0,2) else ep if i==1 else 62+(ep-1)//4)
    c=catalog.make_catalog(kr,qs,actions,cn,cnqs)
    local=catalog.review_template(c)
    local['schema']='openNanaimo.chapter-story-localization.v1'
    local['scope']=dict(first_episode=1,last_episode=16)
    local['activation_allowed']=False
    local['runtime_acceptance']=False
    local['source_catalog_sha256']='fixture'
    local['monk_owner']='manifest/monk_localization.json'
    local['titles']=[r for r in local['titles'] if r['quest_id']>=port.FIRST]
    selected=[q for q in c['chapters'] if q['id']>=port.FIRST]
    ids={o for q in selected for o in q['objective_ids']}
    textids={int(q['header'][9]) for q in selected}|{q['reward_text_id'] for q in selected}
    textids|={int(a['string_uid']) for s in c['scripts'] if 10000<=s['uid']<=10031 for a in s['actions'] if a['type']=='SPEECH'}
    local['objective_names']=[r for r in local['objective_names'] if r['objective_id'] in ids]
    local['texts']=[r for r in local['texts'] if r['qs_id'] in textids]
    for rows in ('titles','objective_names','texts'):
        for r in local[rows]:r['translation_zh']=r['source_ko']
    return c,local


class StoryPortChecks(unittest.TestCase):
    def setUp(self):self.c,self.local=fixture()
    def compile(self):return port.compile_package(self.c,'fixture',self.local)
    def test_scope(self):
        p=self.compile();self.assertEqual(len(p['chapters']),16)
        self.assertEqual(p['chapters'][0]['quest_id'],73000000)
        self.assertEqual(p['chapters'][-1]['next_quest_id'],0)
        self.assertFalse(p['activation_allowed']);self.assertFalse(p['runtime_acceptance'])
    def test_reuse_only(self):
        p=self.compile();monks=[q['existing_monk'] for q in p['chapters'] if q['existing_monk']]
        self.assertEqual([m['clear_mask'] for m in monks],[1,2,4,8])
        self.assertEqual([m['existing_script_uid'] for m in monks],[24000,24001,24002,24003])
        self.assertEqual(sum(len(q['objectives']) for q in p['chapters']),52)
        self.assertEqual(monks[0]['source_objective_id'],75100012)
        self.assertEqual([t for m in monks for t in m['reused_text_ids']],
                         [6000+3*i+j for i in range(4) for j in (0,2,1)])
    def test_reused_monk_order_rejected(self):
        self.c['scripts'][32]['actions'][0]['string_uid']='6001'
        with self.assertRaisesRegex(ValueError,'monk text order'):self.compile()
    def test_first_village_action_order(self):
        for q in self.compile()['chapters'][:4]:
            for d in q['dialogue']:
                actions=next(s['actions'] for s in self.c['scripts'] if s['uid']==d['source_script_uid'])
                self.assertEqual(d['source_actions'],actions)
                self.assertEqual([s['source_attributes'] for s in d['speeches']],actions[:-1])
    def test_activation_rejected(self):
        self.local['activation_allowed']=True
        with self.assertRaisesRegex(ValueError,'activation'):self.compile()
    def test_duplicate(self):
        self.local['texts'].append(self.local['texts'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.compile()
    def test_stale_digest(self):
        self.local['source_catalog_sha256']='stale'
        with self.assertRaisesRegex(ValueError,'Stale'):self.compile()
    def test_stale_text(self):
        self.local['texts'][0]['source_ko']='not source'
        with self.assertRaisesRegex(ValueError,'Stale'):self.compile()
    def test_missing_text(self):
        self.local['texts'].pop()
        with self.assertRaises(ValueError):self.compile()
    def test_missing_name(self):
        self.local['objective_names'].pop()
        with self.assertRaises(ValueError):self.compile()
    def test_unknown_action(self):
        self.c['scripts'][8]['actions'].insert(0,dict(type='D_START'))
        with self.assertRaisesRegex(ValueError,'Unsupported'):self.compile()
    def test_no_terminal_complete(self):
        self.c['scripts'][8]['actions'].pop()
        with self.assertRaisesRegex(ValueError,'terminal'):self.compile()
    def test_successor(self):
        self.c['chapters'][-1]['next_fields'][0]='73000016'
        with self.assertRaisesRegex(ValueError,'successor'):self.compile()
    def test_scene(self):
        self.c['objectives'][13]['raw_fields'][4]='8'
        with self.assertRaisesRegex(ValueError,'scene'):self.compile()
    def test_episode(self):
        self.c['objectives'][14]['raw_fields'][4]='4'
        with self.assertRaisesRegex(ValueError,'episode'):self.compile()
    def test_objective_order(self):
        self.c['objectives'][14]['raw_fields'][2]='1'
        with self.assertRaisesRegex(ValueError,'order'):self.compile()
    def test_script(self):
        self.c['objectives'][13]['raw_fields'][19]='10000'
        with self.assertRaisesRegex(ValueError,'script'):self.compile()
    def test_monk_owner(self):
        self.local['monk_owner']='duplicate.json'
        with self.assertRaisesRegex(ValueError,'owner'):self.compile()
    def test_monk_script(self):
        self.c['objectives'][25]['raw_fields'][19]='24001'
        with self.assertRaisesRegex(ValueError,'monk reference'):self.compile()
    def test_monk_text(self):
        self.local['texts'].append(dict(qs_id=6003,source_ko='a',translation_zh='b',approved=False))
        with self.assertRaisesRegex(ValueError,'coverage'):self.compile()
    def test_collision(self):
        self.c['cn_collisions'].append(dict(namespace='quest',id=73000004))
        with self.assertRaisesRegex(ValueError,'collision'):self.compile()
    def test_invalid_texts(self):
        for value in ('bad#','%n','bad\0','🙂'):
            with self.subTest(value=value):
                row=self.local['texts'][0];previous=row['translation_zh'];row['translation_zh']=value
                with self.assertRaises((ValueError,UnicodeError)):self.compile()
                row['translation_zh']=previous
    def test_title_byte_limit(self):
        self.local['titles'][0]['translation_zh']='中'*20
        with self.assertRaisesRegex(ValueError,'byte limit'):self.compile()
    def test_approval_not_boolean(self):
        self.local['titles'][0]['approved']='yes'
        with self.assertRaisesRegex(ValueError,'approval'):self.compile()
    def test_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=catalog.encoded(self.c)
            (root/'catalog.json').write_bytes(raw)
            (root/'manifest.json').write_text(json.dumps(dict(schema='openNanaimo.story-catalog.v1.build',
                inputs=[],files=[dict(path='catalog.json',size=len(raw),sha256='0'*64)])))
            with self.assertRaisesRegex(ValueError,'identity'):port.load_catalog(root)
    def test_deterministic(self):self.assertEqual(catalog.encoded(self.compile()),catalog.encoded(self.compile()))
    def test_cn_reward_mapping_survives_regeneration(self):
        q=self.c['chapters'][0]
        q['rewards']=[[4,10019997,1]]
        self.local['reward_mappings']=[dict(quest_id=q['id'],source_rewards=q['rewards'],cn_rewards=[[4,10010116,1]])]
        compiled=self.compile()
        self.assertEqual(compiled['chapters'][0]['source_rewards'],[[4,10010116,1]])
        self.assertFalse(compiled['chapters'][0]['rewards_resolved'])
        self.assertFalse(compiled['activation_allowed'])
    def test_stale_or_changed_reward_mapping_rejected(self):
        q=self.c['chapters'][0]
        q['rewards']=[[4,10019997,1]]
        for source, grants in [([[4,1,1]],[[4,10010116,1]]),
                               (q['rewards'],[[4,10010116,2]]),
                               (q['rewards'],[[6,13000001,1]]),
                               (q['rewards'],[]),
                               (q['rewards'],[[4,True,1]])]:
            with self.subTest(source=source,grants=grants):
                self.local['reward_mappings']=[dict(quest_id=q['id'],source_rewards=source,cn_rewards=grants)]
                with self.assertRaises(ValueError):self.compile()
    def test_local_candidate(self):
        root=Path(__file__).resolve().parents[1]
        supplied=os.environ.get('NANAIMO_STORY_CATALOG')
        if not supplied:self.skipTest('Set NANAIMO_STORY_CATALOG for catalog-backed checks')
        source=Path(supplied)
        payload=port.derive(source,root/'manifest/story_localization.json')
        p=json.loads(payload['chapters.json']);self.assertEqual(len(p['texts']),139)
        self.assertEqual(sum(len(d['speeches']) for q in p['chapters'] for d in q['dialogue']),107)
        for name,raw in payload.items():self.assertEqual((root/'release/components/story_chapters'/name).read_bytes(),raw)

if __name__=='__main__':unittest.main()
