#ifndef NANAIMO_SP_ZX_SKILL_STATE_SKILL_SLOTS_INC
#define NANAIMO_SP_ZX_SKILL_STATE_SKILL_SLOTS_INC
/* C3E8 type40 +0x50 is a statically closed unsigned WORD SP snapshot.
 * All known client consumers use MOVZX and the skill-cost gate compares this
 * value against the SK._D35 WORD cost.  0xFFFF is therefore the maximum value
 * representable by the proven carrier. */
#define ZX_SKILL_SP_MAX 65535u
#define ZX_SKILL_GRADE_MAX 5u
#define ZX_SKILL_CODE_MIN 52000000u
#define ZX_SKILL_CODE_MAX 52000015u
static int zx_skill_code_valid(unsigned code){return code>=ZX_SKILL_CODE_MIN&&code<=ZX_SKILL_CODE_MAX;}
#endif
