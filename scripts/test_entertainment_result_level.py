"""Isolated native update/draw-phase tests, not original-client acceptance.

AB3200 is the original animation updater. The graphics boundary records its
cached frame +72, not the requested sequence +68. Images are bounded fixtures.
"""
import json
from pathlib import Path
import struct
import unittest
import unicorn as uc
from unicorn import x86_const as x86
import entertainment_result_compat as recipe
from test_prepare_client_compatibility import compat, synthetic_pe

SET_FRAME = bytes.fromhex('558bec83ec08894df88b45f88b4824e8a2da94ff8945fc8b4dfc837914007426837d08ff74178b55fc8b45083b42147c0c8b4dfc8b511483ea018955088b45f88b4d088948448be55dc20400')
SET_X = bytes.fromhex('558bec51894dfcd945088b45fcd8400c8b4dfcd959048be55dc20400')
SET_LEVEL = bytes.fromhex('558bec51894dfc8b45fc8b4d088948108be55dc20400')
UPDATE = bytes.fromhex('558bec83ec08894df88b45f8837844ff750733c0e93a0200008b4df88b5144528b45f88b4824e816af96ff8945fc837dfc00750733c0e9180200008b4dfc83790c00750733c0e9080200008b55f88b45fc8b4a483b087c0e8b55fc8b45f88b4a043b48487d418b55f88b45fc8b08894a488b55f8c74250010000008b45f88b4dfc8b510c8950548b45f88b4dfc8b51108950588b45f88b485483e9018b55f8894a54e97a0100008b45f883785400751e8b4df88b55fc8b420c8941548b4df88b51488b45f80350508b4df88951488b55f88b425483e8018b4df88941548b55fc837a08000f85910000008b45f88b4dfc8b50483b510475658b45f883785400755c8b4df88379580075428b55f8837a5c007e2d8b45f88b485c83e9018b55f8894a5c8b45f883785c00750cb801000000e91e010000eb0733c0e915010000eb0ab801000000e909010000eb0f8b4df88b515883ea018b45f8895058eb198b4df88b55fc8b41483b42047e0b8b4df88b55fc8b02894148e9a60000008b4df88379540075238b55f88b45fc8b4a483b480475158b55f8837a5001750c8b45f8c74050ffffffffeb7a8b4df88379540075718b55f88b45fc8b4a483b0875648b55f8837a50ff755b8b45f8c74050010000008b4df88379580075398b55f8837a5c007e278b45f88b485c83e9018b55f8894a5c8b45f883785c007509b801000000eb52eb0433c0eb4ceb07b801000000eb43eb0f8b4df88b515883ea018b45f88950588b4df883795c007e278b55f88b425c83e8018b4df889415c8b55f8837a5c007509b801000000eb0aeb0433c0eb04eb0233c08be55dc3')
UPDATE_TAIL = bytes.fromhex('8b45c88b401099b90a000000f7f9528b55c88b4a28e863afdcffc745e400000000eb098b45e483c0018945e4837de4027d1d8b4de48b55c88b448a288b4de48b55c88b4c8a288b008b5010ffd2ebd48b4dc8e8735cddff')


class ResultLevelTests(unittest.TestCase):
    def machine(self, variant='current'):
        m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        m.mem_map(0x400000, 0x800000)
        m.mem_map(0x2000000, 0x40000)
        for va, data in [(0xAB35E0, SET_FRAME), (0x58AE50, SET_X),
                         (0x637B10, SET_LEVEL), (0xAB3200, UPDATE),
                         (recipe.LEVEL_UPDATE_VA, recipe.LEVEL_UPDATE_OLD),
                         (0x6377F3, UPDATE_TAIL), (recipe.LEVEL_DRAW_VA, recipe.LEVEL_DRAW_OLD)]:
            m.mem_write(va, data)
        m.mem_write(0x637845, recipe.LEVEL_LEGACY_DRAW_OLD)
        for va, target in [(0x402770, 0xAB35E0), (0x409372, 0x58AE50), (0x40DD05, 0x637B10)]:
            m.mem_write(va, b'\xe9' + struct.pack('<i', target - va - 5))
        sites = recipe.level_patch_sites() if variant == 'current' else (
            recipe._legacy_level_patch_sites(variant == 'auxiliary') if variant != 'native' else [])
        for _, va, _, target in sites:
            m.mem_write(va, target)
        controller = 0x2000000
        sprites = (0x2010000, 0x2011000)
        for offset, sprite, pos in zip((40, 44), sprites, (331.25, 322.25)):
            m.mem_write(controller + offset, struct.pack('<I', sprite))
            m.mem_write(sprite, struct.pack('<I', 0x2020000))
            m.mem_write(sprite + 36, struct.pack('<I', 0x2028000))
            m.mem_write(sprite + 68, struct.pack('<I', 7))
            m.mem_write(sprite + 72, struct.pack('<I', 7))
            m.mem_write(sprite + 80, struct.pack('<III', 1, 1, 0))
            m.mem_write(sprite + 4, struct.pack('<f', pos))
            m.mem_write(sprite + 12, struct.pack('<f', 7.25))
        m.mem_write(0x2020010, struct.pack('<II', 0xAB3200, 0xAB3460))
        m.mem_write(0x2028014, struct.pack('<I', 10))
        for digit in range(10):
            m.mem_write(0x2029000 + 32 * digit, struct.pack('<IIIII', digit, digit, 0, 1, 0))
        m.mem_write(0x203E000 - 56, struct.pack('<I', controller))
        m.mem_write(0x203E000 - 8, struct.pack('<I', controller))
        m.reg_write(x86.UC_X86_REG_EBP, 0x203E000)
        m.reg_write(x86.UC_X86_REG_ESP, 0x203D000)
        events = []
        def boundary(machine, address, size, unused):
            if address in (0x63784A, 0x6374BF, 0x420000):
                machine.emu_stop()
                return
            if address not in (0x401096, 0x409372, 0x41E141, 0xAB3460, 0x40D4BD, 0x41979F):
                return
            sp = machine.reg_read(x86.UC_X86_REG_ESP)
            pop = 0
            if address == 0x401096:
                machine.reg_write(x86.UC_X86_REG_EAX, 0x2028000)
            elif address == 0x409372:
                value = struct.unpack('<f', machine.mem_read(sp + 4, 4))[0]
                machine.mem_write(machine.reg_read(x86.UC_X86_REG_ECX) + 4,
                                  struct.pack('<f', value + 7.25))
                pop = 4
            elif address == 0x41E141:
                digit = struct.unpack('<I', machine.mem_read(sp + 4, 4))[0]
                self.assertLess(digit, 10)
                machine.reg_write(x86.UC_X86_REG_EAX, 0x2029000 + 32 * digit)
                pop = 4
            elif address == 0xAB3460:
                image = machine.reg_read(x86.UC_X86_REG_ECX)
                events.append(('draw', self.u32(m, image + 72),
                               struct.unpack('<f', machine.mem_read(image + 4, 4))[0]))
                # The actual Draw ABI allows destruction of all volatile registers.
                for reg in (x86.UC_X86_REG_EAX, x86.UC_X86_REG_ECX, x86.UC_X86_REG_EDX):
                    machine.reg_write(reg, 0xDEADBEEF)
            else:
                events.append(('progress_update' if address == 0x40D4BD else 'progress_draw',
                               machine.reg_read(x86.UC_X86_REG_ECX)))
            ret = self.u32(m, sp)
            machine.reg_write(x86.UC_X86_REG_ESP, sp + 4 + pop)
            machine.reg_write(x86.UC_X86_REG_EIP, ret)
        m.hook_add(uc.UC_HOOK_CODE, boundary)
        return m, controller, sprites, events

    @staticmethod
    def u32(m, va):
        return struct.unpack('<I', m.mem_read(va, 4))[0]

    def call(self, m, va, obj, arg=None):
        sp = m.reg_read(x86.UC_X86_REG_ESP)
        values = [0x420000] + ([] if arg is None else [arg])
        m.reg_write(x86.UC_X86_REG_ESP, sp - 4 * len(values))
        m.mem_write(sp - 4 * len(values), struct.pack('<' + 'I' * len(values), *values))
        m.reg_write(x86.UC_X86_REG_ECX, obj)
        m.emu_start(va, 0, count=3000)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_EIP), 0x420000)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), sp)

    def update(self, m):
        m.emu_start(recipe.LEVEL_UPDATE_VA, 0, count=3000)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_EIP), 0x63784A)

    def refresh_positions(self, m, controller):
        m.reg_write(x86.UC_X86_REG_ECX, controller)
        m.emu_start(0x637845, 0, count=3000)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_EIP), 0x63784A)

    def test_native_120_is_90_but_both_failed_recipes_cache_10(self):
        for variant, expected in [('native', 9), ('first', 1), ('auxiliary', 1)]:
            m, c, sprites, events = self.machine(variant)
            self.call(m, 0x40DD05, c, 120)
            self.update(m)
            self.assertEqual(self.u32(m, c + 16), 120)
            self.assertEqual(self.u32(m, c + 4), 0)
            self.assertEqual(self.u32(m, sprites[1] + 72), expected)
            self.assertEqual(self.u32(m, sprites[0] + 72), 0)
            self.assertEqual(('progress_update', c) in events, variant == 'native')

    def test_setter_byte_offset_and_all_levels_keep_full_sprite_state(self):
        m, c, sprites, events = self.machine()
        regs = [x86.UC_X86_REG_EAX, x86.UC_X86_REG_EBX, x86.UC_X86_REG_ECX,
                x86.UC_X86_REG_EDX, x86.UC_X86_REG_ESI, x86.UC_X86_REG_EDI,
                x86.UC_X86_REG_EBP, x86.UC_X86_REG_ESP]
        for level in [*range(1, 201), 120, 10, 99, 100, 120, 200, 1, 255]:
            with self.subTest(level=level):
                m.mem_write(c + 4, struct.pack('<I', 199))
                self.call(m, 0x40DD05, c, level)
                self.assertEqual(self.u32(m, c + 4), 199)
                self.assertEqual(self.u32(m, c + 16), level)
                events.clear()
                self.update(m)
                events.clear()
                self.refresh_positions(m, c)
                self.assertEqual(events, [('progress_update', c)])
                self.assertEqual(self.u32(m, sprites[1] + 72), level // 10 % 10)
                self.assertEqual(self.u32(m, sprites[0] + 72), level % 10)
                before = [bytes(m.mem_read(s, 364)) for s in sprites]
                for flags in (0x246, 0x646):
                    events.clear()
                    # Native 637450 draws the existing pair, then calls this hook.
                    for sprite in reversed(sprites):
                        self.call(m, 0xAB3460, sprite)
                    m.reg_write(x86.UC_X86_REG_ECX, c)
                    m.reg_write(x86.UC_X86_REG_EFLAGS, flags)
                    saved = [m.reg_read(r) for r in regs]
                    m.emu_start(recipe.LEVEL_DRAW_VA, 0, count=3000)
                    self.assertEqual(m.reg_read(x86.UC_X86_REG_EIP), 0x6374BF)
                    self.assertEqual([m.reg_read(r) for r in regs], saved)
                    self.assertEqual(m.reg_read(x86.UC_X86_REG_EFLAGS), flags)
                    self.assertEqual([bytes(m.mem_read(s, 364)) for s in sprites], before)
                    if level >= 100:
                        expected = [('draw', level // 10 % 10, 326.75), ('draw', level % 10, 335.75)]
                    else:
                        expected = [('draw', level // 10 % 10, 322.25), ('draw', level % 10, 331.25)]
                    if level >= 100:
                        expected.append(('draw', level // 100, 317.75))
                    self.assertEqual(events, expected + [('progress_draw', c)])
                m.reg_write(x86.UC_X86_REG_EFLAGS, 0x246)

    def test_exact_migrations_idempotence_embedded_recipe_and_conflicts(self):
        raw, _ = synthetic_pe()
        fixed, _ = compat.patch_dungeon_state_controls(raw)
        self.assertEqual(compat.patch_dungeon_state_controls(fixed)[0], fixed)
        rows = json.loads((Path(__file__).resolve().parents[1] / 'managed-host/Resources/client-compatibility.json').read_text())['sites']
        for name, va, old, target in recipe.level_patch_sites():
            row = next(r for r in rows if r['va'] == va)
            self.assertEqual(row['target'], target.hex())
            self.assertIn(old.hex(), row['known'])
            off = compat._va_offset(raw, va, len(old))
            self.assertEqual(fixed[off:off + len(target)], target)
            bad = bytearray(raw)
            bad[off] ^= 1
            with self.assertRaises(compat.CompatibilityError):
                compat.patch_dungeon_state_controls(bytes(bad))
            restored, _ = compat._patch_site(fixed, va, target, old, 'restore_result_level_site', 'unexpected bytes')
            self.assertEqual(restored[off:off + len(old)], old)
        for auxiliary in (False, True):
            legacy = bytearray(raw)
            for _, va, _, target in recipe._legacy_level_patch_sites(auxiliary):
                off = compat._va_offset(raw, va, len(target))
                legacy[off:off + len(target)] = target
            self.assertEqual(compat.patch_dungeon_state_controls(bytes(legacy))[0], fixed)
        previous = bytearray(raw)
        for _, va, _, target in recipe._previous_current_level_patch_sites():
            off = compat._va_offset(raw, va, len(target))
            previous[off:off + len(target)] = target
        self.assertEqual(compat.patch_dungeon_state_controls(bytes(previous))[0], fixed)


if __name__ == '__main__':
    unittest.main()
