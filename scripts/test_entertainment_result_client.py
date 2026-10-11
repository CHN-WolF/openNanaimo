"""Isolated x86 and resource-parser compatibility checks."""
import json
import os
from pathlib import Path
import struct
import unittest
import pefile
import entertainment_result_compat as recipe
from generate_inventory_card_catalog import fields
from test_prepare_client_compatibility import compat, synthetic_pe
import unicorn as uc
from unicorn import x86_const as x86


class EntertainmentResultTests(unittest.TestCase):
    def machine(self):
        m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        m.mem_map(0x400000, 0xA00000)
        m.mem_map(0x2000000, 0x40000)
        for _, va, _, target in recipe.patch_sites(): m.mem_write(va, target)
        m.reg_write(x86.UC_X86_REG_EBP, 0x203E000)
        m.reg_write(x86.UC_X86_REG_ESP, 0x203D000)
        return m

    def test_migration_and_embedded_recipe(self):
        raw, _ = synthetic_pe()
        patched, _ = compat.patch_dungeon_state_controls(raw)
        again, _ = compat.patch_dungeon_state_controls(patched)
        self.assertEqual(patched, again)
        rows = json.loads((Path(__file__).resolve().parents[1] / 'managed-host/Resources/client-compatibility.json').read_text())['sites']
        for name, va, old, target in recipe.patch_sites():
            row = next(r for r in rows if r['va'] == va)
            self.assertEqual(row['target'], target.hex())
            offset = compat._va_offset(raw, va, len(old))
            bad = bytearray(raw); bad[offset] ^= 1
            with self.assertRaises(compat.CompatibilityError): compat.patch_dungeon_state_controls(bytes(bad))

    def test_domain_classification(self):
        for card in [12000001, 13000001, 13000420, 22000010, *range(22000011, 22000019), 22000019, 50000000, 50000001]:
            with self.subTest(card=card):
                m = self.machine()
                m.mem_write(0x203E010, struct.pack('<I', card))
                reached = []
                def stop(machine, address, size, unused):
                    if address in (0x64A430, 0x64A4DC): reached.append(address); machine.emu_stop()
                m.hook_add(uc.UC_HOOK_CODE, stop)
                m.emu_start(recipe.CLASSIFY_VA, 0, count=100)
                expected = 0x64A430 if 22000011 <= card <= 22000018 or card > 50000000 else 0x64A4DC
                self.assertEqual(reached, [expected])
                self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), 0x203D000)

    def test_special_card_requires_compatible_catalog_lookup(self):
        client = Path(os.environ.get('NANAIMO_AUDIT_CLIENT', str(Path(__file__).resolve().parents[2] / 'game.exe')))
        data = client.read_bytes()
        m = self.machine()
        for va, size in [(0x64A4DC, 0x24), (0x40CA5E, 5), (0x9BED50, 0x170)]:
            off = compat._va_offset(data, va, size); m.mem_write(va, data[off:off + size])
        m.mem_write(0x203E010, struct.pack('<I', 22000014))
        def manager(machine, address, size, unused):
            if address == 0x41B65D:
                sp = machine.reg_read(x86.UC_X86_REG_ESP)
                ret = struct.unpack('<I', machine.mem_read(sp, 4))[0]
                machine.reg_write(x86.UC_X86_REG_EAX, 0x2000000)
                machine.reg_write(x86.UC_X86_REG_ESP, sp + 4)
                machine.reg_write(x86.UC_X86_REG_EIP, ret)
        m.hook_add(uc.UC_HOOK_CODE, manager)
        with self.assertRaises(uc.UcError): m.emu_start(0x64A4DC, 0, count=500)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_EIP), 0x64A4F8)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_ECX), 0)

    def test_special_name_and_preview_stack_contract(self):
        for card in [13000001, *range(22000011, 22000019), 22000019, 50000001]:
            lucky = 22000011 <= card <= 22000018
            for preview in (False, True):
                with self.subTest(card=card, preview=preview):
                    m = self.machine(); stack = 0x203D000; end = 0x203F000
                    args = [end, 2, card] if preview else [end, card]
                    m.mem_write(stack, struct.pack('<' + 'I' * len(args), *args))
                    m.reg_write(x86.UC_X86_REG_ECX, 0x2000000)
                    calls = []
                    def intercept(machine, address, size, unused):
                        if address == end: machine.emu_stop(); return
                        if address not in (0x41DEB2, 0x407C7A, 0x41B176, 0x64B060): return
                        calls.append(address)
                        sp = machine.reg_read(x86.UC_X86_REG_ESP)
                        ret = struct.unpack('<I', machine.mem_read(sp, 4))[0]
                        pop = 0
                        if address == 0x41DEB2: machine.reg_write(x86.UC_X86_REG_EAX, 0x2010000)
                        elif address == 0x64B060:
                            slot, value = struct.unpack('<II', machine.mem_read(sp + 4, 8))
                            self.assertEqual((slot, value), (2, 0 if lucky else card)); pop = 8
                        else:
                            self.assertEqual(struct.unpack('<I', machine.mem_read(sp + 4, 4))[0], card)
                            if address == 0x407C7A: self.assertEqual(machine.reg_read(x86.UC_X86_REG_ECX), 0x2010000)
                            machine.reg_write(x86.UC_X86_REG_EAX, 0x2020000); pop = 4
                        machine.reg_write(x86.UC_X86_REG_ESP, sp + 4 + pop)
                        machine.reg_write(x86.UC_X86_REG_EIP, ret)
                    m.hook_add(uc.UC_HOOK_CODE, intercept)
                    m.emu_start(recipe.CAVE_VA + (128 if preview else 64), 0, count=100)
                    self.assertEqual(calls, [0x64B060] if preview else [0x41DEB2, 0x407C7A] if lucky else [0x41B176])
                    self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), stack + 4 * len(args))
                    if not preview: self.assertEqual(m.reg_read(x86.UC_X86_REG_EAX), 0x20200F5 if lucky else 0x2020000)

    def test_failed_recipe_migrates_exactly_and_unknown_bytes_are_refused(self):
        raw, _ = synthetic_pe()
        legacy = bytearray(raw)
        for _, va, _, target in recipe.legacy_patch_sites():
            offset = compat._va_offset(raw, va, len(target))
            legacy[offset:offset + len(target)] = target
        fixed, _ = compat.patch_dungeon_state_controls(bytes(legacy))
        expected, _ = compat.patch_dungeon_state_controls(raw)
        self.assertEqual(fixed, expected)
        self.assertEqual(compat.patch_dungeon_state_controls(fixed)[0], fixed)
        legacy[compat._va_offset(raw, recipe.CAVE_VA + 120, 1)] ^= 1
        with self.assertRaises(compat.CompatibilityError):
            compat.patch_dungeon_state_controls(bytes(legacy))
        rows = json.loads((Path(__file__).resolve().parents[1] / 'managed-host/Resources/client-compatibility.json').read_text())['sites']
        row = next(r for r in rows if r['va'] == recipe.CAVE_VA)
        self.assertIn(recipe.legacy_encodings(recipe.CAVE_VA)[0].hex(), row['known'])

    def test_all_basic_prizes_keep_native_preview_identity(self):
        m = self.machine()
        stack, end = 0x203D000, 0x203F000
        calls = []
        def intercept(machine, address, size, unused):
            if address == end:
                machine.emu_stop()
            elif address == 0x64B060:
                sp = machine.reg_read(x86.UC_X86_REG_ESP)
                calls.append(struct.unpack('<II', machine.mem_read(sp + 4, 8)))
                machine.reg_write(x86.UC_X86_REG_ESP, sp + 12)
                machine.reg_write(x86.UC_X86_REG_EIP, end)
        m.hook_add(uc.UC_HOOK_CODE, intercept)
        for card in range(13000001, 13000421):
            for slot in range(3):
                m.reg_write(x86.UC_X86_REG_ESP, stack)
                m.mem_write(stack, struct.pack('<III', end, slot, card))
                m.emu_start(recipe.CAVE_VA + 128, 0, count=100)
                self.assertEqual(calls[-1], (slot, card))
                self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), stack + 12)
        self.assertEqual(len(calls), 420 * 3)

    def test_name_bitmap_path_reaches_native_image_extension_parser(self):
        client = Path(os.environ.get('NANAIMO_AUDIT_CLIENT', str(Path(__file__).resolve().parents[2] / 'game.exe')))
        pe = pefile.PE(str(client))
        image = pe.get_memory_mapped_image()
        pe.close()
        table = fields(client.parent / 'Sddakg._D35')
        packed = (client.parent / 'images/ddakg_images.pack').read_bytes()
        self.assertEqual(packed[:9], b'NANA_PACK')
        count = struct.unpack_from('<I', packed, 9)[0]
        directory = dict(struct.iter_unpack('<II', packed[13:13 + 8 * count]))
        for index in range(8):
            row = table[185 + index * 36:185 + (index + 1) * 36]
            card = int(row[0])
            key = int(Path(row[12].replace('\\', '/')).name[:6])
            self.assertIn(key, directory, row[12])
            self.assertLess(directory[key], len(packed) - 4)
            length = struct.unpack_from('<I', packed, directory[key])[0]
            self.assertGreater(length, 0)
            self.assertLessEqual(directory[key] + 4 + length, len(packed))
            for legacy in (True, False):
                with self.subTest(card=card, legacy=legacy):
                    m = self.machine()
                    m.mem_write(0x400000, image[:0xA00000])
                    for _, va, _, target in recipe.legacy_patch_sites() if legacy else recipe.patch_sites():
                        m.mem_write(va, target)
                    record = 0x2020000
                    m.mem_write(record + 8, row[2].encode('gbk') + b'\0')
                    m.mem_write(record + 245, row[12].encode('ascii') + b'\0')
                    end = 0x203F000
                    m.mem_write(0x203D000, struct.pack('<II', end, card))
                    calls = []
                    def lookup(machine, address, size, unused):
                        if address == end:
                            machine.emu_stop()
                            return
                        if address not in (0x41DEB2, 0x407C7A):
                            return
                        calls.append(address)
                        sp = machine.reg_read(x86.UC_X86_REG_ESP)
                        ret = struct.unpack('<I', machine.mem_read(sp, 4))[0]
                        machine.reg_write(x86.UC_X86_REG_EAX, 0x2010000 if address == 0x41DEB2 else record)
                        machine.reg_write(x86.UC_X86_REG_ESP, sp + 4 + (4 if address == 0x407C7A else 0))
                        machine.reg_write(x86.UC_X86_REG_EIP, ret)
                    hook = m.hook_add(uc.UC_HOOK_CODE, lookup)
                    m.emu_start(recipe.CAVE_VA + 64, 0, count=200)
                    m.hook_del(hook)
                    self.assertEqual(calls, [0x41DEB2, 0x407C7A])
                    returned = m.reg_read(x86.UC_X86_REG_EAX)
                    self.assertEqual(returned, record + (8 if legacy else 245))
                    # Execute the original disk-image extension branch, including
                    # strrchr and _stricmp. Only lookup and CRT error reporting
                    # are stubs; neither image decoding nor GUI is emulated.
                    m.mem_write(0x203E008, struct.pack('<I', returned))
                    m.mem_write(0x203E010, struct.pack('<I', 3))
                    m.mem_write(0xD8EBC4, bytes(4))
                    reached = []
                    def boundary(machine, address, size, unused):
                        if address == 0xB5484A:
                            sp = machine.reg_read(x86.UC_X86_REG_ESP)
                            ret = struct.unpack('<I', machine.mem_read(sp, 4))[0]
                            machine.reg_write(x86.UC_X86_REG_EAX, 0x2018000)
                            machine.reg_write(x86.UC_X86_REG_ESP, sp + 4)
                            machine.reg_write(x86.UC_X86_REG_EIP, ret)
                        elif address == 0xB47976:
                            sp = machine.reg_read(x86.UC_X86_REG_ESP)
                            ret = struct.unpack('<I', machine.mem_read(sp, 4))[0]
                            reached.append(ret)
                            machine.emu_stop()
                        elif address == 0xABD776:
                            reached.append(address)
                            extension = struct.unpack('<I', machine.mem_read(0x203E000 - 0x280, 4))[0]
                            self.assertEqual(bytes(machine.mem_read(extension, 5)), b'.im3\0')
                            self.assertNotEqual(machine.reg_read(x86.UC_X86_REG_EAX), 0x7FFFFFFF)
                            machine.emu_stop()
                    m.hook_add(uc.UC_HOOK_CODE, boundary)
                    m.emu_start(0xABD720, 0, count=3000)
                    self.assertEqual(reached, [0xB4E63E if legacy else 0xABD776])


if __name__ == '__main__': unittest.main()
