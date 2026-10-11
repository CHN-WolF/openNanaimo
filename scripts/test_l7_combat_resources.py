"""L7 resource parity and production-policy regressions, never UI acceptance."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import generate_l7_combat as generator
import generate_lumineos_combat as tables
import audit_l7_combat_resources as audit
import test_social_sync_boundaries as wire

ROOT = Path(__file__).resolve().parents[1]
CLIENT = Path(os.environ['NANAIMO_L7_CLIENT']) if os.environ.get('NANAIMO_L7_CLIENT') else None


class L7CombatTests(unittest.TestCase):
    def test_checked_in_generation_manifest_matches_outputs(self):
        report=json.loads((ROOT/'manifest/l7_combat.json').read_text('utf8'))
        self.assertFalse(report['runtime_accepted'])
        self.assertEqual(len(report['scopes']),18)
        for name,identity in report['outputs'].items():
            raw=(ROOT/name).read_bytes()
            self.assertEqual((len(raw),tables.sha(raw)),(identity['size'],identity['sha256']),name)

    def test_eighteen_native_slots_contacts_terminals_and_boss_modes(self):
        source = r"""
#define main unused_adapter_main
#include "adapter/nanaimo_gameplay_bridge.c"
#undef main
#include <assert.h>
static struct hp_sync_context hp;
static struct boss_hp_sync_context boss;
int main(void){
 unsigned st,slot,i,mode,ordinary=0,barrels=0,conveyors=0,preloads=0;
 struct hp_sync_damage_input in;struct hp_sync_hit_result hit;
 struct stable_monster_hp_attack atk;struct stable_monster_hp_decision d;
 struct crate_drop_policy_context crate;struct boss_hp_sync_result bh;
 unsigned char req[32];
 memset(&in,0,sizeof(in));in.have_attack=1;in.attack=4000;
 memset(&atk,0,sizeof(atk));atk.have_value=1;atk.value=100000000;
 for(st=0;st<2;st++)for(slot=0;slot<9;slot++){
  assert(stable_monster_hp_select_stage(&hp,&crate,0,100,6,st,slot/3,1));
  assert(hp_sync_select_segment(&hp,slot%3));
  assert(hp.profile->target_count==(st?(slot%3==0?891u:slot%3==1?925u:919u):(slot%3==0?857u:835u)));
  assert(hp.profile->slot_percent==255u);
  for(i=0;i<hp.profile->target_count;i++){
   const struct hp_sync_target_def*t=hp_sync_static_def(&hp,i);const char*n=hp_sync_resource_name(t->resource_index);
   unsigned binding=0;struct hp_sync_target_state*s=meat_collision_bound_state(&hp,i,&binding);
   assert(s&&s->target_type==t->target_type);
   if(!strcmp(n,"ep22_mb_T_00.mmo")&&t->target_type==5u){
    assert(hp_sync_apply_attack(&hp,i,&in,1,&hit)==HP_SYNC_HIT_HP_ZERO);
    assert(hit.old_hp==600&&hit.basis_after_modifiers==0&&hit.new_hp==0);barrels++;
   }else if(!strcmp(n,"ep22_dg00_obj_convey2.mmo")&&t->target_type==5u){
    assert(i-t->placement_selector_start==3u&&s->max_hp==10000);
    assert(hp_sync_apply_attack(&hp,i,&in,1,&hit)==HP_SYNC_HIT_APPLIED&&hit.new_hp==6000);
    assert(hp_sync_apply_attack(&hp,i,&in,2,&hit)==HP_SYNC_HIT_APPLIED&&hit.new_hp==2000);
    assert(hp_sync_apply_attack(&hp,i,&in,3,&hit)==HP_SYNC_HIT_HP_ZERO&&hit.new_hp==0);conveyors++;
   }
   if(t->reward_kind==5u)continue;
   stable_monster_hp_apply_report(&hp,&crate,100,i,1,1,&atk,4,&d);
   if(t->target_type==4||t->raw_hp<=0){assert(d.action==MONSTER_HP_ACTION_NONE&&!s->terminal);}
   else{
    assert(s->terminal&&s->hp==0);ordinary++;
    stable_monster_hp_apply_report(&hp,&crate,100,i,1,1,&atk,5,&d);
    assert(d.action==MONSTER_HP_ACTION_NONE&&d.reason==MONSTER_HP_REASON_ALREADY_TERMINAL);
   }
  }
  for(i=0;i<PRELOADED_TARGET_COUNT;i++)if(preloaded_targets[i].profile_row==hp.profile->first_row){
   const struct preloaded_target_def*p=&preloaded_targets[i];unsigned binding=0;
   struct hp_sync_target_state*s=meat_collision_bound_state(&hp,p->selector,&binding);
   assert(s&&binding==MEAT_BIND_RUNTIME&&s->target_type==p->type&&s->hp==p->hp);preloads++;
  }
  assert(hp_sync_select_segment(&hp,slot%3));assert(!hp_sync_state_for(&hp,0)->terminal);
  boss_hp_sync_init(&boss);boss_hp_sync_begin_game_domain(&boss,100,0,6,st,slot/3,slot);
  assert(!boss.lookup_miss&&boss.mode_count==(st?2u:1u));
  assert(boss.component_count==(st?91u:8u));
  for(mode=0;mode<boss.mode_count;mode++){
   const struct boss_component_boss_mode*m=boss_component_boss_mode_def(boss.profile,mode);
   for(i=0;i<m->component_count;i++){
    const struct boss_component_boss_component*c=&boss_component_boss_components[m->first_component+i];
    if(!c->scaled_hp)continue;
    memset(req,0,sizeof(req));req[0x12]=mode;req[0x13]=c->child;boss_hp_sync_put32(req,0x14,c->ordinal);
    assert(boss_hp_sync_apply_d011_attack(&boss,req,32,c->scaled_hp+c->basis+1u,1,&bh)==BOSS_HP_SYNC_OK);
    assert(bh.component_first_terminal&&bh.applied_damage==c->scaled_hp);
   }
  }
  assert(boss_hp_sync_final_terminal_seen(&boss));
 }
 assert(barrels==18&&conveyors==36&&ordinary>5000&&preloads>0);
 printf("L7_NATIVE_PASS slots=18 ordinary=%u barrels=%u conveyors=%u preloads=%u\n",ordinary,barrels,conveyors,preloads);return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix='l7-policy-') as temp:
            p=Path(temp);(p/'test.c').write_text(source,'utf8')
            for command in ([str(ROOT/'tools/tcc/tcc.exe'),'-I',str(ROOT),str(p/'test.c'),'-o',str(p/'test.exe')],[str(p/'test.exe')]):
                result=subprocess.run(command,cwd=p,capture_output=True,text=True,timeout=180)
                self.assertEqual(result.returncode,0,result.stdout[-5000:]+result.stderr)
            print(result.stdout.strip())

    def test_meat_first_contact_preload_and_repeat_wire(self):
        hp=(ROOT/tables.DATA).read_text('utf8');profiles=tables.numeric_rows(hp,'hp_sync_profiles');targets=tables.numeric_rows(hp,'hp_sync_target_defs')
        resources=tables.re.findall(r'\{"([^"]+)","[A-F0-9]{64}",\d+u\}',tables.array(hp,'hp_sync_resources')[1])
        pre=json.loads((ROOT/generator.PRELOAD).read_text('utf8'))
        with wire.room(1,profile_extra='hp_current=2000\nmp_current=1000\n') as (connection,):
            def transact(op,payload=b'',wanted=None):
                connection.sendall(wire.frame(op,payload));frames=[]
                if wanted is not None:wire.receive(connection,wanted,frames)
                frames.extend(wire.flush(connection))
                # F102 may precede the score outbox when the request and F101
                # share one recv batch. A second request barrier attributes
                # those trailing frames to this action, not the next one.
                frames.extend(wire.flush(connection));return frames
            state=bytearray(wire.seed(11,0))
            for offset,value in [(20,2000),(28,1000),(52,52000008),(192,1)]:struct.pack_into('<I',state,offset,value)
            transact(0xF100,state,0xF102)
            for round_index in range(2):
                create=bytearray(32);create[0x23-8]=100;create[0x24-8]=6
                transact(0xCF6C,create,0xCF6D);transact(0xCFEB,bytes(4),0xCFEC);transact(0xCF7F,wanted=0xCF80)
                transact(0xCF9B,struct.pack('<I',52000008),0xCF9C)
                p=next(p for p in profiles if p[:7]==(22,0,0,0,0,0,0))
                barrel=next(t[6] for t in targets[p[9]:p[9]+p[10]] if resources[t[4]]=='ep22_mb_T_00.mmo' and t[8]==5)
                preload=next(r for r in pre['rows'] if r[0]==p[9] and r[2]!=4 and r[4]>0 and r[5]<1500 and r[6]!=5)
                for selector in [barrel,preload[1]]:
                    contact=struct.pack('<HH',20,selector)+bytes(16);terminals=0;numbers=[]
                    for hit in range(20):
                        replies=transact(0xD00F,contact)
                        for frame in replies:
                            op=struct.unpack_from('<H',frame,6)[0]
                            if op==0xD00E and frame[0x1A]==200:terminals+=1
                            if op==0xD010:
                                self.assertEqual(len(frame),36);numbers.append(struct.unpack_from('<H',frame,34)[0])
                        if terminals:break
                    self.assertEqual(terminals,1,(round_index,selector,numbers))
                    self.assertTrue(any(numbers))
                    repeat=transact(0xD00F,contact)
                    self.assertFalse(any(struct.unpack_from('<H',f,6)[0]==0xD00E and f[0x1A]==200 for f in repeat))
                    self.assertTrue(any(struct.unpack_from('<H',f,6)[0]==0xD010 and struct.unpack_from('<H',f,34)[0]==0 for f in repeat))
                incoming=struct.pack('<HHH',10,0,0)+bytes(14)
                replies=transact(0xD00F,incoming)
                self.assertFalse(any(struct.unpack_from('<H',f,6)[0] in (0xD00E,0xD012,0xD013) for f in replies),
                                 'incoming projectiles never retire ordinary or Boss targets')

    def test_build_rejects_stale_combat_data_before_output(self):
        import shutil
        with tempfile.TemporaryDirectory(prefix='l7-stale-catalog-') as temp:
            root=Path(temp);data=root/'data';data.mkdir();output=root/'output'
            pet=next((ROOT/'adapter_runtime').rglob('pi._D7'))
            shutil.copy2(pet,data/'pi._D7');(data/'dungeon_combat_catalog.bin').write_bytes(b'DCC7-stale')
            result=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',
                str(ROOT/'scripts/build_complete_adapter.ps1'),'-OutputRoot',str(output),
                '-ResourceDataRoot',str(data),'-TargetFramework','net8.0'],
                capture_output=True,text=True,errors='replace',timeout=30)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Combat catalog differs',result.stdout+result.stderr)
            self.assertFalse(output.exists())

    @unittest.skipUnless(CLIENT and CLIENT.is_dir(),'set NANAIMO_L7_CLIENT for installed-resource audit')
    def test_installed_resources_and_generator_reproducibility(self):
        self.assertTrue(audit.audit(CLIENT)['matches'])
        with tempfile.TemporaryDirectory(prefix='l7-generate-') as temp:
            output=Path(temp);report=generator.generate(CLIENT,output)
            self.assertEqual(len(report['scopes']),18)
            for path in report['outputs']:
                self.assertEqual((ROOT/path).read_bytes(),(output/path).read_bytes(),path)


if __name__=='__main__':unittest.main(verbosity=2)
