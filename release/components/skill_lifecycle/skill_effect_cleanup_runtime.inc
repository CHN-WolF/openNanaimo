#ifndef NANAIMO_SKILL_EFFECT_COMPLETION_RUNTIME_SKILL_LIFECYCLE_INC
#define NANAIMO_SKILL_EFFECT_COMPLETION_RUNTIME_SKILL_LIFECYCLE_INC
/* SKILL_LIFECYCLE local adapter lifecycle policy.
 *
 * Static closure shows that natural root completion clears root0 and advances
 * the secondary gate, but does not clear actor+0x80F8 or the rest of the
 * 0x80F0..0x8110 skill state. CF9D is the packet that resets that complete
 * state group. The live COMBAT_ATTRIBUTION projectile fan-out ended within nine coarse
 * seconds. For meat, two exact-PID samples crossed the authored 600 actor
 * ticks at 9875..9984 ms with a 60 Hz median actor clock; the supplied
 * 2026-09-07 01:54 run also emitted stale contacts after ten seconds. The
 * request-driven completion therefore uses ten seconds for both families,
 * never preclears a young generation, and lets epoch boundaries force
 * cleanup. This is local adapter policy, not an original game endpoint formula. */
#ifndef SKILL_EFFECT_COMPLETION_DELAY_MS
#define SKILL_EFFECT_COMPLETION_DELAY_MS 10000u
#endif
struct skill_effect_cleanup_context {
    unsigned active,code,grade,armed_tick,room_epoch,battle_epoch,generation;
};
static void skill_effect_cleanup_reset(struct skill_effect_cleanup_context*c,unsigned room_epoch,unsigned battle_epoch,const char*reason){
    unsigned generation;if(!c)return;generation=c->generation;memset(c,0,sizeof(*c));c->generation=generation;c->room_epoch=room_epoch;c->battle_epoch=battle_epoch;
    printf("  [SKILL_CLEANUP] reset reason=%s room=%u battle=%u generation=%u\n",reason?reason:"unspecified",room_epoch,battle_epoch,generation);fflush(0);
}
static void skill_effect_cleanup_arm(struct skill_effect_cleanup_context*c,unsigned code,unsigned grade,unsigned room_epoch,unsigned battle_epoch,unsigned now){
    if(!c)return;c->active=1u;c->code=code;c->grade=grade;c->armed_tick=now;c->room_epoch=room_epoch;c->battle_epoch=battle_epoch;c->generation++;
    printf("  [SKILL_CLEANUP] arm code=%u grade=%u tick=%u room=%u battle=%u generation=%u delay_ms=%u\n",code,grade,now,room_epoch,battle_epoch,c->generation,SKILL_EFFECT_COMPLETION_DELAY_MS);fflush(0);
}
static int skill_effect_cleanup_code_is_meat(const struct skill_effect_cleanup_context*c){return c&&c->code>=52000008u&&c->code<=52000015u;}
static int skill_effect_cleanup_meat_invulnerable(const struct skill_effect_cleanup_context*c,unsigned room_epoch,unsigned battle_epoch,unsigned now){
    if(!skill_effect_cleanup_code_is_meat(c)||!c->active||c->room_epoch!=room_epoch||c->battle_epoch!=battle_epoch)return 0;
    return (unsigned)(now-c->armed_tick)<SKILL_EFFECT_COMPLETION_DELAY_MS;
}
static int skill_effect_cleanup_busy(const struct skill_effect_cleanup_context*c,unsigned room_epoch,unsigned battle_epoch,unsigned now){
    if(!c||!c->active||c->room_epoch!=room_epoch||c->battle_epoch!=battle_epoch)return 0;
    return (unsigned)(now-c->armed_tick)<SKILL_EFFECT_COMPLETION_DELAY_MS;
}
static int skill_effect_cleanup_send(struct skill_effect_cleanup_context*c,SOCKET s,unsigned room_epoch,unsigned battle_epoch,unsigned now,const char*reason,unsigned trigger_type){
    char p[4096];unsigned uid,elapsed,code,grade,generation;if(!c||!c->active)return 0;uid=multiplayer_current_uid();if(!uid)return 0;
    elapsed=(unsigned)(now-c->armed_tick);code=c->code;grade=c->grade;generation=c->generation;mkpkt(p,0xCF9D,0x0C,1);stable_put32(p,0x08,uid);sendbuf(s,p,0x0C);multiplayer_broadcast_raw(0xCF9D,(const unsigned char*)p,0x0C);c->active=0u;
    printf("  S0xCF9D SKILL_LIFECYCLE completion actor=%u code=%u grade=%u generation=%u elapsed_ms=%u room=%u battle=%u reason=%s trigger=0x%04X room_broadcast=1 len=12 t=%lds\n",uid,code,grade,generation,elapsed,room_epoch,battle_epoch,reason?reason:"unspecified",trigger_type,sec());fflush(0);return 1;
}
static int skill_effect_cleanup_maybe_send(struct skill_effect_cleanup_context*c,SOCKET s,unsigned room_epoch,unsigned battle_epoch,unsigned now,unsigned trigger_type){
    if(!c||!c->active)return 0;if(c->room_epoch!=room_epoch||c->battle_epoch!=battle_epoch){skill_effect_cleanup_reset(c,room_epoch,battle_epoch,"stale-epoch");return 0;}
    if((unsigned)(now-c->armed_tick)<SKILL_EFFECT_COMPLETION_DELAY_MS)return 0;return skill_effect_cleanup_send(c,s,room_epoch,battle_epoch,now,"elapsed",trigger_type);
}
static int skill_effect_cleanup_force_send(struct skill_effect_cleanup_context*c,SOCKET s,unsigned room_epoch,unsigned battle_epoch,unsigned now,const char*reason,unsigned trigger_type){
    return skill_effect_cleanup_send(c,s,room_epoch,battle_epoch,now,reason,trigger_type);
}
#endif
