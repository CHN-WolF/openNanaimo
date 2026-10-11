"""Enter the initialized multiplayer result page after CF8A row publication."""
import struct

HOOK_VA = 0x006FBCFF
HOOK_OLD = b'\xE8' + struct.pack('<i', 0x0041B635 - HOOK_VA - 5)
CAVE_VA = 0x006E3500
CAVE_SPAN = 96
RESET_HOOK_VA = 0x006FBD88
RESET_CAVE_VA = CAVE_VA + CAVE_SPAN
RESET_CAVE_SPAN = 64

def reset_encodings():
    code = bytearray(b'\xE8' + struct.pack('<i', 0x00419BBE - RESET_CAVE_VA - 5))
    code.extend(bytes.fromhex('9c60'))
    jumps = []
    for compare, branch in (
        ('80780301', 0x75),  # Multiplayer arena mode, not PvE or entertainment.
        ('83780801', 0x72),
        ('83780804', 0x77),
        ('83b8f010000006', 0x75),  # Initialized PvP result page only.
    ):
        code.extend(bytes.fromhex(compare))
        jumps.append(len(code)); code.extend(bytes([branch, 0]))
    # An authorized shared rematch establishes a fresh activity boundary.
    # Explicit CF73 actions retain their native room-leave behavior.
    code.extend(bytes.fromhex('c64007008b4834894840'))
    for jump in jumps:
        code[jump + 1] = len(code) - jump - 2
    code.extend(bytes.fromhex('619dc3'))
    if len(code) > RESET_CAVE_SPAN:
        raise ValueError('Arena rematch activity reset exceeds reserved region')
    hook = b'\xE8' + struct.pack('<i', RESET_CAVE_VA - RESET_HOOK_VA - 5)
    return hook, bytes(code).ljust(RESET_CAVE_SPAN, b'\xCC')

def encodings():
    code = bytearray()
    def call(target):
        code.extend(b'\xE8' + struct.pack('<i', target - CAVE_VA - len(code) - 5))
    call(0x0041B635)  # Complete native row sorting before entering the page.
    code.extend(bytes.fromhex('9c60'))
    call(0x006658E0)
    code.extend(bytes.fromhex('80780301'))
    skip_mode = len(code); code.extend(b'\x75\0')
    code.extend(bytes.fromhex('83b8f010000004'))
    battle = len(code); code.extend(b'\x74\0')
    code.extend(bytes.fromhex('83b8f010000006'))
    skip_page = len(code); code.extend(b'\x75\0')
    result = len(code); code.extend(b'\xEB\0')
    code[battle + 1] = len(code) - battle - 2
    code.extend(bytes.fromhex('6a068bc8'))
    call(0x006692E0)
    code[result + 1] = len(code) - result - 2
    call(0x0040ED77)
    code.extend(bytes.fromhex('8d700c8db80c010000b940000000fcf3a5'))
    code.extend(bytes.fromhex('8db0100200008db820020000b904000000f3a5'))
    for jump in (skip_mode, skip_page):
        code[jump + 1] = len(code) - jump - 2
    code.extend(bytes.fromhex('619dc3'))
    if len(code) > CAVE_SPAN:
        raise ValueError('Arena result entry exceeds reserved region')
    hook = b'\xE8' + struct.pack('<i', CAVE_VA - HOOK_VA - 5)
    return hook, bytes(code).ljust(CAVE_SPAN, b'\xCC')

def patch_sites():
    hook, code = encodings()
    reset_hook, reset_code = reset_encodings()
    return [('arena_result_entry_code', CAVE_VA, b'\xCC' * CAVE_SPAN, code),
            ('arena_result_entry', HOOK_VA, HOOK_OLD, hook),
            ('arena_rematch_activity_code', RESET_CAVE_VA, b'\xCC' * RESET_CAVE_SPAN, reset_code),
            ('arena_rematch_activity', RESET_HOOK_VA,
             b'\xE8' + struct.pack('<i', 0x00419BBE - RESET_HOOK_VA - 5), reset_hook)]
