"""CF86 lucky-card ranking compatibility for the special-card catalogue."""
import struct

CAVE_VA = 0x006E3400
CAVE_SPAN = 192
CLASSIFY_VA = 0x0064A423
CLASSIFY_OLD = bytes.fromhex('817d1080f0fa020f86ac000000')
NAME_VA = 0x0064AC90
NAME_OLD = bytes.fromhex('e8e104ddff')
PREVIEW_VA = 0x0064401F
PREVIEW_OLD = bytes.fromhex('e80740dcff')


def _patch_sites(image_offset):
    code = bytearray()
    def branch(op, target):
        code.extend(op + struct.pack('<i', target - (CAVE_VA + len(code) + len(op) + 4)))
    # Keep normal/SP/event rendering untouched; only opened lucky cards bypass
    # 9BED50, whose domain13/12-only lookup would be dereferenced at 64A4F8.
    code.extend(bytes.fromhex('817d10') + struct.pack('<I', 22000011))
    lower = len(code); code.extend(b'\x72\0')
    code.extend(bytes.fromhex('817d10') + struct.pack('<I', 22000018))
    branch(b'\x0F\x86', 0x0064A430)
    code[lower + 1] = len(code) - lower - 2
    code.extend(CLASSIFY_OLD[:7])
    branch(b'\x0F\x86', 0x0064A4DC)
    branch(b'\xE9', 0x0064A430)
    code.extend(b'\xCC' * (64 - len(code)))
    name = CAVE_VA + len(code)
    code.extend(bytes.fromhex('8b4424043d') + struct.pack('<I', 22000011))
    lower = len(code); code.extend(b'\x72\0')
    code.extend(b'\x3D' + struct.pack('<I', 22000018))
    upper = len(code); code.extend(b'\x77\0')
    code.extend(bytes.fromhex('508b0dd469d800'))
    branch(b'\xE8', 0x0041DEB2)
    code.extend(bytes.fromhex('8bc8'))
    branch(b'\xE8', 0x00407C7A)
    if image_offset == 8:
        code.extend(bytes.fromhex('83c008'))
    else:
        code.extend(b'\x05' + struct.pack('<I', image_offset))
    code.extend(bytes.fromhex('c20400'))
    fallback = len(code)
    for at in (lower, upper): code[at + 1] = fallback - at - 2
    branch(b'\xE9', 0x0041B176)
    code.extend(b'\xCC' * (128 - len(code)))
    preview = CAVE_VA + len(code)
    # The optional large normal-card preview has no special-card layout. Clear
    # those slots while keeping the three actual prizes in the ranked rows.
    code.extend(bytes.fromhex('8b4424083d') + struct.pack('<I', 22000011))
    lower = len(code); code.extend(b'\x72\0')
    code.extend(b'\x3D' + struct.pack('<I', 22000018))
    upper = len(code); code.extend(b'\x77\0')
    code.extend(bytes.fromhex('c744240800000000'))
    fallback = len(code)
    for at in (lower, upper): code[at + 1] = fallback - at - 2
    branch(b'\xE9', 0x0064B060)
    assert len(code) <= CAVE_SPAN
    def hook(va, target, span, opcode):
        return opcode + struct.pack('<i', target - va - 5) + b'\x90' * (span - 5)
    return [
        ('entertainment_result_lucky_code', CAVE_VA, b'\xCC' * CAVE_SPAN, bytes(code).ljust(CAVE_SPAN, b'\xCC')),
        ('entertainment_result_lucky_kind', CLASSIFY_VA, CLASSIFY_OLD, hook(CLASSIFY_VA, CAVE_VA, len(CLASSIFY_OLD), b'\xE9')),
        ('entertainment_result_lucky_name', NAME_VA, NAME_OLD, hook(NAME_VA, name, 5, b'\xE8')),
        ('entertainment_result_lucky_preview', PREVIEW_VA, PREVIEW_OLD, hook(PREVIEW_VA, preview, 5, b'\xE8')),
    ]


def patch_sites():
    # 64AC9F passes this result to the image loader, not to a text renderer.
    # 87EE00 uses special record+245 for the card-name bitmap; +8 is prose.
    return _patch_sites(245) + level_patch_sites()


def legacy_patch_sites():
    """Exact previous encoding accepted during migration to the current recipe."""
    return _patch_sites(8)


def legacy_encodings(va):
    sites = (legacy_patch_sites() + _previous_current_level_patch_sites() +
             _legacy_level_patch_sites(False) + _legacy_level_patch_sites(True))
    return tuple(dict.fromkeys(target for _, address, _, target in sites if address == va))


# CF86 record+5 reaches 637B10 -> result-controller+16. Native 637530
# feeds level/10 to the ten-frame digit sprite; AB35E0 clamps 12 to 9.
# +4 is an animation flag, not an auxiliary level. Sprite vtable+16 updates
# cached frame +72; only vtable+20 draws. Keep those phases separate.
LEVEL_CAVE_VA = 0x006E3700
LEVEL_CAVE_SPAN = 256
LEVEL_UPDATE_VA = 0x006377D9
LEVEL_UPDATE_OLD = bytes.fromhex('8b45c88b401099b90a000000f7f9508b55c88b4a2ce87dafdcff')
LEVEL_LEGACY_DRAW_VA = 0x00637845
LEVEL_LEGACY_DRAW_OLD = bytes.fromhex('e8735cddff')
LEVEL_DRAW_VA = 0x006374BA
LEVEL_DRAW_OLD = bytes.fromhex('e8e022deff')


def _legacy_level_patch_sites(auxiliary):
    """Exact failed recipes, accepted only to migrate them out of clients."""
    code = bytearray()
    def branch32(op, target, base=LEVEL_CAVE_VA):
        code.extend(op + struct.pack('<i', target - (base + len(code) + len(op) + 4)))

    # The native code passes level / 10 to the tens sprite. Divide twice so
    # the tens frame is (level / 10) % 10, then resume the native ones path.
    select = '83f80a7f0d8b55c88b4a0483f90a7e0289c8' if auxiliary else ''
    code.extend(bytes.fromhex('8b45c88b4010' + select + '31d2b90a000000f7f131d2f7f1528b55c88b4a2c'))
    branch32(b'\xE8', 0x00402770)
    branch32(b'\xE9', 0x006377F3)
    code.extend(b'\xCC' * (64 - len(code)))
    draw = LEVEL_CAVE_VA + len(code)

    # Borrow the native tens digit object for the hundreds digit only during
    # this refresh. Preserve the object frame, position, registers and flags.
    code.extend(b'\x9c\x60')
    code.extend(bytes.fromhex('8b55c88b4210' + select + '31d2b964000000f7f185c074'))
    skip = len(code); code.append(0)
    code.extend(bytes.fromhex('8b55c88b4a2c8b4144508b410450'))
    code.extend(bytes.fromhex('8b55c88b421031d2b964000000f7f1'))
    code.extend(bytes.fromhex('8b55c88b4a2c894144'))
    code.extend(b'\x68' + struct.pack('<f', 306.0))
    code.extend(bytes.fromhex('8b55c88b4a2c'))
    branch32(b'\xE8', 0x00409372)
    code.extend(bytes.fromhex('8b01ff50105889410458894144619d'))
    restore = len(code) - 2
    code[skip] = restore - skip - 1
    branch32(b'\xE9', 0x0063784A)
    assert len(code) <= LEVEL_CAVE_SPAN
    def hook(va, target, span):
        return b'\xE9' + struct.pack('<i', target - va - 5) + b'\x90' * (span - 5)
    return [
        ('entertainment_result_level_code', LEVEL_CAVE_VA, b'\xCC' * LEVEL_CAVE_SPAN,
         bytes(code).ljust(LEVEL_CAVE_SPAN, b'\xCC')),
        ('entertainment_result_level_tens', LEVEL_UPDATE_VA, LEVEL_UPDATE_OLD,
         hook(LEVEL_UPDATE_VA, LEVEL_CAVE_VA, len(LEVEL_UPDATE_OLD))),
        ('entertainment_result_level_restore_update', LEVEL_LEGACY_DRAW_VA, LEVEL_LEGACY_DRAW_OLD,
         hook(LEVEL_LEGACY_DRAW_VA, draw, len(LEVEL_LEGACY_DRAW_OLD))),
    ]


def _previous_current_level_patch_sites():
    """The immediately previous accepted three-digit recipe, for migration."""
    code = bytearray()
    def branch32(op, target):
        code.extend(op + struct.pack('<i', target - (LEVEL_CAVE_VA + len(code) + len(op) + 4)))
    code.extend(bytes.fromhex('8b45c88b401031d2b90a000000f7f131d2f7f1528b55c88b4a2c'))
    branch32(b'\xE8', 0x00402770)
    branch32(b'\xE9', 0x006377F3)
    code.extend(b'\xCC' * (64 - len(code)))
    draw = LEVEL_CAVE_VA + len(code)
    code.extend(bytes.fromhex('9c608bd98b431031d2b964000000f7f185c074'))
    skip = len(code); code.append(0)
    code.extend(bytes.fromhex('8b732c81ec6c0100008bfc8beeB95b000000fcf3a58bf5894644'))
    code.extend(b'\x68' + struct.pack('<f', 306.0))
    code.extend(bytes.fromhex('8bce'))
    branch32(b'\xE8', 0x00409372)
    code.extend(bytes.fromhex('8bce8b01ff50108bce8b01ff5014'))
    code.extend(bytes.fromhex('8bfe8bf4b95b000000fcf3a581c46c010000'))
    code[skip] = len(code) - skip - 1
    code.extend(bytes.fromhex('619d'))
    branch32(b'\xE9', 0x0041979F)
    def hook(va, target, span, op=b'\xE9'):
        return op + struct.pack('<i', target - va - 5) + b'\x90' * (span - 5)
    return [
        ('entertainment_result_level_code', LEVEL_CAVE_VA, b'\xCC' * LEVEL_CAVE_SPAN,
         bytes(code).ljust(LEVEL_CAVE_SPAN, b'\xCC')),
        ('entertainment_result_level_tens', LEVEL_UPDATE_VA, LEVEL_UPDATE_OLD,
         hook(LEVEL_UPDATE_VA, LEVEL_CAVE_VA, len(LEVEL_UPDATE_OLD))),
        ('entertainment_result_level_restore_update', LEVEL_LEGACY_DRAW_VA,
         LEVEL_LEGACY_DRAW_OLD, LEVEL_LEGACY_DRAW_OLD),
        ('entertainment_result_level_hundreds', LEVEL_DRAW_VA, LEVEL_DRAW_OLD,
         hook(LEVEL_DRAW_VA, draw, 5, b'\xE8')),
    ]


def level_patch_sites():
    code = bytearray()
    def branch(op, target):
        code.extend(op + struct.pack('<i', target - (LEVEL_CAVE_VA + len(code) + len(op) + 4)))

    code.extend(bytes.fromhex('8b45c88b401031d2b90a000000f7f131d2f7f1528b55c88b4a2c'))
    branch(b'\xE8', 0x402770)
    branch(b'\xE9', 0x6377F3)
    code.extend(b'\xCC' * (64 - len(code)))
    draw = LEVEL_CAVE_VA + len(code)
    code.extend(bytes.fromhex('9c608bd98b431031d2b964000000f7f185c074'))
    skip = len(code)
    code.append(0)
    # Save the entire 364-byte native sprite, including animation cache/ticks.
    # Calls use the original object; no shallow-copy object escapes to the engine.
    code.extend(bytes.fromhex('8b732c81ec6c0100008bfc8beeB95b000000fcf3a58bf5894644'))
    code.extend(b'\x68' + struct.pack('<f', 310.5))
    code.extend(bytes.fromhex('8bce'))
    branch(b'\xE8', 0x409372)
    code.extend(bytes.fromhex('8bce8b01ff50108bce8b01ff5014'))
    code.extend(bytes.fromhex('8bfe8bf4b95b000000fcf3a581c46c010000'))
    code[skip] = len(code) - skip - 1
    code.extend(bytes.fromhex('619d'))
    # Tail-call the displaced progress renderer with original ECX and stack.
    branch(b'\xE9', 0x41979F)

    # Refresh both native digits at absolute positions. The original object
    # adds its own +0x0C offset, so these inputs are the pre-offset values.
    adjust = LEVEL_CAVE_VA + len(code)
    code.extend(b'\x9c\x60\x8b\xd9\x8b\x43\x10\x83\xf8\x64')
    below = len(code)
    code.extend(b'\x72\x00')
    # Three digits: shift the original pair right by half a digit width.
    code.extend(bytes.fromhex('8b4b28') + b'\x68' + struct.pack('<f', 328.5))
    branch(b'\xE8', 0x00409372)
    code.extend(bytes.fromhex('8b4b2c') + b'\x68' + struct.pack('<f', 319.5))
    branch(b'\xE8', 0x00409372)
    join = len(code)
    branch(b'\xE9', 0)
    # Two digits: restore native positions after a high-level result.
    two = len(code)
    code.extend(bytes.fromhex('8b4b28') + b'\x68' + struct.pack('<f', 324.0))
    branch(b'\xE8', 0x00409372)
    code.extend(bytes.fromhex('8b4b2c') + b'\x68' + struct.pack('<f', 315.0))
    branch(b'\xE8', 0x00409372)
    common = len(code)
    code.extend(bytes.fromhex('8bcb'))
    branch(b'\xE8', 0x0040D4BD)
    code.extend(b'\x61\x9d')
    branch(b'\xE9', 0x0063784A)
    code[below + 1] = two - below - 2
    struct.pack_into('<i', code, join + 1, common - (join + 5))
    assert len(code) <= LEVEL_CAVE_SPAN
    def hook(va, target, span, op=b'\xE9'):
        return op + struct.pack('<i', target - va - 5) + b'\x90' * (span - 5)
    return [
        ('entertainment_result_level_code', LEVEL_CAVE_VA, b'\xCC' * LEVEL_CAVE_SPAN,
         bytes(code).ljust(LEVEL_CAVE_SPAN, b'\xCC')),
        ('entertainment_result_level_tens', LEVEL_UPDATE_VA, LEVEL_UPDATE_OLD,
         hook(LEVEL_UPDATE_VA, LEVEL_CAVE_VA, len(LEVEL_UPDATE_OLD))),
        ('entertainment_result_level_restore_update', LEVEL_LEGACY_DRAW_VA,
         LEVEL_LEGACY_DRAW_OLD,
         hook(LEVEL_LEGACY_DRAW_VA, adjust, 5)),
        ('entertainment_result_level_hundreds', LEVEL_DRAW_VA, LEVEL_DRAW_OLD,
         hook(LEVEL_DRAW_VA, draw, 5, b'\xE8')),
    ]
