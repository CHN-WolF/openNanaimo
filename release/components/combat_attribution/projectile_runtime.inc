#ifndef NANAIMO_PROJECTILE_RUNTIME_PROJECTILE_ATTRIBUTION_INC
#define NANAIMO_PROJECTILE_RUNTIME_PROJECTILE_ATTRIBUTION_INC
/* PROJECTILE_ATTRIBUTION projectile attribution context.  The 8-second window and PON values
 * are local adapter attribution/damage candidates, not an original game endpoint
 * duration or damage formula.  CF9B/CF9C only arms attribution; D00D/D011
 * remain the sole HP-changing triggers. */
#define PROJECTILE_ACTIVATION_WINDOW_MS 8000u
struct projectile_activation_context {
    unsigned active,code,grade,expected_owner,activation_tick,room_epoch,battle_epoch;
};
static int projectile_skill_code(unsigned code){return code>=52000000u&&code<=52000007u;}
static unsigned projectile_expected_owner(unsigned code,unsigned grade){
    if(!projectile_skill_code(code)||grade<1u||grade>5u)return 0u;
    return 505u+(code-52000000u)*5u+(grade-1u);
}
static void projectile_activation_reset(struct projectile_activation_context*c,unsigned room_epoch,unsigned battle_epoch,const char*reason){
    if(!c)return;memset(c,0,sizeof(*c));c->room_epoch=room_epoch;c->battle_epoch=battle_epoch;
    printf("  [PROJECTILE] reset reason=%s room=%u battle=%u\n",reason?reason:"unspecified",room_epoch,battle_epoch);fflush(0);
}
static void projectile_activation_arm(struct projectile_activation_context*c,unsigned code,unsigned grade,unsigned room_epoch,unsigned battle_epoch,unsigned now){
    unsigned owner=projectile_expected_owner(code,grade);if(!c||!owner)return;
    c->active=1u;c->code=code;c->grade=grade;c->expected_owner=owner;c->activation_tick=now;c->room_epoch=room_epoch;c->battle_epoch=battle_epoch;
    printf("  [PROJECTILE] activate code=%u grade=%u expected_owner=%u tick=%u room=%u battle=%u window_ms=%u policy=private-attribution-context\n",code,grade,owner,now,room_epoch,battle_epoch,PROJECTILE_ACTIVATION_WINDOW_MS);fflush(0);
}
static int projectile_activation_matches(const struct projectile_activation_context*c,unsigned owner,unsigned room_epoch,unsigned battle_epoch,unsigned now){
    if(!c||!c->active||owner!=c->expected_owner||room_epoch!=c->room_epoch||battle_epoch!=c->battle_epoch)return 0;
    return (unsigned)(now-c->activation_tick)<=PROJECTILE_ACTIVATION_WINDOW_MS;
}
/* Strict only for a context-verified projectile report: the exact original
 * source slot must exist and be positive.  No nearest/first-positive borrowing
 * and no configured fallback are allowed in this branch. */
static void projectile_resolve_strict_source(unsigned owner,unsigned source,struct stable_monster_hp_attack*out){
    unsigned i;stable_monster_hp_zero_attack(out);out->owner=owner;out->source=source;
    for(i=0u;i<HP_SYNC_ATTACK_CANDIDATE_COUNT;i++){
        const struct hp_sync_attack_candidate*r=&hp_sync_attack_candidates[i];
        if((unsigned)r->key!=owner)continue;out->resource=r->resource;
        if(source<(unsigned)r->count&&hp_sync_attack_candidate_values[r->first_value+source]>0){
            out->value=hp_sync_attack_candidate_values[r->first_value+source];out->have_value=1u;out->provenance=MONSTER_HP_ATTACK_PON_CANDIDATE;
        }
#if TEAMPLAY_FEATURE_PROJECTILE_ONE_PAST_ALIAS
        else if(source==(unsigned)r->count&&r->count>0u){
            unsigned j;
            /* Retained runtime reports use exactly one-past on the final
               projectile source. Borrow only the nearest trailing positive
               value, mark it as an alias, and never accept source>count. */
            for(j=(unsigned)r->count;j>0u;j--){int v=hp_sync_attack_candidate_values[r->first_value+j-1u];if(v>0){out->value=v;out->have_value=1u;out->provenance=MONSTER_HP_ATTACK_PON_ONE_PAST_ALIAS;break;}}
        }
#endif
        return;
    }
}
static void projectile_apply_effective_attack(const struct projectile_activation_context*c,struct stable_monster_hp_attack*a){
#if TEAMPLAY_FEATURE_PROJECTILE_CODE7_EFFECTIVE_ATTACK
    if(c&&a&&c->active&&c->code==52000007u&&c->grade==5u&&c->expected_owner==544u&&a->owner==544u&&a->have_value&&a->value==1000){
        /* SURRENDER_REARM original-client correlation: local D011 damage1565 on basis235
           closes the current-profile effective attack at1800. This remains a
           bounded local adapter policy until the actor bonus writer is closed. */
        a->value=1800;a->provenance=MONSTER_HP_ATTACK_PROJECTILE_EFFECTIVE;
    }
#else
    (void)c;(void)a;
#endif
}
static const char*projectile_policy_label(const struct stable_monster_hp_attack*a,int verified){
    if(verified&&a&&a->have_value&&a->provenance==MONSTER_HP_ATTACK_PROJECTILE_EFFECTIVE)return "projectile-skill-profile-effective";
    if(verified&&a&&a->have_value&&a->provenance==MONSTER_HP_ATTACK_PON_ONE_PAST_ALIAS)return "projectile-skill-pon-one-past";
    if(verified&&a&&a->have_value&&a->provenance==MONSTER_HP_ATTACK_PON_CANDIDATE)return "projectile-skill-pon-verified";
    if(verified)return "projectile-skill-source-unresolved";
    if(a&&a->provenance==MONSTER_HP_ATTACK_PON_CANDIDATE&&a->owner>=505u&&a->owner<=544u)return "projectile-owner-unverified-pon-candidate";
    if(a&&a->provenance==MONSTER_HP_ATTACK_PON_CANDIDATE)return "pon-candidate";
    if(a&&a->provenance==MONSTER_HP_ATTACK_CONFIG_FALLBACK)return "fallback-unresolved";
    if(a&&a->provenance==MONSTER_HP_ATTACK_TEST_OVERRIDE)return "test-override";
    return "unresolved";
}
#endif
