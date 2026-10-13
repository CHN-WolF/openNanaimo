"""Bounded x86 dialogue, cancellation, selection and source-position checks."""
import struct
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
        self.profile, self.window = 0x2000000, 0x2010000
        self.stack, self.end = 0x2040000, 0x2041000
        self.put(r.PROFILE, self.profile)
        self.calls = []
        self.village, self.page = 0, 27
        self.entry = 8
        stubs = {0x4D77B0:0, 0x411379:0, 0x41DE8A:4, 0x404A52:4,
                 0x419BBE:0, 0x4079AA:4, 0x404296:4, 0x4170D5:4,
                 0x40D69D:4, 0x402EF0:4, 0x403D19:0}
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
            self.assertEqual(bytes(self.m.mem_read(self.window+100,396)),bytes(self.m.mem_read(source,396)))
            for number in range(count):
                self.m.mem_write(self.window+52,struct.pack('<2H',2,1))
                self.calls.clear()
                result=self.run_code(r.DIALOGUE)
                if number+1<count:
                    self.assertEqual(result,1)
                    self.assertFalse(any(a==0x402EF0 for a,_ in self.calls))
                    self.assertEqual(self.get(self.window+72),number+1)
                    self.assertEqual(bytes(self.m.mem_read(self.window+100,396)),bytes(self.m.mem_read(source+(number+1)*396,396)))
                else:
                    self.assertEqual(result,2)
                    self.assertIn((0x404A52,index+8),self.calls)
                    self.assertIn((0x402EF0,9),self.calls)
                    self.assertEqual(self.get(r.ORIGIN),1)

    def test_cancel_close_and_mouse_press_preserve_selection(self):
        self.put(self.window+68,r.TABLE); self.put(self.window+72,0)
        for state,choice,result in ((2,0,2),(2,2,2),(1,1,1),(0,1,1)):
            self.calls.clear(); self.m.mem_write(self.window+52,struct.pack('<2H',state,choice))
            self.assertEqual(self.run_code(r.DIALOGUE),result)
            self.assertFalse(any(a==0x404A52 for a,_ in self.calls))

    def test_origin_change_cancels_final_confirmation(self):
        self.put(self.window+68,r.TABLE); self.put(self.window+72,self.get(r.TABLE+28)-1)
        self.m.mem_write(self.window+52,struct.pack('<2H',2,1))
        self.page=28
        self.assertEqual(self.run_code(r.DIALOGUE),2)
        self.assertFalse(any(a==0x402EF0 for a,_ in self.calls))

    def test_bounded_gbk_rows_and_exact_patch_spans(self):
        raw=r.payload(); self.assertEqual(len(raw),r.SPAN)
        for index in range(4):
            table=r.TABLE+32*index
            start,count=self.get(table+24),self.get(table+28)
            for page in range(count):
                for row in range(3):
                    text=bytes(self.m.mem_read(start+page*396+row*132,132)).split(b'\0',1)[0]
                    self.assertLessEqual(len(text),36); text.decode('gbk')
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
        offset=len(raw); raw.extend(b'\0'*0x10000)
        struct.pack_into('<H',raw,pe+6,count+1)
        struct.pack_into('<4I',raw,table+count*40+8,0x10000,0x120000,0x10000,offset)
        for _,va,old,_ in r.sites():
            at=compat._va_offset(raw,va,len(old)); raw[at:at+len(old)]=old
        changed,_=compat.patch_monk_dialogue(bytes(raw))
        self.assertEqual(changed,compat.patch_monk_dialogue(changed)[0])
        for name,va,old,new in r.sites():
            at=compat._va_offset(raw,va,len(old)); self.assertEqual(changed[at:at+len(new)],new)
            bad=bytearray(raw); bad[at]^=1
            with self.subTest(site=name),self.assertRaises(compat.CompatibilityError):
                compat.patch_monk_dialogue(bytes(bad))

    def test_ready_room_selects_challenge_resources_in_all_four_villages(self):
        self.m.mem_write(0x73AFE0,bytes.fromhex('8B442404898148E501008BC1C20400'))
        for active,village,index,native,expected in ((1,0,8,0,100),(1,1,9,4,100),
                                                    (1,2,10,8,100),(1,3,11,12,100),
                                                    (0,0,8,0,0),(1,0,0,0,0)):
            self.put(r.ORIGIN,active);self.put(r.ORIGIN+4,village)
            self.put(self.profile+0x1E54C,index)
            self.m.reg_write(x.UC_X86_REG_ECX,self.profile)
            self.m.reg_write(x.UC_X86_REG_ESP,self.stack)
            self.put(self.stack,self.end);self.put(self.stack+4,native)
            self.m.emu_start(r.READY,self.end,count=100)
            self.assertEqual(self.get(self.profile+0x1E548),expected)
            self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+8)

    def test_click_gates_native_allocation_and_window_ownership(self):
        context,input_object,actor=0x2020000,0x2030000,0x2018000
        self.put(context+0x334,actor)
        native={0x52A3E0:0,0x406F82:0,0x7EBC20:0,0x414A6F:0,0x40ED77:0,
                0x415ED3:4,0x4043D6:0,0x417184:0,0xB4CA30:0,0xB479CC:0,
                0x4064FB:0,0x41759E:4,0x408F5D:4,0x410299:4,0x418B83:0,0x419B0A:0}
        for address,args in native.items():
            self.m.mem_write(address,b'\xC2'+struct.pack('<H',args) if args else b'\xC3')
        allowed,clicked=1,1
        records=[]
        def callback(m,address,size,user):
            if address not in native:return
            arg=self.get(m.reg_read(x.UC_X86_REG_ESP)+4)
            records.append((address,arg))
            value={0x52A3E0:0x777,0x406F82:context,0x7EBC20:allowed,
                   0x414A6F:input_object,0x40ED77:input_object,0x415ED3:clicked,
                   0xB4CA30:400,0xB479CC:self.window,0x4064FB:self.window}.get(address,0)
            m.reg_write(x.UC_X86_REG_EAX,value)
        hook=self.m.hook_add(uc.UC_HOOK_CODE,callback)
        try:
            for village,page,cursor,background,button,expected in (
                    (0,27,(293,157),1,1,True),(1,26,(282,425),1,1,True),
                    (2,12,(127,416),1,1,True),(3,6,(186,255),1,1,True),
                    (4,27,(293,157),1,1,False),(0,26,(293,157),1,1,False),
                    (0,27,(317,157),1,1,False),(0,27,(293,205),1,1,False),
                    (0,27,(293,157),0,1,False),(0,27,(293,157),1,0,False)):
                self.village,self.page=village,page
                allowed,clicked=background,button
                self.put(input_object+36236,cursor[0]);self.put(input_object+36240,cursor[1])
                records.clear()
                self.m.reg_write(x.UC_X86_REG_ECX,context)
                self.m.reg_write(x.UC_X86_REG_ESP,self.stack);self.put(self.stack,self.end)
                self.m.emu_start(r.UPDATE,self.end,count=500)
                self.assertEqual(self.m.reg_read(x.UC_X86_REG_EAX),0x777)
                self.assertEqual(self.m.reg_read(x.UC_X86_REG_ESP),self.stack+4)
                self.assertEqual(any(address==0xB479CC for address,_ in records),expected)
                if expected:
                    self.assertIn((0xB479CC,0x1F0),records)
                    self.assertIn((0x41759E,9),records)
                    self.assertIn((0x410299,self.window),records)
                    self.assertEqual(self.get(self.window),r.VTABLE)
                    self.assertEqual(self.get(self.window+68),r.TABLE+village*32)
        finally:self.m.hook_del(hook)


if __name__=='__main__': unittest.main()
