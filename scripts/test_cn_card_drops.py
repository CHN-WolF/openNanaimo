"""CSV identity/rate-group/weight parity and compiled production card-policy regressions."""
from pathlib import Path
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / 'release/components/cards'
TCC = ROOT / 'tools/tcc/tcc.exe'
spec = importlib.util.spec_from_file_location('cn_cards', ROOT / 'scripts/generate_cn_card_drops.py')
cn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cn)


class CnCardDropTests(unittest.TestCase):
    def test_csv_and_generation(self):
        pools = cn.load_pools()
        with cn.SOURCE.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 3752)
        self.assertEqual(len(pools), 3073)
        self.assertEqual(len({code for p in pools.values() for code in p}), 494)
        receipt = json.loads(cn.BINDINGS.read_text('utf-8'))
        self.assertEqual(cn.generate(pools, receipt).encode(), cn.OUTPUT.read_bytes())
        self.assertEqual(receipt['csv_sha256'], cn.digest(cn.SOURCE.read_bytes()))
        # Every expanded CSV association survives, including enabled lucky domain22.
        for row in rows:
            for stage in row['sstg'].lower().split(';'):
                self.assertEqual(pools[cn.map_key(stage), row['mmo'].lower()][int(row['card_id'])], (int(row['rate']), int(row['weight'])))

    def test_duplicate_and_invalid_inputs(self):
        header = ','.join(cn.COLUMNS)
        row = 'hd0_ep02_dg00_st00.sstg,test.mmo,12000001,SP,SP卡,8,100'
        def parse(*rows):
            return cn.load_pools(data=('\n'.join([header, *rows]) + '\n').encode())
        self.assertEqual(next(iter(parse(row, row).values())), {12000001: (8, 100)})
        for bad in [row.rsplit(',', 1)[0] + ',99', row.replace('.sstg', '.bad'),
                    row.replace(',8,100', ',101,100'), row.replace(',8,100', ',-1,100'),
                    row.replace(',8,100', ',8,-1'), row.replace(',8,100', ',8,32769'),
                    row.replace(',8,100', ',8.5,100')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse(row, bad)
        # A group is counted once, even with distinct cards and duplicate rows.
        other = row.replace('12000001', '12000002')
        self.assertEqual(len(next(iter(parse(row, other, row).values()))), 2)
        with self.assertRaisesRegex(ValueError, 'exceed 100'):
            parse(row.replace(',8,100', ',60,100'), other.replace(',8,100', ',50,100'))
        with self.assertRaisesRegex(ValueError, 'random bound'):
            parse(row.replace(',8,100', ',8,32768'), other)
        for disabled in [',0,100', ',8,0']:
            self.assertTrue(parse(row.replace(',8,100', disabled)))

    def test_user_example_and_zero_weight(self):
        pools = cn.load_pools()
        pool = pools[cn.map_key('hd0_ep20_dg00_st00.sstg'), 'ep20_dg00_mb_182_02.mmo']
        self.assertEqual(pool, {12000009: (8, 100), 13000310: (5, 50), 12000015: (5, 50)})
        self.assertEqual(sum({rate for rate, weight in pool.values()}), 13)
        self.assertEqual(pools[cn.map_key('hd0_ep16_dg00_st00.sstg'), 'ep16_dg00_m_158_02.mmo'][12000003], (5, 0))
        self.assertEqual(sum(len({r for r, w in p.values()}) for p in pools.values()), 3085)

    def test_workbook_import(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest('openpyxl is only needed when importing a workbook')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cards.xlsx'
            book = openpyxl.Workbook()
            book.active.append(cn.COLUMNS + [None, 'note'])
            row = ['hd0_ep02_dg00_st00.sstg', 'test.mmo', 12000001, 'SP', 'SP卡', 8, 0]
            book.active.append(row)
            book.active.append([None] * 7 + ['ignored note'])
            book.save(path)
            data = cn.workbook_csv(path)
            self.assertEqual(len(data.decode().splitlines()), 2)
            self.assertEqual(next(iter(cn.load_pools(data=data).values())), {12000001: (8, 0)})
            book.active.cell(2, 6).value = 8.5
            book.save(path)
            with self.assertRaisesRegex(ValueError, 'integer'):
                cn.workbook_csv(path)

    def test_closure_requires_csv_only_when_table_is_compiled(self):
        from refresh_source_manifest import collect
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'adapter').mkdir()
            for name in ['nanaimo_adapter.c', 'nanaimo_adapter_testports.c']:
                (root / 'adapter' / name).write_text('int main(void){return 0;}', 'utf-8')
            self.assertEqual(len(collect(root)), 2)
            cards = root / 'release/components/cards'
            cards.mkdir(parents=True)
            (cards / 'card_drop_cn_data.inc').write_text('/* table */', 'utf-8')
            (root / 'adapter/nanaimo_adapter.c').write_text('#include "../release/components/cards/card_drop_cn_data.inc"', 'utf-8')
            with self.assertRaisesRegex(ValueError, 'missing card distribution input'):
                collect(root)
            (cards / 'card_drop_cn.csv').write_text('source', 'utf-8')
            (cards / 'card_drop_cn_boss_bindings.json').write_text('{}', 'utf-8')
            (root / 'scripts').mkdir()
            (root / 'scripts/generate_cn_card_drops.py').write_text('# generator', 'utf-8')
            self.assertEqual(len(collect(root)), 6)

    def test_distribution_inputs_have_exact_export_whitelist(self):
        import export_patch as export
        rows = []
        for rel in ['release/components/cards/card_drop_cn.csv',
                    'release/components/cards/card_drop_cn_boss_bindings.json',
                    'scripts/generate_cn_card_drops.py']:
            path = ROOT / rel
            rows.append({'path': rel, 'size': path.stat().st_size, 'sha256': cn.digest(path.read_bytes())})
        export.validated_closure({'count': len(rows), 'files': rows})
        rows[0] = {**rows[0], 'path': 'release/components/cards/unreviewed.csv'}
        with self.assertRaises(export.ExportError):
            export.validated_closure({'count': len(rows), 'files': rows})

    def test_reviewed_resource_row_policy_generation_and_catalog_identity(self):
        import copy
        import re
        import generate_card_reward_rows as policy
        receipt = json.loads(policy.SOURCE.read_text('utf-8'))
        self.assertEqual(policy.generate(receipt).encode('utf-8'), policy.OUTPUT.read_bytes())
        hp = (ROOT / 'release/components/targets/hp_resource_global_data.inc').read_text('utf-8')
        identities = {name.lower(): (sha, int(count)) for name, sha, count in
                      re.findall(r'\{"([^"\n]+)","([A-F0-9]{64})",(\d+)u\}', hp)}
        self.assertEqual(receipt['scan']['mixed_resources'], len(receipt['resources']))
        self.assertEqual(len(receipt['resources']), 90)
        self.assertEqual(sum(len(r['deny_card_rows']) for r in receipt['resources']), 774)
        for r in receipt['resources']:
            if r['resource'] not in identities:
                self.assertFalse(r['deny_card_rows'])  # CSV-only object, not a generated target.
                continue
            self.assertEqual(identities[r['resource']], (r['sha256'], r['record_count']))
        child = next(r for r in receipt['resources'] if r['resource'] == 'ep03_dg02_mb_32_1_00.mmo')
        self.assertEqual(child['deny_card_rows'], list(range(11)))
        self.assertNotIn(19, child['deny_card_rows'])
        old = next(r for r in receipt['resources'] if r['resource'] == 'ep01_dg00_mb_36_1_00.mmo')
        self.assertNotIn(18, old['deny_card_rows'])
        self.assertNotIn(19, old['deny_card_rows'])
        for mutate in ('duplicate', 'outside', 'all_not_card', 'csv', 'runtime'):
            bad = copy.deepcopy(receipt)
            if mutate == 'duplicate': bad['resources'].append(bad['resources'][0])
            elif mutate == 'outside': bad['resources'][0]['deny_card_rows'] = [65535]
            elif mutate == 'all_not_card': bad['resources'][0]['deny_all_rows'] = [65535]
            elif mutate == 'csv': bad['card_csv_sha256'] = '0' * 64
            else: bad['runtime_acceptance'] = True
            with self.assertRaises((ValueError, KeyError)):
                policy.generate(bad)

    def test_native_all_pools_and_live_reward_entrypoints(self):
        pools = cn.load_pools()
        # Independent expected table parsed directly from CSV, not generated C.
        expected = []
        for (key, name), pool in sorted(pools.items()):
            expected += [f'{{{key}u,"{name}",{code}u,{rate}u,{weight}u}},' for code, (rate, weight) in sorted(pool.items())]
        team = (ROOT / 'release/components/adapter_core/teamplay_adapter.inc').read_text('utf-8')
        team = team[team.index('#define CARD_DROP_BUILD_TAG'):team.index('/* D00D target damage')]
        boss = (ROOT / 'release/components/winter_boss/boss_hp_sync_runtime.inc').read_text('utf-8')
        boss = boss[boss.index('static unsigned boss_hp_sync_terminal_card('):boss.index('\n#endif\nstatic int boss_hp_sync_encode_d012_payload')]
        code = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static char g_account_name[64]="cncardtest",g_stable_name[32]="cncardtest";
static unsigned g_stable_name_len=10u,g_next=0u;
static unsigned g_values[3],g_value_count=0u,g_value_index=0u,g_calls=0u;
static unsigned g_rnd(void){g_calls++;return g_value_index<g_value_count?g_values[g_value_index++]:g_next;}
#ifdef TEST_PROFILE
#include "release/components/cards/profile_state.inc"
#else
#include "release/components/cards/card_system.inc"
#endif
#define MULTI_MAX_PLAYERS 3
#define CARD_ORDINARY_DROP_MIN_HP 0u
static unsigned combat_economy_coin_amount_for_hp(unsigned hp){return hp/100u;}
struct hp_sync_profile_def{unsigned hd_id,stage_id,dungeon_id,stage_index,slot_index;};
struct hp_sync_target_def{unsigned reward_kind,raw_hp,target_type,selector,placement_selector_start;};
static int terminal_item_drop_is_authored(const struct hp_sync_target_def*t,const struct hp_sync_profile_def*p){return 0;}
static void teamplay_note_drop(unsigned n){}
static int flight_items_coin_index(void){return 0;}
static int flight_items_contains(const char*a,const char*b){return strstr(a,b)!=0;}
static int card_ordinary_drop_hp_eligible(unsigned hp){return hp>0u;}
static void combat_economy_coin_note_card_replacement(unsigned hp){}
static unsigned flight_items_coin_on_terminal(const struct hp_sync_target_def*t,const char*r,unsigned s,unsigned old,unsigned now,unsigned hp){return old&&!now?combat_economy_coin_amount_for_hp(hp):0u;}
static unsigned g_bonus=0u,g_multiplier=100u;
static unsigned pet_crafting_pet_economy_percent(unsigned effect){assert(effect==7u);return g_bonus;}
static unsigned flight_items_flight_card_percent(void){return g_multiplier;}
struct boss_hp_sync_result {unsigned stage,card_pool_hd,card_pool_key;};
'''
        code += team + '\n' + boss
        code += '\nstruct expected{unsigned map;const char*name;unsigned code,rate,weight;};\nstatic const struct expected expected_rows[]={\n' + '\n'.join(expected) + '\n};\n'
        receipt = json.loads((CARDS / 'card_reward_rows.json').read_text('utf-8'))
        row_cases = []
        for resource in receipt['resources']:
            key = next(k for k, name in sorted(pools) if name == resource['resource'])
            for row in resource['rows']:
                policy = 2 if row['row'] in resource['deny_all_rows'] else int(row['row'] in resource['deny_card_rows'])
                row_cases.append('{"%s",%du,%du,%du,%du},' %
                                 (resource['resource'], key, row['row'], row['hp'], policy))
        code += '\nstruct row_case{const char*name;unsigned map,row,hp,policy;};\n'
        code += 'static const struct row_case row_cases[]={\n' + '\n'.join(row_cases) + '\n};\n'
        code += r'''
int main(void){
 unsigned i,j,f,t,n=sizeof(expected_rows)/sizeof(expected_rows[0]),subtype,code;
 const struct card_cn_pool*p;struct hp_sync_target_def td={0u,100u,0u};
 for(i=0u;i<n;i++){
  const struct expected*e=&expected_rows[i];unsigned found=0u;
  p=card_cn_lookup(e->map>>24,(e->map>>16)&255u,(e->map>>8)&255u,e->map&255u,e->name);assert(p);
  for(j=0u;j<p->count;j++)if(card_cn_entries[p->first+j].code==e->code){assert(card_cn_entries[p->first+j].rate==e->rate);assert(card_cn_entries[p->first+j].weight==e->weight);found++;}
  assert(found==1u);
 }
 for(i=0u;i<CARD_CN_POOL_COUNT;i++){
  unsigned group_ticket=0u;
  p=&card_cn_pools[i];
  for(f=1u;f<=100u;f++){
   unsigned total=card_cn_group_weight(p,f),ticket=0u;
   for(j=0u;j<p->count;j++){
    const struct card_cn_entry*e=&card_cn_entries[p->first+j];
    /* Independent eligibility oracle, not the production filter. */
    if(e->rate!=f||!e->weight)continue;
    for(t=0u;t<e->weight;t++)assert(card_cn_pick_ticket(p,f,ticket++)==e->code);
   }
   assert(ticket==total);assert(card_cn_pick_ticket(p,f,total)==0u);
   if(total)for(t=0u;t<f;t++)assert(card_cn_pick_group(p,group_ticket++)==f);
  }
  assert(group_ticket==card_cn_total_rate(p));assert(card_cn_pick_group(p,group_ticket)==0u);
  card_system_reset_epoch(i+1u);g_next=0u;
  code=card_cn_drop_create(2u,123u,p,group_ticket*100u);
  assert(code==card_cn_pick_ticket(p,card_cn_pick_group(p,0u),0u));
  assert(g_card_claim_count==(code?1u:0u));
  if(group_ticket<100u){unsigned claims=g_card_claim_count;
   g_next=group_ticket*100u;
   assert(!card_cn_drop_create(2u,123u,p,group_ticket*100u));assert(g_card_claim_count==claims);
  }
 }
 g_next=0u;
 assert(!card_cn_lookup(0u,23u,0u,0u,"ani_mon_m_03_01.mmo"));
 assert(!card_cn_lookup(256u,0u,0u,0u,"ani_mon_m_03_01.mmo"));
 assert(!card_cn_lookup(0u,2u,0u,0u,0));assert(!card_cn_lookup(0u,2u,0u,0u,""));
 assert(!card_cn_lookup(0u,2u,0u,0u,"unknown.mmo"));
 p=card_cn_lookup(0u,2u,0u,0u,"ANI_MON_M_03_01.MMO");assert(p&&card_cn_total_rate(p)==10u);
 assert(card_cn_pick_ticket(p,10u,0u)==12000001u);
 {struct card_cn_entry e={22000011u,100u,100u};assert(card_cn_entry_eligible(&e));e.code=22000018u;assert(card_cn_entry_eligible(&e));}
 card_system_reset_epoch(777u);
 code=card_cn_drop_create(2u,123u,p,1000u);assert(code==12000001u);
 assert(card_pickup_commit(55u,code)==1);assert(card_pickup_commit(55u,code)==2);
 assert(card_pickup_commit(55u,12000002u)==0);g_card_loaded=0;
 assert(card_inventory_count(code)==1u);card_system_reset_epoch(778u);
 assert(card_pickup_commit(55u,code)==0);
 assert(!card_cn_drop_create(2u,123u,0,0u)&&g_card_claim_count==0u);
 g_card_claim_count=CARD_DROP_CAP;assert(!card_cn_drop_create(2u,123u,p,1000u));card_system_reset_epoch(779u);
 {struct hp_sync_profile_def profile={0u,2u,0u,0u,0u};
 combat_economy_select_ordinary_terminal_reward(&td,&profile,"ani_mon_m_03_01.mmo",123u,1u,0u,100u,&subtype,&code);
 assert(subtype==30u&&code==12000001u); /* cards are independent of the Hans calculation */
 profile.stage_id=23u;
 combat_economy_select_ordinary_terminal_reward(&td,&profile,"ani_mon_m_03_01.mmo",123u,1u,0u,500u,&subtype,&code);
 assert(subtype==20u&&code==5u); /* no cross-map/SP fallback */
 profile.stage_id=2u;
 combat_economy_select_ordinary_terminal_reward(&td,&profile,"ani_mon_m_03_01.mmo",123u,1u,1u,500u,&subtype,&code);
 assert(subtype==0u&&code==0u); /* non-terminal remains no drop */
 }
 for(i=0u;i<CARD_CN_BOSS_COUNT;i++){
  const struct card_cn_boss*b=&card_cn_bosses[i];struct boss_hp_sync_result r;
  unsigned ep=(b->map>>16)&255u,dg=(b->map>>8)&255u,st=b->map&255u;
  r.stage=ep;r.card_pool_hd=b->map>>24;r.card_pool_key=(ep<<25)|(dg<<23)|(st<<22)|(b->slot<<18);
  p=card_cn_boss_lookup(r.card_pool_hd,r.card_pool_key);assert(p==&card_cn_pools[b->pool]);
  card_system_reset_epoch(i+800u);code=boss_hp_sync_terminal_card(&r);
  assert(code==card_cn_pick_ticket(p,card_cn_pick_group(p,0u),0u));
 }
 /* Boss misses must not allocate a claim; no implicit guaranteed card. */
 for(i=0u;i<CARD_CN_BOSS_COUNT;i++){
  const struct card_cn_boss*b=&card_cn_bosses[i];struct boss_hp_sync_result r;
  unsigned ep=(b->map>>16)&255u,dg=(b->map>>8)&255u,st=b->map&255u;
  r.stage=ep;r.card_pool_hd=b->map>>24;r.card_pool_key=(ep<<25)|(dg<<23)|(st<<22)|(b->slot<<18);
  p=&card_cn_pools[b->pool];card_system_reset_epoch(i+1800u);
  if(card_cn_total_rate(p)<100u){g_next=card_cn_total_rate(p)*100u;assert(!boss_hp_sync_terminal_card(&r));assert(!g_card_claim_count);}
 }
 /* Every actual boss slot: equipment, clover, combined cap, and withdrawal.
  * Control each RNG draw independently so the gate cannot mask selection. */
 for(i=0u;i<CARD_CN_BOSS_COUNT;i++){
  const struct card_cn_boss*b=&card_cn_bosses[i];struct boss_hp_sync_result r;
  unsigned ep=(b->map>>16)&255u,dg=(b->map>>8)&255u,st=b->map&255u,variant;
  r.stage=ep;r.card_pool_hd=b->map>>24;r.card_pool_key=(ep<<25)|(dg<<23)|(st<<22)|(b->slot<<18);
  p=&card_cn_pools[b->pool];
  for(variant=0u;variant<7u;variant++){
   unsigned base=card_cn_total_rate(p),bp;
   g_bonus=(variant==1u||variant==3u||variant==5u)?27u:0u;
   g_multiplier=(variant==2u||variant==3u)?200u:(variant==4u||variant==5u)?120u:100u;
   bp=base*(100u+g_bonus)*g_multiplier/100u;if(bp>10000u)bp=10000u;
   card_system_reset_epoch(3000u+i*7u+variant);
   g_values[0]=bp?bp-1u:0u;g_values[1]=g_values[2]=0u;g_value_count=3u;g_value_index=0u;
   code=boss_hp_sync_terminal_card(&r);
   assert(code==card_cn_pick_ticket(p,card_cn_pick_group(p,0u),0u));
   assert(g_card_claim_count==(code?1u:0u));
   if(bp<10000u){
    unsigned claims=g_card_claim_count;
    g_values[0]=bp;g_value_index=0u;
    assert(!boss_hp_sync_terminal_card(&r));assert(g_card_claim_count==claims);
   }else{
    g_card_claim_count=0u;g_values[0]=9999u;g_value_index=0u;
    assert(boss_hp_sync_terminal_card(&r)==code&&g_card_claim_count==1u);
   }
  }
 }
 g_bonus=0u;g_multiplier=100u;g_value_count=g_value_index=0u;g_next=0u;
 /* Ordinary terminal uses the same live 120% bonus source and exact gate. */
 {struct hp_sync_profile_def profile={0u,2u,0u,0u,0u};
  card_system_reset_epoch(29999u);g_bonus=27u;g_multiplier=120u;
  g_values[0]=1523u;g_values[1]=g_values[2]=0u;g_value_count=3u;g_value_index=0u;
  combat_economy_select_ordinary_terminal_reward(&td,&profile,"ani_mon_m_03_01.mmo",123u,1u,0u,500u,&subtype,&code);
  assert(subtype==30u&&code==12000001u&&g_card_claim_count==1u);
  g_values[0]=1524u;g_value_index=0u;
  combat_economy_select_ordinary_terminal_reward(&td,&profile,"ani_mon_m_03_01.mmo",124u,1u,0u,500u,&subtype,&code);
  assert(subtype==20u&&code==5u&&g_card_claim_count==1u);
  g_bonus=0u;g_multiplier=100u;g_value_count=g_value_index=0u;g_next=0u;
 }
 /* User example: 13% gate, then 8:5 groups, with 50:50 within the 5% group. */
 p=card_cn_lookup(0u,20u,0u,0u,"ep20_dg00_mb_182_02.mmo");assert(p);
 assert(card_cn_total_rate(p)==13u);
 {unsigned counts[3]={0u,0u,0u},wins=0u;
  for(i=0u;i<13u;i++)for(j=0u;j<100u;j++){
   code=card_cn_pick_ticket(p,card_cn_pick_group(p,i),j);
   assert(code==12000009u||code==13000310u||code==12000015u);
   counts[code==12000009u?0u:code==13000310u?1u:2u]++;
  }
  assert(counts[0]==800u&&counts[1]==250u&&counts[2]==250u);
  for(i=0u;i<10000u;i++){
   g_card_claim_count=0u;g_next=i;
   code=card_cn_drop_create(2u,123u,p,1300u);
   assert((code!=0u)==(i<1300u));assert(g_card_claim_count==(code?1u:0u));wins+=(code!=0u);
  }
  assert(wins==1300u);
  g_values[0]=1299u;g_values[1]=0u;g_values[2]=49u;g_value_count=3u;g_value_index=0u;g_card_claim_count=0u;
  assert(card_cn_drop_create(2u,123u,p,1300u)==12000015u&&g_value_index==3u);
  g_values[2]=50u;g_value_index=0u;g_card_claim_count=0u;
  assert(card_cn_drop_create(2u,123u,p,1300u)==13000310u);
  g_values[1]=5u;g_value_index=0u;g_card_claim_count=0u;
  assert(card_cn_drop_create(2u,123u,p,1300u)==12000009u);
  g_value_count=g_value_index=0u;g_next=0u;
 }
 assert(card_cn_basis_points(13u,0u,100u)==1300u);
 assert(card_cn_basis_points(13u,27u,100u)==1651u);
 assert(card_cn_basis_points(13u,27u,200u)==3302u);
 assert(card_cn_basis_points(13u,0u,120u)==1560u);
 assert(card_cn_basis_points(13u,27u,120u)==1981u);
 assert(card_cn_basis_points(100u,27u,200u)==10000u);
 assert(card_cn_basis_points(50u,27u,200u)==10000u); /* raw 127%, capped */
 assert(card_cn_basis_points(13u,0xFFFFFFFFu,0xFFFFFFFFu)==10000u);
 assert(card_cn_basis_points(0u,0xFFFFFFFFu,100u)==0u);
 assert(card_cn_basis_points(13u,27u,0u)==0u);
 {unsigned calls=g_calls;g_card_claim_count=0u;
  assert(!card_cn_drop_create(2u,123u,p,0u)&&!g_card_claim_count&&g_calls==calls);
  g_card_claim_count=CARD_DROP_CAP;
  assert(!card_cn_drop_create(2u,123u,p,1300u)&&g_calls==calls);
 }
 /* A failed gate falls back to Hans in the real ordinary entrypoint. */
 {struct hp_sync_profile_def profile={0u,20u,0u,0u,0u};
  card_system_reset_epoch(9999u);g_next=1300u;
  combat_economy_select_ordinary_terminal_reward(&td,&profile,"ep20_dg00_mb_182_02.mmo",123u,1u,0u,500u,&subtype,&code);
  assert(subtype==20u&&code==5u&&!g_card_claim_count);
 }
 /* Shared MMO rows must not inherit the body's pool, even at capped bonuses.
    Test both native inventory implementations with the production entrypoint. */
 {struct hp_sync_profile_def profile={0u,1u,0u,0u,0u};
  struct hp_sync_target_def child={0u,30u,0u,100u,100u};unsigned variant,row,calls;
  const char*name="ep01_dg00_mb_36_1_00.mmo";
  for(variant=0u;variant<4u;variant++){
   g_bonus=variant==3u?0xFFFFFFFFu:27u;g_multiplier=variant==0u?100u:variant==1u?120u:200u;
   card_system_reset_epoch(40000u+variant);g_next=0u;calls=g_calls;
   for(row=1u;row<=16u;row++){
    child.selector=100u+row;
    combat_economy_select_ordinary_terminal_reward(&child,&profile,name,child.selector,1u,0u,1000u,&subtype,&code);
    assert(subtype==20u&&code==10u&&!g_card_claim_count&&g_calls==calls);
   }
   child.selector=100u;child.raw_hp=5000u;
   combat_economy_select_ordinary_terminal_reward(&child,&profile,name,child.selector,1u,0u,5000u,&subtype,&code);
   assert(subtype==30u&&code==13000026u&&g_card_claim_count==1u);
   child.raw_hp=30u;
  }
  child.selector=101u;assert(combat_economy_terminal_row_policy(&child,name));
  assert(combat_economy_terminal_row_policy(&child,"EP01_DG00_MB_36_1_00.MMO"));
  assert(!combat_economy_terminal_row_policy(&child,"ep01_dg00_mb_36_1_01.mmo"));
  assert(!combat_economy_terminal_row_policy(&child,"ani_mon_m_03_01.mmo"));
  child.selector=100u;assert(!combat_economy_terminal_row_policy(&child,name));
  for(row=17u;row<=20u;row++){child.selector=100u+row;assert(!combat_economy_terminal_row_policy(&child,name));}
  child.selector=99u;assert(!combat_economy_terminal_row_policy(&child,name));
  assert(!combat_economy_terminal_row_policy(0,name));
  assert(!combat_economy_terminal_row_policy(&child,0));
  g_bonus=0u;g_multiplier=100u;
 }
 /* Regression: 4-3's eleven 500-HP children cannot use row19's pool. */
 {struct hp_sync_profile_def profile={0u,3u,2u,1u,0u};
  struct hp_sync_target_def child={0u,500u,0u,100u,100u};unsigned row,calls;
  g_bonus=0xFFFFFFFFu;g_multiplier=200u;card_system_reset_epoch(50001u);g_next=0u;calls=g_calls;
  for(row=0u;row<=10u;row++){
   child.selector=100u+row;
   combat_economy_select_ordinary_terminal_reward(&child,&profile,"ep03_dg02_mb_32_1_00.mmo",child.selector,500u,0u,500u,&subtype,&code);
   assert(subtype!=30u&&!g_card_claim_count&&g_calls==calls);
  }
  child.selector=119u;child.raw_hp=7337u;
  combat_economy_select_ordinary_terminal_reward(&child,&profile,"ep03_dg02_mb_32_1_00.mmo",119u,7337u,0u,7337u,&subtype,&code);
  assert(subtype==30u&&g_card_claim_count==1u);g_bonus=0u;g_multiplier=100u;
 }
 /* Every reviewed positive-HP row: never consume RNG or claims for children.
    Body/deform rows, alternate maps and placement offsets stay independent. */
 for(i=0u;i<sizeof(row_cases)/sizeof(row_cases[0]);i++){
  const struct row_case*r=&row_cases[i];unsigned offset,calls,variant;
  for(offset=0u;offset<=317u;offset+=317u){
   struct hp_sync_profile_def profile={r->map>>24,(r->map>>16)&255u,(r->map>>8)&255u,r->map&255u,0u};
   struct hp_sync_target_def target={0u,r->hp,0u,offset+r->row,offset};
   assert(combat_economy_terminal_row_policy(&target,r->name)==r->policy);
   if(!r->policy)continue;
   for(variant=0u;variant<4u;variant++){
    card_system_reset_epoch(60000u+i*8u+variant);g_next=0u;calls=g_calls;
    g_bonus=variant==3u?0xFFFFFFFFu:27u;g_multiplier=variant==0u?100u:variant==1u?120u:200u;
    combat_economy_select_ordinary_terminal_reward(&target,&profile,r->name,target.selector,r->hp,0u,r->hp,&subtype,&code);
    assert(subtype!=30u&&!g_card_claim_count&&g_calls==calls);
    if(r->policy==2u)assert(subtype==0u&&code==0u);
    else if(r->hp>=100u)assert(subtype==20u&&code==r->hp/100u);
   }
  }
 }
 g_bonus=0u;g_multiplier=100u;
 assert(!card_cn_boss_lookup(0u,0xFFFFFFFFu));assert(!card_cn_boss_lookup(0u,9u<<18));
 assert(!card_cn_boss_lookup(0u,23u<<25));assert(!boss_hp_sync_terminal_card(0));
 puts("CN_CARD_NATIVE_PARITY_PASS");return 0;
}
'''
        for profile in [False, True]:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temp:
                temp = Path(temp)
                src, exe = temp / 'test.c', temp / 'test.exe'
                src.write_text(code, 'utf-8')
                subprocess.run([str(TCC), '-I', str(ROOT), *(['-DTEST_PROFILE=1'] if profile else []), str(src), '-o', str(exe)], check=True)
                out = subprocess.run([str(exe)], cwd=temp, text=True, capture_output=True)
                self.assertEqual(out.returncode, 0, out.stdout[-1500:] + out.stderr)
                self.assertIn('CN_CARD_NATIVE_PARITY_PASS', out.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
