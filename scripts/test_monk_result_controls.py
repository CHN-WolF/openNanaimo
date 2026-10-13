'''Isolated x86 routing and ABI checks for challenge result controls.'''
import itertools
import struct
import unittest

import unicorn as uc
from unicorn import x86_const as x
import monk_dialogue_compat as r


class ResultControlChecks(unittest.TestCase):
    def test_room_name_and_boss_use_native_positions_without_mutating_records(self):
        sites={name:(va,old,new) for name,va,old,new in r.sites()}
        manager,controller,frame,stack=0x2020000,0x2000000,0x2041000,0x2040000
        regs=(x.UC_X86_REG_EAX,x.UC_X86_REG_EBX,x.UC_X86_REG_ECX,x.UC_X86_REG_EDX,
              x.UC_X86_REG_ESI,x.UC_X86_REG_EDI,x.UC_X86_REG_EBP,x.UC_X86_REG_ESP,
              x.UC_X86_REG_EFLAGS)
        # Native drawing tails from CShootingGameRoom::Draw at 0x70F610.
        cases=(('monk_room_stage_name',0x438,r.TITLE_STRINGS,107,19,0xFFE088,
                '506A136A6BE80D53D0FF8BC8E8B3E2CFFF',
                ('龙飞峡谷','坎泽峡谷','踏坦峡谷','白豹山')),
               ('monk_room_boss_name',0x53C,r.BOSS_STRINGS,362,38,0xFFFFFF,
                '506A26686A010000E83850D0FF8BC8E8DEDFCFFF',
                ('废铁巨人','提诺战机','死亡骑士','迷你比克')))
        tuples=itertools.product((0,1),(0,23,24,25,26,27,28,0xFFFFFFFF),(0,1),(0,1))
        for hd,ep,dg,st in tuples:
            monk=hd==0 and 24<=ep<=27 and dg==0 and st==0
            for name,offset,strings,xpos,ypos,color,tail,names in cases:
                with self.subTest(tuple=(hd,ep,dg,st),site=name):
                    states=[]
                    for patched in (False,True):
                        m=uc.Uc(uc.UC_ARCH_X86,uc.UC_MODE_32)
                        m.mem_map(0x400000,0xA00000);m.mem_map(0x2000000,0x50000)
                        m.mem_write(r.EXT_BASE,r.gameplay_payload())
                        va,old,new=sites[name];resume=va+len(old)
                        m.mem_write(va,new if patched else old)
                        m.mem_write(resume,bytes.fromhex(tail))
                        m.mem_write(0x419BBE,b'\xB8'+struct.pack('<I',manager)+b'\xC3')
                        m.mem_write(0x414A6F,bytes.fromhex('B800002102C3'))
                        m.mem_write(0x40DA1C,bytes.fromhex('C23400'))
                        for off,value in ((0x1E530,hd),(0x1E534,ep),(0x1E538,dg),(0x1E540,st)):
                            m.mem_write(manager+off,struct.pack('<I',value))
                        m.mem_write(frame-0x6C,struct.pack('<I',controller))
                        m.mem_write(controller+offset,b'native\0')
                        # Ten arguments are already pushed at either pointer hook.
                        m.mem_write(stack,struct.pack('<10I',color,0,0,1,0,0,0,0,0,0))
                        initial=[0x12340000+i*0x111 for i in range(6)]+[frame,stack,0x246]
                        for reg,value in zip(regs,initial):m.reg_write(reg,value)
                        before=(bytes(m.mem_read(controller,0x1000)),bytes(m.mem_read(manager,0x1E550)))
                        calls=[]
                        def trace(machine,address,size,user):
                            if address==resume:states.append([machine.reg_read(reg) for reg in regs])
                            if address==0x40DA1C:
                                sp=machine.reg_read(x.UC_X86_REG_ESP)
                                args=struct.unpack('<13I',machine.mem_read(sp+4,52))
                                text=bytes(machine.mem_read(args[2],32)).split(b'\0')[0].decode('gbk')
                                calls.append((args,text))
                        m.hook_add(uc.UC_HOOK_CODE,trace)
                        m.emu_start(va,resume+len(bytes.fromhex(tail)),count=300)
                        ptr=strings+(ep-24)*32 if patched and monk else controller+offset
                        self.assertEqual(calls,[((xpos,ypos,ptr,color,0,0,1,0,0,0,0,0,0),
                                                names[ep-24] if patched and monk else 'native')])
                        self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),stack+40)
                        self.assertEqual(before,(bytes(m.mem_read(controller,0x1000)),bytes(m.mem_read(manager,0x1E550))))
                    self.assertEqual(states[0][1:],states[1][1:])
                    self.assertEqual(states[1][0],strings+(ep-24)*32 if monk else states[0][0])

    def test_create_page_restores_original_call_and_accepts_only_known_old_hook(self):
        site=next(row for row in r.sites() if row[0]=='monk_ready_named_header')
        self.assertEqual(site[1],0x737DAD)
        self.assertEqual(site[2],site[3])
        self.assertEqual(site[3],b'\xE8'+struct.pack('<i',0x411379-0x737DAD-5))

    def test_actual_room_heading_preserves_data_and_native_stack_fallback(self):
        manager,stack,end=0x2020000,0x2040000,0x2041000
        sites={name:(va,old,new) for name,va,old,new in r.sites()}
        va,old,new=sites['monk_room_named_header']
        for hd,ep,dg,st in ((0,24,0,0),(0,25,0,0),(0,26,0,0),(0,27,0,0),
                            (1,24,0,0),(0,23,0,0),(0,28,0,0),(0,24,1,0),(0,24,0,1)):
            monk=hd==0 and 24<=ep<=27 and dg==0 and st==0
            m=uc.Uc(uc.UC_ARCH_X86,uc.UC_MODE_32)
            m.mem_map(0x400000,0xA00000);m.mem_map(0x2000000,0x50000)
            m.mem_write(r.EXT_BASE,r.gameplay_payload());m.mem_write(va,new)
            m.mem_write(0x419BBE,b'\xB8'+struct.pack('<I',manager)+b'\xC3')
            m.mem_write(0x414A6F,b'\xB8'+struct.pack('<I',0x2010000)+b'\xC3')
            m.mem_write(0x40DA1C,bytes.fromhex('C23400'))
            for offset,value in ((0x1E530,hd),(0x1E534,ep),(0x1E538,dg),(0x1E540,st)):
                m.mem_write(manager+offset,struct.pack('<I',value))
            initial=bytes(m.mem_read(manager,0x1E550));calls=[];destinations=[]
            def trace(machine,address,size,user):
                if address==0x40DA1C:
                    sp=machine.reg_read(x.UC_X86_REG_ESP)
                    args=struct.unpack('<13I',machine.mem_read(sp+4,52))
                    self.assertEqual(machine.reg_read(x.UC_X86_REG_ECX),0x2010000)
                    calls.append(args)
                if address in (0x70FA0B,0x70F76F):
                    destinations.append(address);machine.emu_stop()
            m.hook_add(uc.UC_HOOK_CODE,trace)
            for reg in (x.UC_X86_REG_EAX,x.UC_X86_REG_EBX,x.UC_X86_REG_ECX,x.UC_X86_REG_EDX,
                        x.UC_X86_REG_ESI,x.UC_X86_REG_EDI,x.UC_X86_REG_EBP):
                m.reg_write(reg,0x12345678)
            m.reg_write(x.UC_X86_REG_ESP,stack);m.reg_write(x.UC_X86_REG_EFLAGS,0x246)
            m.emu_start(va,end,count=300)
            self.assertEqual(destinations,[0x70FA0B if monk else 0x70F76F])
            self.assertEqual(m.reg_read(x.UC_X86_REG_ESP),stack if monk else stack-12)
            self.assertEqual(m.reg_read(x.UC_X86_REG_EFLAGS),0x246)
            self.assertEqual(bytes(m.mem_read(manager,0x1E550)),initial)
            self.assertEqual(len(calls),2 if monk else 0)
            if monk:
                self.assertEqual(calls[0],(380,11,r.ROOM_NUMBER,0xFFE088,0,0,1,0,0,0,0,0,0))
                self.assertEqual(calls[1],(458,11,r.ROOM_NUMBER,0x0FFFB3,0,0,1,0,0,0,0,0,0))
                self.assertEqual(bytes(m.mem_read(r.ROOM_NUMBER,3)),b'01\0')
            else:
                self.assertEqual(bytes(m.mem_read(stack-12,12)),b'\0'*12)

    def test_exact_tuple_only_and_original_flags_registers_stack(self):
        sites={name:(va,old,new) for name,va,old,new in r.sites()}
        manager,controller,frame,stack=0x2020000,0x2000000,0x2041000,0x2040000
        registers=(x.UC_X86_REG_EAX,x.UC_X86_REG_EBX,x.UC_X86_REG_ECX,x.UC_X86_REG_EDX,
                   x.UC_X86_REG_ESI,x.UC_X86_REG_EDI,x.UC_X86_REG_EBP,x.UC_X86_REG_ESP)
        for hd,ep,dg,st in itertools.product((0,1),(0,23,24,25,26,27,28,0xFFFFFFFF),(0,1),(0,1)):
            monk=hd==0 and 24<=ep<=27 and dg==0 and st==0
            for name,native,retry,changed in (
                ('monk_result_retry_only_input',0x762F7B,0x763C69,2),
                ('monk_result_retry_only_draw',0x765240,0x7653A7,0)):
                for flag in (0,1):
                    with self.subTest(tuple=(hd,ep,dg,st),site=name,flag=flag):
                        m=uc.Uc(uc.UC_ARCH_X86,uc.UC_MODE_32)
                        m.mem_map(0x400000,0xA00000);m.mem_map(0x2000000,0x50000)
                        m.mem_write(r.EXT_BASE,r.gameplay_payload())
                        va,old,new=sites[name];m.mem_write(va,new)
                        m.mem_write(0x419BBE,b'\xB8'+struct.pack('<I',manager)+b'\xC3')
                        for offset,value in ((0x1E530,hd),(0x1E534,ep),(0x1E538,dg),(0x1E540,st)):
                            m.mem_write(manager+offset,struct.pack('<I',value))
                        for at,value in ((frame-0x14,controller),(frame-0x94,controller),(controller+0x20,flag)):
                            m.mem_write(at,struct.pack('<I',value))
                        initial=[0x12340000+i*0x111 for i in range(8)];initial[-2:]=[frame,stack]
                        for register,value in zip(registers,initial):m.reg_write(register,value)
                        m.reg_write(x.UC_X86_REG_EFLAGS,0x246)
                        destinations=[]
                        def stop(machine,address,size,user):
                            if address in (native,retry):
                                destinations.append(address);machine.emu_stop()
                        m.hook_add(uc.UC_HOOK_CODE,stop);m.emu_start(va,0,count=200)
                        self.assertEqual(destinations,[retry if monk else native])
                        expected=initial[:]
                        if not monk:expected[changed]=controller
                        self.assertEqual([m.reg_read(reg) for reg in registers],expected)
                        flags=m.reg_read(x.UC_X86_REG_EFLAGS)
                        self.assertEqual(flags,0x246 if monk or changed==0 or flag==0 else 0x202)

    def test_native_availability_retry_exit_and_settlement_pump_are_not_replaced(self):
        changed=[(va,va+len(old)) for _,va,old,new in r.sites() if old!=new]
        for protected in (0x762F09,0x762F57,0x762F6A,0x763D1F,0x76521A,0x765230,0x7653E5):
            if protected==0x762F09:
                target=next(new for _,va,_,new in r.sites() if va==protected)
                self.assertEqual(target,bytes.fromhex('8B55EC837A3C01'))
            else:
                self.assertFalse(any(start<=protected<end for start,end in changed),hex(protected))


if __name__=='__main__':unittest.main()
