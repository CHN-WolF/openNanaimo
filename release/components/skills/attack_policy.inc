#ifndef NANAIMO_SP_ZX_ATTACK_POLICY_SKILL_SLOTS_INC
#define NANAIMO_SP_ZX_ATTACK_POLICY_SKILL_SLOTS_INC
/* Classification is a local adapter provenance label, not an original game endpoint
 * shape field.  D00D/D011 have no proven projectile/collision discriminator. */
static const char *zx_attack_policy(const struct stable_monster_hp_attack *a){
    if(a && a->provenance==MONSTER_HP_ATTACK_PON_CANDIDATE && a->owner>=505u && a->owner<=544u)
        return "projectile-skill-pon-candidate";
    if(a && a->provenance==MONSTER_HP_ATTACK_CONFIG_FALLBACK)
        return "fallback-unresolved";
    if(a && a->provenance==MONSTER_HP_ATTACK_TEST_OVERRIDE)
        return "test-override";
    if(a && a->provenance==MONSTER_HP_ATTACK_PON_CANDIDATE)
        return "pon-candidate";
    return "fallback-unresolved";
}
#endif
