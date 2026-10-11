"""Isolated x86 checks for bounded in-room record refresh."""
import json
import os
from pathlib import Path
import struct
import unittest
import pefile
import unicorn as uc
from unicorn import x86_const as x86
import entertainment_room_compat as recipe

ROOT = Path(__file__).resolve().parents[1]
CLIENT = Path(os.environ.get('NANAIMO_AUDIT_CLIENT', str(ROOT.parent / 'game.exe')))

class RoomRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pe = pefile.PE(str(CLIENT))
    @classmethod
    def tearDownClass(cls):
        cls.pe.close()

    def execute(self, length=80, magic=recipe.MAGIC, room=17, game=1, name_end=0, patched=True):
        m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        m.mem_map(0x400000, 0xA00000)
        for va, size in [(recipe.ENTRY_VA, 0x60), (0xA750A0, 32), (0x41B3E7, 5), (0xA750E0, 32), (0xA75120, 48)]:
            m.mem_write(va, self.pe.get_data(va - self.pe.OPTIONAL_HEADER.ImageBase, size))
        m.mem_map(0x2000000, 0x40000)
        profile, frame, stack, stop = 0x2000000, 0x2010000, 0x2030000, 0x2020000
        for _, va, old, new in recipe.patch_sites():
            if patched: m.mem_write(va, new)
        if not patched: m.mem_write(recipe.ENTRY_VA, recipe.ENTRY_OLD)
        m.mem_write(0xD869D4, struct.pack('<I', profile))
        m.mem_write(0xD8CE78, struct.pack('<I', 0x2018000))
        m.mem_write(profile+0x5D0, bytes([game]))
        m.mem_write(profile+0xD5C, struct.pack('<I', 17))
        m.mem_write(profile+0xE70, struct.pack('<I', 100))
        m.mem_write(profile+0xE74, b'Old\0')
        data = bytearray(80)
        struct.pack_into('<HH', data, 4, length, 0xCF7A)
        data[8:12] = b'Room'
        data[32:35] = b'123'
        struct.pack_into('<IIII', data, 40, 3, magic, room, 4558)
        data[56:62] = b'Winner'
        data[79] = name_end
        m.mem_write(frame, bytes(data))
        m.mem_write(stack, struct.pack('<II', stop, frame))
        m.reg_write(x86.UC_X86_REG_ESP, stack)
        m.reg_write(x86.UC_X86_REG_EBP, 0x2031000)
        m.reg_write(x86.UC_X86_REG_ECX, 0x2028000)
        initial = {x86.UC_X86_REG_EBX: 0x1234, x86.UC_X86_REG_ESI: 0x5678, x86.UC_X86_REG_EDI: 0x9876}
        for reg, value in initial.items(): m.reg_write(reg, value)
        consumed = []
        def hook(machine, address, size, _):
            if address not in (0x40BBB3, 0x411F40, 0xB4ACA7, 0xADA730): return
            esp = machine.reg_read(x86.UC_X86_REG_ESP)
            ret = struct.unpack('<I', machine.mem_read(esp, 4))[0]
            if address == 0xADA730:
                consumed.append(True)
                machine.reg_write(x86.UC_X86_REG_EAX, 0)
                pop = 4
            elif address == 0xB4ACA7:
                dest, cap, src = struct.unpack('<III', machine.mem_read(esp+4, 12))
                value = bytes(machine.mem_read(src, 24)).split(b'\0')[0]
                self.assertLess(len(value), cap)
                machine.mem_write(dest, value+b'\0')
                pop = 4
            else:
                src = struct.unpack('<I', machine.mem_read(esp+4, 4))[0]
                cap = 24 if address == 0x40BBB3 else 8
                value = bytes(machine.mem_read(src, cap)).split(b'\0')[0]
                dest = profile + (0xD60 if address == 0x40BBB3 else 0xE64)
                machine.mem_write(dest, value+b'\0')
                pop = 8
            machine.reg_write(x86.UC_X86_REG_ESP, esp+pop)
            machine.reg_write(x86.UC_X86_REG_EIP, ret)
        m.hook_add(uc.UC_HOOK_CODE, hook)
        m.emu_start(recipe.ENTRY_VA, stop, count=1000)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_ESP), stack+8)
        self.assertEqual(m.reg_read(x86.UC_X86_REG_EBP), 0x2031000)
        for reg, value in initial.items(): self.assertEqual(m.reg_read(reg), value)
        self.assertEqual(len(consumed), 1)
        return (struct.unpack('<I', m.mem_read(profile+0xE70,4))[0],
                bytes(m.mem_read(profile+0xE74,24)).split(b'\0')[0],
                struct.unpack('<I',m.mem_read(profile+0xE6C,4))[0])

    def test_client_sites_match_supported_bytes(self):
        for _, va, old, new in recipe.patch_sites():
            self.assertIn(self.pe.get_data(va-self.pe.OPTIONAL_HEADER.ImageBase,len(old)),(old,new))

    def test_current_room_record_and_difficulty(self):
        for game in (1,2,3):
            self.assertEqual(self.execute(game=game), (4558,b'Winner',3))
    def test_legacy_settings_keep_native_behavior(self):
        self.assertEqual(self.execute(length=44), self.execute(length=44,patched=False))
        self.assertEqual(self.execute(length=44), (100,b'Old',3))
    def test_invalid_extension_is_consumed_without_profile_changes(self):
        cases = [dict(length=n) for n in (0,8,43,45,72,79,81,65535)]
        cases += [dict(magic=0),dict(room=18),dict(game=0),dict(game=4),dict(name_end=65)]
        for case in cases:
            with self.subTest(case=case): self.assertEqual(self.execute(**case),(100,b'Old',0))
    def test_patch_migration_and_unknown_bytes(self):
        from test_prepare_client_compatibility import compat, synthetic_pe
        raw, _ = synthetic_pe()
        patched, _ = compat.patch_dungeon_state_controls(raw)
        again, _ = compat.patch_dungeon_state_controls(patched)
        self.assertEqual(patched, again)
        for _, va, old, new in recipe.patch_sites():
            offset = compat._va_offset(raw, va, len(old))
            self.assertEqual(patched[offset:offset+len(new)], new)
            bad = bytearray(raw); bad[offset] ^= 1
            with self.assertRaises(compat.CompatibilityError):
                compat.patch_dungeon_state_controls(bytes(bad))

    def test_embedded_recipe_identity(self):
        rows=json.loads((ROOT/'managed-host/Resources/client-compatibility.json').read_text())['sites']
        for name,va,old,new in recipe.patch_sites():
            row=next(r for r in rows if r['va']==va)
            self.assertEqual(int(row['va'],16) if isinstance(row['va'],str) else row['va'],va)
            self.assertEqual(row['target'],new.hex())

if __name__ == '__main__': unittest.main(verbosity=2)
