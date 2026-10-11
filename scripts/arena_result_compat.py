"""Enter the initialized multiplayer result page after CF8A row publication."""
import struct

HOOK_VA = 0x006FBCFF
HOOK_OLD = b'\xE8' + struct.pack('<i', 0x0041B635 - HOOK_VA - 5)
CAVE_VA = 0x006E3500
CAVE_SPAN = 96
RESET_HOOK_VA = 0x006FBD88
RESET_CAVE_VA = CAVE_VA + CAVE_SPAN
RESET_CAVE_SPAN = 64
CLEANUP_CAVE_VA = RESET_CAVE_VA + RESET_CAVE_SPAN
CLEANUP_CAVE_SPAN = 80
# A previously installed rematch build kept a narrow game-type-1 guard while
# using the current manager/arena reset body. Keep this exact byte sequence as a bounded
# migration input; it is not a wildcard acceptance rule.
RESET_MIXED_LEGACY = bytes.fromhex(
    'e85966d3ff9c6080780301752e837808017228837808047722'
    '83b8f0100000067519c64007008b48348948408b0dc02fd70085'
    'c97405e845ca0600619dc3cccc'
)
def cleanup_encoding():
    code = bytearray()
    def call(target):
        code.extend(b'\xE8' + struct.pack('<i', target - CLEANUP_CAVE_VA - len(code) - 5))
    call(0x0041B635)
    code.extend(bytes.fromhex('9c60'))
    call(0x006658E0)
    jumps = []
    for compare, branch in (('80780301', 0x75), ('83780801', 0x72), ('83780804', 0x77)):
        code.extend(bytes.fromhex(compare))
        jumps.append(len(code)); code.extend(bytes([branch, 0]))
    code.extend(bytes.fromhex('83b8f010000004'))
    battle = len(code); code.extend(b'\x74\0')
    code.extend(bytes.fromhex('83b8f010000006'))
    jumps.append(len(code)); code.extend(b'\x75\0')
    code[battle + 1] = len(code) - battle - 2
    code.extend(bytes.fromhex('8b0dc02fd70085c9'))
    jumps.append(len(code)); code.extend(b'\x74\0')
    # Retire the old arena ending state before leaving its update loop.
    # This reset does not stop the world or alter the published result rows.
    call(0x0074FFE0)
    for jump in jumps:
        code[jump + 1] = len(code) - jump - 2
    code.extend(bytes.fromhex('619dc3'))
    if len(code) > CLEANUP_CAVE_SPAN:
        raise ValueError('Arena terminal cleanup exceeds reserved region')
    return bytes(code).ljust(CLEANUP_CAVE_SPAN, b'\xCC')
def reset_encodings(legacy=False, previous=False):
    code = bytearray(b'\xE8' + struct.pack('<i', 0x00419BBE - RESET_CAVE_VA - 5))
    def call(target):
        code.extend(b'\xE8' + struct.pack('<i', target - RESET_CAVE_VA - len(code) - 5))
    code.extend(bytes.fromhex('9c60'))
    jumps = []
    for compare, branch in (
        ('80780301', 0x75),  # Multiplayer arena mode, not PvE or entertainment.
        ('83780801', 0x72),
        ('83780804', 0x77),
    ):
        code.extend(bytes.fromhex(compare))
        jumps.append(len(code)); code.extend(bytes([branch, 0]))
    # The hook is the authorized CF8C rematch boundary itself. Keep the
    # current recipe independent of whether the manager has reached page 4
    # or page 6; the legacy migration retains the old page-6-only encoding.
    if legacy:
        code.extend(bytes.fromhex('83b8f010000006'))
        jumps.append(len(code)); code.extend(b'\x75\0')
    # The manager owns the leave latch. Activity counters belong to the
    # separate main-loop object and are initialized by native ready-page entry.
    code.extend(bytes.fromhex('c6400700'))
    if legacy or previous:
        code.extend(bytes.fromhex('8b4834894840'))
    if not legacy:
        # Reset only an existing arena instance, preserving the manager return.
        code.extend(bytes.fromhex('8b0dc02fd70085c9'))
        jumps.append(len(code)); code.extend(b'\x74\0')
        call(0x0074FFE0)
    for jump in jumps:
        code[jump + 1] = len(code) - jump - 2
    code.extend(bytes.fromhex('619dc3'))
    if len(code) > RESET_CAVE_SPAN:
        raise ValueError('Arena rematch activity reset exceeds reserved region')
    hook = b'\xE8' + struct.pack('<i', RESET_CAVE_VA - RESET_HOOK_VA - 5)
    return hook, bytes(code).ljust(RESET_CAVE_SPAN, b'\xCC')

def encodings(legacy=False):
    code = bytearray()
    def call(target):
        code.extend(b'\xE8' + struct.pack('<i', target - CAVE_VA - len(code) - 5))
    call(0x0041B635 if legacy else CLEANUP_CAVE_VA)
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
             b'\xE8' + struct.pack('<i', 0x00419BBE - RESET_HOOK_VA - 5), reset_hook),
            ('arena_terminal_cleanup_code', CLEANUP_CAVE_VA,
             b'\xCC' * CLEANUP_CAVE_SPAN, cleanup_encoding())]

def legacy_encodings(va):
    if va == CAVE_VA:
        return (encodings(legacy=True)[1],)
    if va == RESET_CAVE_VA:
        return (reset_encodings(legacy=True)[1], RESET_MIXED_LEGACY,
                reset_encodings(previous=True)[1])
    return ()
