#ifndef NANAIMO_LUMINEOS_UNLOCK_PATCH_INC
#define NANAIMO_LUMINEOS_UNLOCK_PATCH_INC
/* Preserve the APARTMENTS helper/source and its exact-hash rebuild contract. */
#define nanaimo_unlock_all_dungeon_stages nanaimo_unlock_all_dungeon_stages_apartments_base
#include "../dungeon/unlock_patch.inc"
#undef nanaimo_unlock_all_dungeon_stages

/* C355 FULL FRAME +0x80/+0x84 -> sub_544000 (0x5441CC..0x5441E8)
 * -> sub_54EDD0 -> first progression object +0x48/+0x4C.
 * hd=4 page movement (0x500666..0x500ADA) requires sub_509EC0(k),
 * i.e. BOTH bits 2*k and 2*k+1, k=0..21. This is NOT +0xC8's
 * packed stage-display table (second progression object +0x40).
 * Local adapter policy: mark only the 22 predecessors needed to reach
 * all 23 Lumineos entries. Leave bit44..63, including final-clear pair22,
 * unchanged. Retain state1/0x55 display bytes, not highest-stage scores.
 * This patch adds no packet and no state: C354 still drives C355 and every
 * current C355 builder applies the policy after its final fixture writer.
 */
static int nanaimo_unlock_all_dungeon_stages(
    unsigned char *frame, int frame_len, unsigned int packed_state,
    int mark_first_progression_bits)
{
    int i;
    if (!nanaimo_unlock_all_dungeon_stages_apartments_base(
            frame, frame_len, packed_state, mark_first_progression_bits))
        return 0;
    if (mark_first_progression_bits) {
        for (i = 0x80; i < 0x85; ++i) frame[i] = 0xFF;
        frame[0x85] |= 0x0F; /* only 44 statically consumed prerequisite bits */
    }
    return 1;
}
#endif
