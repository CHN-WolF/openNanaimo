"""Pure sampler checks; no original-client runtime claim."""
import hashlib
import os
from pathlib import Path
import struct
import unittest
import arena_state_probe as probe


class ArenaStateProbeTests(unittest.TestCase):
    def test_null_singletons_do_not_allocate_or_dereference(self):
        reads = []
        def read(address, count):
            reads.append((address, count)); return bytes(count)
        self.assertEqual([v['address'] for v in probe.decode_snapshot(read).values()], [0]*5)
        self.assertEqual(len(reads), 10)

    def test_offsets_read_bytes_and_dwords_without_mutation(self):
        memory = bytearray(0xE00000)
        def put(address, value): struct.pack_into('<I', memory, address, value)
        for slot, address in [(0xD72CE8,0x10000),(0xD72D20,0x20000),(0xD72FC0,0x30000),
                              (0xD72EB8,0x40000),(0xD72E90,0x50000)]: put(slot,address)
        for flag in (0xD72CE4, 0xD72D1E, 0xD72FBE, 0xD72EB6, 0xD72E8C): memory[flag] = 1
        memory[0x10003] = 1; put(0x10008,4); put(0x110F0,4)
        put(0x3001C,7); put(0x3000C,99); put(0x40024,3); put(0x50008,1234)
        before = bytes(memory)
        result = probe.decode_snapshot(lambda a,n: bytes(memory[a:a+n]))
        self.assertEqual(result['manager']['mode'], 1)
        self.assertEqual(result['manager']['page'], 4)
        self.assertEqual(result['world']['running'], 0)
        self.assertEqual(result['arena']['state'], 7)
        self.assertEqual(result['arena']['update_counter'], 99)
        self.assertEqual(result['ready']['state'], 3)
        self.assertEqual(result['countdown']['tick'], 1234)
        self.assertEqual(memory, before)

    def test_destroyed_singletons_do_not_dereference_leftover_pointer(self):
        def read(address, count):
            if count == 1: return b'\0'
            if address < 0xD00000: self.fail('dereferenced a destroyed object')
            return struct.pack('<I', 0x123400)
        result = probe.decode_snapshot(read)
        self.assertTrue(all(v == {'address': 0x123400, 'initialized': 0} for v in result.values()))

    def test_bad_reads_remain_errors_not_fabricated_frozen_zeroes(self):
        def read(a,n): raise OSError('unreadable')
        self.assertTrue(all(v == {'error':'unreadable'} for v in probe.decode_snapshot(read).values()))

    def test_live_code_signatures_match_user_owned_disk_input(self):
        image = Path(os.environ.get('NANAIMO_AUDIT_CLIENT', str(Path(__file__).resolve().parents[2]/'game.exe')))
        if not image.is_file(): self.skipTest('user-supplied client required')
        data = image.read_bytes()
        for va, expected in probe.SIGNATURES.items():
            at = probe._va_offset(data, va, 32)
            self.assertEqual(hashlib.sha256(data[at:at+32]).hexdigest(), expected)


if __name__ == '__main__': unittest.main()
