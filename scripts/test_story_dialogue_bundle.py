"""Checks for the chapter dialogue data bundle.

The fixtures are synthetic: one catalog binding per chapter, a localization row
per speech, and text long enough to force wrapping.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_dialogue_bundle as bundle  # noqa: E402


def gbk(text: str) -> str:
    return text.encode('gbk').decode('gbk')


def speech(text_id: int) -> dict:
    return dict(type='SPEECH', npc_uid='52', string_uid=str(text_id), expression='0',
                value='0', close='1', face_count='1')


def catalog_fixture(chapters=(1, 2)) -> dict:
    scripts = {uid: [speech(3000 + uid - 10000), dict(type='COMPLETE', step_clear='1')]
               for uid in range(10000, 10036)}
    bindings, rows = [], []
    for episode in chapters:
        quest = 73_000_000 + episode - 1
        uid = 10000 + 2 * (episode - 1)
        rows.append(dict(id=quest, episode=episode))
        bindings.append(dict(quest_id=quest, objective_id=75100000 + 3 * (episode - 1),
                             objective_index=0, script_uid=uid,
                             attributes=speech(3000 + uid - 10000)))
    return dict(schema='openNanaimo.story-catalog.v1',
                scripts=[dict(uid=uid, actions=actions) for uid, actions in scripts.items()],
                bindings=bindings, chapters=rows)


def localization_fixture(texts: dict[int, str], approved: bool = True) -> dict:
    return dict(schema='openNanaimo.chapter-story-localization.v1',
                activation_allowed=False, runtime_acceptance=False,
                texts=[dict(qs_id=text_id, source_ko='KR', translation_zh=text,
                            approved=approved) for text_id, text in texts.items()])


def load(catalog: dict, localization: dict) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        catalog_path = root / 'catalog.json'
        catalog_path.write_bytes(json.dumps(catalog).encode('utf-8'))
        texts = root / 'texts.json'
        texts.write_bytes(json.dumps(localization).encode('utf-8'))
        return bundle.load_catalog(catalog_path), bundle.load_localization(texts)


class WrapTests(unittest.TestCase):
    def test_short_text_is_one_line(self):
        self.assertEqual(bundle.wrap('你好'), ['你好'])

    def test_explicit_break_starts_a_new_line(self):
        self.assertEqual(bundle.wrap('第一段^&第二段'), ['第一段', '第二段'])

    def test_lines_respect_the_gbk_budget(self):
        lines = bundle.wrap(gbk('测' * 40))
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertLessEqual(len(line.encode('gbk')), bundle.LINE_BYTES)

    def test_page_holds_four_lines_and_pads(self):
        raw = bundle.page_bytes(['a', 'b'])
        self.assertEqual(len(raw), bundle.PAGE_BYTES)
        self.assertEqual(raw.count(0), bundle.PAGE_BYTES - 2)

    def test_too_many_lines_are_refused(self):
        with self.assertRaises(ValueError):
            bundle.page_bytes(['a', 'b', 'c', 'd', 'e'])


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_fixture()
        self.texts = {3000: gbk('第一段^&第二段'), 3002: gbk('测' * 60)}

    def test_builds_one_script_per_chapter(self):
        catalog, localization = load(self.catalog, localization_fixture(self.texts))
        built = bundle.build(catalog, localization, [1, 2], allow_unreviewed=False)
        self.assertEqual([row['uid'] for row in built['scripts']], [10000, 10002])
        self.assertTrue(built['review_complete'])
        self.assertEqual(built['scripts'][0]['pages'], 1)
        self.assertEqual(len(bundle.wrap(gbk('测' * 60))), 3)

    def test_unreviewed_text_requires_the_flag(self):
        catalog, localization = load(self.catalog, localization_fixture(self.texts, approved=False))
        with self.assertRaises(ValueError):
            bundle.build(catalog, localization, [1], allow_unreviewed=False)
        built = bundle.build(catalog, localization, [1], allow_unreviewed=True)
        self.assertFalse(built['review_complete'])

    def test_missing_text_is_refused(self):
        texts = dict(self.texts)
        texts.pop(3002)
        catalog, localization = load(self.catalog, localization_fixture(texts))
        with self.assertRaises(ValueError):
            bundle.build(catalog, localization, [2], allow_unreviewed=True)


class CodecTests(unittest.TestCase):
    def setUp(self):
        catalog, localization = load(catalog_fixture(), localization_fixture(
            {3000: gbk('你好^&世界'), 3002: gbk('再见')}))
        self.built = bundle.build(catalog, localization, [1, 2], allow_unreviewed=False)
        self.raw = bundle.encode(self.built)

    def test_header_and_size(self):
        decoded = bundle.decode(self.raw)
        self.assertEqual([row['uid'] for row in decoded['scripts']], [10000, 10002])
        self.assertEqual(len(self.raw), bundle.HEADER.size + 2 * bundle.INDEX.size
                         + sum(row['pages'] for row in self.built['scripts']) * bundle.PAGE_BYTES)

    def test_pages_read_back_as_text(self):
        decoded = bundle.decode(self.raw)
        self.assertEqual(bundle.page_text(decoded, 10000, 0), ['你好', '世界'])
        self.assertEqual(bundle.page_text(decoded, 10002, 0), ['再见'])

    def test_unknown_script_or_page_is_refused(self):
        decoded = bundle.decode(self.raw)
        with self.assertRaises(ValueError):
            bundle.page_text(decoded, 99999, 0)
        with self.assertRaises(ValueError):
            bundle.page_text(decoded, 10000, 99)

    def test_truncated_bundle_is_refused(self):
        with self.assertRaises(ValueError):
            bundle.decode(self.raw[:bundle.HEADER.size + bundle.INDEX.size])


class CliTests(unittest.TestCase):
    def test_build_and_verify(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            catalog_path = root / 'catalog.json'
            catalog_path.write_bytes(json.dumps(catalog_fixture()).encode('utf-8'))
            texts = root / 'texts.json'
            texts.write_bytes(json.dumps(
                localization_fixture({3000: '你好', 3002: '再见'})).encode('utf-8'))
            output = root / 'out'
            bundle.main(['build', '--catalog', str(catalog_path), '--localization', str(texts),
                         '--chapters', '1-2', '--output', str(output)])
            report = json.loads((output / 'dialogue-report.json').read_bytes().decode('utf-8'))
            self.assertEqual(report['counts']['scripts'], 2)
            self.assertEqual(report['page_bytes'], bundle.PAGE_BYTES)
            self.assertEqual(report['consumer']['magic'], 'SDLG')
            bundle.main(['verify', '--catalog', str(catalog_path), '--localization', str(texts),
                         '--chapters', '1-2', '--output', str(output)])
            with self.assertRaises(ValueError):
                bundle.main(['build', '--catalog', str(catalog_path), '--localization', str(texts),
                             '--chapters', '1-2', '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
