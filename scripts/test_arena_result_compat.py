"""Isolated x86 checks for the arena result-page entry."""
import json
import struct
import unittest
from pathlib import Path
import arena_result_compat as recipe
from test_prepare_client_compatibility import compat, synthetic_pe
try:
    import unicorn as uc
    from unicorn import x86_const as x86
except ImportError:
    uc = None

class ArenaResultTests(unittest.TestCase):
    @unittest.skipUnless(uc, 'x86 execution engine required')
    def test_shared_rematch_retires_only_the_arena_result_inactivity_latch(self):
        for mode in (0, 1, 2):
            for game_type in (0, 1, 4, 5):
                for page in (4, 6, 7):
                    with self.subTest(mode=mode, game_type=game_type, page=page):
                        m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
                        m.mem_map(0x400000, 0x400000); m.mem_map(0x2000000, 0x30000)
                        m.mem_write(recipe.RESET_CAVE_VA, recipe.reset_encodings()[1])
                        manager, stack, end = 0x2000000, 0x202E000, 0x202F000
                        def put(a, v): m.mem_write(a, struct.pack('<I', v))
                        def get(a): return struct.unpack('<I', m.mem_read(a, 4))[0]
                        m.mem_write(manager + 3, bytes([mode])); m.mem_write(manager + 7, b'\x01')
                        put(manager + 8, game_type); put(manager + 0x10F0, page)
                        put(manager + 0x34, 10000); put(manager + 0x40, 100)
                        m.reg_write(x86.UC_X86_REG_ESP, stack); put(stack, end)
                        m.reg_write(x86.UC_X86_REG_EFLAGS, 0x202)
                        regs = (x86.UC_X86_REG_EBX, x86.UC_X86_REG_ECX, x86.UC_X86_REG_EDX,
                                x86.UC_X86_REG_ESI, x86.UC_X86_REG_EDI, x86.UC_X86_REG_EBP)
                        for i, reg in enumerate(regs): m.reg_write(reg, 0x2004000 + i * 0x100)
                        calls = []
                        def intercept(machine, address, size, unused):
                            if address == end: machine.emu_stop(); return
                            if address != 0x419BBE: return
                            calls.append(address); sp = machine.reg_read(x86.UC_X86_REG_ESP)
                            machine.reg_write(x86.UC_X86_REG_EAX, manager)
                            machine.reg_write(x86.UC_X86_REG_EIP, get(sp))
                            machine.reg_write(x86.UC_X86_REG_ESP, sp + 4)
                        m.hook_add(uc.UC_HOOK_CODE, intercept)
                        m.emu_start(recipe.RESET_CAVE_VA, end + 1, count=80)
                        eligible = mode == 1 and 1 <= game_type <= 4 and page == 6
                        self.assertEqual(bytes(m.mem_read(manager + 7, 1)), b'\0' if eligible else b'\1')
                        self.assertEqual(get(manager + 0x40), 10000 if eligible else 100)
                        self.assertEqual(get(manager + 0x10F0), page)
                        self.assertEqual(calls, [0x419BBE])
                        self.assertEqual(m.reg_read(x86.UC_X86_REG_EAX), manager)
                        self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), stack + 4)
                        self.assertEqual(m.reg_read(x86.UC_X86_REG_EFLAGS), 0x202)
                        for i, reg in enumerate(regs):
                            self.assertEqual(m.reg_read(reg), 0x2004000 + i * 0x100)

    def test_preexisting_result_recipe_migrates_without_touching_other_bytes(self):
        raw, _ = synthetic_pe()
        previous = bytearray(raw)
        for _, va, old, new in recipe.patch_sites()[:2]:
            off = compat._va_offset(raw, va, len(old))
            previous[off:off + len(new)] = new
        upgraded = compat.patch_dungeon_state_controls(bytes(previous))[0]
        self.assertEqual(upgraded, compat.patch_dungeon_state_controls(raw)[0])

    def test_patch_idempotence_and_conflicts(self):
        raw, _ = synthetic_pe()
        patched, _ = compat.patch_dungeon_state_controls(raw)
        self.assertEqual(patched, compat.patch_dungeon_state_controls(patched)[0])
        for _, va, old, new in recipe.patch_sites():
            off = compat._va_offset(raw, va, len(old))
            self.assertEqual(patched[off:off + len(new)], new)
            bad = bytearray(raw); bad[off] ^= 1
            with self.assertRaises(compat.CompatibilityError):
                compat.patch_dungeon_state_controls(bytes(bad))

    def test_managed_recipe_matches_python_sites(self):
        root = Path(__file__).resolve().parents[1]
        rows = json.loads((root / 'managed-host/Resources/client-compatibility.json').read_text())['sites']
        by_name = {r['operation']: r for r in rows}
        for name, va, old, new in recipe.patch_sites():
            row = by_name['patch_' + name]
            self.assertEqual((row['va'], row['target'], row['known']), (va, new.hex(), [old.hex()]))

    @unittest.skipUnless(uc, 'x86 execution engine required')
    def test_native_entry_preserves_rows_registers_and_input(self):
        for mode in (0, 1, 2):
            for page in (0, 3, 4, 6, 7, 10):
                with self.subTest(mode=mode, page=page):
                    m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
                    m.mem_map(0x400000, 0x400000); m.mem_map(0x2000000, 0x30000)
                    m.mem_write(recipe.CAVE_VA, recipe.encodings()[1])
                    manager, keyboard, stack, end = 0x2000000, 0x2010000, 0x202E000, 0x202F000
                    def put(a, v): m.mem_write(a, struct.pack('<I', v))
                    def get(a): return struct.unpack('<I', m.mem_read(a, 4))[0]
                    m.mem_write(manager + 3, bytes([mode])); put(manager + 0x10F0, page)
                    current, previous, mouse = bytes(range(256)), b'\x80' * 256, bytes(range(16))
                    m.mem_write(keyboard + 12, current); m.mem_write(keyboard + 268, previous)
                    m.mem_write(keyboard + 528, mouse); m.mem_write(keyboard + 544, b'\xEE' * 16)
                    registers = [x86.UC_X86_REG_EBX, x86.UC_X86_REG_ECX, x86.UC_X86_REG_EDX,
                                 x86.UC_X86_REG_ESI, x86.UC_X86_REG_EDI, x86.UC_X86_REG_EBP]
                    for i, r in enumerate(registers): m.reg_write(r, 0x2004000 + i * 0x100)
                    m.reg_write(x86.UC_X86_REG_ESP, stack); put(stack, end)
                    m.reg_write(x86.UC_X86_REG_EFLAGS, 0x202); calls = []
                    def intercept(machine, address, size, unused):
                        if address == end: machine.emu_stop(); return
                        if address not in (0x41B635, 0x6658E0, 0x6692E0, 0x40ED77): return
                        calls.append(address); sp = machine.reg_read(x86.UC_X86_REG_ESP); ret = get(sp)
                        value = {0x41B635: 0x12345678, 0x6658E0: manager, 0x40ED77: keyboard}.get(address, manager)
                        extra = 0
                        if address == 0x6692E0:
                            self.assertEqual(machine.reg_read(x86.UC_X86_REG_ECX), manager)
                            self.assertEqual(get(sp + 4), 6); put(manager + 0x10F0, 6); extra = 4
                        machine.reg_write(x86.UC_X86_REG_EAX, value)
                        machine.reg_write(x86.UC_X86_REG_ESP, sp + 4 + extra); machine.reg_write(x86.UC_X86_REG_EIP, ret)
                    m.hook_add(uc.UC_HOOK_CODE, intercept)
                    m.emu_start(recipe.CAVE_VA, end + 1, count=400)
                    eligible = mode == 1 and page in (4, 6)
                    self.assertEqual(get(manager + 0x10F0), 6 if eligible else page)
                    self.assertEqual(bytes(m.mem_read(keyboard + 268, 256)), current if eligible else previous)
                    self.assertEqual(bytes(m.mem_read(keyboard + 544, 16)), mouse if eligible else b'\xEE' * 16)
                    self.assertEqual(calls.count(0x41B635), 1)
                    self.assertEqual(m.reg_read(x86.UC_X86_REG_EAX), 0x12345678)
                    for i, r in enumerate(registers): self.assertEqual(m.reg_read(r), 0x2004000 + i * 0x100)
                    self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), stack + 4)
                    self.assertEqual(m.reg_read(x86.UC_X86_REG_EFLAGS), 0x202)

    def test_catalog_has_exact_slot_local_obstacles(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / 'release/components/target_resources/arena_target_catalog.json').read_text('utf-8'))
        self.assertEqual(len(data['profiles']), 18)
        self.assertEqual(len({(p['stage'], p['slot']) for p in data['profiles']}), 18)
        names = data['resources']
        for profile in data['profiles']:
            self.assertTrue(profile['smmo'].startswith(f"arena00_st{profile['stage']:02}_"))
            for kind, hp, contact, defense, resource, ordinal in profile['rows']:
                self.assertGreaterEqual(min(hp, contact, defense, ordinal), 0)
                self.assertLess(resource, len(names))
        for profile in (p for p in data['profiles'] if p['stage'] == 0):
            final = [r for r in profile['rows'] if names[r[4]] == 'ani_mon_om_pig_01_04.mmo']
            self.assertEqual(len(final), 6)
            self.assertTrue(all(r[0] == 4 and r[1] == 0 for r in final))
            ball = [r for r in profile['rows'] if names[r[4]] == 'ssky_pvp_bbm_ball100.mmo']
            self.assertTrue(ball and all(r[1] == 8000 for r in ball))

if __name__ == '__main__':
    unittest.main()
