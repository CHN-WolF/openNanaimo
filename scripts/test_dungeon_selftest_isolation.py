"""A new diagnostic connection must not reset or publish into an active battle."""
import struct
import unittest

import test_social_sync_boundaries as social


class DungeonSelfTestIsolationTests(unittest.TestCase):
    def test_live_boss_survives_unrelated_create_and_roster_requests(self):
        for dungeon, child, ordinal in ((0, 0, 7), (2, 1, 0)):
            for wire_difficulty in range(3):
                with self.subTest(dungeon=dungeon, wire_difficulty=wire_difficulty):
                    self.check_intrusion(dungeon, child, ordinal, wire_difficulty)

    def check_intrusion(self, dungeon, child, ordinal, wire_difficulty):
        with social.room(2) as (owner, diagnostic):
            create = bytearray(44)
            create[27] = 2  # UI 3-1 and 3-3, in all three resource slots.
            create[28] = dungeon
            struct.pack_into("<H", create, 30, wire_difficulty)
            owner.sendall(social.frame(0xCF6C, create))
            social.receive(owner, 0xCF6D)
            owner.sendall(social.frame(0xCF70))
            social.flush(owner)
            for opcode, payload in ((0xCFEB, bytes(4)), (0xCFD3, b""),
                                    (0xCFD5, struct.pack("<I", 1)), (0xCF7F, b"")):
                owner.sendall(social.frame(opcode, payload))
                social.flush(owner)

            hit = bytearray(24)
            struct.pack_into("<HH", hit, 4, 317, 0)
            hit[11] = child
            struct.pack_into("<I", hit, 12, ordinal)

            def boss_hp():
                owner.sendall(social.frame(0xD011, hit))
                frames = social.flush(owner)
                answers = [f for f in frames if struct.unpack_from("<H", f, 6)[0] == 0xD012]
                self.assertEqual(len(answers), 1, "one request-driven Boss update")
                return struct.unpack_from("<I", answers[0], 0x28)[0]

            before = boss_hp()
            for repeat in range(2):
                diagnostic.sendall(social.frame(0xCF09, bytes(56)))
                social.flush(diagnostic)
                entry = bytearray(44)
                struct.pack_into("<H", entry, 30, 2)
                for opcode, payload in ((0xCF6C, entry), (0xCF70, b""),
                                        (0xCF77, struct.pack("<HBBBBH", 100, 0, 0, 0, 2, 0)),
                                        (0xCF7F, b"")):
                    diagnostic.sendall(social.frame(opcode, payload))
                    replies = social.flush(diagnostic)
                    self.assertFalse(any(struct.unpack_from("<H", f, 6)[0] in
                                         (0xCF6D, 0xCF71, 0xCF72, 0xCF80) for f in replies))
                    pushed = social.flush(owner)
                    self.assertEqual(pushed, [], "no unsolicited ready-room or actor frames")
                after = boss_hp()
                self.assertLess(after, before, "the original Boss ledger still takes damage")
                before = after
            diagnostic.close()
            self.assertEqual(social.flush(owner), [], "nonmember disconnect does not publish CF74")
            self.assertLess(boss_hp(), before)
            print(f"INTRUSION_PASS ep=2 dg={dungeon} wire_difficulty={wire_difficulty}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
