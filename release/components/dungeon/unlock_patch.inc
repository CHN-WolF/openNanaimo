#ifndef NANAIMO_DUNGEON_UNLOCK_PATCH_INC
#define NANAIMO_DUNGEON_UNLOCK_PATCH_INC

/*
 * C355 full-frame offsets, proven against game_decrypted.bin:
 *   +0x88..+0xC3: 20 dungeon ids * 3 difficulty/page bytes.
 *   Each byte packs four 2-bit internal-stage states.
 *   +0xC4..+0xC7 and +0xC8..+0xDE are the auxiliary progression domains.
 *
 * packed_state values accepted by the client renderer:
 *   0 -> no stage object, 1/2/3 -> three nonzero image/state sets.
 * For an unlock-only adapter fixture, use packed_state=1 (fill byte 0x55).
 * The legacy broad-open experiment used packed_state=3 (fill byte 0xFF),
 * which also forges the highest progression state and is not the default.
 *
 * This helper receives a COMPLETE C355 frame, including the 8-byte header.
 * Call it after copying/filling C355 and before sendbuf().  The current stable
 * sendbuf() recalculates the checksum from the final bytes.
 */

#define NANAIMO_C355_FRAME_LEN             0x2D8
#define NANAIMO_C355_FIRST_TABLE_BEGIN     0x03C
#define NANAIMO_C355_FIRST_TABLE_END       0x077
#define NANAIMO_C355_SECOND_BEGIN          0x088
#define NANAIMO_C355_SECOND_END            0x0DE

static unsigned char nanaimo_repeat_2bit_state(unsigned int state)
{
    state &= 3u;
    return (unsigned char)(state | (state << 2) | (state << 4) | (state << 6));
}

/* Returns 1 on patch applied, 0 on invalid input. */
static int nanaimo_unlock_all_dungeon_stages(
    unsigned char *frame,
    int frame_len,
    unsigned int packed_state,
    int mark_first_progression_bits)
{
    int i;
    unsigned char packed;
    if (!frame || frame_len < NANAIMO_C355_FRAME_LEN) return 0;
    if (frame[6] != 0x55 || frame[7] != 0xC3) return 0; /* opcode C355 LE */
    if (packed_state < 1u || packed_state > 3u) return 0;

    packed = nanaimo_repeat_2bit_state(packed_state);
    for (i = NANAIMO_C355_SECOND_BEGIN; i <= NANAIMO_C355_SECOND_END; ++i)
        frame[i] = packed;

    /* Optional and intentionally disabled by the recommended recipe.
       This first table is also consumed as availability/completion bits and
       by village-page prerequisite logic.  Enabling it marks all four bits,
       not merely UI visibility. */
    if (mark_first_progression_bits) {
        for (i = NANAIMO_C355_FIRST_TABLE_BEGIN;
             i <= NANAIMO_C355_FIRST_TABLE_END; ++i)
            frame[i] = 0x0F;
    }
    return 1;
}

#endif
