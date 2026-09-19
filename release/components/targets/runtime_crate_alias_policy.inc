/*
 * Evidence-only runtime selector aliases for visual item blocks.
 *
 * These are NOT a general "unknown selector" suppression rule.  They join
 * selectors observed on the wire to item_block_00.mmo rows from a later
 * stage segment whose selector allocation shares the live manager domain.
 */
#ifndef NANAIMO_RUNTIME_CRATE_ALIAS_POLICY_INC
#define NANAIMO_RUNTIME_CRATE_ALIAS_POLICY_INC

struct runtime_crate_alias_row {
    unsigned short actual_selector;
    unsigned short local_selector;
    unsigned char stage;
    unsigned char segment;
    unsigned char crate_kind;
    unsigned char reward_kind;
};

static const struct runtime_crate_alias_row g_runtime_crate_aliases[] = {
    {291u, 18u, 0u, 1u, CRATE_DROP_KIND_ITEM_BLOCK, 5u}, /* integrated1 + 1_full + 3 battle1 */
    {366u, 93u, 0u, 1u, CRATE_DROP_KIND_ITEM_BLOCK, 5u}, /* integrated1 */
    {420u,127u, 0u, 1u, CRATE_DROP_KIND_ITEM_BLOCK, 5u}, /* integrated1 duplicate -> UID7/UID8 */
    {374u, 11u, 1u, 1u, CRATE_DROP_KIND_ITEM_BLOCK, 5u}, /* 6_battle */
    {409u, 46u, 1u, 1u, CRATE_DROP_KIND_ITEM_BLOCK, 5u}, /* 6_battle triple D00E */
};
#define RUNTIME_CRATE_ALIAS_COUNT ((unsigned)(sizeof(g_runtime_crate_aliases)/sizeof(g_runtime_crate_aliases[0])))

static const struct runtime_crate_alias_row *runtime_crate_alias_find(unsigned stage,
                                                                      unsigned selector) {
    unsigned i;
    if (selector > 0xFFFFu) return 0;
    for (i=0; i<RUNTIME_CRATE_ALIAS_COUNT; ++i) {
        const struct runtime_crate_alias_row *r=&g_runtime_crate_aliases[i];
        if ((unsigned)r->stage==stage && (unsigned)r->actual_selector==selector) return r;
    }
    return 0;
}

#endif
