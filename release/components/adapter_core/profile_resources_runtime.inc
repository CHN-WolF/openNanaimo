#ifndef NANAIMO_PROFILE_RESOURCES_RUNTIME_INC
#define NANAIMO_PROFILE_RESOURCES_RUNTIME_INC

/* Candidate-only profile resource state. Protocol widths:
   HP/MP are unsigned 16-bit little-endian; the two account balances are
   unsigned 64-bit little-endian low/high DWORD pairs. */
typedef unsigned long long stable_u64;
static unsigned g_profile_hp_max=1500u;
static unsigned g_profile_hp_current=1500u;
static unsigned g_profile_mp_max=500u;
static unsigned g_profile_mp_current=500u;
#if TEAMPLAY_FEATURE_PLAYER_COMBAT_STATS
/* MULTIPLAYER_COMBAT local adapter combat attributes. Attack is the unsigned additive
   modifier mirrored into CFEC +0x2E0; defense is a adapter-side flat reduction
   applied before absolute HP injury replies. Neither is an original formula. */
static unsigned g_profile_attack_modifier=0u;
static unsigned g_profile_defense_flat=0u;
#endif
static stable_u64 g_profile_coin_hans=0ull;
static stable_u64 g_profile_nana_cash=0ull;
static unsigned g_profile_seen_hp_max=0u,g_profile_seen_hp_current=0u;
static unsigned g_profile_seen_mp_max=0u,g_profile_seen_mp_current=0u;
static int g_profile_resources_valid=1;
/* PROFILE_RESOURCES card-album key carriers. C3E8 stores four counted key slots as
   BYTE +0x40..+0x43 and the time-limited/free-key availability flag at
   WORD +0x88. The cached YYYYMMDDHH current/expiry values use +0x4C/+0x84. */
static unsigned g_profile_card_key_normal=99u;
static unsigned g_profile_card_key_gold=99u;
static unsigned g_profile_card_key_mystery=99u;
static unsigned g_profile_card_key_special=99u;
static unsigned g_profile_free_magic_key_current=2026090100u;
static unsigned g_profile_free_magic_key_expiry=2099123123u;

static int stable_resource_key(const char *line,const char *key,const char **value){
    const char *a=line,*b=key;
    while(*b && *a==*b){a++;b++;}
    if(*b || *a!='=')return 0;
    *value=a+1;return 1;
}
static int stable_parse_u64_strict(const char *s,stable_u64 *out){
    stable_u64 v=0ull,maxv=~(stable_u64)0;unsigned digit,n=0u;
    while(*s>='0'&&*s<='9'){
        digit=(unsigned)(*s-'0');
        if(v>(maxv-(stable_u64)digit)/10ull)return 0;
        v=v*10ull+(stable_u64)digit;s++;n++;
    }
    if(n==0u)return 0;
    if(*s!='\0'&&*s!='\r'&&*s!='\n')return 0;
    *out=v;return 1;
}
static int stable_profile_resource_bad(const char *key,const char *line){
    printf("  [PROFILE_RESOURCE] invalid %s line=%s",key,line);fflush(0);
    g_profile_resources_valid=0;return 1;
}
/* Returns 1 for a recognized resource key (valid or invalid), 0 for unknown. */
static int stable_profile_resources_parse_line(const char *line){
    const char *s;stable_u64 v;
    if(stable_resource_key(line,"hp_max",&s)){
        if(!stable_parse_u64_strict(s,&v)||v<1ull||v>65535ull)return stable_profile_resource_bad("hp_max",line);
        g_profile_hp_max=(unsigned)v;g_profile_seen_hp_max=1u;return 1;
    }
    if(stable_resource_key(line,"hp_current",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>65535ull)return stable_profile_resource_bad("hp_current",line);
        g_profile_hp_current=(unsigned)v;g_profile_seen_hp_current=1u;return 1;
    }
    if(stable_resource_key(line,"mp_max",&s)){
        if(!stable_parse_u64_strict(s,&v)||v<1ull||v>65535ull)return stable_profile_resource_bad("mp_max",line);
        g_profile_mp_max=(unsigned)v;g_profile_seen_mp_max=1u;return 1;
    }
    if(stable_resource_key(line,"mp_current",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>65535ull)return stable_profile_resource_bad("mp_current",line);
        g_profile_mp_current=(unsigned)v;g_profile_seen_mp_current=1u;return 1;
    }
#if TEAMPLAY_FEATURE_PLAYER_COMBAT_STATS
    if(stable_resource_key(line,"attack",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>1000000ull)return stable_profile_resource_bad("attack",line);
        g_profile_attack_modifier=(unsigned)v;return 1;
    }
    if(stable_resource_key(line,"defense",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>65535ull)return stable_profile_resource_bad("defense",line);
        g_profile_defense_flat=(unsigned)v;return 1;
    }
#endif
    if(stable_resource_key(line,"coin",&s)){
        if(!stable_parse_u64_strict(s,&v))return stable_profile_resource_bad("coin",line);
        g_profile_coin_hans=v;return 1;
    }
    if(stable_resource_key(line,"nana_point",&s)){
        if(!stable_parse_u64_strict(s,&v))return stable_profile_resource_bad("nana_point",line);
        g_profile_nana_cash=v;return 1;
    }
    if(stable_resource_key(line,"card_key_normal",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>255ull)return stable_profile_resource_bad("card_key_normal",line);
        g_profile_card_key_normal=(unsigned)v;return 1;
    }
    if(stable_resource_key(line,"card_key_gold",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>255ull)return stable_profile_resource_bad("card_key_gold",line);
        g_profile_card_key_gold=(unsigned)v;return 1;
    }
    if(stable_resource_key(line,"card_key_mystery",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>255ull)return stable_profile_resource_bad("card_key_mystery",line);
        g_profile_card_key_mystery=(unsigned)v;return 1;
    }
    if(stable_resource_key(line,"card_key_special",&s)){
        if(!stable_parse_u64_strict(s,&v)||v>255ull)return stable_profile_resource_bad("card_key_special",line);
        g_profile_card_key_special=(unsigned)v;return 1;
    }
    if(stable_resource_key(line,"free_magic_key_expiry",&s)){
        if(!stable_parse_u64_strict(s,&v)||v<2000010100ull||v>2100123123ull)return stable_profile_resource_bad("free_magic_key_expiry",line);
        g_profile_free_magic_key_expiry=(unsigned)v;return 1;
    }
    return 0;
}
static void stable_profile_resources_finalize(void){
    if(g_profile_seen_hp_max&&!g_profile_seen_hp_current)g_profile_hp_current=g_profile_hp_max;
    if(g_profile_seen_mp_max&&!g_profile_seen_mp_current)g_profile_mp_current=g_profile_mp_max;
    if(g_profile_hp_current>g_profile_hp_max){printf("  [PROFILE_RESOURCE] hp_current=%u exceeds hp_max=%u\n",g_profile_hp_current,g_profile_hp_max);g_profile_resources_valid=0;}
    if(g_profile_mp_current>g_profile_mp_max){printf("  [PROFILE_RESOURCE] mp_current=%u exceeds mp_max=%u\n",g_profile_mp_current,g_profile_mp_max);g_profile_resources_valid=0;}
    printf("  [PROFILE_RESOURCE] hp=%u/%u mp=%u/%u coin_hans=%u:%u nana_cash=%u:%u valid=%d\n",
        g_profile_hp_current,g_profile_hp_max,g_profile_mp_current,g_profile_mp_max,
        (unsigned)(g_profile_coin_hans>>32),(unsigned)g_profile_coin_hans,
        (unsigned)(g_profile_nana_cash>>32),(unsigned)g_profile_nana_cash,g_profile_resources_valid);fflush(0);
#if TEAMPLAY_FEATURE_PLAYER_COMBAT_STATS
    printf("  [PLAYER_COMBAT] attack_modifier=%u defense_flat=%u attack_carrier=CFEC+0x2E0 defense_policy=max(1,raw-defense) original_formula=0\n",g_profile_attack_modifier,g_profile_defense_flat);fflush(0);
#endif
    printf("  [CARD_KEY_RESOURCE] normal=%u gold=%u mystery=%u special=%u free_current=%u free_expiry=%u enabled=%u\n",
        g_profile_card_key_normal,g_profile_card_key_gold,g_profile_card_key_mystery,g_profile_card_key_special,
        g_profile_free_magic_key_current,g_profile_free_magic_key_expiry,
        g_profile_free_magic_key_expiry>g_profile_free_magic_key_current?1u:0u);fflush(0);
}
static void stable_resource_put16(char *p,int off,unsigned v){p[off]=(char)v;p[off+1]=(char)(v>>8);}
static void stable_resource_put64(char *p,int off,stable_u64 v){
    int i;for(i=0;i<8;i++)p[off+i]=(char)(v>>(i*8));
}
static void stable_profile_write_c368(char *p){
    stable_resource_put16(p,0x34,g_profile_hp_max);stable_resource_put16(p,0x36,g_profile_mp_max);
    stable_resource_put16(p,0x38,g_profile_hp_current);stable_resource_put16(p,0x3A,g_profile_mp_current);
}
static void stable_profile_write_cf71(char *p){
    stable_resource_put16(p,0x4A,g_profile_hp_max);stable_resource_put16(p,0x4C,g_profile_mp_max);
    stable_resource_put16(p,0x4E,g_profile_hp_current);stable_resource_put16(p,0x50,g_profile_mp_current);
}
static void stable_profile_write_c379_balances(char *p){
    stable_resource_put64(p,0xD0,g_profile_coin_hans);stable_resource_put64(p,0xD8,g_profile_nana_cash);
}
static void stable_profile_write_c37b_balances(char *p){
    stable_resource_put64(p,0x08,g_profile_coin_hans);stable_resource_put64(p,0x10,g_profile_nana_cash);
}
static void stable_profile_write_d010_hp(char *p,unsigned hp){stable_resource_put16(p,0x10,hp);}

#endif
