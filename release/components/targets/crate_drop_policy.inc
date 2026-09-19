/*
 * crate_drop_policy.inc
 * Nanaimo crate/item-block drop policy sidecar.
 *
 * Proven original behavior:
 *   item_block_00.mmo has reward_kind=5.
 *   Every matched D00E/200 subtype0 for the item-block target consumes one
 *   CFEC random-type entry and creates one category-40 scene item.
 *   Original game endpoint answers every D00D, so simultaneous hits legitimately
 *   create multiple items from one visual block.
 *
 * Default mode preserves that behavior. SINGLE_VISUAL is an optional local
 * preference and is explicitly not original game endpoint faithful.
 */
#ifndef NANAIMO_CRATE_DROP_POLICY_INC
#define NANAIMO_CRATE_DROP_POLICY_INC

#include "crate_drop_profiles.inc"

#define CRATE_DROP_KIND_NONE       0u
#define CRATE_DROP_KIND_ITEM_BLOCK 1u
#define CRATE_DROP_KIND_EVENT_BOX  2u
#define CRATE_DROP_REWARD_RANDOM   5u
#define CRATE_DROP_MODE_ORIGINAL   0u
#define CRATE_DROP_MODE_SINGLE_VISUAL 1u
#define CRATE_DROP_DEDUPE_CAP 4096u

struct crate_drop_seen_row {
    unsigned selector;
    unsigned generation;
};
struct crate_drop_policy_context {
    unsigned mode;
    unsigned stage;
    unsigned difficulty;
    unsigned segment;
    unsigned profile_active;
    unsigned seen_count;
    struct crate_drop_seen_row seen[CRATE_DROP_DEDUPE_CAP];
};

static void crate_drop_policy_init(struct crate_drop_policy_context *ctx, unsigned mode) {
    ctx->mode=mode; ctx->stage=0; ctx->difficulty=0; ctx->segment=0;
    ctx->profile_active=0; ctx->seen_count=0;
}
static void crate_drop_policy_select_profile(struct crate_drop_policy_context *ctx,
                                              unsigned stage, unsigned difficulty,
                                              unsigned segment) {
    ctx->stage=stage; ctx->difficulty=difficulty; ctx->segment=segment;
    ctx->profile_active=1; ctx->seen_count=0;
}
static unsigned crate_drop_profile_kind(unsigned stage, unsigned difficulty,
                                        unsigned segment, unsigned selector,
                                        unsigned *reward_kind_out) {
    unsigned i;
    if(reward_kind_out) *reward_kind_out=0;
    if(selector>65535u) return CRATE_DROP_KIND_NONE;
    for(i=0;i<CRATE_DROP_PROFILE_COUNT;i++) {
        const struct crate_drop_profile_row *r=&g_crate_drop_profiles[i];
        if(r->stage==stage && r->difficulty==difficulty && r->segment==segment &&
           r->selector==(unsigned short)selector) {
            if(reward_kind_out) *reward_kind_out=r->reward_kind;
            return r->crate_kind;
        }
    }
    return CRATE_DROP_KIND_NONE;
}
static unsigned crate_drop_policy_profile_kind(const struct crate_drop_policy_context *ctx,
                                               unsigned selector,
                                               unsigned *reward_kind_out) {
    if (reward_kind_out) *reward_kind_out=0;
    if (!ctx || !ctx->profile_active) return CRATE_DROP_KIND_NONE;
    return crate_drop_profile_kind(ctx->stage,ctx->difficulty,ctx->segment,
                                   selector,reward_kind_out);
}

/* Return 1 when the existing proven D00E sender should run.
 * ORIGINAL mode always preserves one D00E per D00D, including repeated hits.
 * SINGLE_VISUAL suppresses only repeated reward_kind=5 item-block reports for
 * the same selector generation; monsters, event boxes, and unknown selectors
 * are untouched. */
static int crate_drop_should_send_d00e(struct crate_drop_policy_context *ctx,
                                       unsigned selector, unsigned generation,
                                       unsigned crate_kind, unsigned reward_kind) {
    unsigned i;
    if(ctx->mode==CRATE_DROP_MODE_ORIGINAL) return 1;
    if(crate_kind!=CRATE_DROP_KIND_ITEM_BLOCK || reward_kind!=CRATE_DROP_REWARD_RANDOM) return 1;
    for(i=0;i<ctx->seen_count;i++)
        if(ctx->seen[i].selector==selector && ctx->seen[i].generation==generation) return 0;
    if(ctx->seen_count<CRATE_DROP_DEDUPE_CAP) {
        ctx->seen[ctx->seen_count].selector=selector;
        ctx->seen[ctx->seen_count].generation=generation;
        ctx->seen_count++;
    }
    /* Capacity exhaustion fails open: never make later targets unkillable. */
    return 1;
}

#endif
