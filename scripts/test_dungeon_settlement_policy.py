import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "release/components/dungeon_progression/settlement_result_policy.inc"
TCC_CANDIDATES = [ROOT / "tools/tcc/tcc.exe"]

class DungeonSettlementPolicyTests(unittest.TestCase):
    def test_death_rating_and_clear_rating_are_distinct(self):
        tcc = next((path for path in TCC_CANDIDATES if path.is_file()), None)
        self.assertIsNotNone(tcc)
        with tempfile.TemporaryDirectory(prefix="settlement-policy-") as temp:
            source = Path(temp) / "check.c"
            exe = Path(temp) / "check.exe"
            source.write_text(
                '#include <assert.h>\n#include "' + POLICY.as_posix() + '"\n'
                'int main(void){assert(dungeon_settlement_visible_rating(0u)==0u);'
                'assert(dungeon_settlement_visible_rating(1u)==5u);return 0;}\n',
                encoding="utf-8")
            subprocess.run([str(tcc), str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_native_cf88_uses_failure_rating_when_progress_is_disallowed(self):
        text = (ROOT / "release/components/protocol_extensions/protocol_overrides.inc").read_text("utf-8")
        self.assertIn('teamplay_settlement_member_rating(idx==g_multi_current||idx<0,allow_progress,profile->hp_current,score,idx)', text)
        self.assertIn('(local?allow_progress:(hp>0u))?combat_economy_rating_for_member(score,1u,multiplayer_shared_boss_context(),idx):dungeon_settlement_visible_rating(0u)', text)
        self.assertNotIn('p[off+0x0B]=5;', text)
        policy = POLICY.read_text('utf-8')
        self.assertIn('dungeon_settlement_visible_rating(unsigned allow_progress)', policy)
        self.assertNotIn('dungeon_settlement_visible_rating(unsigned score', policy)

    def test_death_retry_resource_policy_matches_town_return(self):
        with tempfile.TemporaryDirectory(prefix="death-retry-policy-") as temp:
            source = Path(temp) / "check.c"
            exe = Path(temp) / "check.exe"
            source.write_text(
                '#include <assert.h>\n#include "' + POLICY.as_posix() + '"\n'
                'int main(void){unsigned hp,mp;for(hp=0;hp<=65535u;hp++)'
                '{unsigned expected=hp/6u;assert(dungeon_death_return_hp(hp)==(expected?expected:1u));}'
                'for(mp=0;mp<=65535u;mp++)assert(dungeon_death_return_mp(mp,500u)==(mp<500u?mp:500u));'
                'assert(dungeon_death_return_mp(0u,0u)==0u);return 0;}\n', encoding="utf-8")
            subprocess.run([str(TCC_CANDIDATES[0]), str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_dead_party_member_uses_same_resource_policy(self):
        text = (ROOT / "release/components/game_session/gs_runtime.inc").read_text("utf-8")
        branch = text.split("if(teamplay_continuation_take_current(&continuation)){", 1)[1].split(
            "injury_armed=0;injury_dead=0;", 1)[0]
        self.assertIn("combat_hp=dungeon_death_return_hp(g_profile_hp_max)", branch)
        self.assertIn("dungeon_death_return_mp(g_profile_mp_current,g_profile_mp_max)", branch)
        self.assertNotIn("combat_hp=pet_crafting_pet_effective_hp_max()", branch)

if __name__ == "__main__":
    unittest.main()
