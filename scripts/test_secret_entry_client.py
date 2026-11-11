"""Isolated original-x86 entry regressions, not original-client acceptance.

Supply --client-exe to execute the exact C37B handler with modeled callees.
The server-side companion is --secret-entry-self-test.
"""
import argparse
import struct
import unittest
from pathlib import Path

from verify_client_baseline import read_va

try:
    import unicorn as uc
    from unicorn import x86_const as x86
except ImportError:
    uc = None

CLIENT_EXE = None
HANDLER = bytes.fromhex(
    '558bec51894dfc8b45088b480c518b5008528b0dd469d800e8b809f4ff'
    '8b45088b4814518b5010528b0dd469d800e81fb4f4ff6a44e8f834f3ff'
    '8bc8e88581f4ff85c0740b8b0d78ced800e8906c60008be55dc20400')


@unittest.skipIf(uc is None, 'Unicorn required for isolated x86 checks')
class SecretEntryWalletQueueTests(unittest.TestCase):
    def test_exact_native_wallet_consumer_needs_window(self):
        if CLIENT_EXE is None:
            self.skipTest('supply --client-exe for original-x86 execution')
        client = CLIENT_EXE.read_bytes()
        self.assertEqual(read_va(client, 0x4D3A50, len(HANDLER)), HANDLER)
        for window in (False, True):
            with self.subTest(balance_window_68=window):
                machine = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
                for address, size in ((0x400000, 0xA00000), (0x2000000, 0x10000)):
                    machine.mem_map(address, size)
                stack, packet, stop = 0x2008000, 0x2001000, 0x200F000
                machine.mem_write(0x4D3A50, HANDLER)
                machine.mem_write(packet, struct.pack('<4H2Q', 0, 0, 24, 0xC37B, 142737, 30))
                machine.mem_write(stack, struct.pack('<2I', stop, packet))
                machine.reg_write(x86.UC_X86_REG_ESP, stack)
                calls, balances = [], []

                def hook(vm, address, size, _):
                    if address not in (0x414425, 0x41EEA2, 0x406F82, 0x41BC16, 0xADA730):
                        return
                    esp = vm.reg_read(x86.UC_X86_REG_ESP)
                    ret = struct.unpack('<I', vm.mem_read(esp, 4))[0]
                    if address in (0x414425, 0x41EEA2):
                        balances.append(struct.unpack('<Q', vm.mem_read(esp + 4, 8))[0])
                        cleanup, result = 8, 0
                    elif address == 0x406F82:
                        self.assertEqual(struct.unpack('<I', vm.mem_read(esp + 4, 4))[0], 68)
                        cleanup, result = 4, 0x2002000
                    elif address == 0x41BC16:
                        cleanup, result = 0, int(window)
                    else:
                        calls.append('release_packet')
                        cleanup, result = 0, 0
                    vm.reg_write(x86.UC_X86_REG_EAX, result)
                    vm.reg_write(x86.UC_X86_REG_ESP, esp + 4 + cleanup)
                    vm.reg_write(x86.UC_X86_REG_EIP, ret)

                machine.hook_add(uc.UC_HOOK_CODE, hook)
                machine.emu_start(0x4D3A50, stop, count=100)
                self.assertEqual(machine.reg_read(x86.UC_X86_REG_EIP), stop)
                self.assertEqual(balances, [142737, 30])
                self.assertEqual(calls, ['release_packet'] if window else [])
                self.assertEqual(machine.reg_read(x86.UC_X86_REG_ESP), stack + 8)

    def test_paid_allowance_open_byte_precedes_native_expulsion_gate(self):
        if CLIENT_EXE is None:
            self.skipTest('supply --client-exe for original-x86 execution')
        client = CLIENT_EXE.read_bytes()
        self.assertEqual(read_va(client, 0x4D529C, 4), bytes.fromhex('0fb6480b'))
        self.assertEqual(read_va(client, 0x4D52B6, 4), bytes.fromhex('0fb6420b'))
        self.assertEqual(read_va(client, 0x4D795D, 6), bytes.fromhex('8988b0260000'))
        self.assertEqual(read_va(client, 0x54D50A, 6), bytes.fromhex('8b80b0260000'))
        for open_byte in (0, 1, 255):
            for effect in (0, 10069101, 10069201):
                with self.subTest(open_byte=open_byte, effect=effect):
                    vm = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
                    vm.mem_map(0x400000, 0xA00000)
                    vm.mem_map(0x2000000, 0x20000)
                    for address, length in ((0x4D5299, 0x33), (0x41C751, 5),
                            (0x4D7950, 0x19), (0x41E5B0, 5), (0xA86010, 0x16),
                            (0x410780, 5), (0x54D500, 0x14), (0x523B5F, 0x37)):
                        vm.mem_write(address, read_va(client, address, length))
                    profile, ui, packet, bp = 0x2010000, 0x2014000, 0x2015000, 0x2009000
                    vm.mem_write(0xD869D4, struct.pack('<I', profile))
                    vm.mem_write(packet, struct.pack('<4HHBBI', 0, 0, 16, 0xC5AB, 11, 0, open_byte, 3000))
                    vm.mem_write(bp + 8, struct.pack('<I', packet))
                    vm.reg_write(x86.UC_X86_REG_EBP, bp)
                    vm.reg_write(x86.UC_X86_REG_ESP, bp - 0x200)
                    boundary = []

                    def hook(machine, address, size, _):
                        if address in (0x523B96, 0x523E3C):
                            boundary.append(address)
                            machine.emu_stop()
                            return
                        if address not in (0x40C1EE, 0x4037C4):
                            return
                        esp = machine.reg_read(x86.UC_X86_REG_ESP)
                        ret, arg = struct.unpack('<II', machine.mem_read(esp, 8))
                        result = ui
                        if address == 0x4037C4:
                            appearance = bytearray(36)
                            struct.pack_into('<I', appearance, 24, effect)
                            machine.mem_write(arg, bytes(appearance))
                            result = arg
                        machine.reg_write(x86.UC_X86_REG_EAX, result)
                        # The UI getter takes no argument: the pushed flag belongs
                        # to the following thiscall setter, not this getter.
                        machine.reg_write(x86.UC_X86_REG_ESP, esp + (8 if address == 0x4037C4 else 4))
                        machine.reg_write(x86.UC_X86_REG_EIP, ret)

                    vm.hook_add(uc.UC_HOOK_CODE, hook)
                    vm.emu_start(0x4D5299, 0x4D52CC, count=200)
                    self.assertEqual(vm.reg_read(x86.UC_X86_REG_EIP), 0x4D52CC)
                    closed = int(open_byte == 0)
                    self.assertEqual(struct.unpack('<I', vm.mem_read(profile + 0x26B0, 4))[0], closed)
                    self.assertEqual(bytes(vm.mem_read(ui + 1, 1)), bytes([closed]))
                    vm.mem_write(bp - 0x10, struct.pack('<I', 100691))
                    vm.emu_start(0x523B5F, 0x523E3D, count=200)
                    expelled = closed and effect // 100 != 100691
                    self.assertEqual(boundary, [0x523B96 if expelled else 0x523E3C])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-exe', type=Path)
    args, rest = parser.parse_known_args()
    CLIENT_EXE = args.client_exe
    unittest.main(argv=[__file__, *rest])
