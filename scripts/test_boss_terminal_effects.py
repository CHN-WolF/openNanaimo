"""Terminal MMO effects: exact-site safety and isolated state2/state3 gates."""
import json
import os
from pathlib import Path
import struct
import unittest

import prepare_client_compatibility as compat
from test_prepare_client_compatibility import synthetic_pe

try:
    import unicorn as uc
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP
except ImportError:
    uc = None

ROOT = Path(__file__).resolve().parents[1]
CLIENT = Path(os.environ.get('NANAIMO_AUDIT_CLIENT', ROOT.parent / 'game.exe'))
NAME, VA, OLD, NEW = compat.BOSS_TERMINAL_EFFECT_SITES[0]
FALLTHROUGH, SKIP = 0x6CD79C, 0x6CD906
OBJECT, STACK, STOP = 0x2000000, 0x2010000, 0x2020000


def guard(machine, code, state):
    machine.mem_write(VA, code)
    machine.mem_write(OBJECT + 0x3C0, struct.pack('<I', state))
    machine.reg_write(UC_X86_REG_EAX, OBJECT)
    machine.reg_write(UC_X86_REG_ECX, OBJECT)
    machine.emu_start(VA, FALLTHROUGH, count=8)
    return machine.reg_read(UC_X86_REG_EIP) == FALLTHROUGH


def machine():
    result = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
    result.mem_map(0x6C0000, 0x10000)
    result.mem_map(OBJECT, 0x30000)
    result.hook_add(uc.UC_HOOK_CODE, lambda m, address, size, _: m.emu_stop() if address == SKIP else None)
    return result


class BossTerminalEffectsTests(unittest.TestCase):
    def test_exact_site_idempotence_unknown_bytes_and_one_byte_diff(self):
        before, _ = synthetic_pe()
        after, report = compat.patch_boss_terminal_effects(before)
        offset = compat._va_offset(before, VA, len(OLD))
        self.assertTrue(report['changed'])
        self.assertEqual(compat.patch_boss_terminal_effects(after)[0], after)
        self.assertEqual(after[offset:offset + len(NEW)], NEW)
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b], [offset + 8])
        for index in range(len(OLD)):
            bad = bytearray(before)
            bad[offset + index] ^= 1
            with self.assertRaises(compat.CompatibilityError):
                compat.patch_boss_terminal_effects(bytes(bad))

    def test_dungeon_state_derivation_and_verification_include_guard(self):
        before, _ = synthetic_pe()
        after, report = compat.patch_dungeon_state_controls(before)
        self.assertTrue(report['boss_terminal']['changed'])
        checks = compat._verify_client_bytes(after, False, False, True)
        self.assertTrue(next(row['ok'] for row in checks if row['name'] == NAME))
        offset = compat._va_offset(after, VA, len(OLD))
        wrong = bytearray(after)
        wrong[offset:offset + len(OLD)] = OLD
        self.assertFalse(next(row['ok'] for row in compat._verify_client_bytes(bytes(wrong), False, False, True) if row['name'] == NAME))

    def test_managed_embedded_recipe_matches_python(self):
        recipe = json.loads((ROOT / 'managed-host/Resources/client-compatibility.json').read_text('utf8'))
        rows = [row for row in recipe['sites'] if row['operation'] == NAME]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['group'], 'dungeon-state')
        self.assertEqual(rows[0]['va'], VA)
        self.assertEqual(bytes.fromhex(rows[0]['target']), NEW)
        self.assertEqual(rows[0]['known'], [OLD.hex()])

    @unittest.skipUnless(uc, 'isolated x86 engine required')
    def test_original_and_fixed_state_gate(self):
        m = machine()
        for state in (0, 1, 2, 3, 4, 0x7FFFFFFF):
            self.assertEqual(guard(m, OLD, state), state != 2)
            self.assertEqual(guard(m, NEW, state), state < 2)

    @unittest.skipUnless(uc and CLIENT.is_file(), 'local client and isolated x86 engine required')
    def test_animation_finishes_in_state3_and_old_guard_replays_without_rearming(self):
        raw = CLIENT.read_bytes()
        m = machine()
        m.mem_map(0x400000, 0x10000)
        for va, size in ((0x6CB490, 0xAF), (0x401C3A, 5), (0x6CC95E, 0x1A)):
            offset = compat._va_offset(raw, va, size)
            m.mem_write(va, raw[offset:offset + size])
        # Execute the real monotonic state write, excluding only coordinates.
        m.hook_add(uc.UC_HOOK_CODE, lambda cpu, address, size, _: cpu.reg_write(UC_X86_REG_EIP, 0x6CB539) if address == 0x6CB4D9 else None)
        bp = STACK + 0x8000
        m.mem_write(bp - 0xCC, struct.pack('<I', OBJECT))
        m.mem_write(OBJECT + 8, struct.pack('<I', 13500))
        m.mem_write(OBJECT + 0x3C0, struct.pack('<I', 2))
        m.reg_write(UC_X86_REG_EBP, bp)
        m.reg_write(UC_X86_REG_ESP, bp - 0x800)
        m.emu_start(0x6CC95E, 0x6CC978, count=100)
        self.assertEqual(struct.unpack('<I', m.mem_read(OBJECT + 0x3C0, 4))[0], 3)
        self.assertEqual(struct.unpack('<I', m.mem_read(OBJECT + 8, 4))[0], 0)
        for code, expected in ((OLD, [True] * 3), (NEW, [False] * 3)):
            calls = []
            for _ in range(3):
                calls.append(guard(m, code, 3))
                sp = STACK + 0xF000
                m.mem_write(sp, struct.pack('<II', STOP, 2))
                m.reg_write(UC_X86_REG_ECX, OBJECT)
                m.reg_write(UC_X86_REG_ESP, sp)
                m.emu_start(0x6CB490, STOP, count=100)
                self.assertEqual(struct.unpack('<I', m.mem_read(OBJECT + 0x3C0, 4))[0], 3)
            self.assertEqual(calls, expected)


if __name__ == '__main__':
    unittest.main()
