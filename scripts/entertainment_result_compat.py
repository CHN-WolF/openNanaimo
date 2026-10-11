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
    return _patch_sites(245)


def legacy_patch_sites():
    """Exact previous encoding accepted during migration to the current recipe."""
    return _patch_sites(8)


def legacy_encodings(va):
    return tuple(target for _, address, _, target in legacy_patch_sites() if address == va)
