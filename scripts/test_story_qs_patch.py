'''Checks for the candidate CN QS text patch.

The fixtures are synthetic: no user-supplied resource is read, and the checks
cover the reuse rule, the text validator, the refusal conditions and the round
trip.
'''
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_qs_patch as patch  # noqa: E402
import story_qt_patch as shared  # noqa: E402

GBK = 'gbk'
SHIPPED_MONK = (6000, 6001, 6002)


def gbk_text(value: str) -> str:
    return value.encode(GBK).decode(GBK)


def shipped_table() -> dict:
    entries = [(600 + index, gbk_text('既有文本%d' % index)) for index in range(5)]
    entries += [(text_id, gbk_text('修道僧文本%d' % text_id)) for text_id in SHIPPED_MONK]
    return dict(header=['NANA_QUEST_TEXT', '80625.01', str(len(entries))], entries=entries)


def chapter(quest_id: int, description: int, reward: int, objective_ids: list[int]) -> dict:
    header = ['0'] * shared.KR_QUEST_HEAD
    header[0] = str(quest_id)
    header[1] = '2'
    header[9] = str(description)
    return dict(id=quest_id, type=2, header=header, objective_ids=objective_ids,
                objective_values=[-1] * len(objective_ids), reward_text_id=reward,
                rewards=[[1, 0, 200], [6, 13000020, 1]])


def bindings(quest_id: int, objective_id: int, text_ids: list[int]) -> list[dict]:
    return [dict(quest_id=quest_id, objective_id=objective_id, objective_index=0,
                 script_uid=10000, action_order=index, attributes=dict(type='SPEECH',
                                                                       string_uid=str(text_id)))
            for index, text_id in enumerate(text_ids)]


def catalog_fixture() -> dict:
    chapters = [chapter(73_000_000, 3000, 3003, [75100000, 75100001, 75100002]),
                chapter(73_000_001, 3004, 3008, [75100003, 75100004, 75100005])]
    rows = [dict(quest_id=73_000_000, objective_id=75100000, objective_index=0, script_uid=10000,
                 action_order=0, attributes=dict(type='SPEECH', string_uid='3001'))]
    rows += bindings(73_000_001, 75100003, [3005, 3006])
    # A monk text that only exists in the shipped table.
    rows += bindings(73_000_001, 75100003, [6000])
    return dict(chapters=chapters, bindings=rows)


def localization_fixture(approved=True, mutate=None) -> dict:
    texts = {}
    for text_id in (3000, 3001, 3003, 3004, 3005, 3006, 3008):
        texts[text_id] = dict(qs_id=text_id, source_ko='가^&나', translation_zh=gbk_text('第一行^&第二行'),
                              approved=approved)
    if mutate:
        mutate(texts)
    return dict(schema='openNanaimo.chapter-story-localization.v1', activation_allowed=False,
                runtime_acceptance=False, texts=list(texts.values()))


def catalog_document(catalog: dict) -> dict:
    chapters = [entry for entry in catalog['chapters']]
    chapters += [chapter(73_000_000 + offset, 3000 + offset, 3030 + offset,
                         [75100000 + 3 * offset]) for offset in range(2, 16)]
    objectives = [dict(id=75100000 + offset, raw_fields=['0'] * shared.KR_OBJECTIVE_WIDTH)
                  for offset in range(52)]
    return dict(schema='openNanaimo.story-catalog.v1', counts=dict(chapters=16, objectives=52),
                chapters=chapters, objectives=objectives, bindings=catalog['bindings'])


def build_payload(catalog: dict, localization: dict, chapters=(1, 2), allow_unreviewed=True):
    table = shipped_table()
    return patch.plan(patch.serialize_qs(table),
                      dict(chapters={entry['id']: entry for entry in catalog['chapters']},
                           bindings=catalog['bindings'], sha256='0' * 64),
                      dict(texts={int(row['qs_id']): row for row in localization['texts']},
                           task_panel_texts={int(k): v for k, v in localization.get('task_panel_texts', {}).items()},
                           sha256='0' * 64),
                      list(chapters), allow_unreviewed)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_fixture()
        self.localization = localization_fixture()

    def test_roundtrip_is_byte_exact(self):
        raw = shared.encrypt_qt(patch.serialize_qs(shipped_table()))
        self.assertEqual(shared.encrypt_qt(shared.decrypt_qt(raw)), raw)

    def test_appends_only_missing_ids_and_updates_count(self):
        planned = build_payload(self.catalog, self.localization)
        added = [entry_id for entry_id, _ in planned['added']]
        self.assertEqual(added, [3000, 3001, 3003, 3004, 3005, 3006, 3008])
        self.assertEqual(planned['reused'], [6000])
        self.assertEqual(len(planned['candidate']['entries']), len(shipped_table()['entries']) + 7)
        self.assertEqual(planned['candidate']['header'][2],
                         str(len(shipped_table()['entries']) + 7))

    def test_shipped_entries_untouched(self):
        planned = build_payload(self.catalog, self.localization)
        table = shipped_table()
        self.assertEqual(planned['candidate']['entries'][:len(table['entries'])], table['entries'])

    def test_unreviewed_requires_flag(self):
        with self.assertRaises(ValueError):
            build_payload(self.catalog, localization_fixture(approved=False), allow_unreviewed=False)

    def test_delimiter_rejected(self):
        with self.assertRaises(ValueError):
            build_payload(self.catalog, localization_fixture(
                mutate=lambda texts: texts[3001].update(translation_zh=gbk_text('坏#文本^&第二行'))))

    def test_format_token_mismatch_rejected(self):
        def mutate(texts):
            texts[3001]['source_ko'] = '%s 가^&나'
            texts[3001]['translation_zh'] = gbk_text('没有占位^&第二行')
        with self.assertRaises(ValueError):
            build_payload(self.catalog, localization_fixture(mutate=mutate))

    def test_line_break_count_must_match(self):
        def mutate(texts):
            texts[3001]['translation_zh'] = gbk_text('只有一行')
        with self.assertRaises(ValueError):
            build_payload(self.catalog, localization_fixture(mutate=mutate))

    def test_missing_localization_row_rejected(self):
        with self.assertRaises(ValueError):
            build_payload(self.catalog, localization_fixture(
                mutate=lambda texts: texts.pop(3004)))

    def test_unknown_chapter_refused(self):
        with self.assertRaises(ValueError):
            build_payload(self.catalog, self.localization, chapters=(1, 5))

    def test_binding_outside_linked_objectives_refused(self):
        self.catalog['bindings'].append(dict(quest_id=73_000_000, objective_id=75100009,
                                             objective_index=0, script_uid=10000, action_order=0,
                                             attributes=dict(type='SPEECH', string_uid='3001')))
        with self.assertRaises(ValueError):
            build_payload(self.catalog, self.localization)

    def test_size_profile_reports_growth(self):
        planned = build_payload(self.catalog, self.localization)
        profile = planned['size_profile']
        self.assertEqual(set(profile), {'max_added', 'max_shipped', 'by_kind', 'total_added'})
        self.assertEqual(profile['max_added'], len(gbk_text('第一行^&第二行').encode(GBK)))
        self.assertGreater(profile['total_added'], 0)
        self.assertEqual(sorted(profile['by_kind']), ['description', 'reward', 'speech'])
        self.assertGreaterEqual(profile['max_shipped'], profile['max_added'])

    def test_range_guard(self):
        with self.assertRaises(ValueError):
            patch.select_chapters('2-4')

    def test_task_line_byte_boundary(self):
        origin = dict(kind='reward')
        chapter = dict(rewards=[[1, 0, 1]])
        for text in ('x' * 30, '\u4e2d' * 15):
            self.assertEqual(patch.task_panel_text(3026, text, origin, chapter, {}), text)
        for text in ('x' * 31, '\u4e2d' * 15 + 'x'):
            with self.assertRaisesRegex(ValueError, '30 GBK bytes'):
                patch.task_panel_text(3026, text, origin, chapter, {})

    def test_reward_extra_lines_are_not_silently_hidden(self):
        with self.assertRaisesRegex(ValueError, 'QT reward line count'):
            patch.task_panel_text(3026, 'a^&b', dict(kind='reward'), dict(rewards=[[1, 0, 1]]), {})

    def test_projection_preserves_canonical_translation(self):
        original = self.localization['texts'][0]['translation_zh']
        self.localization['task_panel_texts'] = {'3000': 'short'}
        planned = build_payload(self.catalog, self.localization)
        self.assertEqual(dict(planned['added'])[3000], 'short')
        self.assertEqual(self.localization['texts'][0]['translation_zh'], original)

    def test_speech_does_not_use_task_line_limit_or_projection(self):
        text = 'x' * 100
        self.assertEqual(patch.task_panel_text(3001, text, dict(kind='speech'), {}, {}), text)
        with self.assertRaisesRegex(ValueError, 'cannot replace speech'):
            patch.task_panel_text(3001, text, dict(kind='speech'), {}, {3001: 'short'})

    def test_all_current_chapters_fit_task_panel(self):
        root = Path(__file__).resolve().parents[1]
        local = patch.load_localization(root / 'manifest/story_localization.json')
        package = json.loads((root / 'release/components/story_chapters/chapters.json').read_text('utf-8'))
        for chapter in package['chapters']:
            for kind, key in [('description', 'description_qs_id'), ('reward', 'reward_qs_id')]:
                uid = chapter[key]
                with self.subTest(episode=chapter['episode'], kind=kind):
                    patch.task_panel_text(uid, local['texts'][uid]['translation_zh'],
                                          dict(kind=kind), dict(rewards=chapter['source_rewards']),
                                          local['task_panel_texts'])


class EndToEndTests(unittest.TestCase):
    def test_build_and_verify(self):
        catalog = catalog_fixture()
        localization = localization_fixture()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            client = root / 'client'
            client.mkdir()
            (client / patch.CN_QS_NAME).write_bytes(
                shared.encrypt_qt(patch.serialize_qs(shipped_table())))
            (root / 'catalog.json').write_text(json.dumps(catalog_document(catalog)), 'utf-8')
            (root / 'localization.json').write_text(json.dumps(localization), 'utf-8')
            output = root / 'out'
            patch.main(['build', '--client', str(client), '--catalog', str(root / 'catalog.json'),
                        '--localization', str(root / 'localization.json'), '--chapters', '1-2',
                        '--allow-unreviewed', '--output', str(output)])
            report = json.loads((output / 'qs-patch-report.json').read_text('utf-8'))
            self.assertFalse(report['activation_allowed'])
            self.assertEqual(report['counts']['added'], 7)
            self.assertEqual(report['counts']['reused'], 1)
            patched = patch.parse_qs(shared.decrypt_qt((output / patch.CN_QS_NAME).read_bytes()))
            self.assertEqual(len(patched['entries']), len(shipped_table()['entries']) + 7)
            patch.main(['verify', '--client', str(client), '--catalog', str(root / 'catalog.json'),
                        '--localization', str(root / 'localization.json'), '--chapters', '1-2',
                        '--allow-unreviewed', '--output', str(output)])

    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            client = root / 'client'
            client.mkdir()
            (client / patch.CN_QS_NAME).write_bytes(
                shared.encrypt_qt(patch.serialize_qs(shipped_table())))
            (root / 'catalog.json').write_text(json.dumps(catalog_document(catalog_fixture())), 'utf-8')
            (root / 'localization.json').write_text(json.dumps(localization_fixture()), 'utf-8')
            output = root / 'out'
            output.mkdir()
            with self.assertRaises(ValueError):
                patch.main(['build', '--client', str(client), '--catalog', str(root / 'catalog.json'),
                            '--localization', str(root / 'localization.json'), '--chapters', '1-2',
                            '--allow-unreviewed', '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
