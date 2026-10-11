"""Isolated original-client x86 difficulty carriers; not GUI/runtime acceptance."""
import os
from pathlib import Path
import struct
import unittest
import pefile
import unicorn as uc
from unicorn import x86_const as x86

CLIENT = Path(os.environ.get('NANAIMO_AUDIT_CLIENT', str(Path(__file__).resolve().parents[2] / 'game.exe')))

class EntertainmentDifficultyClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pe = pefile.PE(str(CLIENT))

    @classmethod
    def tearDownClass(cls):
        cls.pe.close()

    def machine(self):
        m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        m.mem_map(0x400000, 0xA00000)
        m.mem_map(0x2000000, 0x40000)
        # Only the original setter/getter and their thunks; no substituted semantics.
        for va, size in [(0x41B3E7, 5), (0xA750A0, 48), (0x402095, 5), (0xA750C0, 40)]:
            m.mem_write(va, self.pe.get_data(va - self.pe.OPTIONAL_HEADER.ImageBase, size))
        m.mem_write(0xD869D4, struct.pack('<I', 0x2000000))
        m.mem_write(0x2000000 + 0xE6C, struct.pack('<I', 99))
        m.reg_write(x86.UC_X86_REG_EBP, 0x203E000)
        m.reg_write(x86.UC_X86_REG_ESP, 0x203D000)
        return m

    def execute_carrier(self, start, stop, difficulty, full_offset=None, width=1):
        m = self.machine()
        m.mem_write(start, self.pe.get_data(start - self.pe.OPTIONAL_HEADER.ImageBase, stop-start))
        if full_offset is not None:
            m.mem_write(0x203E008, struct.pack('<I', 0x2020000))
            m.mem_write(0x2020000 + full_offset, difficulty.to_bytes(width, 'little'))
        if start == 0x643533:
            m.mem_write(0x203E000 - 4, struct.pack('<I', 0x2020000))
        if start == 0x777534:
            m.mem_write(0x203E000 - 0x12, struct.pack('<H', difficulty))
        m.emu_start(start, stop, count=100)
        self.assertEqual(struct.unpack('<I', m.mem_read(0x2000000 + 0xE6C, 4))[0], difficulty)
        # The GAME INFO getter must retrieve the exact same global profile field.
        m.reg_write(x86.UC_X86_REG_ECX, 0x2000000)
        m.reg_write(x86.UC_X86_REG_ESP, 0x203D000)
        m.mem_write(0x203D000, struct.pack('<I', 0x2030000))
        m.emu_start(0x402095, 0x2030000, count=100)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_EAX), difficulty)

    def test_join_cf76_byte9_reaches_game_info(self):
        for value in range(5):
            with self.subTest(value=value):
                self.execute_carrier(0x77DF22, 0x77DF35, value, 9)

    def test_owner_create_selection_reaches_same_game_info(self):
        for value in range(5):
            with self.subTest(value=value):
                self.execute_carrier(0x777534, 0x777544, value)

    def test_settings_cf7a_dword40_preserves_same_difficulty(self):
        for value in range(5):
            with self.subTest(value=value):
                self.execute_carrier(0x643533, 0x643545, value, 40, 4)

    def test_cf0c_is_lobby_type_not_room_difficulty(self):
        # 53004 == CF0C, never CF6C; prevent the original decimal/hex mistake.
        self.assertEqual(53004, 0xCF0C)
        self.assertEqual(self.pe.get_data(0x77E8F8 - self.pe.OPTIONAL_HEADER.ImageBase, 10),
                         bytes.fromhex('81bd50ffffff0ccf0000'))
        self.assertNotEqual(53004, 0xCF6C)

if __name__ == '__main__':
    unittest.main(verbosity=2)
