'''Checks for the candidate CN QT chapter patch.

Every fixture is synthetic: no user-supplied resource and no KR byte is needed
to exercise the layout, the refusal conditions or the round trip.
'''
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_qt_patch as patch  # noqa: E402

GBK = 'gbk'
SCRIPT_SLOT = 19


def gbk_text(value: str) -> str:
    return value.encode(GBK).decode(GBK)


def objective_row(objective_id: int, kind: int, script: int = 0) -> list[str]:
    row = ['0'] * patch.CN_OBJECTIVE_WIDTH
    row[0] = str(objective_id)
    row[1] = gbk_text('目标%d' % objective_id)
    row[2] = str(kind)
    row[3] = '1'
    row[4] = '1'
    row[SCRIPT_SLOT] = str(script)
    return row


def quest_entry(quest_id: int, index: int, objective_ids: list[int], kind: int = 1) -> dict:
    header = ['0'] * patch.CN_QUEST_HEAD
    header[0] = str(quest_id)
    header[1] = str(kind)
    header[2] = str(index)
    header[4] = gbk_text('任务%d' % quest_id)
    header[5] = '1' if kind == 6 else '0'
    header[6] = '1' if kind == 6 else '0'
    header[7] = str(10000 + index)
    header[8] = '-1'
    header[9] = '-1'
    header[10] = '3'
    return dict(header=header, objective_ids=[str(value) for value in objective_ids],
                objective_values=['-1'] * len(objective_ids),
                reward_text_id='9', rewards=[['3', '1', '1']])


def shipped_table(objective_count: int = patch.CN_OBJECTIVE_COUNT,
                  quest_count: int = patch.CN_QUEST_COUNT) -> dict:
    objectives = [objective_row(75000000 + index, 1) for index in range(objective_count)]
    quests = []
    for index in range(quest_count):
        # 71000000 is the reference quest: its template slots must be zero.
        kind = 1 if index < 13 else 6
        quests.append(quest_entry(71000000 + index, 1000 + index, [75000000 + index % objective_count],
                                  kind))
    return dict(header=['QUEST', '20080625', str(objective_count)], objectives=objectives,
                quests=quests)


def chapter_objective(objective_id: int, kind: int, script: int) -> list[str]:
    kr = ['0'] * patch.KR_OBJECTIVE_WIDTH
    kr[0] = str(objective_id)
    kr[1] = gbk_text('KR目标%d' % objective_id)
    kr[2] = str(kind)
    kr[3] = '1'
    kr[4] = '1'
    kr[19] = str(script)
    return kr


def chapter_entry(quest_id: int, objective_ids: list[int]) -> dict:
    header = ['0'] * patch.KR_QUEST_HEAD
    header[0] = str(quest_id)
    header[1] = '2'
    header[2] = '6'
    header[3] = '1218'
    header[5] = gbk_text('KR任务%d' % quest_id)
    header[6] = '1'
    header[9] = str(3000 + quest_id % 100)
    header[10] = '-1'
    header[11] = '-1'
    header[12] = '3'
    return dict(id=quest_id, type=2, header=header, objective_ids=objective_ids,
                objective_values=[-1] * len(objective_ids), reward_text_id=3003,
                rewards=[[1, 0, 200], [6, 13000020, 10]])


def catalog_fixture(chapters=(1, 2)) -> dict:
    rows, entries = {}, []
    for episode in chapters:
        quest_id = 73_000_000 + episode - 1
        base = 75100000 + 4 * (episode - 1)
        ids = [base, base + 1, base + 2]
        rows[ids[0]] = chapter_objective(ids[0], 39, 10000 + 2 * (episode - 1))
        rows[ids[1]] = chapter_objective(ids[1], 40, 0)
        rows[ids[2]] = chapter_objective(ids[2], 39, 10001 + 2 * (episode - 1))
        if episode % 4 == 0:
            ids.append(base + 3)
            rows[ids[3]] = chapter_objective(ids[3], 1, 10032 + episode // 4 - 1)
        entries.append(chapter_entry(quest_id, ids))
    return dict(chapters=entries, objectives=rows)


def localization_fixture(catalog: dict, approved=True) -> dict:
    titles = [dict(quest_id=73_000_000 + offset, source_ko='KR',
                   translation_zh=gbk_text('章节标题%d' % offset), approved=approved)
              for offset in range(16)]
    names = [dict(objective_id=75100000 + offset, source_ko='KR',
                  translation_zh=gbk_text('目标名%d' % offset), approved=approved)
             for offset in range(52)]
    return dict(schema='openNanaimo.chapter-story-localization.v1', activation_allowed=False,
                runtime_acceptance=False, titles=titles, objective_names=names)


def catalog_document(catalog: dict) -> dict:
    return dict(schema='openNanaimo.story-catalog.v1', counts=dict(chapters=16, objectives=52),
                chapters=[dict(entry, id=entry['id']) for entry in catalog['chapters']]
                + [chapter_entry(73_000_000 + offset, [75100000 + 3 * offset])
                   for offset in range(len(catalog['chapters']), 16)],
                objectives=[dict(id=int(row[0]), raw_fields=row)
                            for row in catalog['objectives'].values()]
                + [dict(id=75100052 + offset, raw_fields=chapter_objective(75100052 + offset, 39, 10000))
                   for offset in range(len(catalog['objectives']), 52)])


class PatchPlanTests(unittest.TestCase):
    def setUp(self):
        self.table = shipped_table()
        self.text = patch.serialize_qt(self.table)
        self.catalog = catalog_fixture()
        self.localization = localization_fixture(self.catalog)

    def test_roundtrip_is_byte_exact(self):
        raw = patch.encrypt_qt(self.text)
        self.assertEqual(patch.encrypt_qt(patch.decrypt_qt(raw)), raw)

    def test_appends_rows_and_keeps_shipped_ones(self):
        planned = package_plan(self)
        patch.verify_appended(planned['candidate'], planned['table'], [1, 2], SCRIPT_SLOT)
        self.assertEqual(len(planned['candidate']['objectives']),
                         patch.CN_OBJECTIVE_COUNT + 6)
        self.assertEqual(len(planned['candidate']['quests']), patch.CN_QUEST_COUNT + 2)

    def test_script_slot_receives_dialogue_script_only(self):
        planned = package_plan(self)
        added = planned['candidate']['objectives'][patch.CN_OBJECTIVE_COUNT:]
        self.assertEqual([row[SCRIPT_SLOT] for row in added], ['10000', '0', '10001',
                                                              '10002', '0', '10003'])

    def test_tail_slots_stay_zero(self):
        planned = package_plan(self)
        for row in planned['candidate']['objectives'][patch.CN_OBJECTIVE_COUNT:]:
            for slot in range(patch.TAIL_FIRST, patch.TAIL_LAST + 1):
                if slot != SCRIPT_SLOT:
                    self.assertEqual(row[slot], '0')

    def test_objective_collision_refused(self):
        self.catalog['objectives'][75000000] = chapter_objective(75000000, 39, 10000)
        self.catalog['chapters'][0]['objective_ids'][0] = 75000000
        with self.assertRaises(ValueError):
            package_plan(self)

    def test_unreviewed_translation_requires_flag(self):
        self.localization['titles'][0]['approved'] = False
        with self.assertRaises(ValueError):
            package_plan(self, allow_unreviewed=False)

    def test_script_slot_outside_tail_refused(self):
        for slot in (16, 27):
            with self.assertRaises(ValueError):
                package_plan(self, script_slot=slot)

    def test_awkward_objective_order_refused(self):
        first = self.catalog['chapters'][0]['objective_ids']
        self.catalog['objectives'][first[0]] = chapter_objective(first[0], 40, 0)
        with self.assertRaises(ValueError):
            package_plan(self)

    def test_nonzero_reference_slot_refused(self):
        self.table['quests'][0]['header'][5] = '1'
        with self.assertRaises(ValueError):
            package_plan(self, text=patch.serialize_qt(self.table))

    def test_chapter_range_must_start_at_one(self):
        with self.assertRaises(ValueError):
            patch.select_chapters('2-4')
        self.assertEqual(patch.select_chapters('1-4'), [1, 2, 3, 4])

    def test_gbk_and_delimiter_rules(self):
        self.assertEqual(patch.gbk('地下迷宫', 'name'), '地下迷宫')
        for value in ('a#b', 'a\nb', ''):
            with self.assertRaises(ValueError):
                patch.gbk(value, 'name')
        with self.assertRaises(UnicodeEncodeError):
            patch.gbk('emoji \U0001F600', 'name')

    def test_monk_reference_keeps_no_kr_script(self):
        catalog = catalog_fixture((4,))
        planned = package_plan(self, catalog=catalog, chapters=[4])
        added = planned['candidate']['objectives'][patch.CN_OBJECTIVE_COUNT:]
        self.assertEqual(len(added), 4)
        self.assertEqual(added[3][SCRIPT_SLOT], '0')
        self.assertEqual(int(added[3][2]), 1)


def package_plan(case, **overrides):
    options = dict(chapters=[1, 2], script_slot=SCRIPT_SLOT, reference_quest=71000000,
                   allow_unreviewed=True)
    options.update(overrides)
    catalog = options.get('catalog') or case.catalog
    localization = options.get('localization') or case.localization
    text = options.get('text') or case.text
    return patch.plan(text,
                      dict(chapters={entry['id']: entry for entry in catalog['chapters']},
                           objectives=catalog['objectives'], sha256='0' * 64),
                      dict(titles={row['quest_id']: row for row in localization['titles']},
                           names={row['objective_id']: row
                                  for row in localization['objective_names']},
                           sha256='0' * 64),
                      options['chapters'], options['script_slot'],
                      options['reference_quest'], options['allow_unreviewed'])


class EndToEndTests(unittest.TestCase):
    def test_build_and_verify_round_trip(self):
        catalog = catalog_fixture((1, 2))
        localization = localization_fixture(catalog)
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            client = root / 'client'
            client.mkdir()
            (client / patch.CN_QT_NAME).write_bytes(patch.encrypt_qt(
                patch.serialize_qt(shipped_table())))
            (root / 'catalog.json').write_text(json.dumps(catalog_document(catalog)), 'utf-8')
            (root / 'localization.json').write_text(json.dumps(localization), 'utf-8')
            output = root / 'out'
            patch.main(['build', '--client', str(client), '--catalog', str(root / 'catalog.json'),
                        '--localization', str(root / 'localization.json'), '--chapters', '1-2',
                        '--allow-unreviewed', '--output', str(output)])
            report = json.loads((output / 'patch-report.json').read_text('utf-8'))
            self.assertFalse(report['activation_allowed'])
            self.assertFalse(report['runtime_acceptance'])
            self.assertEqual(report['counts'], dict(chapters=2, objectives=6, quests=2))
            candidate = patch.parse_qt(patch.decrypt_qt((output / patch.CN_QT_NAME).read_bytes()))
            self.assertEqual(len(candidate['objectives']), patch.CN_OBJECTIVE_COUNT + 6)
            self.assertEqual(len(candidate['quests']), patch.CN_QUEST_COUNT + 2)
            patch.main(['verify', '--client', str(client), '--catalog', str(root / 'catalog.json'),
                        '--localization', str(root / 'localization.json'), '--chapters', '1-2',
                        '--allow-unreviewed', '--output', str(output)])

    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            client = root / 'client'
            client.mkdir()
            (client / patch.CN_QT_NAME).write_bytes(patch.encrypt_qt(
                patch.serialize_qt(shipped_table())))
            catalog = catalog_fixture((1, 2))
            (root / 'catalog.json').write_text(json.dumps(catalog_document(catalog)), 'utf-8')
            (root / 'localization.json').write_text(json.dumps(localization_fixture(catalog)), 'utf-8')
            output = root / 'out'
            output.mkdir()
            with self.assertRaises(ValueError):
                patch.main(['build', '--client', str(client), '--catalog', str(root / 'catalog.json'),
                            '--localization', str(root / 'localization.json'), '--chapters', '1-2',
                            '--allow-unreviewed', '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
