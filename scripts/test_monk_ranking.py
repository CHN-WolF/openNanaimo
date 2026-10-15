"""Isolated x86 monk popup/cache checks; not original-client acceptance."""
import itertools,struct,unittest
import unicorn as uc
from unicorn import x86_const as x
import monk_dialogue_compat as r

class MonkRankingChecks(unittest.TestCase):
    def machine(self,episode=24,hd=0,dungeon=0,stage=0):
        m=uc.Uc(uc.UC_ARCH_X86,uc.UC_MODE_32)
        m.mem_map(0x400000,0xA00000);m.mem_map(0x2000000,0x60000)
        m.mem_write(r.EXT_BASE,r.gameplay_payload())
        self.manager,self.cache,self.window,self.frame,self.stack,self.end=0x2000000,0x2010000,0x2020000,0x2030000,0x2040000,0x2050000
        def put(a,v):m.mem_write(a,struct.pack('<I',v))
        put(r.PROFILE,self.manager);put(self.manager+0x26A4,self.cache)
        for off,val in [(0x1E530,hd),(0x1E534,episode),(0x1E538,dungeon),(0x1E540,stage)]:put(self.manager+off,val)
        m.mem_write(0x419BBE,b'\xB8'+struct.pack('<I',self.manager)+b'\xC3')
        m.reg_write(x.UC_X86_REG_ECX,self.cache);m.reg_write(x.UC_X86_REG_EBP,self.frame)
        m.reg_write(x.UC_X86_REG_ESP,self.stack);put(self.stack,self.end)
        self.put=put
        return m

    def test_get_set_current_difficulty_and_no_downgrade(self):
        for challenge,difficulty,current,new in itertools.product(range(4),range(3),range(4),range(4)):
            m=self.machine(24+challenge);data=bytearray([0xA5]*87)
            at=0x44+challenge;data[at]=(data[at]&~(3<<(2*difficulty)))|(current<<(2*difficulty))
            m.mem_write(self.cache,bytes(data));args=[0,24+challenge,difficulty,0]
            for i,val in enumerate(args):self.put(self.stack+4+4*i,val)
            m.emu_start(r.RANK_GET,self.end,count=200)
            self.assertEqual(m.reg_read(x.UC_X86_REG_EAX),current)
            self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack+20)
            m.reg_write(x.UC_X86_REG_ECX,self.cache);m.reg_write(x.UC_X86_REG_ESP,self.stack)
            self.put(self.stack+20,new)
            for reg,val in [(x.UC_X86_REG_EBX,0x1111),(x.UC_X86_REG_ESI,0x2222),(x.UC_X86_REG_EDI,0x3333)]:m.reg_write(reg,val)
            m.emu_start(r.RANK_SET,self.end,count=250)
            expected=data[:];expected[at]=(data[at]&~(3<<(2*difficulty)))|(max(current,new)<<(2*difficulty))
            self.assertEqual(m.mem_read(self.cache,len(data)),expected)
            self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack+24)
            self.assertEqual([m.reg_read(a) for a in [x.UC_X86_REG_EBX,x.UC_X86_REG_ESI,x.UC_X86_REG_EDI]],[0x1111,0x2222,0x3333])

    def test_popup_initializes_exact_twelve_badges_and_four_names(self):
        m=self.machine();ratings=bytes([0xE4,0x1B,0x39,0x06]);m.mem_write(self.cache+0x44,ratings)
        self.put(self.frame-0x60,self.window);self.put(self.frame-0x10,77)
        calls=[];effects=[]
        for a,raw in [(0xB479CC,b'\xB8'+struct.pack('<I',0x2025000)+b'\xC3'),
            (0x41BE00,b'\x8B\xC1\xC3'),(0x404232,b'\xC2\x14\x00'),
            (0x41E67D,b'\xC2\x0C\x00'),(0x414A6F,b'\xC3'),(0x40DA1C,b'\xC2\x34\x00')]:m.mem_write(a,raw)
        def hook(mm,a,size,data):
            sp=mm.reg_read(x.UC_X86_REG_ESP)
            if a==0x41E67D:
                args=struct.unpack('<3I',mm.mem_read(sp+4,12));calls.append(args)
                value=0x1000+len(calls);effects.append(value);mm.reg_write(x.UC_X86_REG_EAX,value)
            if a==0x40DA1C:calls.append(('text',struct.unpack('<13I',mm.mem_read(sp+4,52))))
            if a in (0x8C2DDE,0x8C3182):mm.emu_stop()
        m.hook_add(uc.UC_HOOK_CODE,hook);m.emu_start(r.RANK_INIT,0,count=2000)
        expected=[((ratings[c]>>(2*d))&3,238+d*140,268+c*38) for c in range(4) for d in range(3)]
        self.assertEqual(calls,expected)
        self.assertEqual(list(struct.unpack('<12I',m.mem_read(self.window+44,48))),effects)
        self.assertEqual(m.mem_read(self.window+44+48,36*4),b'\0'*(36*4))
        self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack)
        self.assertEqual(struct.unpack('<I',m.mem_read(self.frame-0x10,4))[0],77)
        self.put(self.frame-0x10,self.window);m.reg_write(x.UC_X86_REG_ESP,self.stack)
        m.emu_start(r.RANK_DRAW,0,count=1000)
        texts=[row[1] for row in calls if row[0]=='text']
        self.assertEqual([(t[0],t[1],t[2]) for t in texts],[(128,268+i*38,r.TITLE_STRINGS+i*32) for i in range(4)])
        self.assertTrue(all(t[3:]==(0xFFFFFF,0,0,1,0,0,0,0,0,0) for t in texts))
        self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack)

    def test_popup_all_four_identities_and_invalid_cache_updates(self):
        for challenge in range(4):
            m=self.machine(24+challenge);m.mem_write(self.cache+0x44,bytes([0x39]*4))
            for difficulty in [3,255]:
                for entry,count in [(r.RANK_GET,4),(r.RANK_SET,5)]:
                    original=bytes(m.mem_read(self.cache,87));m.reg_write(x.UC_X86_REG_ECX,self.cache)
                    m.reg_write(x.UC_X86_REG_ESP,self.stack);self.put(self.stack,self.end)
                    for i,val in enumerate([0,24+challenge,difficulty,0,3][:count]):self.put(self.stack+4+4*i,val)
                    m.emu_start(entry,self.end,count=250)
                    self.assertEqual(bytes(m.mem_read(self.cache,87)),original)
            m.reg_write(x.UC_X86_REG_ECX,self.cache);m.reg_write(x.UC_X86_REG_ESP,self.stack)
            for i,val in enumerate([0,24+challenge,0,0,255]):self.put(self.stack+4+4*i,val)
            original=bytes(m.mem_read(self.cache,87));m.emu_start(r.RANK_SET,self.end,count=250)
            self.assertEqual(bytes(m.mem_read(self.cache,87)),original)

    def test_previous_released_payload_migrates_without_losing_existing_hooks(self):
        import prepare_client_compatibility as compat
        from test_prepare_client_compatibility import synthetic_pe
        raw,_=synthetic_pe();raw=bytearray(raw)
        pe=struct.unpack_from('<I',raw,60)[0];count=struct.unpack_from('<H',raw,pe+6)[0]
        table=pe+24+struct.unpack_from('<H',raw,pe+20)[0]
        for rva,span in [(0x120000,0x10000),(0x330000,0x10000),(0x2FA000,0x18000),(0x4C0000,0x10000)]:
            offset=len(raw);raw.extend(b'\0'*span)
            struct.pack_into('<4I',raw,table+count*40+8,span,rva,span,offset);count+=1
        struct.pack_into('<H',raw,pe+6,count)
        for _,va,old,new in r.sites():
            at=compat._va_offset(raw,va,len(old));raw[at:at+len(old)]=old
        at=compat._va_offset(raw,r.EXT_BASE,r.EXT_SPAN)
        raw[at:at+r.EXT_SPAN]=r.gameplay_payload(legacy_ranking=True)
        patched,_=compat.patch_monk_dialogue(bytes(raw))
        self.assertEqual(compat.patch_monk_dialogue(patched)[0],patched)
        for _,va,_,new in r.sites():
            at=compat._va_offset(patched,va,len(new));self.assertEqual(patched[at:at+len(new)],new)

    def test_outside_exact_tuple_falls_back_without_mutating_cache(self):
        for hd,ep,dg,st in [(1,24,0,0),(0,23,0,0),(0,28,0,0),(0,100,0,0),(0,24,1,0),(0,24,0,1)]:
            for entry,native in [(r.RANK_GET,0x40EDC2),(r.RANK_SET,0x4103D9),(r.RANK_INIT,0x8C25B3),(r.RANK_DRAW,0x8C30F2)]:
                m=self.machine(ep,hd,dg,st);original=bytes([0xA5]*87);m.mem_write(self.cache,original)
                m.mem_write(0x411379,b'\xB8\x03\x00\x00\x00\xC3');hit=[]
                def stop(mm,a,size,data):
                    if a==native:hit.append(a);mm.emu_stop()
                m.hook_add(uc.UC_HOOK_CODE,stop);m.emu_start(entry,0,count=250)
                self.assertEqual(hit,[native]);self.assertEqual(bytes(m.mem_read(self.cache,87)),original)
                self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack)

if __name__=='__main__':unittest.main()
