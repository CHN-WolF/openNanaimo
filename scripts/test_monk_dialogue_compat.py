"""Bounded x86 dialogue, cancellation, selection and source-position checks."""
import struct
import hashlib
import json
from pathlib import Path
import unittest
import unicorn as uc
from unicorn import x86_const as x
import monk_dialogue_compat as r


class DialogueChecks(unittest.TestCase):
    def setUp(self):
        self.m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        self.m.mem_map(0x400000, 0xA00000)
        self.m.mem_map(0x2000000, 0x50000)
        self.m.mem_write(r.BASE, r.payload())
        self.m.mem_write(r.EXT_BASE, r.gameplay_payload())
        self.m.mem_write(r.FOLLOW_BASE, r.followup_payload())
        self.profile, self.window = 0x2000000, 0x2010000
        self.stack, self.end = 0x2040000, 0x2041000
        self.put(r.PROFILE, self.profile)
        self.calls = []
        self.village, self.page = 0, 27
        self.entry = 8
        self.button, self.escape, self.enter = 0, 0, 0
        self.effect, self.effect_vtable = 0x2024000, 0x2025000
        self.put(self.window+r.GUIDE+252, self.effect)
        self.put(self.effect, self.effect_vtable)
        self.put(self.effect_vtable+16, 0x406122)
        stubs = {0x4D77B0:0, 0x411379:0, 0x41DE8A:4, 0x404A52:4,
                 0x419BBE:0, 0x4079AA:4, 0x404296:4, 0x4170D5:4,
                 0x40D69D:4, 0x402EF0:4, 0x403D19:0, 0x405F7E:4,
                 0x40ED77:0, 0x407DCE:0, 0x415064:0, 0x4169A0:0,
                 0x418B83:0, 0x419B0A:0, 0x402770:4, 0x406122:0, 0x414353:0}
        for address, args in stubs.items():
            self.m.mem_write(address, b'\xC2'+struct.pack('<H', args) if args else b'\xC3')
        def callback(m, address, size, user):
            if address not in stubs: return
            value = self.get(m.reg_read(x.UC_X86_REG_ESP)+4)
            self.calls.append((address, value))
            if address == 0x411379: m.reg_write(x.UC_X86_REG_EAX, self.village)
            elif address == 0x403D19: m.reg_write(x.UC_X86_REG_EAX, self.entry)
            elif address == 0x41DE8A: m.reg_write(x.UC_X86_REG_EAX, self.page)
            elif address == 0x419BBE: m.reg_write(x.UC_X86_REG_EAX, 0x2020000)
            elif address == 0x407DCE: m.reg_write(x.UC_X86_REG_EAX, self.escape)
            elif address == 0x415064: m.reg_write(x.UC_X86_REG_EAX, self.enter)
            elif address == 0x4169A0: m.reg_write(x.UC_X86_REG_EAX, self.button)
        self.m.hook_add(uc.UC_HOOK_CODE, callback)

    def put(self, at, value): self.m.mem_write(at, struct.pack('<I', value))
    def get(self, at): return struct.unpack('<I', self.m.mem_read(at,4))[0]
    def run_code(self, address):
        for reg in (x.UC_X86_REG_EBX,x.UC_X86_REG_ESI,x.UC_X86_REG_EDI):
            self.m.reg_write(reg,0x12345678)
        self.m.reg_write(x.UC_X86_REG_ECX,self.window)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.put(self.stack,self.end)
        self.m.emu_start(address,self.end,count=500)
        self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+4)
        for reg in (x.UC_X86_REG_EBX,x.UC_X86_REG_ESI,x.UC_X86_REG_EDI):
            self.assertEqual(self.m.reg_read(reg),0x12345678)
        return self.m.reg_read(x.UC_X86_REG_EAX)

    def test_pages_and_final_confirmation_for_every_village(self):
        for index,(village,page,_,_) in enumerate(r.ENTRIES):
            self.village,self.page=village,page
            table=r.TABLE+index*32
            self.put(self.window+68,table); self.put(self.window+72,0)
            self.run_code(r.PAGE)
            source=self.get(table+24); count=self.get(table+28)
            self.assertEqual(bytes(self.m.mem_read(self.window+r.GUIDE+40,r.PAGE_SIZE)),bytes(self.m.mem_read(source,r.PAGE_SIZE)))
            for number in range(count):
                self.assertEqual(self.get(self.window+r.GUIDE+356),int(number+1==count))
                self.button=5
                self.calls.clear()
                result=self.run_code(r.DIALOGUE)
                if number+1<count:
                    self.assertEqual(result,1)
                    self.assertFalse(any(a==0x402EF0 for a,_ in self.calls))
                    self.assertEqual(self.get(self.window+72),number+1)
                    self.assertEqual(bytes(self.m.mem_read(self.window+r.GUIDE+40,r.PAGE_SIZE)),bytes(self.m.mem_read(source+(number+1)*r.PAGE_SIZE,r.PAGE_SIZE)))
                else:
                    self.assertEqual(result,2)
                    self.assertIn((0x404A52,index+8),self.calls)
                    self.assertIn((0x402EF0,9),self.calls)
                    self.assertEqual(self.get(r.ORIGIN),1)

    def test_cancel_close_and_mouse_press_preserve_selection(self):
        self.put(self.window+68,r.TABLE); self.put(self.window+72,0)
        for button,escape,result in ((0,1,2),(0,0,1),(1,0,1),(2,0,1)):
            self.calls.clear(); self.button,self.escape=button,escape
            self.assertEqual(self.run_code(r.DIALOGUE),result)
            self.assertFalse(any(a==0x404A52 for a,_ in self.calls))

    def test_origin_change_cancels_final_confirmation(self):
        self.put(self.window+68,r.TABLE); self.put(self.window+72,self.get(r.TABLE+28)-1)
        self.button=5
        self.page=28
        self.assertEqual(self.run_code(r.DIALOGUE),2)
        self.assertFalse(any(a==0x402EF0 for a,_ in self.calls))

    def test_bounded_gbk_rows_and_exact_patch_spans(self):
        raw=r.payload(); self.assertEqual(len(raw),r.SPAN)
        for index in range(4):
            table=r.TABLE+32*index
            start,count=self.get(table+24),self.get(table+28)
            for page in range(count):
                for row in range(4):
                    text=bytes(self.m.mem_read(start+page*r.PAGE_SIZE+row*51,51)).split(b'\0',1)[0]
                    self.assertLessEqual(len(text),48); text.decode('gbk')
        for name,va,old,new in r.sites(): self.assertEqual(len(old),len(new),name)

    def test_return_restores_only_the_current_challenge_origin(self):
        frame=0x2030000
        self.m.reg_write(x.UC_X86_REG_EBP,frame)
        self.put(frame-0x7AC,0x2020000)
        for active,village,page,entry,expected in ((1,0,27,8,(400,320)),(0,0,27,8,(10,20)),
                                                 (1,1,27,8,(10,20)),(1,0,28,8,(10,20)),
                                                 (1,0,27,0,(10,20))):
            self.village,self.page,self.entry=village,page,entry
            self.put(r.ORIGIN,active); self.put(r.ORIGIN+4,0); self.put(r.ORIGIN+8,27)
            self.put(r.ORIGIN+12,400); self.put(r.ORIGIN+16,320)
            self.put(frame-28,10); self.put(frame-24,20)
            self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
            self.m.emu_start(r.RETURN,0x53CE19,count=500)
            self.assertEqual((self.get(frame-28),self.get(frame-24)),expected)
            self.assertEqual(self.get(r.ORIGIN),0)
            self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack)

    def test_exact_sites_are_idempotent_and_reject_unknown_bytes(self):
        from test_prepare_client_compatibility import compat,synthetic_pe
        raw,_=synthetic_pe(); raw=bytearray(raw)
        pe=struct.unpack_from('<I',raw,60)[0]
        count=struct.unpack_from('<H',raw,pe+6)[0]
        table=pe+24+struct.unpack_from('<H',raw,pe+20)[0]
        for rva, span in ((0x120000,0x10000),(0x330000,0x10000),(0x2FA000,0x18000),(0x4C0000,0x10000)):
            offset=len(raw);raw.extend(b'\0'*span)
            struct.pack_into('<4I',raw,table+count*40+8,span,rva,span,offset);count+=1
        struct.pack_into('<H',raw,pe+6,count)
        for _,va,old,_ in r.sites():
            at=compat._va_offset(raw,va,len(old)); raw[at:at+len(old)]=old
        changed,_=compat.patch_monk_dialogue(bytes(raw))
        self.assertEqual(changed,compat.patch_monk_dialogue(changed)[0])
        legacy=bytearray(raw)
        at=compat._va_offset(legacy,r.BASE,r.SPAN)
        legacy[at:at+r.SPAN]=r.legacy_payload()
        self.assertEqual(hashlib.sha256(r.legacy_payload(legacy_names=True)).hexdigest(),
                         '2f49189e78ac9d28723d60252759312369951bf50f78578aa390e0c9524664e0')
        self.assertEqual(changed,compat.patch_monk_dialogue(bytes(legacy))[0])
        legacy[at:at+r.SPAN]=r.payload(legacy_guide=True)
        self.assertEqual(hashlib.sha256(r.payload(True, legacy_names=True)).hexdigest(),
                         'e97bee081a8139f44ba1ea6d2b81f54d8a759f8a2f3a0b4d432e618821ec6640')
        self.assertEqual(changed,compat.patch_monk_dialogue(bytes(legacy))[0])
        legacy[at:at+r.SPAN]=r.payload(legacy_lifetime=True)
        self.assertEqual(hashlib.sha256(r.payload(legacy_lifetime=True, legacy_names=True)).hexdigest(),
                         '95722048998a9f275f0d7298be065b37430c89af35ee1124c2ccbfd7adcf7181')
        self.assertEqual(changed,compat.patch_monk_dialogue(bytes(legacy))[0])
        for payload in (r.gameplay_payload(legacy_room=True),r.gameplay_payload(legacy_portrait=True)):
            legacy=bytearray(changed)
            at=compat._va_offset(legacy,r.EXT_BASE,r.EXT_SPAN)
            legacy[at:at+r.EXT_SPAN]=payload
            at=compat._va_offset(legacy,0x737DAD,5)
            legacy[at:at+5]=b'\xE8'+struct.pack('<i',r.READY_TITLE-0x737DAD-5)
            self.assertEqual(changed,compat.patch_monk_dialogue(bytes(legacy))[0])
        old_names = bytearray(changed)
        for va, build in ((r.BASE, r.payload), (r.EXT_BASE, r.gameplay_payload),
                          (r.FOLLOW_BASE, r.followup_payload)):
            previous = build(legacy_names=True)
            at = compat._va_offset(old_names, va, len(previous))
            old_names[at:at+len(previous)] = previous
        self.assertNotEqual(bytes(old_names), changed)
        self.assertEqual(changed, compat.patch_monk_dialogue(bytes(old_names))[0])
        for name,va,old,new in r.sites():
            at=compat._va_offset(raw,va,len(old)); self.assertEqual(changed[at:at+len(new)],new)
            bad=bytearray(raw); bad[at]^=1
            with self.subTest(site=name),self.assertRaises(compat.CompatibilityError):
                compat.patch_monk_dialogue(bytes(bad))

    def test_embedded_game_dialogue_uses_current_names(self):
        local = r.localization()
        data = r.payload()
        followup = r.followup_payload()
        for village in range(4):
            pointer, count = struct.unpack_from('<2I', data, r.TABLE-r.BASE+village*32+24)
            text = b''.join(data[pointer-r.BASE+i*51:pointer-r.BASE+(i+1)*51].rstrip(b'\0')
                            for i in range(count*4)).decode('gbk')
            self.assertIn(local['stage_names'][village], text)
            self.assertIn(local['villages'][village], text)
        pointer, count = struct.unpack_from('<2I', followup, r.OUTCOME_TABLE-r.FOLLOW_BASE+32+24)
        text = b''.join(followup[pointer-r.FOLLOW_BASE+i*51:pointer-r.FOLLOW_BASE+(i+1)*51].rstrip(b'\0')
                        for i in range(count*4)).decode('gbk')
        self.assertIn(local['villages'][0], text)

    def test_ready_room_selects_challenge_resources_in_all_four_villages(self):
        self.m.mem_write(0x73AFE0,bytes.fromhex('8B442404898148E501008BC1C20400'))
        for active,village,index,native,expected in ((1,0,8,0,100),(1,1,9,4,100),
                                                    (1,2,10,8,100),(1,3,11,12,100),
                                                    (0,0,8,0,0),(1,0,0,0,0)):
            self.village,self.entry=village,index
            self.put(r.ORIGIN,active);self.put(r.ORIGIN+4,village)
            # The manager index is intentionally stale before 0x72F228.
            self.put(self.profile+0x1E54C,0xDEADBEEF)
            self.m.reg_write(x.UC_X86_REG_ECX,self.profile)
            self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
            self.put(self.stack,self.end);self.put(self.stack+4,native)
            self.m.emu_start(r.READY,self.end,count=100)
            self.assertEqual(self.get(self.profile+0x1E548),expected)
            self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+8)

    def test_click_gates_native_allocation_and_window_ownership(self):
        context,input_object,actor=0x2020000,0x2030000,0x2018000
        self.put(context+0x334,actor)
        self.put(context+0x3B0,actor)
        self.put(0xD732C4,context)
        native={0x52A3E0:0,0x406F82:0,0x7EBC20:0,0x414A6F:0,0x40ED77:0,
                0x415ED3:4,0x4043D6:0,0x417184:0,0xB4CA30:0,0xB479CC:0,
                0x4064FB:0,0x41759E:4,0x408F5D:4,0x410299:4,0x418B83:0,0x419B0A:0,
                0x4163BF:4,0xA12CC0:8,0x41B5D1:0,0x40B744:4,0x4157CB:12,r.INIT_PORTRAIT:0}
        for address,args in native.items():
            self.m.mem_write(address,b'\xC2'+struct.pack('<H',args) if args else b'\xC3')
        allowed,clicked=1,1
        records=[]
        def callback(m,address,size,user):
            if address not in native:return
            if address == r.INIT_PORTRAIT:
                self.assertEqual(m.reg_read(x.UC_X86_REG_ECX), self.window+r.GUIDE)
                self.assertEqual(m.reg_read(x.UC_X86_REG_EDX), self.village)
            arg=self.get(m.reg_read(x.UC_X86_REG_ESP)+4)
            records.append((address,arg))
            value={0x52A3E0:0x777,0x406F82:context,0x7EBC20:allowed,
                   0x414A6F:input_object,0x40ED77:input_object,0x415ED3:clicked,
                   0xB4CA30:400,0xB479CC:self.window,0x4064FB:self.window}.get(address,0)
            m.reg_write(x.UC_X86_REG_EAX,value)
        hook=self.m.hook_add(uc.UC_HOOK_CODE,callback)
        try:
            for village,page,cursor,background,button,expected in (
                    (0,27,(293,189),1,1,True),(1,26,(282,425),1,1,True),
                    (2,12,(223,376),1,1,True),(3,6,(186,255),1,1,True),
                    (2,12,(127,416),1,1,False),
                    (4,27,(293,189),1,1,False),(0,26,(293,189),1,1,False),
                    (0,27,(317,189),1,1,False),(0,27,(293,237),1,1,False),
                    (0,27,(293,189),0,1,False),(0,27,(293,189),1,0,False),
                    (0,27,(293,189),1,2,False),(0,27,(293,189),1,3,False)):
                self.village,self.page=village,page
                allowed,clicked=background,button
                self.m.mem_write(input_object+0x21C, bytes([128 if button in (1,2) else 0]))
                self.m.mem_write(input_object+0x22C, bytes([128 if button in (2,3) else 0]))
                self.put(input_object+36236,cursor[0]);self.put(input_object+36240,cursor[1])
                records.clear()
                self.m.reg_write(x.UC_X86_REG_ECX,context)
                self.m.reg_write(x.UC_X86_REG_ESP,self.stack);self.put(self.stack,self.end)
                self.m.emu_start(r.UPDATE,self.end,count=500)
                self.assertEqual(self.m.reg_read(x.UC_X86_REG_EAX),0x777)
                self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+4)
                self.assertEqual(any(address==0xB479CC for address,_ in records),expected)
                if expected:
                    self.assertIn((0xB479CC,r.WINDOW_SIZE),records)
                    self.assertIn((0x41759E,9),records)
                    self.assertIn((0x410299,self.window),records)
                    self.assertEqual(self.get(self.window),r.VTABLE)
                    self.assertEqual(self.get(self.window+68),r.TABLE+village*32)
                    self.assertFalse(any(address==0x408F5D for address,_ in records))
                    self.assertIn((0xA12CC0,0),records)
                    self.assertEqual(sum(a == r.INIT_PORTRAIT for a,_ in records),1)
        finally:self.m.hook_del(hook)

    def test_original_ready_initialization_with_stale_previous_room(self):
        import monk_village_compat as selection
        # Native room initialization at 0x72F202..0x72F2C1.
        native=bytes.fromhex(
            '8b55f052e8b3a9ceff8bc8e834f4ceff8b0dd469d800e8fc4acdff0fb6c050'
            'e898a9ceff8bc8e883c6ceffe88ca9ceff8bc8e841edceff83f864752e'
            '8b0dd469d800e8d04acdff0fb6c883c11051e869a9ceff8bc8e84ef0cdff'
            '6a00e85ba9ceff8bc8e8419acdffeb558b0dd469d800e8ac7bceff0fb710'
            '8955e4e83ca9ceff8bc8e8a44acdff85c074098b45e483e8108945e4'
            '8b4de451e81fa9ceff8bc8e804f0cdff8b0dd469d800e8684acdff0fb6d0'
            '52e804a9ceff8bc8e8ea99cdff')
        self.m.mem_write(0x72F202,native)
        self.m.mem_write(selection.CODE_VA,selection.code())
        for _,va,_,new in (*r.sites(),*selection.sites()):
            if va in (0x72F20D,0x72F265):self.m.mem_write(va,new)
        # Exact native setters; preserve the real order (chapter before entry).
        for address,offset in ((0x73AFE0,0x1E548),(0x41B8B0,0x1E54C),
                               (0x40E2AA,0x1E534),(0x408CAB,0x1E538)):
            self.m.mem_write(address,bytes.fromhex('558bec51894dfc8b45fc8b4d088988')+
                             struct.pack('<I',offset)+bytes.fromhex('8be55dc20400'))
        self.m.mem_write(0x41DF7A,bytes.fromhex('8b8148e50100c3'))
        self.m.mem_write(0x403D2D,bytes.fromhex('33c0c3'))
        self.m.mem_write(0x416E23,b'\xB8'+struct.pack('<I',self.profile+0x100)+b'\xC3')
        manager=0x2020000
        for implementation in ('legacy','current'):
            payload=r.legacy_payload() if implementation=='legacy' else r.payload()
            self.m.mem_write(r.BASE,payload)
            self.m.ctl_remove_cache(r.BASE,r.BASE+r.SPAN)
            for village in range(4):
                for stale in (0,8,11,24,27,0xFFFFFFFF):
                    self.village,self.entry=village,8+village
                    self.put(r.ORIGIN,1);self.put(r.ORIGIN+4,village)
                    self.put(manager+0x1E530,0);self.put(manager+0x1E54C,stale)
                    self.put(self.profile+0x100,village*4)
                    self.m.reg_write(x.UC_X86_REG_EBP,self.stack-0x100)
                    self.put(self.stack-0x110,village*4)
                    self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
                    self.m.emu_start(0x72F202,0x72F2C1,count=1000)
                    actual=tuple(self.get(manager+o) for o in (0x1E534,0x1E538,0x1E548,0x1E54C))
                    expected=(24+village,0,24+village,0)
                    if implementation=='current' or stale==8+village:
                        self.assertEqual(actual,expected,(implementation,village,stale))
                    else:
                        self.assertNotEqual(actual,expected)
                    self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack)

    def test_hover_runs_after_native_cursor_reset(self):
        context=0x2020000
        self.put(context+0x334,0x12345678)
        self.m.mem_write(0x527C80,bytes.fromhex('b877070000c3'))
        self.m.mem_write(r.HIT,b'\xB8'+struct.pack('<I',r.TABLE)+b'\xC3')
        self.m.reg_write(x.UC_X86_REG_ECX,context)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack);self.put(self.stack,self.end)
        self.m.emu_start(r.HOVER,self.end,count=100)
        self.assertEqual(self.m.reg_read(x.UC_X86_REG_EAX),0x777)
        self.assertIn((0x402770,1),self.calls)
        self.calls.clear()
        self.m.mem_write(r.HIT,bytes.fromhex('33c0c3'))
        self.m.ctl_remove_cache(r.HIT,r.HIT+0x100)
        self.run_code(r.HOVER)
        self.assertFalse(any(a==0x402770 for a,_ in self.calls))

    def test_guide_destruction_precedes_native_window_destruction(self):
        seen=[]
        self.m.mem_write(0x41B6A8,b'\xC3')
        self.m.mem_write(0x4D7830,bytes.fromhex('8bc1c20400'))
        def record(m,address,size,user):
            if address in (0x41B6A8,0x4D7830):
                seen.append((address,m.reg_read(x.UC_X86_REG_ECX)))
        self.m.hook_add(uc.UC_HOOK_CODE,record)
        self.m.reg_write(x.UC_X86_REG_ECX,self.window)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.put(self.stack,self.end);self.put(self.stack+4,1)
        self.m.emu_start(r.DESTROY,self.end,count=100)
        self.assertEqual(seen,[(0x41B6A8,self.window+r.GUIDE),(0x4D7830,self.window)])
        self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+8)

    def test_native_window_sweep_preserves_open_pages_and_releases_closed_pages(self):
        # Native window reclamation at 0x7EC5C0..0x7EC65D.
        native=bytes.fromhex(
            '558bec83ec18894decc745fc000000008b4dece889e2c2ff8945f8837df8007479'
            '8b45f88b481c894dfc8b55f88b028b4df88b500cffd20fb6c085c074548b4df851'
            '8b4dece8965dc2ff8b4df8e811e0c1ff0fb6d083fa10750c6a008b4df8e8fb0b'
            'c2ffeb2c8b45f88945f08b4df0894df4837df40074136a018b55f48b028b4df4'
            '8b10ffd28945e8eb07c745e8000000008b45fc8945f8eb818be55dc3')
        self.m.mem_write(0x7EC5C0,native)
        self.m.mem_write(0x41A861,b'\xB8'+struct.pack('<I',self.window)+b'\xC3')
        self.m.mem_write(0x40A623,bytes.fromhex('b009c3'))
        self.m.mem_write(0x4123A0,bytes.fromhex('c20400'))
        self.m.mem_write(0x41B6A8,b'\xC3')
        self.m.mem_write(0x4D7830,bytes.fromhex('8bc1c20400'))
        seen=[]
        def record(m,address,size,user):
            if address in (0x4123A0,0x41B6A8,0x4D7830): seen.append(address)
        self.m.hook_add(uc.UC_HOOK_CODE,record)
        self.put(self.window,r.VTABLE)
        for legacy,state,removed in ((True,1,True),(False,0,False),
                                     (False,1,False),(False,1,False),(False,2,True)):
            self.m.mem_write(r.BASE,r.payload(legacy_lifetime=legacy))
            self.m.ctl_remove_cache(r.BASE,r.BASE+r.SPAN)
            self.m.mem_write(self.window+0x34,struct.pack('<H',state))
            seen.clear()
            self.run_code(0x7EC5C0)
            self.assertEqual(seen,[0x4123A0,0x41B6A8,0x4D7830] if removed else [])

    def test_embedded_dialogue_matches_migration_and_hover_sites(self):
        recipe=json.loads((Path(__file__).resolve().parents[1]/
                           'managed-host/Resources/client-compatibility.json').read_text('utf-8'))
        rows={row['va']:row for row in recipe['sites'] if row['group']=='monk-dialogue'}
        for _,va,old,new in r.sites():
            self.assertEqual(rows[va]['target'],new.hex())
            self.assertIn(old.hex(),rows[va]['known'])
        self.assertIn(r.legacy_payload().hex(),rows[r.BASE]['known'])
        self.assertIn(r.payload(True).hex(),rows[r.BASE]['known'])
        self.assertIn(r.payload(legacy_lifetime=True).hex(),rows[r.BASE]['known'])


class VisualChecks(unittest.TestCase):
    setUp = DialogueChecks.setUp
    put = DialogueChecks.put
    get = DialogueChecks.get
    run_code = DialogueChecks.run_code
    def test_local_tuple_guards_do_not_rewrite_manager(self):
        manager=0x2020000
        self.m.mem_write(0x419BBE,b'\xB8'+struct.pack('<I',manager)+b'\xC3')
        self.m.mem_write(0x403D2D,bytes.fromhex('8B8130E50100C3'))
        for hd,ep,dg,active in ((0,24,0,True),(0,25,0,True),(0,26,0,True),(0,27,0,True),
                               (0,23,0,False),(0,28,0,False),(1,24,0,False),(0,24,1,False)):
            for off,value in ((0x1E530,hd),(0x1E534,ep),(0x1E538,dg)):
                self.put(manager+off,value)
            before=bytes(self.m.mem_read(manager,0x1E600))
            self.village=0
            self.assertEqual(self.run_code(r.VILLAGE_GATE),4 if active else 0)
            self.m.reg_write(x.UC_X86_REG_ECX,manager);self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
            self.put(self.stack,self.end);self.m.emu_start(r.HD_GATE,self.end,count=500)
            self.assertEqual(self.m.reg_read(x.UC_X86_REG_EAX),1 if active else hd)
            self.assertEqual(bytes(self.m.mem_read(manager,0x1E600)),before)

    def test_first_village_native_update_skips_both_null_icons(self):
        # Native room icon update at 0x737C3B..0x737C85.
        raw=bytes.fromhex('8B4DC883390575428B0DD469D800E82B97CDFF83F8047D328B55C88B828C0000008B4DC88B898C0000008B108B4210FFD08B4DC88B91900000008B45C88B88900000008B12508B4210FFD0')
        # Exact tail has mov edx,[edx], not an extra push.
        raw=raw.replace(bytes.fromhex('8B12508B4210'),bytes.fromhex('8B128B4210'))
        self.assertEqual(len(raw),0x737C85-0x737C3B)
        manager,frame,controller=0x2020000,0x2030000,0x2018000
        self.put(frame-0x38,controller);self.put(controller,5)
        self.put(controller+0x8C,0);self.put(controller+0x90,0)
        self.m.mem_write(0x419BBE,b'\xB8'+struct.pack('<I',manager)+b'\xC3')
        self.put(manager+0x1E530,0);self.put(manager+0x1E534,24);self.put(manager+0x1E538,0)
        self.m.reg_write(x.UC_X86_REG_EBP,frame);self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.m.mem_write(0x737C3B,raw)
        with self.assertRaises(uc.UcError):self.m.emu_start(0x737C3B,0x737C85,count=500)
        self.m.mem_write(0x737C49,b'\xE8'+struct.pack('<i',r.VILLAGE_GATE-0x737C49-5))
        self.m.ctl_remove_cache(0x737C3B,0x737C85)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.m.emu_start(0x737C3B,0x737C85,count=500)
        self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack)

    def test_late_guide_draw_owns_only_open_monk_and_keeps_cursor_last(self):
        manager,chain,peer=0x2020000,0x2020100,0x2020200
        self.m.mem_write(0x406F82,b'\xB8'+struct.pack('<I',manager)+b'\xC3')
        self.m.mem_write(0xA13630,b'\xC3');self.m.mem_write(0x41CB16,b'\xC3')
        self.put(manager,chain);self.put(chain+8,peer);self.put(peer,0x12345678)
        self.put(peer+24,self.window);self.put(self.window,r.VTABLE);self.put(self.window+24,0)
        calls=[]
        def record(m,at,size,user):
            if at in (0xA13630,0x41CB16):calls.append((at,m.reg_read(x.UC_X86_REG_ECX)))
        self.m.hook_add(uc.UC_HOOK_CODE,record)
        for state in (1,2):
            calls.clear();self.put(self.window+0x34,state)
            self.run_code(r.DRAW);self.assertEqual(calls,[])
            self.run_code(r.LATE_DRAW)
            expected=[(0xA13630,self.window+r.GUIDE)] if state==1 else []
            self.assertEqual(calls,expected+[(0x41CB16,self.window)])

    def test_named_header_native_text_abi_and_both_branches(self):
        manager=0x2020000;self.m.mem_write(0x419BBE,b'\xB8'+struct.pack('<I',manager)+b'\xC3')
        self.m.mem_write(0x414A6F,bytes.fromhex('B800002202C3'))
        self.m.mem_write(0x40DA1C,bytes.fromhex('C23400'))
        calls=[]
        def record(m,at,size,user):
            if at==0x40DA1C:
                sp=m.reg_read(x.UC_X86_REG_ESP);ptr=self.get(sp+12)
                calls.append((self.get(sp+4),self.get(sp+8),bytes(m.mem_read(ptr,32)).split(b'\0')[0].decode('gbk')))
        self.m.hook_add(uc.UC_HOOK_CODE,record)
        for ep,title in enumerate(('龙飞峡谷','坎泽峡谷','踏坦峡谷','白豹山'),24):
            self.put(manager+0x1E530,0);self.put(manager+0x1E534,ep);self.put(manager+0x1E538,0)
            calls.clear();self.run_code(r.READY_TITLE);self.assertEqual(calls,[])
            self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
            self.m.emu_start(r.RESULT_TITLE,0x764E22,count=500)
            self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack)
            self.assertEqual(calls[-1],(31,69,title))
        self.put(manager+0x1E534,3);calls.clear();self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.m.emu_start(r.RESULT_TITLE,0x764C9B,count=500)
        self.assertEqual(calls,[]);self.assertEqual(self.m.reg_read(x.UC_X86_REG_EAX),manager)
        self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack)


    def result_stubs(self):
        self.uid=1234
        stubs={0x40B744:4,0x407ACC:4}
        for a,n in stubs.items():self.m.mem_write(a,b'\xC2'+struct.pack('<H',n))
        def callback(m,a,size,user):
            if a==0x40B744:m.reg_write(x.UC_X86_REG_EAX,self.uid)
        self.m.hook_add(uc.UC_HOOK_CODE,callback)
        self.manager=0x2020000
        self.put(self.manager+0x1E530,0);self.put(self.manager+0x1E538,0)
        self.put(r.ORIGIN,1)

    def test_own_result_all_four_villages_and_six_ratings(self):
        self.result_stubs();row=0x2032000
        for village in range(4):
            for rating in range(6):
                self.put(self.manager+0x1E534,24+village)
                self.put(r.ORIGIN+4,village)
                self.run_code(r.ARM_RESULT)
                self.assertEqual(self.get(r.RESULT_STATE),1)
                self.put(row,self.uid);self.m.mem_write(row+0xA4,bytes([rating]))
                self.put(self.stack+4,row)
                self.m.reg_write(x.UC_X86_REG_ESP,self.stack);self.put(self.stack,self.end)
                self.m.emu_start(r.CAPTURE_RESULT,self.end,count=500)
                self.assertEqual(self.get(r.RESULT_STATE+4),r.OUTCOME_TABLE+32*(village*2+(rating==0)))
                self.assertEqual(self.get(r.RESULT_STATE),0)
                self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+8)
                self.put(r.RESULT_STATE+4,0)
                self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
                self.m.emu_start(r.CAPTURE_RESULT,self.end,count=500)
                self.assertEqual(self.get(r.RESULT_STATE+4),0,'duplicate CF88 must not reopen')

    def test_foreign_stale_invalid_and_nonchallenge_results_do_not_open(self):
        self.result_stubs();row=0x2032000
        for ep,owner,rating in [(24,9999,1),(25,1234,1),(24,1234,6)]:
            self.put(self.manager+0x1E534,24);self.run_code(r.ARM_RESULT)
            self.put(self.manager+0x1E534,ep);self.put(row,owner)
            self.m.mem_write(row+0xA4,bytes([rating]));self.put(self.stack+4,row)
            self.m.reg_write(x.UC_X86_REG_ESP,self.stack);self.put(self.stack,self.end)
            self.m.emu_start(r.CAPTURE_RESULT,self.end,count=500)
            self.assertEqual(self.get(r.RESULT_STATE+4),0)
        self.put(self.manager+0x1E534,23);self.run_code(r.ARM_RESULT)
        self.assertEqual(self.get(r.RESULT_STATE),0)

    def test_success_failure_pages_close_without_entry_and_escape_closes(self):
        for village in range(4):
            for outcome in range(2):
                table=r.OUTCOME_TABLE+32*(village*2+outcome)
                self.put(self.window+0x44,table);self.put(self.window+0x48,0)
                self.put(self.window+0x4C,1);self.button=5;self.escape=0
                count=self.get(table+28)
                self.assertGreater(count,0);self.calls.clear()
                for i in range(count):
                    self.assertEqual(self.run_code(r.DIALOGUE),2 if i==count-1 else 1)
                self.assertFalse(any(a==0x402EF0 for a,_ in self.calls))
                self.put(self.window+0x34,1);self.escape=1
                self.assertEqual(self.run_code(r.DIALOGUE),2)
        self.escape=0

    def test_capture_origin_is_own_actor_not_mouse_and_rejects_collision(self):
        actor,mouse,context,mapobj=0x2018000,0x2019000,0x2020000,0x2028000
        self.put(context+0x3B0,actor);self.put(context+0x334,mouse);self.put(0xD732C4,mapobj)
        self.owner=1234;self.collision=0;self.coordinate=0;seen=[]
        for a,n in {0x41B5D1:0,0x40B744:4,0x4043D6:0,0x417184:0,0xB4CA30:0,0x4157CB:12}.items():
            self.m.mem_write(a,b'\xC2'+struct.pack('<H',n) if n else b'\xC3')
        def cb(m,a,size,user):
            if a==0x41B5D1:m.reg_write(x.UC_X86_REG_EAX,self.owner)
            elif a==0x40B744:m.reg_write(x.UC_X86_REG_EAX,1234)
            elif a in (0x4043D6,0x417184):
                self.assertEqual(m.reg_read(x.UC_X86_REG_ECX),actor)
                self.coordinate=321 if a==0x4043D6 else 289
            elif a==0xB4CA30:m.reg_write(x.UC_X86_REG_EAX,self.coordinate)
            elif a==0x4157CB:
                sp=m.reg_read(x.UC_X86_REG_ESP)
                seen.append(tuple(self.get(sp+4+i*4) for i in range(3)))
                m.reg_write(x.UC_X86_REG_EAX,self.collision)
        self.m.hook_add(uc.UC_HOOK_CODE,cb)
        for owner,blocked,expected in [(1234,0,1),(9999,0,0),(1234,1,0),(1234,0xFFFFFFFF,0)]:
            self.owner,self.collision=owner,blocked
            self.put(r.ORIGIN+12,10);self.put(r.ORIGIN+16,20)
            self.m.reg_write(x.UC_X86_REG_ECX,context);self.m.reg_write(x.UC_X86_REG_ESP,self.stack);self.put(self.stack,self.end)
            self.m.emu_start(r.CAPTURE_ORIGIN,self.end,count=300)
            self.assertEqual(self.m.reg_read(x.UC_X86_REG_EAX),expected)
            self.assertEqual((self.get(r.ORIGIN+12),self.get(r.ORIGIN+16)),(321,289) if expected else (10,20))
            self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+4)
        self.assertTrue(all(v==(321,289,1) for v in seen))

    def town_result_stubs(self):
        self.result_stubs();self.put(self.manager+0x1E534,24)
        self.put(self.window+0x334,self.effect);self.put(self.window+0x3B0,0x2018000)
        self.allocated=0x201A000;self.result_calls=[];self.available=1;self.alloc_ok=True
        stubs={0x406F82:0,0x7EBC20:0,0xB479CC:0,0x4064FB:0,
               0x41759E:4,0x4163BF:4,0xA12CC0:8,0x410299:4,0xA13630:0,
               r.INIT_PORTRAIT:0,0x41B5D1:0}
        for a,n in stubs.items():self.m.mem_write(a,b'\xC2'+struct.pack('<H',n) if n else b'\xC3')
        def cb(m,a,size,user):
            if a not in stubs:return
            if a == r.INIT_PORTRAIT:
                self.assertEqual(m.reg_read(x.UC_X86_REG_ECX),self.allocated+r.GUIDE)
                self.assertEqual(m.reg_read(x.UC_X86_REG_EDX),self.village)
            self.result_calls.append((a,m.reg_read(x.UC_X86_REG_ECX)))
            if a in (0xB479CC,0x4064FB):m.reg_write(x.UC_X86_REG_EAX,self.allocated if self.alloc_ok else 0)
            if a==0x406F82:m.reg_write(x.UC_X86_REG_EAX,self.manager)
            if a==0x7EBC20:m.reg_write(x.UC_X86_REG_EAX,self.available)
            if a==0x41B5D1:m.reg_write(x.UC_X86_REG_EAX,self.uid)
            if a==0x4163BF:self.assertEqual(self.get(m.reg_read(x.UC_X86_REG_ESP)+4),self.effect)
        self.m.hook_add(uc.UC_HOOK_CODE,cb)

    def capture_outcome(self,village,rating):
        self.village=village;self.page=r.ENTRIES[village][1];self.entry=8+village
        self.put(r.ORIGIN,1);self.put(r.ORIGIN+4,village);self.put(r.ORIGIN+8,self.page)
        self.put(self.manager+0x1E534,24+village);self.run_code(r.ARM_RESULT)
        row=0x2032000;self.put(row,self.uid);self.m.mem_write(row+0xA4,bytes([rating]))
        self.put(self.stack+4,row);self.put(self.stack,self.end)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.m.emu_start(r.CAPTURE_RESULT,self.end,count=500)
        return r.OUTCOME_TABLE+32*(village*2+(rating==0))

    def return_to_town(self):
        frame=0x2030000;self.m.reg_write(x.UC_X86_REG_EBP,frame)
        self.put(frame-0x7AC,self.window)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.m.emu_start(r.RETURN,0x53CE19,count=500)
        self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack)

    def test_outcome_waits_for_matching_return_all_villages_and_ratings(self):
        self.town_result_stubs()
        for village in range(4):
            for rating in range(6):
                with self.subTest(village=village,rating=rating):
                    self.result_calls.clear();table=self.capture_outcome(village,rating)
                    self.assertEqual(self.get(r.RESULT_STATE+4),table)
                    self.put(self.window+0x3C,1)
                    self.assertEqual(self.run_code(r.OPEN_RESULT),0,'idle settlement is not a town return')
                    self.assertFalse(any(a==0xB479CC for a,_ in self.result_calls))
                    self.return_to_town();self.assertEqual(self.get(r.RESULT_STATE+16),1)
                    self.put(self.manager+0x1E534,0)
                    self.assertEqual(self.run_code(r.OPEN_RESULT),1)
                    self.assertEqual(self.get(self.allocated),r.VTABLE)
                    self.assertEqual(self.get(self.allocated+0x44),table)
                    self.assertEqual(self.get(self.allocated+0x4C),1)
                    self.assertEqual(self.get(r.RESULT_STATE+4),0)
                    self.assertEqual(self.get(r.RESULT_STATE+16),0)
                    self.assertEqual(self.run_code(r.OPEN_RESULT),0)
                    self.assertEqual(sum(a==0xB479CC for a,_ in self.result_calls),1)

    def test_outcome_retry_clears_pending_and_abort_has_no_dialogue(self):
        self.town_result_stubs();self.capture_outcome(0,0)
        self.run_code(r.ARM_RESULT)
        self.assertEqual(self.get(r.RESULT_STATE+4),0)

        self.assertEqual(self.get(r.RESULT_STATE+16),0)
        self.return_to_town()
        self.assertEqual(self.get(r.RESULT_STATE),0,'leaving disarms delayed CF88')
        self.assertEqual(self.run_code(r.OPEN_RESULT),0)
        row=0x2032000;self.put(row,self.uid);self.m.mem_write(row+0xA4,b'\x01')
        self.put(self.stack+4,row);self.put(self.stack,self.end)
        self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
        self.m.emu_start(r.CAPTURE_RESULT,self.end,count=500)
        self.assertEqual(self.get(r.RESULT_STATE+4),0)

    def test_outcome_origin_episode_and_stage_must_match(self):
        self.result_stubs()
        self.put(self.manager+0x1E534,25);self.put(r.ORIGIN+4,0)
        self.run_code(r.ARM_RESULT);self.assertEqual(self.get(r.RESULT_STATE),0)
        self.put(r.ORIGIN+4,1);self.put(self.manager+0x1E540,1)
        self.run_code(r.ARM_RESULT);self.assertEqual(self.get(r.RESULT_STATE),0)
        self.put(self.manager+0x1E540,0)
        self.run_code(r.ARM_RESULT);self.assertEqual(self.get(r.RESULT_STATE),1)

    def test_outcome_rejects_wrong_return_and_discards_changed_identity(self):
        self.town_result_stubs()
        for field in ('village','page','entry'):
            self.capture_outcome(0,1);setattr(self,field,getattr(self,field)+1)
            self.return_to_town()
            self.assertEqual(self.get(r.RESULT_STATE+16),0,field)
            self.assertEqual(self.run_code(r.OPEN_RESULT),0)
        for field in ('village','page','uid'):
            self.capture_outcome(0,1);self.return_to_town()
            old=getattr(self,field);setattr(self,field,old+1)
            self.assertEqual(self.run_code(r.OPEN_RESULT),0,field)
            self.assertEqual(self.get(r.RESULT_STATE+4),0)
            setattr(self,field,old)

    def test_outcome_waits_for_actor_cursor_window_and_allocation(self):
        self.town_result_stubs();table=self.capture_outcome(0,1);self.return_to_town()
        for offset in (0x334,0x3B0):
            old=self.get(self.window+offset);self.put(self.window+offset,0)
            self.assertEqual(self.run_code(r.OPEN_RESULT),0)
            self.assertEqual(self.get(r.RESULT_STATE+4),table)
            self.put(self.window+offset,old)
        self.available=0;self.assertEqual(self.run_code(r.OPEN_RESULT),0)
        self.available=1;self.alloc_ok=False;self.assertEqual(self.run_code(r.OPEN_RESULT),0)
        self.assertEqual(self.get(r.RESULT_STATE+4),table)
        self.alloc_ok=True;self.assertEqual(self.run_code(r.OPEN_RESULT),1)

    def test_settlement_pump_is_restored_and_village_draw_is_late_only(self):
        sites={name:(old,new) for name,_,old,new in r.sites()}
        self.assertEqual(sites['monk_result_dialogue_pump'][1],bytes.fromhex('8B55EC837A3C01'))
        self.assertNotIn('monk_result_late_guide_draw',sites)
        self.assertEqual(r.payload()[r.DRAW-r.BASE],0xC3)

if __name__=='__main__': unittest.main()
