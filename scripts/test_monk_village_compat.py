"""Exact client selection bytes and isolated x86 state contract checks."""
import json
from pathlib import Path
import struct
import unittest
import unicorn as uc
from unicorn import x86_const as x86
import monk_village_compat as recipe
from test_prepare_client_compatibility import compat, synthetic_pe


class SelectionTests(unittest.TestCase):
    def test_exact_sites_idempotence_and_unknown_rejection(self):
        raw, _ = synthetic_pe()
        changed, _ = compat.patch_dungeon_state_controls(raw)
        self.assertEqual(changed, compat.patch_dungeon_state_controls(changed)[0])
        for name, va, old, new in recipe.sites():
            offset = compat._va_offset(raw, va, len(old))
            self.assertEqual(changed[offset:offset+len(new)], new)
            bad = bytearray(raw); bad[offset] ^= 1
            with self.subTest(site=name), self.assertRaises(compat.CompatibilityError):
                compat.patch_dungeon_state_controls(bytes(bad))

    def test_all_entry_bytes_hd_modes_and_register_contract(self):
        m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        m.mem_map(0x400000, 0x400000)
        m.mem_map(0x2000000, 0x40000)
        m.mem_write(recipe.CODE_VA, recipe.code())
        manager, stack, end = 0x2000000, 0x2030000, 0x2031000
        registers = [x86.UC_X86_REG_EBX, x86.UC_X86_REG_EDX, x86.UC_X86_REG_ESI,
                     x86.UC_X86_REG_EDI, x86.UC_X86_REG_EBP]
        def put(at, value): m.mem_write(at, struct.pack('<I', value))
        def get(at): return struct.unpack('<I', m.mem_read(at, 4))[0]
        for hd in (0, 1, 4):
            for index in range(256):
                for r in registers: m.reg_write(r, 0x12345678)
                m.reg_write(x86.UC_X86_REG_ECX, manager)
                m.reg_write(x86.UC_X86_REG_ESP, stack)
                m.reg_write(x86.UC_X86_REG_EFLAGS, 0x202)
                put(stack, end);put(stack+4, 0)
                put(manager+0x1e530, hd);put(manager+0x1e534, index+16)
                put(manager+0x1e538, 99);put(manager+0x1e540, 0)
                put(manager+0x1e548, 100);put(manager+0x1e54c, index)
                m.emu_start(recipe.CODE_VA, end, count=100)
                eligible = hd == 0 and index == 8
                expected = (hd, index+16 if eligible else 100, 0 if eligible else index, 0)
                actual = tuple(get(manager+x) for x in (0x1e530,0x1e548,0x1e54c,0x1e540))
                self.assertEqual(actual, expected)
                self.assertEqual(get(manager+0x1e534), index+16)
                self.assertEqual(get(manager+0x1e538), 0)
                for r in registers: self.assertEqual(m.reg_read(r), 0x12345678)
                self.assertEqual(m.reg_read(x86.UC_X86_REG_ECX), manager)
                self.assertEqual(m.reg_read(x86.UC_X86_REG_EAX), manager)
                self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), stack+8)
                self.assertEqual(m.reg_read(x86.UC_X86_REG_EFLAGS), 0x202)

    def test_embedded_recipe_matches_python_and_entry_contract(self):
        root = Path(__file__).resolve().parents[1]
        embedded = json.loads((root/'managed-host/Resources/client-compatibility.json').read_text())
        contract = json.loads((root/'manifest/monk_village_entries.json').read_text())
        self.assertEqual(embedded['monk_village_entries'], contract)
        for _, va, old, new in recipe.sites():
            row = next(r for r in embedded['sites'] if r['va'] == va)
            self.assertEqual(row['target'], new.hex())
            self.assertIn(old.hex(), row['known'])


if __name__ == '__main__': unittest.main()
