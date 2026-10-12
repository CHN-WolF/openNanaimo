"""Isolated native challenge settlement, main-story isolation and death retry tests."""
import importlib.util
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TCC = ROOT / "tools/tcc/tcc.exe"
spec = importlib.util.spec_from_file_location(
    "monk_native_support", ROOT / "tests/SocialRegression/test_native_social.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)

HARNESS = r'''
#define main monk_unused_main
#include "adapter/nanaimo_gameplay_bridge.c"
#undef main
#define CHECK(x) do {if(!(x)){printf("FAIL %d: %s\n",__LINE__,#x);return 1;}} while(0)
static unsigned char captured[4096];static unsigned count,length;
static int __attribute__((stdcall)) capture(SOCKET s,const char*p,int n,int flags){
    if(n<0||n>sizeof(captured))return -1;
    memcpy(captured,p,n);length=(unsigned)n;count++;return n;
}
static DWORD __attribute__((stdcall)) fixed_clock(void){return 123400u;}
static int frontier(void){
    struct progression_dungeon_grade_state before,after;
    struct progression_dungeon_grade_result result;
    struct progression_dungeon_tuple tuple;
    unsigned ep,diff,st,allow,seed;
    memcpy(g_stable_name,"MonkNative",10);g_stable_name_len=10;
    for(seed=0;seed<2;seed++){
        memset(&before,0,sizeof(before));
        if(seed){before.grade=39;before.frontier_valid=1;before.frontier.episode=3;
            before.frontier.dungeon=2;before.frontier.stage_index=1;}
        CHECK(progression_dungeon_grade_save_name(g_stable_name,g_stable_name_len,&before));
        for(ep=24;ep<=27;ep++)for(diff=0;diff<3;diff++)for(st=0;st<3;st++)for(allow=0;allow<2;allow++){
            memset(&tuple,0,sizeof(tuple));tuple.episode=ep;tuple.difficulty=diff;tuple.stage_index=st;
            CHECK(progression_dungeon_grade_award_current(allow,&tuple,&result));
            CHECK(!result.saved&&!result.grade_up&&!result.frontier_advanced&&result.new_grade==before.grade);
            CHECK(progression_dungeon_grade_read_name(g_stable_name,g_stable_name_len,&after,0));
            CHECK(!memcmp(&before,&after,sizeof(before)));
        }
    }
    memset(&before,0,sizeof(before));
    CHECK(progression_dungeon_grade_save_name(g_stable_name,g_stable_name_len,&before));
    memset(&tuple,0,sizeof(tuple));tuple.episode=3;tuple.dungeon=2;tuple.stage_index=1;
    CHECK(progression_dungeon_grade_award_current(1,&tuple,&result));
    CHECK(result.saved&&result.new_grade==4&&result.frontier_advanced);
    return 0;
}
static int settlement(void){
    struct boss_hp_sync_context*c=multiplayer_shared_boss_context();
    struct boss_hp_sync_result hit;struct progression_dungeon_grade_state before,after;
    struct progression_progression_state progression;
    unsigned j,slot;const struct boss_component_boss_mode*mode;
    pSd=capture;pT=(void*)fixed_clock;g_account_name[0]=0;g_multi_current=0;
    memset(g_multi_conn,0,sizeof(g_multi_conn));memset(g_multi_transport_alive,0,sizeof(g_multi_transport_alive));
    g_multi_conn[0].active=1;g_multi_conn[0].room_active=1;g_multi_transport_alive[0]=1;
    g_multi_conn[0].uid=11;g_multi_conn[0].socket=100;g_multi_conn[0].join_order=1;
    g_multi_conn[0].profile.hp_current=100;g_multi_conn[0].profile.level=1;
    memcpy(g_stable_name,"MonkGate",8);g_stable_name_len=8;
    memcpy(g_multi_conn[0].profile.name,g_stable_name,8);g_multi_conn[0].profile.name_len=8;
    memset(&progression,0,sizeof(progression));progression.level=1;
    CHECK(progression_progression_save_name(g_stable_name,g_stable_name_len,&progression));
    memset(&before,0,sizeof(before));before.grade=39;before.frontier_valid=1;
    before.frontier.episode=3;before.frontier.dungeon=2;before.frontier.stage_index=1;
    CHECK(progression_dungeon_grade_save_name(g_stable_name,g_stable_name_len,&before));
    g_stable_level=1;g_progression_profile_exp_total=0;teamplay_score_begin(1);
    g_managed_clear_masks[0][0]=8;
    boss_hp_sync_init(c);
    for(slot=0;slot<9;slot++){
    g_multi_conn[0].profile.hp_current=100;
    boss_hp_sync_begin_game_domain(c,24,0,0,0,slot/3,slot);CHECK(c->profile&&c->mode_count==1);
    CHECK(c->stage==24&&c->stage_index==0&&c->hd==0&&c->dungeon==0);count=0;
    progression_send_cf88_playable_impl(100,0,1);
    CHECK(count==0&&!(g_progression_settlement_epoch_valid[0]&&g_progression_settlement_epoch[0]==c->battle_epoch));
    CHECK(g_stable_level==1&&g_progression_profile_exp_total==0);
    mode=boss_component_boss_mode_def(c->profile,0);CHECK(mode);
    for(j=0;j<mode->component_count;j++){
        const struct boss_component_boss_component*x=&boss_component_boss_components[mode->first_component+j];
        if(!x->scaled_hp)continue;
        CHECK(boss_hp_sync_apply_external_component_damage(c,0,x->child,x->ordinal,
            x->scaled_hp+x->basis+1,&hit)==BOSS_HP_SYNC_OK);
    }
    CHECK(boss_hp_sync_final_terminal_seen(c));
    progression_send_cf88_playable_impl(100,0,1);
    CHECK(count==1&&length==64&&boss_hp_sync_get16(captured,6)==0xCF88&&captured[23]>0);
    CHECK(g_progression_settlement_epoch_valid[0]);
    CHECK(progression_dungeon_grade_read_name(g_stable_name,g_stable_name_len,&after,0));
    CHECK(!memcmp(&before,&after,sizeof(before)));
    CHECK(g_managed_clear_masks[0][0]==8);
    boss_hp_sync_begin_game_domain(c,24,0,0,0,slot/3,slot);CHECK(c->profile);
    g_multi_conn[0].profile.hp_current=0;count=0;
    progression_send_cf88_playable_impl(100,0,0);
    CHECK(count==1&&captured[23]==0&&boss_hp_sync_get32(captured,24)==0);
    CHECK(!boss_hp_sync_final_terminal_seen(c));
    CHECK(progression_dungeon_grade_read_name(g_stable_name,g_stable_name_len,&after,0));
    CHECK(!memcmp(&before,&after,sizeof(before)));
    CHECK(g_managed_clear_masks[0][0]==8);
    }
    return 0;
}
int main(void){unsigned requested,epoch,valid,required,seen;
    for(requested=0;requested<2;requested++)for(epoch=0;epoch<2;epoch++)
    for(valid=0;valid<2;valid++)for(required=0;required<2;required++)for(seen=0;seen<2;seen++)
        CHECK(dungeon_settlement_progress_allowed(requested,epoch,valid,required,seen)
            ==(requested&&epoch&&valid&&(!required||seen)));
    CHECK(!frontier());CHECK(!settlement());
    puts("MONK_NATIVE_ISOLATED_PASS frontier=144 boss_slots=9 settlement=terminal-gated failure=no-clear");return 0;
}
'''


class MonkNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="nanaimo-monk-native-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.bridge = cls.work / "bridge.exe"
        cls.compile(ROOT / "adapter/nanaimo_gameplay_bridge.c", cls.bridge)

    @classmethod
    def compile(cls, source, output):
        result = subprocess.run([str(TCC), "-I", str(ROOT), str(source), "-o", str(output)],
                                cwd=cls.work, capture_output=True, text=True, errors="replace", timeout=180)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_current_native_gate_and_main_story_isolation(self):
        source, binary = self.work / "isolated.c", self.work / "isolated.exe"
        source.write_text(HARNESS, encoding="ascii")
        self.compile(source, binary)
        result = subprocess.run([str(binary)], cwd=self.work, capture_output=True,
                                text=True, errors="replace", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MONK_NATIVE_ISOLATED_PASS", result.stdout)

    def test_actual_worker_three_failure_retries(self):
        port = None
        for candidate in range(57100, 58000, 10):
            reservations = []
            try:
                for value in range(candidate, candidate + 9):
                    item = socket.socket()
                    reservations.append(item)
                    item.bind(("127.0.0.1", value))
                port = candidate
                break
            except OSError:
                pass
            finally:
                for item in reservations:
                    item.close()
        self.assertIsNotNone(port, "No isolated worker port range is available")
        with tempfile.TemporaryDirectory(prefix="monk-worker-", dir=self.work) as temp:
            directory = Path(temp)
            profile = directory / "profile.ini"
            profile.write_text("version=2\nname_hex=4D6F6E6B\nlevel=1\npet=0\n"
                               "hp_max=100\nhp_current=100\nmp_max=500\nmp_current=123\n", encoding="ascii")
            connection = None
            with (directory / "worker.txt").open("wb") as output:
                process = subprocess.Popen([str(self.bridge), str(port + 8), "0", "0", "0", str(profile), str(port)],
                                           cwd=directory, stdout=output, stderr=output,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    deadline = time.monotonic() + 10
                    while connection is None:
                        try:
                            connection = socket.create_connection(("127.0.0.1", port), timeout=2)
                        except OSError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                raise
                            time.sleep(.05)
                    connection.settimeout(8)

                    def exchange(opcode, payload, reply, captured=None):
                        connection.sendall(support.frame(opcode, payload))
                        return support.receive(connection, reply, captured)

                    def snapshot():
                        return exchange(0xF101, b"", 0xF102)[8:]

                    def start():
                        for opcode, payload, reply in [(0xC587, b"", 0xC588), (0xCF70, bytes(4), 0xCF71),
                            (0xCFEB, bytes(4), 0xCFEC), (0xCFD3, b"", 0xCFD4),
                            (0xCFD5, struct.pack("<I", 1), 0xCFD6), (0xCF7F, b"", 0xCF80)]:
                            exchange(opcode, payload, reply)

                    state = bytearray(support.seed(11, 0))
                    for offset, value in {16: 100, 20: 100, 24: 500, 28: 123, 60: 0, 5024: 39,
                                          5028: 1, 5032: 0, 5036: 3, 5040: 2, 5044: 0, 5048: 1, 5112: 1}.items():
                        struct.pack_into("<I", state, offset, value)
                    state[5052] = 8
                    exchange(0xF100, state, 0xF102)
                    selection = bytearray(44)
                    selection[27] = 24
                    exchange(0xCF6C, selection, 0xCF6D)
                    start()
                    initial = snapshot()
                    for cycle in range(3):
                        connection.sendall(support.frame(0xCF87, struct.pack("<HH", 123, 0)))
                        pending = []
                        exchange(0xF101, b"", 0xF102, pending)
                        self.assertFalse(any(struct.unpack_from("<H", item, 6)[0] == 0xCF88 for item in pending),
                                         "Boss must terminate before the worker publishes a successful result")
                        exchange(0xD014, struct.pack("<HHHBB", 20, 0, cycle, 12, 11), 0xD015)
                        dead = snapshot()
                        self.assertEqual(struct.unpack_from("<I", dead, 20)[0], 0)
                        result = exchange(0xCF87, struct.pack("<HH", 123, 0), 0xCF88)
                        self.assertEqual(result[23], 0)
                        self.assertEqual(struct.unpack_from("<I", result, 24)[0], 0)
                        reset = exchange(0xCF8B, bytes([0, 0, 1, 0]), 0xCF8C)
                        self.assertEqual(reset[40:42], bytes(2))
                        retried = snapshot()
                        self.assertEqual(struct.unpack_from("<II", retried, 16), (100, 16))
                        self.assertEqual(struct.unpack_from("<I", retried, 28)[0], 123)
                        self.assertEqual(retried[5024:5112], initial[5024:5112])
                        start()
                        active = snapshot()
                        self.assertEqual(active[5024:5112], initial[5024:5112])
                except Exception:
                    output.flush()
                    print((directory / "worker.txt").read_text("utf8", errors="replace")[-12000:])
                    raise
                finally:
                    if connection is not None:
                        connection.close()
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
