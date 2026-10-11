"""Bounded same-room record refresh for the entertainment settings controller."""
import struct

ENTRY_VA = 0x00643500
ENTRY_OLD = bytes.fromhex('558bec83ec08')
CAVE_VA = 0x006E3600
CAVE_SPAN = 256
MAGIC = 0x31305245


def encoding():
    code = bytearray(ENTRY_OLD + bytes.fromhex('9c60'))
    labels, fixes = {}, []
    def branch(op, label):
        fixes.append((len(code) + len(op), label))
        code.extend(op + bytes(4))
    def call(va):
        code.extend(b'\xe8' + struct.pack('<i', va - CAVE_VA - len(code) - 5))
    code.extend(bytes.fromhex('8b4508668378042c'))
    branch(b'\x0f\x84', 'resume')
    code.extend(bytes.fromhex('6683780450'))
    branch(b'\x0f\x85', 'finish')
    code.extend(bytes.fromhex('81782c') + struct.pack('<I', MAGIC))
    branch(b'\x0f\x85', 'finish')
    code.extend(bytes.fromhex('80784f00'))
    branch(b'\x0f\x85', 'finish')
    code.extend(bytes.fromhex('8b0dd469d80085c9'))
    branch(b'\x0f\x84', 'finish')
    code.extend(bytes.fromhex('0fb691d005000083fa01'))
    branch(b'\x0f\x82', 'finish')
    code.extend(bytes.fromhex('83fa03'))
    branch(b'\x0f\x87', 'finish')
    code.extend(bytes.fromhex('8b50303b915c0d0000'))
    branch(b'\x0f\x85', 'finish')
    code.extend(bytes.fromhex('ff7034'))
    call(0x00A750E0)
    code.extend(bytes.fromhex('8b450883c038508b0dd469d800'))
    call(0x00A75120)
    labels['resume'] = len(code)
    code.extend(bytes.fromhex('619d'))
    code.extend(b'\xe9' + struct.pack('<i', ENTRY_VA + 6 - CAVE_VA - len(code) - 5))
    labels['finish'] = len(code)
    code.extend(bytes.fromhex('619d'))
    code.extend(b'\xe9' + struct.pack('<i', 0x00643545 - CAVE_VA - len(code) - 5))
    for at, label in fixes:
        struct.pack_into('<i', code, at, labels[label] - at - 4)
    assert len(code) <= CAVE_SPAN
    return bytes(code).ljust(CAVE_SPAN, b'\xcc')


def patch_sites():
    return [
        ('entertainment_room_record_body', CAVE_VA, b'\xcc' * CAVE_SPAN, encoding()),
        ('entertainment_room_record_entry', ENTRY_VA, ENTRY_OLD,
         b'\xe9' + struct.pack('<i', CAVE_VA - ENTRY_VA - 5) + b'\x90'),
    ]
