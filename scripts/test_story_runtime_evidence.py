"""Check runtime preflight and state classification with synthetic fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_story_tables as tables  # noqa: E402
import port_lumineos_resources as io  # noqa: E402
import story_runtime_evidence as evidence  # noqa: E402


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def report(name: str, payload: bytes, baseline: dict) -> dict:
    return dict(schema='openNanaimo.story-qt-patch.v1', status='candidate-only',
                activation_allowed=False, runtime_acceptance=False,
                inputs=[dict(name=key, size=len(value), sha256=io.digest(value))
                        for key, value in baseline.items()],
                output=dict(name=name, size=len(payload), sha256=io.digest(payload)))


def make_bundle(client: Path) -> Path:
    bundle = client.parent / 'bundle'
    qt = (client / 'QT._D30').read_bytes()
    qs = (client / 'QS._D31').read_bytes()
    new_qt, new_qs = qt + b'chapter', qs + b'chapter'
    write(bundle / 'QT._D30', new_qt)
    write(bundle / 'QS._D31', new_qs)
    write(bundle / 'patch-report.json', io.encoded(report('QT._D30', new_qt,
                                                          {'QT._D30': qt, 'QS._D31': qs})))
    write(bundle / 'qs-patch-report.json', io.encoded(report('QS._D31', new_qs, {'QS._D31': qs})))
    return bundle


LOG_LINES = [
    '2026-10-18T10:00:00 chapter 73000000: town 1 is not its village 0; the dialogue stays unconfirmed',
    '2026-10-18T10:00:05 chapter 73000000: village 0 confirmed objective 0->1 rewardPending=False',
    '2026-10-18T10:05:00 chapter 73000000: dungeon 0 of episode 1 settled mask=1 objective=1',
    '2026-10-18T10:09:00 chapter 73000000: dungeon 1 of episode 1 settled mask=3 objective=1',
    '2026-10-18T10:13:00 chapter 73000000: dungeon 2 of episode 1 settled mask=7 objective=2',
    '2026-10-18T10:20:00 chapter 73000000: village 0 confirmed objective 2->2 rewardPending=True',
    '2026-10-18T10:21:00 chapter 73000000: reward claim ReviewRequired against review ; the chapter stays pending',
]


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.log = self.root / 'adapter.log'

    def tearDown(self):
        self.temp.cleanup()

    def run_evidence(self, lines, quest=73_000_000):
        self.log.write_text('\n'.join(lines) + '\n', 'utf-8')
        return evidence.evidence(self.log, quest)

    def test_full_chain_passes(self):
        result = self.run_evidence(LOG_LINES)
        self.assertTrue(result['passed'])
        self.assertTrue(all(result['verdict'][key] for key in
                            ('entry_confirmed', 'three_distinct_dungeons', 'exit_confirmed')))
        self.assertFalse(result['verdict']['reward_claimed'])
        self.assertEqual(result['steps']['dungeons'][2]['mask'], 7)

    def test_entry_only_fails(self):
        result = self.run_evidence(LOG_LINES[:2])
        self.assertFalse(result['passed'])
        self.assertTrue(result['verdict']['entry_confirmed'])
        self.assertFalse(result['verdict']['three_distinct_dungeons'])

    def test_repeated_dungeon_bit_is_not_three(self):
        lines = LOG_LINES[:3] + [LOG_LINES[2]] + [LOG_LINES[2]] + LOG_LINES[6:]
        result = self.run_evidence(lines)
        self.assertFalse(result['verdict']['three_distinct_dungeons'])
        self.assertFalse(result['passed'])

    def test_claim_is_recorded(self):
        lines = LOG_LINES[:-1] + [
            '2026-10-18T10:22:00 chapter 73000000: reward claimed review=review-1 next=73000001 revision=9']
        result = self.run_evidence(lines)
        self.assertTrue(result['verdict']['reward_claimed'])
        self.assertEqual(result['steps']['claim']['next'], 73000001)

    def test_refusal_is_recorded(self):
        result = self.run_evidence(LOG_LINES)
        self.assertEqual(result['steps']['refused'][0]['status'], 'ReviewRequired')

    def test_other_quest_is_ignored(self):
        lines = [line.replace('73000000', '73000001') for line in LOG_LINES]
        result = self.run_evidence(lines)
        self.assertFalse(result['passed'])

    def test_exit_jump_without_entry_does_not_count(self):
        result = self.run_evidence([LOG_LINES[5]])
        self.assertFalse(result['verdict']['entry_confirmed'])
        self.assertTrue(result['verdict']['exit_confirmed'])
        self.assertFalse(result['passed'])


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = self.root / 'client'
        write(self.client / 'QT._D30', b'QUEST#20080625#357#' + b'0#' * 8)
        write(self.client / 'QS._D31', b'NANA_QUEST_TEXT#80625.01#633#' + b'0#' * 8)
        self.bundle = make_bundle(self.client)

    def tearDown(self):
        self.temp.cleanup()

    def test_preflight_reports_the_change_and_writes_nothing(self):
        adapter = self.root / 'Nanaimo.Adapter.exe'
        write(adapter, b'fake-adapter')
        before = (self.client / 'QT._D30').read_bytes()
        result = evidence.preflight(self.bundle, self.client, adapter)
        self.assertEqual(result['status'], 'go')
        self.assertEqual(result['changed'], 2)
        self.assertEqual(result['adapter']['size'], len(b'fake-adapter'))
        self.assertGreaterEqual(len(result['checklist']), 5)
        self.assertEqual((self.client / 'QT._D30').read_bytes(), before)
        self.assertFalse((self.client / tables.BACKUP_ROOT).exists())

    def test_preflight_of_an_installed_pair_is_idempotent(self):
        bundle = self.bundle
        tables.apply(bundle, self.client)
        self.assertEqual(evidence.preflight(bundle, self.client, None)['status'], 'already-installed')


if __name__ == '__main__':
    unittest.main()
