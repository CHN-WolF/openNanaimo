#ifndef NANAIMO_BATTLE_SCORE_RUNTIME_BATTLE_SCORE_INC
#define NANAIMO_BATTLE_SCORE_RUNTIME_BATTLE_SCORE_INC
#define BATTLE_SCORE_KIND_ORDINARY 1u
#define BATTLE_SCORE_KIND_BOSS 2u
struct battle_score_context {unsigned total,battle_epoch,applied_hit_count,ordinary_damage,boss_damage,reset_count;};
static void battle_score_init(struct battle_score_context*c){memset(c,0,sizeof(*c));}
static void battle_score_reset_transport(struct battle_score_context*c){unsigned resets=c->reset_count+1u;memset(c,0,sizeof(*c));c->reset_count=resets;}
static void battle_score_begin(struct battle_score_context*c,unsigned battle_epoch){c->total=0u;c->battle_epoch=battle_epoch;c->applied_hit_count=0u;c->ordinary_damage=0u;c->boss_damage=0u;}
static unsigned battle_score_add(struct battle_score_context*c,unsigned damage,unsigned kind){unsigned before=c->total;if(damage>0xFFFFFFFFu-before)c->total=0xFFFFFFFFu;else c->total=before+damage;if(damage){c->applied_hit_count++;if(kind==BATTLE_SCORE_KIND_BOSS){if(damage>0xFFFFFFFFu-c->boss_damage)c->boss_damage=0xFFFFFFFFu;else c->boss_damage+=damage;}else{if(damage>0xFFFFFFFFu-c->ordinary_damage)c->ordinary_damage=0xFFFFFFFFu;else c->ordinary_damage+=damage;}}return c->total;}
#endif
