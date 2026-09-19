#ifndef ATTACK_MODE_POWERUP_RUNTIME_INC
#define ATTACK_MODE_POWERUP_RUNTIME_INC
#define ATTACK_MODE_AUTO 0xFFFFFFFFu
struct attack_mode_powerup_context {
    unsigned configured_initial_mode; /* advisory until a wire setter is proven */
    unsigned observed_power_stage;
    unsigned power_pickups;
    unsigned hp_pickups;
    unsigned mp_pickups;
    unsigned speed_pickups;
    unsigned battle_epoch;
};
static void attack_mode_powerup_reset(struct attack_mode_powerup_context *x,unsigned configured,unsigned epoch){
    x->configured_initial_mode=configured;
    x->observed_power_stage=(configured<=3u)?configured:0u;
    x->power_pickups=0;x->hp_pickups=0;x->mp_pickups=0;x->speed_pickups=0;x->battle_epoch=epoch;
}
static unsigned attack_mode_powerup_pick(struct attack_mode_powerup_context *x,unsigned item_type){
    if(item_type==1u){if(x->observed_power_stage<3u)x->observed_power_stage++;x->power_pickups++;}
    else if(item_type==2u)x->hp_pickups++;
    else if(item_type==3u)x->mp_pickups++;
    else if(item_type==4u)x->speed_pickups++;
    return x->observed_power_stage;
}
#endif
