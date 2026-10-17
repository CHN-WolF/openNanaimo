"""Checks for the minidump survey used by the dialogue project."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_dialogue_survey as survey  # noqa: E402


def fake_dump(base: int, image: bytes) -> bytes:
    """Minimal MDMP with one memory-list range holding `image`."""
    blob = bytearray(struct.pack('<IIII', 0x504D444D, 0, 1, 0x20))
    blob += b'\0' * (0x20 - len(blob))
    blob += struct.pack('<III', survey.MEMORY_LIST, 4 + 16, 0x40)
    blob += b'\0' * (0x40 - len(blob))
    blob += struct.pack('<I', 1) + struct.pack('<QII', base, len(image), 0x100)
    blob += b'\0' * (0x100 - len(blob))
    blob += image
    return bytes(blob)


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_the_single_range(self):
        path = self.root / 'client.dmp'
        path.write_bytes(fake_dump(0x401000, b'\x55\x8b\xec' + b'\x00' * 16))
        base, image = survey.load_image(path)
        self.assertEqual(base, 0x401000)
        self.assertEqual(image[:3], b'\x55\x8b\xec')

    def test_rejects_a_file_that_is_not_a_dump(self):
        path = self.root / 'nope.dmp'
        path.write_bytes(b'not a dump at all')
        with self.assertRaises(ValueError):
            survey.load_image(path)


class SurveyTests(unittest.TestCase):
    def test_reports_literals_functions_and_caves(self):
        image = bytearray(b'\xCC' * 0x2000)
        image[0:3] = b'\x55\x8b\xec'            # objective parser prologue
        image[0x2000:0x2000] = b''
        image = bytes(image) + b'NANA_QUEST_TEXT' + b'\xCC' * 0x2000
        result = survey.survey(0x401000, image, minimum=4096,
                             functions={0x401000: 'objective parser'})
        self.assertEqual(result['image_base'], 0x401000)
        self.assertEqual(result['literals']['NANA_QUEST_TEXT'], [0x403000])
        self.assertTrue(result['functions']['objective parser']['looks_like_function'])
        self.assertGreaterEqual(len(result['caves']['int3']), 2)
        self.assertEqual(result['caves']['int3'][0]['size'], 0x2000)
        self.assertFalse(result['activation_allowed'])

    def test_known_function_outside_the_image_is_reported(self):
        result = survey.survey(0x401000, b'\xCC' * 0x100, minimum=64,
                             functions={0x401000: 'objective parser', 0x9000000: 'outside'})
        parser = result['functions']['objective parser']
        self.assertTrue(parser['inside_image'])
        self.assertFalse(parser['looks_like_function'])
        self.assertFalse(result['functions']['outside']['inside_image'])

    def test_zero_caves_are_reported_separately(self):
        result = survey.survey(0x401000, b'\x00' * 0x2000, minimum=4096)
        self.assertEqual(result['caves']['zero'][0]['size'], 0x2000)
        self.assertEqual(result['caves']['int3'], [])


class CliTests(unittest.TestCase):
    def test_writes_the_survey(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            dump = root / 'client.dmp'
            dump.write_bytes(fake_dump(0x401000, b'\x55\x8b\xec' + b'\xCC' * 0x2000))
            output = root / 'survey.json'
            survey.main(['--dump', str(dump), '--output', str(output)])
            document = json.loads(output.read_text('utf-8'))
            self.assertEqual(document['schema'], survey.SCHEMA)
            self.assertEqual(document['image_size'], 0x2003)
            with self.assertRaises(ValueError):
                survey.main(['--dump', str(dump), '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
