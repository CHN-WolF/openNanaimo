#ifndef DUNGEON_SETTLEMENT_RESULT_POLICY_INC
#define DUNGEON_SETTLEMENT_RESULT_POLICY_INC
static unsigned dungeon_settlement_visible_rating(unsigned allow_progress){return allow_progress?5u:0u;}
/* Free death retry uses the same base-profile floor/cap as a death town return. */
static unsigned dungeon_death_return_hp(unsigned maximum_hp){unsigned hp=maximum_hp/6u;return hp?hp:1u;}
static unsigned dungeon_death_return_mp(unsigned current_mp,unsigned maximum_mp){return current_mp<maximum_mp?current_mp:maximum_mp;}
/* Only a completed battle can authorize progression at the result boundary. */
static unsigned dungeon_settlement_progress_allowed(unsigned requested,unsigned epoch,unsigned tuple_valid,unsigned terminal_required,unsigned terminal_seen){
    return requested&&epoch&&tuple_valid&&(!terminal_required||terminal_seen)?1u:0u;
}
#endif
