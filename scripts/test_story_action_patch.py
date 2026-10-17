"""Checks for the candidate chapter action-script package.

The fixtures are synthetic catalogs: the builder only needs script rows, text
ids and bindings, so no user-supplied resource is read here.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_action_patch as patch  # noqa: E402
import story_qt_patch as shared  # noqa: E402

TEXTS = [75100000 + offset for offset in range(151)]


def speech(text_id: int, npc: int = 52) -> dict:
    return dict(type='SPEECH', npc_uid=str(npc), string_uid=str(text_id), expression='0',
                value='0', close='1', face_count='1')


def catalog_fixture(chapters=(1, 2)) -> dict:
    scripts, bindings, rows = [], [], []
    for uid in range(10000, 10036):
        actions = [dict(speech(TEXTS[uid - 10000]), **{}), dict(type='COMPLETE', step_clear='1')]
        scripts.append(dict(uid=uid, actions=actions))
    for episode in chapters:
        quest = 73_000_000 + episode - 1
        objectives = [75100000 + 3 * (episode - 1) + offset for offset in range(3)]
        rows.append(dict(id=quest, episode=episode, header=['0'] * 24,
                         objective_ids=objectives, objective_values=[-1] * 3,
                         reward_text_id=3000, rewards=[[1, 0, 200]]))
        for offset in range(2):
            uid = 10000 + 2 * (episode - 1) + offset
            bindings.append(dict(quest_id=quest, objective_id=objectives[offset * 2],
                                 objective_index=offset * 2, script_uid=uid,
                                 attributes=scripts[uid - 10000]['actions'][0]))
    return dict(schema='openNanaimo.story-catalog.v1', action_root_attributes=dict(
        target='0', version='20080904.01'), chapters=rows, scripts=scripts,
        texts=[dict(qs_id=text) for text in TEXTS], bindings=bindings)


def load_fixture(catalog: dict) -> dict:
    path_dir = tempfile.mkdtemp()
    path = Path(path_dir) / 'catalog.json'
    path.write_text(json.dumps(catalog), 'utf-8')
    return patch.load_catalog(path)


def plan_fixture(catalog: dict, chapters=(1, 2)) -> dict:
    return patch.plan(load_fixture(catalog), list(chapters))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_fixture()

    def test_selects_two_scripts_per_episode(self):
        planned = plan_fixture(self.catalog)
        self.assertEqual([row['script_uid'] for row in planned['scripts']],
                         [10000, 10001, 10002, 10003])

    def test_render_is_stable_and_escaped(self):
        planned = plan_fixture(self.catalog)
        root = self.catalog['action_root_attributes']
        first = patch.render(root, planned['scripts'])
        second = patch.render(root, planned['scripts'])
        self.assertEqual(first, second)
        self.assertIn(b'<SCRIPTS target="0" version="20080904.01">', first)
        self.assertIn(b'<ACTION type="SPEECH" close="1" expression="0" face_count="1" '
                      b'npc_uid="52" string_uid=', first)
        self.assertTrue(first.endswith(b'</SCRIPTS>\n'))

    def test_encrypted_container_round_trips(self):
        planned = plan_fixture(self.catalog)
        xml = patch.render(self.catalog['action_root_attributes'], planned['scripts'])
        encrypted = shared.encrypt_qt(xml.decode('gbk'))
        self.assertEqual(shared.decrypt_qt(encrypted).encode('gbk'), xml)

    def test_missing_script_refused(self):
        self.catalog['scripts'] = [row for row in self.catalog['scripts'] if row['uid'] != 10001]
        with self.assertRaises(ValueError):
            plan_fixture(self.catalog)

    def test_unknown_action_type_refused(self):
        self.catalog['scripts'][0]['actions'][1]['type'] = 'TELEPORT'
        with self.assertRaises(ValueError):
            plan_fixture(self.catalog)

    def test_incomplete_speech_refused(self):
        del self.catalog['scripts'][0]['actions'][0]['face_count']
        with self.assertRaises(ValueError):
            plan_fixture(self.catalog)

    def test_speech_text_must_exist(self):
        self.catalog['scripts'][0]['actions'][0]['string_uid'] = '99999'
        with self.assertRaises(ValueError):
            plan_fixture(self.catalog)

    def test_non_numeric_attribute_refused(self):
        self.catalog['scripts'][0]['actions'][0]['npc_uid'] = 'npc'
        with self.assertRaises(ValueError):
            plan_fixture(self.catalog)

    def test_binding_must_match_the_chapter(self):
        self.catalog['bindings'][0]['quest_id'] = 73_000_005
        with self.assertRaises(ValueError):
            plan_fixture(self.catalog)

    def test_unbound_script_refused(self):
        self.catalog['bindings'] = [row for row in self.catalog['bindings']
                                    if row['script_uid'] != 10003]
        with self.assertRaises(ValueError):
            plan_fixture(self.catalog)

    def test_chapter_range_must_start_at_one(self):
        with self.assertRaises(ValueError):
            patch.select_chapters('2-4')


class EndToEndTests(unittest.TestCase):
    def test_build_and_verify(self):
        catalog = catalog_fixture((1, 2))
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'catalog.json'
            source.write_text(json.dumps(catalog), 'utf-8')
            output = root / 'out'
            patch.main(['build', '--catalog', str(source), '--chapters', '1-2',
                        '--output', str(output)])
            report = json.loads((output / patch.REPORT_NAME).read_text('utf-8'))
            self.assertFalse(report['activation_allowed'])
            self.assertEqual(report['counts']['scripts'], 4)
            self.assertEqual(report['counts']['speeches'], 4)
            self.assertEqual(report['counts']['unique_texts'], 4)
            self.assertEqual((output / patch.BINARY_NAME).read_bytes(),
                             shared.encrypt_qt((output / patch.XML_NAME).read_bytes().decode('gbk')))
            patch.main(['verify', '--catalog', str(source), '--chapters', '1-2',
                        '--output', str(output)])

    def test_existing_output_refused(self):
        catalog = catalog_fixture((1, 2))
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'catalog.json'
            source.write_text(json.dumps(catalog), 'utf-8')
            output = root / 'out'
            output.mkdir()
            with self.assertRaises(ValueError):
                patch.main(['build', '--catalog', str(source), '--chapters', '1-2',
                            '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
