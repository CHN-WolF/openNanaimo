"""Isolated arena terminal cleanup; not original-client gameplay acceptance."""
import hashlib
import os
import struct
import unittest
from pathlib import Path

import arena_result_compat as recipe
from test_prepare_client_compatibility import compat
try:
    import unicorn as uc
    from unicorn import x86_const as x86
except ImportError:
    uc = None


class ArenaRoundBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(uc, 'x86 execution engine required')
    def test_cleanup_scope_original_sort_registers_flags_and_stack(self):
        for mode in (0, 1, 2):
            for game_type in (0, 1, 4, 5):
                for page in (0, 3, 4, 6, 7):
                    for existing in (False, True):
                        with self.subTest(mode=mode, game_type=game_type, page=page, existing=existing):
                            m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
                            m.mem_map(0x400000, 0xA00000); m.mem_map(0x2000000, 0x40000)
                            m.mem_write(recipe.CLEANUP_CAVE_VA, recipe.cleanup_encoding())
                            manager, arena, result, stack, end = 0x2000000, 0x2010000, 0x2020000, 0x203E000, 0x203F000
                            def put(a, v): m.mem_write(a, struct.pack('<I', v))
                            def get(a): return struct.unpack('<I', m.mem_read(a, 4))[0]
                            m.mem_write(manager + 3, bytes([mode])); put(manager + 8, game_type)
                            put(manager + 0x10F0, page); put(0xD72FC0, arena if existing else 0)
                            put(arena + 0x1C, 7); put(stack, end)
                            regs = (x86.UC_X86_REG_EBX, x86.UC_X86_REG_ECX, x86.UC_X86_REG_EDX,
                                    x86.UC_X86_REG_ESI, x86.UC_X86_REG_EDI, x86.UC_X86_REG_EBP)
                            vals = (123, result, 456, 789, 234, 567)
                            for reg, val in zip(regs, vals): m.reg_write(reg, val)
                            m.reg_write(x86.UC_X86_REG_ESP, stack); m.reg_write(x86.UC_X86_REG_EFLAGS, 0x246)
                            calls = []
                            def intercept(machine, address, size, unused):
                                if address == end: machine.emu_stop(); return
                                if address not in (0x41B635, 0x6658E0, 0x74FFE0): return
                                calls.append(address); sp = m.reg_read(x86.UC_X86_REG_ESP)
                                if address == 0x41B635:
                                    self.assertEqual(m.reg_read(x86.UC_X86_REG_ECX), result)
                                    value = 0x12345678
                                elif address == 0x6658E0:
                                    value = manager
                                else:
                                    self.assertEqual(m.reg_read(x86.UC_X86_REG_ECX), arena)
                                    put(arena + 0x1C, 0); value = arena
                                m.reg_write(x86.UC_X86_REG_EAX, value)
                                m.reg_write(x86.UC_X86_REG_EIP, get(sp)); m.reg_write(x86.UC_X86_REG_ESP, sp + 4)
                            m.hook_add(uc.UC_HOOK_CODE, intercept)
                            m.emu_start(recipe.CLEANUP_CAVE_VA, end + 1, count=150)
                            eligible = mode == 1 and 1 <= game_type <= 4 and page in (4, 6) and existing
                            self.assertEqual(calls.count(0x74FFE0), int(eligible))
                            self.assertEqual(calls.count(0x41B635), 1)
                            self.assertEqual(get(arena + 0x1C), 0 if eligible else 7)
                            self.assertEqual(get(manager + 0x10F0), page)
                            self.assertEqual(m.reg_read(x86.UC_X86_REG_EAX), 0x12345678)
                            self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), stack + 4)
                            self.assertEqual(m.reg_read(x86.UC_X86_REG_EFLAGS), 0x246)
                            for reg, val in zip(regs, vals): self.assertEqual(m.reg_read(reg), val)

    @unittest.skipUnless(uc, 'x86 execution engine required')
    def test_native_old_arena_terminal_cannot_stop_next_world(self):
        client = Path(os.environ.get('NANAIMO_AUDIT_CLIENT', str(Path(__file__).resolve().parents[2] / 'game.exe')))
        if not client.is_file(): self.skipTest('user-supplied original client required')
        data = client.read_bytes()
        def code(va, n):
            off = compat._va_offset(data, va, n)
            return data[off:off + n]
        reset, terminal, stop = code(0x74FFE0, 0x1C6), code(0x7530C2, 0x44), code(0x66F3A0, 0x38)
        self.assertEqual(hashlib.sha256(reset).hexdigest(), '26f5bd34b393d65df4c26701c2b818955e564bfc37ffad7bef2f044d52d86823')
        self.assertEqual(hashlib.sha256(terminal).hexdigest(), '94b8ed82290285fce1150a5b5846bb54c9c2016e1c3a499ee1a0489ff87dfdd1')
        for boundary in (None, 'entry', 'rematch'):
            repaired = boundary is not None
            m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
            m.mem_map(0x400000, 0xA00000); m.mem_map(0x2000000, 0x60000)
            manager, arena, world, anim, vt, stack, end = 0x2000000, 0x2010000, 0x2020000, 0x2030000, 0x2031000, 0x205E000, 0x205F000
            def put(a, v): m.mem_write(a, struct.pack('<I', v))
            def get(a): return struct.unpack('<I', m.mem_read(a, 4))[0]
            m.mem_write(0x74FFE0, reset); m.mem_write(0x7530C2, terminal); m.mem_write(0x66F3A0, stop)
            m.mem_write(recipe.CLEANUP_CAVE_VA, recipe.cleanup_encoding())
            m.mem_write(recipe.RESET_CAVE_VA, recipe.reset_encodings()[1])
            for thunk, target in ((0x41C409, 0x74FFE0), (0x403E27, 0x66F3A0)):
                m.mem_write(thunk, b'\xE9' + struct.pack('<i', target - thunk - 5))
            put(0xD72FC0, arena); m.mem_write(manager + 3, b'\1')
            put(manager + 8, 4); put(manager + 0x10F0, 6 if boundary == 'rematch' else 4)
            put(anim, vt); put(vt + 16, 0x401010)
            for off in (0x20, 0x128, 0x12C, 0x130, 0x34): put(arena + off, anim)
            # UI/resource calls are stubs; reset, stale terminal and world-stop writes are native instructions.
            stubs = {0x419BBE: 0, 0x41B635: 0, 0x6658E0: 0, 0x40C419: 0, 0x419835: 0, 0x41EA9C: 0,
                     0x415B09: 0, 0x41316F: 4, 0x417954: 0, 0x41D183: 0, 0x401010: 0,
                     0x40395E: 0, 0x405565: 0, 0x40C3AB: 0, 0x412DCD: 0, 0x40425A: 0, 0x41F6C7: 0}
            stopped = []
            def intercept(machine, address, size, unused):
                if address in (end, 0x753106, 0x7532A2): machine.emu_stop(); return
                if address == 0x66F3A0: stopped.append(address)
                if address not in stubs: return
                sp = m.reg_read(x86.UC_X86_REG_ESP); ret = get(sp)
                value = manager if address in (0x419BBE, 0x6658E0) else 4 if address == 0x401010 else world
                m.reg_write(x86.UC_X86_REG_EAX, value)
                m.reg_write(x86.UC_X86_REG_ESP, sp + 4 + stubs[address]); m.reg_write(x86.UC_X86_REG_EIP, ret)
            m.hook_add(uc.UC_HOOK_CODE, intercept)
            for epoch in range(5):
                put(arena + 0x1C, 7); put(arena + 0x124, 1); put(world, 1)
                if repaired:
                    put(stack, end); m.reg_write(x86.UC_X86_REG_ESP, stack)
                    start = recipe.RESET_CAVE_VA if boundary == 'rematch' else recipe.CLEANUP_CAVE_VA
                    m.emu_start(start, end + 1, count=1000)
                    self.assertEqual(get(arena + 0x1C), 0); self.assertEqual(get(arena + 0x124), 0)
                    self.assertEqual(get(world), 1)
                put(world, 1); m.reg_write(x86.UC_X86_REG_EBP, stack); put(stack - 0x1C, arena)
                m.reg_write(x86.UC_X86_REG_ESP, stack - 0x100)
                m.emu_start(0x7530C2, end + 1, count=1000)
                self.assertEqual(get(world), 1 if repaired else 0)
            self.assertEqual(len(stopped), 0 if repaired else 5)


if __name__ == '__main__': unittest.main(verbosity=2)
