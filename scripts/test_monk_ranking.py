"""Isolated x86 monk popup/cache checks; not original-client acceptance."""
import hashlib,itertools,struct,unittest
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

    def test_get_set_single_slot_and_no_downgrade(self):
        for challenge,current,new in itertools.product(range(4),range(4),range(4)):
            m=self.machine(24+challenge);data=bytearray([0xA5]*87)
            at=0x44+challenge;data[at]=current
            m.mem_write(self.cache,bytes(data));args=[0,24+challenge,0,0]
            for i,val in enumerate(args):self.put(self.stack+4+4*i,val)
            m.emu_start(r.RANK_GET,self.end,count=200)
            self.assertEqual(m.reg_read(x.UC_X86_REG_EAX),current)
            self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack+20)
            m.reg_write(x.UC_X86_REG_ECX,self.cache);m.reg_write(x.UC_X86_REG_ESP,self.stack)
            self.put(self.stack+20,new)
            for reg,val in [(x.UC_X86_REG_EBX,0x1111),(x.UC_X86_REG_ESI,0x2222),(x.UC_X86_REG_EDI,0x3333)]:m.reg_write(reg,val)
            m.emu_start(r.RANK_SET,self.end,count=250)
            expected=data[:];expected[at]=max(current,new)
            self.assertEqual(m.mem_read(self.cache,len(data)),expected)
            self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack+24)
            self.assertEqual([m.reg_read(a) for a in [x.UC_X86_REG_EBX,x.UC_X86_REG_ESI,x.UC_X86_REG_EDI]],[0x1111,0x2222,0x3333])

    def test_popup_initializes_exact_four_badges_and_numbers(self):
        for episode in range(24,28):
            with self.subTest(episode=episode):
                self.check_popup(episode)

    def test_each_digit_allocation_failure_still_draws_remaining_widgets(self):
        for digit in range(8):
            with self.subTest(digit=digit):
                self.check_popup(24, digit)

    def check_popup(self, episode, failed_digit=None):
        m=self.machine(episode);ratings=bytes([0,1,2,3]);m.mem_write(self.cache+0x44,ratings)
        self.put(self.frame-0x60,self.window);self.put(self.frame-0x10,77)
        calls=[];effects=[];backgrounds=[];digits=[];frames=[];draws=[];moves=[];rects=[]
        vtable=0x202E000
        self.put(vtable+0x14,0x400800);self.put(vtable+0x1C,0x400900)
        for index in range(2):
            button=0x202D000+index*0x100;sprite=button+0x40
            self.put(self.window+0x20+index*4,button);self.put(button,sprite);self.put(sprite,vtable)
        for a,raw in [(0xB479CC,b'\xB8'+struct.pack('<I',0x2025000)+b'\xC3'),
            (0x41BE00,b'\x8B\xC1\xC3'),(0x404232,b'\xC2\x14\x00'),
            (0x41E67D,b'\xC2\x0C\x00'),(0x41206C,b'\xC3'),(0x40DA1C,b'\xC2\x34\x00'),
            (0x41CC33,b'\xC3'),(0x41E0E7,b'\xC2\x20\x00'),
            (0x40A62D,b'\x8B\xC1\xC2\x10\x00'),(0x402770,b'\xC2\x04\x00'),
            (0x400800,b'\xC3'),(0x400900,b'\xC2\x04\x00'),(0x410DFC,b'\xC2\x08\x00')]:m.mem_write(a,raw)
        def hook(mm,a,size,data):
            sp=mm.reg_read(x.UC_X86_REG_ESP)
            if a==0xB479CC:
                size=struct.unpack('<I',mm.mem_read(sp+4,4))[0]
                if size==0x16C and mm.reg_read(x.UC_X86_REG_EBX)==failed_digit:
                    # Skip the allocator stub, retaining its ordinary return.
                    mm.reg_write(x.UC_X86_REG_EAX,0)
                    mm.reg_write(x.UC_X86_REG_EIP,a+5)
            if a==0x41E67D:
                args=struct.unpack('<3I',mm.mem_read(sp+4,12));calls.append(args)
                value=0x1000+len(calls);effects.append(value);mm.reg_write(x.UC_X86_REG_EAX,value)
            if a==0x40DA1C:calls.append(('text',struct.unpack('<13I',mm.mem_read(sp+4,52))))
            if a==0x404232:backgrounds.append(struct.unpack('<5I',mm.mem_read(sp+4,20)))
            if a==0x41E0E7:
                self.assertEqual(struct.unpack('<8I',mm.mem_read(sp+4,32)),(13,0xCA5AE4,0,3,0,0,0,0))
            if a==0x40A62D:
                obj=0x2026000+len(digits)*0x200
                mm.reg_write(x.UC_X86_REG_ECX,obj);self.put(obj,vtable)
                digits.append(struct.unpack('<IIff',mm.mem_read(sp+4,16)))
            if a==0x402770:frames.append(struct.unpack('<I',mm.mem_read(sp+4,4))[0])
            if a==0x400800:draws.append(mm.reg_read(x.UC_X86_REG_ECX))
            if a==0x410DFC:moves.append(struct.unpack('<ff',mm.mem_read(sp+4,8)))
            if a==0x400900:rects.append(struct.unpack('<I',mm.mem_read(sp+4,4))[0])
            if a in (0x8C2DDE,0x8C3182):mm.emu_stop()
        m.hook_add(uc.UC_HOOK_CODE,hook);m.emu_start(r.RANK_INIT,0,count=2000)
        expected=[(ratings[c],431,268+c*38) for c in range(4)]
        self.assertEqual(calls,expected)
        self.assertEqual(backgrounds,[(r.RANK_BACKGROUND,0,400,300,0)])
        path=b'interface\\openNanaimo_monk_rank.eff\0'
        self.assertEqual(bytes(m.mem_read(r.RANK_BACKGROUND,len(path))),path)
        self.assertEqual(list(struct.unpack('<4I',m.mem_read(self.window+44,16))),effects)
        self.assertEqual(m.mem_read(self.window+44+16,44*4),b'\0'*(44*4))
        self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack)
        self.assertEqual(struct.unpack('<I',m.mem_read(self.frame-0x10,4))[0],77)
        visible=[i for i in range(8) if i!=failed_digit]
        self.assertEqual([(d[1],d[2],d[3]) for d in digits],[(0,253.+14*(i%2),273.+38*(i//2)) for i in visible])
        self.assertEqual(frames,[0 if i%2==0 else i//2+1 for i in visible])
        if failed_digit is not None:
            self.assertEqual(bytes(m.mem_read(self.window+0xEC+4*failed_digit,4)),bytes(4))
        self.assertEqual(moves,[(557.,428.),(599.,141.)])
        self.assertEqual(rects,[0x202D008,0x202D108])
        title=r.localization()['game_strings'][str(2504+episode-24)].encode('gbk')+b'\0'
        self.assertEqual(bytes(m.mem_read(self.window+0x110,len(title))),title)
        self.put(self.frame-0x10,self.window);m.reg_write(x.UC_X86_REG_ESP,self.stack)
        m.emu_start(r.RANK_DRAW,0,count=1000)
        texts=[row[1] for row in calls if row[0]=='text']
        self.assertEqual([(t[0],t[1],t[2]) for t in texts],[(357,181,self.window+0x110)])
        self.assertEqual(draws,[0x2026000+i*0x200 for i in range(len(visible))])
        self.assertTrue(all(t[3:]==(0xFFFFFF,0,0,1,0,2,0,0,0,0) for t in texts))
        self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack)

    def test_popup_all_four_identities_and_invalid_cache_updates(self):
        for challenge in range(4):
            m=self.machine(24+challenge);m.mem_write(self.cache+0x44,bytes([0x39]*4))
            for difficulty in [1,2,3,255]:
                for entry,count in [(r.RANK_GET,4),(r.RANK_SET,5)]:
                    native=0x40EDC2 if count==4 else 0x4103D9
                    m.mem_write(native,b'\x33\xC0\xC2'+struct.pack('<H',count*4))
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
        self.assertEqual(hashlib.sha256(r.gameplay_payload(legacy_rank_matrix=True)).hexdigest(),
            '320652b2fe4f8440d9748052afde6139c33a49c9a12aa1f11b8fc3a56689f45f')
        self.assertEqual(hashlib.sha256(r.gameplay_payload(legacy_rank_layout=True)).hexdigest(),
            '5f98e5f6ba79a3ea518970d0c7c301a2167402512da52a04055f73de56d4cf05')
        for old in [r.gameplay_payload(legacy_ranking=True),r.gameplay_payload(legacy_rank_matrix=True),
                    r.gameplay_payload(legacy_rank_layout=True)]:
            at=compat._va_offset(raw,r.EXT_BASE,r.EXT_SPAN);raw[at:at+r.EXT_SPAN]=old
            patched,_=compat.patch_monk_dialogue(bytes(raw))
            self.assertEqual(compat.patch_monk_dialogue(patched)[0],patched)
            for _,va,_,new in r.sites():
                at=compat._va_offset(patched,va,len(new));self.assertEqual(patched[at:at+len(new)],new)
            raw=bytearray(patched)
        at=compat._va_offset(raw,r.RANK_INIT,1);raw[at]^=1
        with self.assertRaises(ValueError):compat.patch_monk_dialogue(bytes(raw))

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

    def test_mismatched_arguments_and_nonzero_difficulty_use_native_path(self):
        for args in [(1,24,0,0),(0,25,0,0),(0,24,1,0),(0,24,2,0),(0,24,0,1)]:
            for entry,native in [(r.RANK_GET,0x40EDC2),(r.RANK_SET,0x4103D9)]:
                m=self.machine();hit=[]
                for i,value in enumerate((*args,3)):self.put(self.stack+4+4*i,value)
                def stop(mm,a,size,data):
                    if a==native:hit.append(a);mm.emu_stop()
                m.hook_add(uc.UC_HOOK_CODE,stop);m.emu_start(entry,0,count=250)
                self.assertEqual(hit,[native]);self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack)

    def test_background_allocation_failure_leaves_lifecycle_safe(self):
        m=self.machine();self.put(self.frame-0x60,self.window)
        m.mem_write(0xB479CC,b'\x33\xC0\xC3');m.mem_write(0x41E67D,b'\x33\xC0\xC2\x0C\x00')
        hit=[]
        def stop(mm,a,size,data):
            if a in (0x41BE00,0x404232):self.fail('null background was dereferenced')
            if a==0x8C2DDE:hit.append(a);mm.emu_stop()
        m.hook_add(uc.UC_HOOK_CODE,stop);m.emu_start(r.RANK_INIT,0,count=1000)
        self.assertEqual(hit,[0x8C2DDE]);self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack)
        self.assertEqual(bytes(m.mem_read(self.window+40,4+48*4)),bytes(4+48*4))

    def test_native_destructor_releases_badges_and_digit_slots_once(self):
        import os
        from pathlib import Path
        from prepare_client_compatibility import _va_offset
        client=Path(os.environ.get('NANAIMO_CLIENT',Path(__file__).resolve().parents[2]))/'game.exe'
        if not client.is_file():self.skipTest('native CN executable is unavailable')
        raw=client.read_bytes();at=_va_offset(raw,0x8C2170,0x159)
        m=self.machine();m.mem_write(0x8C2170,raw[at:at+0x159])
        vtable=0x202E000;deleter=0x400800;self.put(vtable,deleter)
        m.mem_write(deleter,b'\xC2\x04\x00');m.mem_write(0x41AFD7,b'\xC2\x04\x00')
        offsets=[0x20,0x24,0x28]+[0x2C+i*4 for i in range(4)]+[0xEC+i*4 for i in range(8)]
        pointers=[0x2026000+i*0x200 for i in range(len(offsets))]
        for offset,pointer in zip(offsets,pointers):
            self.put(self.window+offset,pointer);self.put(pointer,vtable)
        seen=[]
        def hook(mm,a,size,data):
            if a in (deleter,0x41AFD7):
                seen.append(mm.reg_read(x.UC_X86_REG_ECX))
                self.assertEqual(struct.unpack('<I',mm.mem_read(mm.reg_read(x.UC_X86_REG_ESP)+4,4))[0],1)
        m.hook_add(uc.UC_HOOK_CODE,hook);m.reg_write(x.UC_X86_REG_ECX,self.window)
        m.emu_start(0x8C2170,self.end,count=2500)
        self.assertCountEqual(seen,pointers)
        self.assertEqual(bytes(m.mem_read(self.window+0x20,0x10C-0x20)),bytes(0x10C-0x20))
        self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),self.stack+4)


class MonkRankingResources(unittest.TestCase):
    def test_right_and_bottom_edges_have_no_matrix_remnants(self):
        import os
        from pathlib import Path
        import monk_ranking_resources as assets
        from gui_launcher.generate_furniture_previews import decode_im3
        client=Path(os.environ.get('NANAIMO_CLIENT',Path(__file__).resolve().parents[2]))
        if not (client/assets.SOURCE_IMAGE).is_file():self.skipTest('native CN popup source is unavailable')
        raw=(client/assets.SOURCE_IMAGE).read_bytes()
        original=decode_im3(raw)
        image=decode_im3(assets.single_slot_bitmap(raw))
        # The old crop retained the last header glyph and four half sockets.
        for y in range(99,278):
            with self.subTest(edge='right',y=y):
                self.assertEqual(set(image.crop((416,y,427,y+1)).getdata()),
                                 {original.getpixel((147,y))})
        # Include the final body scanline, but keep the genuine lower frame.
        for y in range(278,284):
            with self.subTest(edge='bottom',y=y):
                for left,right in ((112,255),(288,416)):
                    self.assertEqual(set(image.crop((left,y,right,y+1)).getdata()),
                                     {original.getpixel((147,y))})
        self.assertEqual(image.crop((112,283,416,284)).getextrema(),
                         ((181,181),(181,181),(181,181),(255,255)))

    def test_unknown_background_and_effect_are_rejected(self):
        import monk_ranking_resources as assets
        import tempfile
        from pathlib import Path
        with self.assertRaisesRegex(ValueError,'unknown monk ranking background'):
            assets.single_slot_bitmap(bytes(44))
        with tempfile.TemporaryDirectory() as root:
            effect=Path(root)/assets.SOURCE_EFFECT;effect.parent.mkdir(parents=True)
            effect.write_bytes(b'unknown')
            with self.assertRaisesRegex(ValueError,'unknown monk ranking effect'):
                assets.ranking_files(root)

    def test_native_frame_and_epi_boxes_survive_without_matrix(self):
        import os
        from pathlib import Path
        import monk_ranking_resources as assets
        from gui_launcher.generate_furniture_previews import decode_im3
        client=Path(os.environ.get('NANAIMO_CLIENT',Path(__file__).resolve().parents[2]))
        if not (client/assets.SOURCE_IMAGE).is_file():self.skipTest('native CN popup source is unavailable')
        files=assets.ranking_files(client)
        import json
        recipe=json.loads((Path(__file__).resolve().parents[1]/'manifest/monk_dialogue_resources.json').read_text('utf8'))
        rows={row['path']:row for row in recipe['files']}
        for path,raw in files.items():
            self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(rows[path]['size'],rows[path]['sha256']))
        original=decode_im3((client/assets.SOURCE_IMAGE).read_bytes())
        image=decode_im3(files[assets.IMAGE])
        self.assertEqual(image.size,(450,336))
        for box in [(0,0,300,30),(0,30,430,84),(0,84,112,284),(0,284,350,336)]:
            self.assertEqual(image.crop(box).tobytes(),original.crop(box).tobytes())
        for box in [(300,0,450,30),(430,30,450,84),(416,84,450,99),(427,99,450,278),(350,284,450,336)]:
            left,top,right,bottom=box
            self.assertEqual(image.crop(box).tobytes(),original.crop((left+104,top,right+104,bottom)).tobytes())
        for row in range(4):
            y=134+row*38
            self.assertEqual(image.crop((255,y,288,y+35)).tobytes(),original.crop((148,y,181,y+35)).tobytes())
        for y,right in enumerate((426,426,425,425,423,420),278):
            self.assertEqual(image.crop((right,y,450,y+1)).tobytes(),
                             original.crop((right+104,y,554,y+1)).tobytes())
        for y in range(84,134):
            self.assertEqual(len(set(image.crop((112,y,416,y+1)).getdata())),1)
        self.assertAlmostEqual(struct.unpack_from('<f',files[assets.EFFECT],392)[0],450/554)
        model=assets.resources.codec_module().eff2(files[assets.EFFECT])
        self.assertEqual(model['refs'],['nanaimo_cs_pop00.im3',Path(assets.IMAGE).name])

if __name__=='__main__':unittest.main()
