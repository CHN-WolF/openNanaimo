'''Synthetic regression tests; no copyrighted client resources required.'''
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import prepare_story_catalog as story


def qt_fixture(region):
    width, head = (26, 24) if region == 'kr' else (27, 22)
    objective = ['1', 'Objective'] + ['0'] * (width - 2)
    header = ['2', '2'] + ['0'] * (head - 2)
    header[5 if region == 'kr' else 4] = 'Quest'
    fields = ['QUEST', 'version', '1'] + objective + ['1'] + header
    fields += ['1', '1', '-1', '9', '1', '1', '0', '200']
    if region == 'kr':
        fields += ['0', '1', '10', 'images/npc.im3', 'Name', '1', '1', '62']
    return '#'.join(fields + [''])


def catalog_fixture():
    kr = dict(header=['QUEST', '20081023', '409'], quests={}, objectives={}, npc_bindings={})
    cn = dict(quests={}, objectives={})
    qs, actions = {}, dict(attributes={'version': 'fixture'}, scripts={})
    speech_id = 30000
    for script in range(10000, 10036):
        count = 4 if script < 10011 else 3
        rows = []
        for _ in range(count):
            rows.append(dict(type='SPEECH', npc_uid='52', string_uid=str(speech_id),
                             expression='0', value='0', close='1', face_count='1'))
            qs[speech_id] = 'Hello %s^&Next'
            speech_id += 1
        rows.append(dict(type='COMPLETE', step_clear='1'))
        actions['scripts'][script] = rows
    objective_id = 75100000
    for chapter in range(16):
        ids = []
        for index, kind in enumerate([39, 40, 39] + ([1] if chapter % 4 == 3 else [])):
            uid = objective_id
            objective_id += 1
            ids.append(uid)
            row = [str(uid), 'Objective', str(kind)] + ['0'] * 23
            if index == 0:
                row[19] = str(10000 + chapter * 2)
            elif index == 2:
                row[19] = str(10001 + chapter * 2)
            elif index == 3:
                row[19] = str(10032 + chapter // 4)
                kr['npc_bindings'][uid] = 62 + chapter // 4
            kr['objectives'][uid] = row
        header = ['0'] * 24
        header[9] = str(20000 + chapter)
        qs[20000 + chapter] = 'Description'
        qs[21000 + chapter] = 'Reward'
        uid = 73000000 + chapter
        kr['quests'][uid] = dict(id=uid, type=2, title='Chapter', header=header, objective_ids=ids,
            objective_values=[-1] * len(ids), reward_text_id=21000 + chapter, rewards=[[1, 0, 200]],
            next_fields=[str(uid + 1 if chapter < 15 else 0), '0'], extra=[])
    for i in range(357):
        kr['objectives'][i] = [str(i), 'Filler'] + ['0'] * 24
    for i in range(217):
        kr['quests'][i] = dict(id=i, type=6)
    return kr, qs, actions, cn, {}


class StoryCatalogTests(unittest.TestCase):
    def test_separate_qt_layouts_and_opaque_extras(self):
        for region, width in [('kr', 26), ('cn', 27)]:
            result = story.parse_qt(qt_fixture(region), region)
            self.assertEqual(len(result['objectives'][1]), width)
            self.assertEqual(result['quests'][2]['objective_values'], [-1])
            if region == 'kr':
                self.assertEqual(result['quests'][2]['extra'], [['10', 'images/npc.im3', 'Name']])
                self.assertEqual(result['npc_bindings'], {1: 62})

    def test_qt_rejects_truncation_and_trailing_data(self):
        for region in ('kr', 'cn'):
            text = qt_fixture(region)
            for damaged in (text[:-1], text + 'extra#', text.replace('#1#1#-1#9#', '#1#999#-1#9#')):
                with self.subTest(region=region, damaged=damaged[-30:]), self.assertRaises(ValueError):
                    story.parse_qt(damaged, region)

    def test_wrong_region_is_not_a_conversion(self):
        for source, target in [('kr', 'cn'), ('cn', 'kr')]:
            with self.assertRaises(ValueError):
                story.parse_qt(qt_fixture(source), target)

    def test_qs_count_duplicates_and_tail(self):
        self.assertEqual(story.parse_qs('NANA_QUEST_TEXT#1#1#3#Hello#'), {3: 'Hello'})
        for text in ('NANA_QUEST_TEXT#1#2#3#Hello#', 'NANA_QUEST_TEXT#1#2#3#A#3#B#',
                     'NANA_QUEST_TEXT#1#1#3#Hello#junk#', 'OTHER#1#0#'):
            with self.assertRaises(ValueError):
                story.parse_qs(text)

    def test_xml_preserves_all_attributes_and_empty_values(self):
        root = ET.Element('SCRIPTS', target='0', version='1')
        script = ET.SubElement(root, 'SCRIPT', uid='10032')
        ET.SubElement(script, 'ACTION', type='D_START', dtype='3', episode='0', dungeon='', level='', condition='1')
        ET.SubElement(script, 'ACTION', type='CONDITION', value='1', goto='4')
        ET.SubElement(script, 'ACTION', type='COMPLETE', step_clear='0')
        result = story.parse_actions(ET.tostring(root))
        self.assertEqual(result['scripts'][10032][0], dict(script[0].attrib))
        self.assertEqual(result['scripts'][10032][1]['goto'], '4')

    def test_xml_rejects_duplicate_unknown_and_entities(self):
        for raw in (b'<SCRIPTS><SCRIPT uid="1"><ACTION type="UNKNOWN"/></SCRIPT></SCRIPTS>',
                    b'<!DOCTYPE x><SCRIPTS/>',
                    b'<SCRIPTS><SCRIPT uid="1"/></SCRIPTS>',
                    b'<SCRIPTS><SCRIPT uid="1"><ACTION type="SPEECH"/></SCRIPT></SCRIPTS>'):
            with self.assertRaises(ValueError):
                story.parse_actions(raw)
        root = ET.Element('SCRIPTS')
        for _ in range(2):
            script = ET.SubElement(root, 'SCRIPT', uid='1')
            ET.SubElement(script, 'ACTION', type='COMPLETE', step_clear='1')
        with self.assertRaises(ValueError):
            story.parse_actions(ET.tostring(root))

    def test_full_chain_is_separate_and_inactive(self):
        args = catalog_fixture()
        catalog = story.make_catalog(*args)
        self.assertEqual(catalog['counts'], dict(chapters=16, objectives=52, scripts=36, speeches=119,
                                                story_speeches=107, monk_speeches=12))
        self.assertEqual(catalog['chapters'][-1]['next_fields'][0], '0')
        self.assertFalse(catalog['activation_allowed'])
        self.assertFalse(catalog['runtime_acceptance'])
        self.assertEqual(len(catalog['chapters']), 16)
        self.assertEqual(len(catalog['texts']), 151)
        self.assertEqual(json.loads(story.encoded(catalog))['scripts'], catalog['scripts'])
        self.assertEqual(catalog['objectives'][0]['raw_fields'], args[0]['objectives'][75100000])

    def test_successor_objective_script_text_and_npc_gates(self):
        for change in ('next', 'objective', 'script', 'text', 'npc', 'type', 'speech'):
            args = catalog_fixture()
            kr, qs, actions, _, _ = args
            if change == 'next': kr['quests'][73000000]['next_fields'][0] = '0'
            if change == 'objective': kr['objectives'][75100001][2] = '39'
            if change == 'script': kr['objectives'][75100000][19] = '30000'
            if change == 'text': del qs[30000]
            if change == 'npc': kr['npc_bindings'][75100012] = 99
            if change == 'type': kr['quests'][73000000]['type'] = 1
            if change == 'speech': actions['scripts'][10000][0]['string_uid'] = '30001'
            with self.subTest(change=change), self.assertRaises(ValueError):
                story.make_catalog(*args)

    def test_conflicts_reported_without_overwriting_cn(self):
        args = catalog_fixture()
        args[3]['quests'][73000000] = {'existing': True}
        args[3]['objectives'][75100000] = ['existing']
        args[4][30000] = 'Existing CN'
        before = copy.deepcopy(args)
        catalog = story.make_catalog(*args)
        self.assertEqual(args, before)
        self.assertEqual({r['namespace'] for r in catalog['cn_collisions']}, {'quest', 'objective', 'qs'})
        self.assertFalse(catalog['cn_collisions'][-1]['same_source_text'])

    def test_review_does_not_invent_translation_or_approval(self):
        review = story.review_template(story.make_catalog(*catalog_fixture()))
        for field, count in [('texts', 151), ('titles', 16), ('objective_names', 52)]:
            self.assertEqual(len(review[field]), count)
            self.assertTrue(all(not r['approved'] and r['translation_zh'] == '' for r in review[field]))

    def test_existing_monk_mapping_reuses_owner_and_reports_loose_qs_drift(self):
        catalog = dict(scripts=[], cn_collisions=[dict(namespace='qs', id=6000)])
        existing = dict(scripts={})
        local = dict(quest_strings={str(uid): 'Existing translation' for uid in range(6000, 6012)})
        for index in range(4):
            actions = [dict(type='D_START', dtype='3', episode=str(index), dungeon='', level='', condition='1'),
                       dict(type='CONDITION', value='1', goto='4'), dict(type='COMPLETE', step_clear='1')]
            catalog['scripts'].append(dict(uid=10032 + index, actions=actions))
            mapped = copy.deepcopy(actions)
            mapped[0].update(dtype='0', episode=str(24 + index), dungeon='0', level='0')
            existing['scripts'][24000 + index] = mapped
        story.reuse_monk(catalog, {6000: 'Older loose QS text'}, local, existing)
        self.assertEqual(len(catalog['reused_monk']), 12)
        self.assertEqual(catalog['reused_monk'][0]['existing_script_uid'], 24000)
        self.assertFalse(catalog['reused_monk'][0]['installed_qs_matches_owner'])
        self.assertEqual(catalog['cn_collisions'][0]['resolution'], 'reuse-existing-monk-localization')
        existing['scripts'][24000][0]['episode'] = '99'
        with self.assertRaises(ValueError): story.reuse_monk(catalog, {}, local, existing)

    def test_translation_tokens_encoding_and_byte_boundaries(self):
        self.assertEqual(story.validate_translation('Hi %s^&OK', 'Yo %s^&OK'), b'Yo %s^&OK')
        self.assertEqual(story.validate_translation('X', '\u4f60\u597d', 4), b'\xc4\xe3\xba\xc3')
        for source, translated, limit in [('Hi %s', 'Hi', None), ('%s %s', '%s', None),
                ('A^&B', 'AB', None), ('A', '%n', None), ('A', 'A#B', None), ('A', 'A\0', None),
                ('A', '\U0001f600', None), ('X', '\u4f60\u597d', 3)]:
            with self.subTest(translated=translated), self.assertRaises((ValueError, UnicodeError)):
                story.validate_translation(source, translated, limit)

    def test_output_is_new_and_verifiable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, client, output = root / 'kr', root / 'cn', root / 'out'
            source.mkdir()
            client.mkdir()
            payload = {'catalog.json': b'{}', 'manifest.json': b'{}'}
            with patch.object(story, 'derive', return_value=payload):
                story.build(source, client, output)
                self.assertEqual(story.verify(source, client, output)['status'], 'rederived-exact')
                with self.assertRaises(ValueError): story.build(source, client, output)
                with self.assertRaises(ValueError): story.build(source, client, client / 'out')
                (output / 'catalog.json').write_bytes(b'changed')
                with self.assertRaises(ValueError): story.verify(source, client, output)

    def test_source_hash_required_before_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'QT._D30').write_bytes(b'unreviewed')
            with self.assertRaisesRegex(ValueError, 'Unreviewed KR input'):
                story.derive(root, root)


if __name__ == '__main__':
    unittest.main()
