'''Monk portrait loading, animation, ownership and migration checks.'''
import hashlib
import json
import struct
import unittest
from pathlib import Path

import unicorn as uc
from unicorn import x86_const as x
import monk_dialogue_compat as r
import test_monk_dialogue_compat as dialogue_checks


class PortraitChecks(unittest.TestCase):
    setUp = dialogue_checks.DialogueChecks.setUp
    put = dialogue_checks.DialogueChecks.put
    get = dialogue_checks.DialogueChecks.get
    run_code = dialogue_checks.DialogueChecks.run_code

    def test_native_effect_abi_for_each_village_and_allocation_failure(self):
        guide = self.window+r.GUIDE
        effect = 0x2026000
        stubs = {0xB479CC:0, 0x41BE00:0, 0x404232:20}
        for address, args in stubs.items():
            self.m.mem_write(address, b'\xC2'+struct.pack('<H',args) if args else b'\xC3')
        seen = []
        allocation = effect
        def record(m, address, size, user):
            if address not in stubs:
                return
            sp = m.reg_read(x.UC_X86_REG_ESP)
            seen.append(address)
            if address == 0xB479CC:
                self.assertEqual(self.get(sp+4), 0x144)
                m.reg_write(x.UC_X86_REG_EAX, allocation)
            elif address == 0x41BE00:
                self.assertEqual(m.reg_read(x.UC_X86_REG_ECX),effect)
                m.reg_write(x.UC_X86_REG_EAX,effect)
            else:
                self.assertEqual(m.reg_read(x.UC_X86_REG_ECX),effect)
                name = bytes(m.mem_read(self.get(sp+4),64)).split(b'\0',1)[0]
                self.assertEqual(name, f'interface\\NPC_{62+village}_0.eff'.encode('ascii'))
                self.assertEqual(tuple(self.get(sp+8+i*4) for i in range(4)),(0,400,300,0))
        self.m.hook_add(uc.UC_HOOK_CODE,record)
        for village, allocation in [(i,effect) for i in range(4)]+[(0,0),(4,effect),(0xFFFFFFFF,effect)]:
            with self.subTest(village=village,allocation=allocation):
                self.put(guide+0xF4,0)
                self.put(guide+0xF8,0)
                self.put(guide+0x12C,400)
                self.put(guide+0x130,300)
                before = bytes(self.m.mem_read(guide,0x16C))
                seen.clear()
                for reg in (x.UC_X86_REG_EBX,x.UC_X86_REG_ESI,x.UC_X86_REG_EDI):
                    self.m.reg_write(reg,0x12345678)
                self.m.reg_write(x.UC_X86_REG_ECX,guide)
                self.m.reg_write(x.UC_X86_REG_EDX,village)
                self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
                self.put(self.stack,self.end)
                self.m.emu_start(r.INIT_PORTRAIT,self.end,count=200)
                self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+4)
                for reg in (x.UC_X86_REG_EBX,x.UC_X86_REG_ESI,x.UC_X86_REG_EDI):
                    self.assertEqual(self.m.reg_read(reg),0x12345678)
                expected = bytearray(before)
                if village < 4 and allocation:
                    struct.pack_into('<I',expected,0xF4,effect)
                self.assertEqual(bytes(self.m.mem_read(guide,0x16C)),bytes(expected))
                self.assertEqual(seen,list(stubs) if village<4 and allocation else [0xB479CC] if village<4 else [])

    def test_portrait_advances_once_per_tick_and_not_when_closing(self):
        portrait, vtable, update = 0x2026000, 0x2027000, 0x406128
        self.put(self.window+r.GUIDE+0xF4,portrait)
        self.put(portrait,vtable)
        self.put(vtable+16,update)
        self.m.mem_write(update,b'\xC3')
        seen=[]
        def record(m,address,size,user):
            if address in (update,0x406122):
                seen.append((address,m.reg_read(x.UC_X86_REG_ECX)))
        self.m.hook_add(uc.UC_HOOK_CODE,record)
        for _ in range(3):
            self.run_code(r.DIALOGUE)
        self.assertEqual(seen,[(update,portrait),(0x406122,self.effect)]*3)
        seen.clear()
        self.escape=1
        self.run_code(r.DIALOGUE)
        self.assertEqual(seen,[])
        self.escape=0
        self.put(self.window+r.GUIDE+0xF4,0)
        self.run_code(r.DIALOGUE)
        self.assertEqual(seen,[(0x406122,self.effect)])

    def test_both_dialogue_kinds_skip_early_draw(self):
        self.m.mem_write(0xA13630,b'\xC3')
        seen=[]
        self.m.hook_add(uc.UC_HOOK_CODE,lambda m,a,s,u: seen.append(a) if a==0xA13630 else None)
        for kind in (0,1):
            self.put(self.window+0x4C,kind)
            self.run_code(r.DRAW)
        self.assertEqual(seen,[])

    def test_original_guide_destructor_releases_portrait_before_window(self):
        # Native guide destructor at 0xA12790..0xA128B3.
        native=bytes.fromhex(
            '558bec83ec38894dd8c745fc00000000eb098b45fc83c0018945fc837dfc027d49'
            '8b4dfc8b55d88b848af40000008945f48b4df4894df8837df80074136a018b55f8'
            '8b028b4df88b10ffd28945d4eb07c745d4000000008b45fc8b4dd8c78481f400'
            '000000000000eba88b55d88b82fc0000008945ec8b4dec894df0837df0007413'
            '6a018b55f08b028b4df08b10ffd28945d0eb07c745d0000000008b45d8c780fc'
            '000000000000008b4dd88b91040100008955e48b45e48945e8837de800740f6a01'
            '8b4de8e87c87a0ff8945cceb07c745cc000000008b4dd8c7810401000000000000'
            '8b55d88b82080100008945dc8b4ddc894de0837de000740f6a018b4de0e84187a0'
            'ff8945c8eb07c745c8000000008b55d8c78208010000000000008be55dc3')
        self.assertEqual(len(native),291)
        self.m.mem_write(0xA12790,native)
        self.m.mem_write(0x41B6A8,b'\xE9'+struct.pack('<i',0xA12790-0x41B6A8-5))
        self.m.mem_write(0x4D7830,bytes.fromhex('C20400'))
        deleter=0x406130
        self.m.mem_write(deleter,bytes.fromhex('C20400'))
        self.m.mem_write(0x41AFD7,bytes.fromhex('C20400'))
        pointers=[0x2026000+i*0x100 for i in range(5)]
        offsets=(0xF4,0xF8,0xFC,0x104,0x108)
        for ptr,off in zip(pointers,offsets):
            self.put(self.window+r.GUIDE+off,ptr)
            self.put(ptr,self.effect_vtable)
        self.put(self.effect_vtable,deleter)
        seen=[]
        def record(m,address,size,user):
            if address in (deleter,0x41AFD7,0x4D7830):
                seen.append((address,m.reg_read(x.UC_X86_REG_ECX)))
                self.assertEqual(self.get(m.reg_read(x.UC_X86_REG_ESP)+4),1)
        self.m.hook_add(uc.UC_HOOK_CODE,record)
        self.m.reg_write(x.UC_X86_REG_ECX,self.window)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.put(self.stack,self.end);self.put(self.stack+4,1)
        self.m.emu_start(r.DESTROY,self.end,count=500)
        self.assertEqual(seen,[(deleter,p) for p in pointers[:3]]+
                         [(0x41AFD7,p) for p in pointers[3:]]+[(0x4D7830,self.window)])
        self.assertTrue(all(self.get(self.window+r.GUIDE+off)==0 for off in offsets))
        self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+8)

    def test_previous_portraitless_bytes_remain_an_exact_migration_input(self):
        recipe=json.loads((Path(__file__).resolve().parents[1]/'managed-host/Resources/client-compatibility.json').read_text('utf-8'))
        sites={row['va']:row for row in recipe['sites'] if row['group']=='monk-dialogue'}
        for va, previous in ((r.BASE,r.payload(legacy_portrait=True)),
                             (r.FOLLOW_BASE,r.followup_payload(legacy_portrait=True))):
            self.assertIn(previous.hex(),sites[va]['known'])
        # Retain the original guide/lifetime migrations byte-for-byte.
        self.assertEqual(hashlib.sha256(r.payload(legacy_guide=True)).hexdigest(),
                         'e97bee081a8139f44ba1ea6d2b81f54d8a759f8a2f3a0b4d432e618821ec6640')


if __name__ == '__main__':
    unittest.main()
