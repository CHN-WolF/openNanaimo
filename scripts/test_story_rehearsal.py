"""Check catalog topology and isolated bundle preparation."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_rehearsal as rehearsal  # noqa: E402


def chapter_row(quest_id: int, kinds: tuple[int, ...]) -> dict:
    return dict(quest_id=quest_id, reward_text_id=3003,
                objectives=[dict(objective_id=75_100_000 + offset, objective_type=kind)
                            for offset, kind in enumerate(kinds)])


def probe_fixture(chapters: int = 1) -> dict:
    rows = []
    base = 75_100_000
    for index in range(chapters):
        kinds = (39, 40, 39, 1) if index % 4 == 3 else (39, 40, 39)
        rows.append(chapter_row(73_000_000 + index, kinds))
    while len(rows) < 4:
        rows.append(None)
    return dict(schema='openNanaimo.quest-catalog-probe.v1', story_chapters=True,
                quests=217 + chapters, scrolls=204, mainline=13,
                objectives=219 + sum(len(row['objectives']) for row in rows if row),
                chapters=rows)


class JudgeTests(unittest.TestCase):
    def test_single_chapter_passes(self):
        verdict = rehearsal.judge(probe_fixture(1), 1)
        self.assertTrue(verdict['passed'], verdict['failures'])
        self.assertEqual(verdict['chapters'], 1)

    def test_four_chapters_pass(self):
        self.assertTrue(rehearsal.judge(probe_fixture(4), 4)['passed'])

    def test_mainline_regression_is_caught(self):
        probe = probe_fixture(4)
        probe['mainline'] = 17
        verdict = rehearsal.judge(probe, 4)
        self.assertFalse(verdict['passed'])
        self.assertIn('mainline=17 expected 13', verdict['failures'][0])

    def test_wrong_objective_kinds_are_caught(self):
        probe = probe_fixture(1)
        probe['chapters'][0]['objectives'][1]['objective_type'] = 39
        verdict = rehearsal.judge(probe, 1)
        self.assertFalse(verdict['passed'])
        self.assertTrue(any('kinds' in failure for failure in verdict['failures']))

    def test_missing_chapter_row_is_caught(self):
        probe = probe_fixture(1)
        probe['chapters'][0] = None
        verdict = rehearsal.judge(probe, 1)
        self.assertFalse(verdict['passed'])

    def test_count_mismatch_is_caught(self):
        verdict = rehearsal.judge(probe_fixture(1), 2)
        self.assertFalse(verdict['passed'])


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.build = self.root / 'build'
        self.build.mkdir()
        (self.build / 'Nanaimo.Adapter.exe').write_bytes(b'fake')
        (self.build / 'nested').mkdir()
        (self.build / 'nested' / 'file.txt').write_bytes(b'x')
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        (self.bundle / 'QT._D30').write_bytes(b'patched-qt')
        (self.bundle / 'QS._D31').write_bytes(b'patched-qs')

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_copies_and_swaps(self):
        work = self.root / 'work'
        rehearsal.prepare(self.build, self.bundle, work)
        self.assertTrue((work / 'nested' / 'file.txt').is_file())
        self.assertEqual((work / rehearsal.DATA / 'QT._D30').read_bytes(), b'patched-qt')
        self.assertEqual((work / rehearsal.DATA / 'QS._D31').read_bytes(), b'patched-qs')

    def test_existing_work_directory_is_refused(self):
        work = self.root / 'work'
        work.mkdir()
        with self.assertRaises(ValueError):
            rehearsal.prepare(self.build, self.bundle, work)

    def test_bundle_must_carry_both_tables(self):
        (self.bundle / 'QS._D31').unlink()
        with self.assertRaises(ValueError):
            rehearsal.prepare(self.build, self.bundle, self.root / 'work')

    def test_missing_build_executable_is_refused(self):
        (self.build / 'Nanaimo.Adapter.exe').unlink()
        with self.assertRaises(ValueError):
            rehearsal.prepare(self.build, self.bundle, self.root / 'work')


if __name__ == '__main__':
    unittest.main()
