#ifndef NANAIMO_BOSS_HP_SYNC_PROTOCOL_ADAPTER_INC
#define NANAIMO_BOSS_HP_SYNC_PROTOCOL_ADAPTER_INC
static void send_d012_boss_hp_sync_score(SOCKET c,const struct boss_hp_sync_result*r,unsigned total_score){
    char p[4096];unsigned out_len=(r->first_terminal||r->repeated_terminal)?64u:(unsigned)BOSS_HP_SYNC_D012_LEN;
    mkpkt(p,0xD012,(int)out_len,1);boss_hp_sync_encode_d012_payload((unsigned char*)p,BOSS_HP_SYNC_D012_LEN,r);
    stable_put32(p,0x08,total_score);stable_put32(p,0x0C,0u);stable_put32(p,0x10,0u);
    if(r->first_terminal||r->repeated_terminal)p[0x3C]=5;
    sendbuf(c,p,(int)out_len);multiplayer_broadcast_raw(0xD012,(const unsigned char*)p,(int)out_len);
    printf("  S0xD012 BOSS_ADAPTER score_slot0=%u slot1=0 slot2=0 policy=WIRE4000_210_SHARED_MODE_TOPOLOGY_ONLY profile=%u slot=%u mode=%u/%u wire=%u child=%u ordinal=%u expected=%u type=%u owner=%u source=%u atk_observed=%u have=%u fixed210=%u fallback=%u basis_debug=%u resource_mode_hp_debug=%u zero_gate=%u damage=%u hp=%u cumulative=%u intermediate=%u final=%u first=%u repeat=%u mismatch=%u lookup_miss=%u invalid_slot=%u len=%u t=%lds\n",
           total_score,r->profile_kind,r->absolute_slot,r->mode_index,r->mode_count,r->wire_mode,r->wire_child,r->target_ordinal,r->expected_ordinal,r->target_type,r->owner_key,r->source_index,r->attack_value,r->have_attack,r->fixed_damage_policy,r->fallback_used,r->basis,r->resource_mode_hp,r->zero_hp_gate,r->applied_damage,r->hp,r->cumulative_damage,r->intermediate_terminal,r->final_terminal,r->first_terminal,r->repeated_terminal,r->target_mismatch,r->lookup_miss,r->invalid_slot,out_len,sec());fflush(0);
}
#endif
