"""Client-owned fifth-village challenge selection, before native room submission."""
import struct

CALL_VA = 0x72F265
CALL_OLD = bytes.fromhex('E8419ACDFF')
CODE_VA = 0x6E33C0
CODE_SPAN = 64


def code(last_entry=11):
    # This callsite belongs to the chapter-100 branch. Retain the native
    # resource-dungeon setter and select the resource-complete challenge tuple.
    body = bytearray.fromhex('9C528BC18B54240C899138E50100')
    jumps = []
    body += bytes.fromhex('83B930E5010000')  # hd == 0
    jumps.append(len(body)); body += b'\x75\x00'
    body += bytes.fromhex('8B914CE5010083EA0883FA') + bytes([last_entry - 8])  # entries 8..11
    jumps.append(len(body)); body += b'\x77\x00'
    body += bytes.fromhex('83C218899148E50100C7814CE5010000000000')
    end = len(body)
    body += bytes.fromhex('5A9DC20400')
    for at in jumps: body[at + 1] = end - at - 2
    if len(body) > CODE_SPAN: raise ValueError('challenge selection code exceeds reserved size')
    return bytes(body).ljust(CODE_SPAN, b'\xCC')


def sites():
    return (
        ('monk_native_selection_code', CODE_VA, b'\xCC' * CODE_SPAN, code()),
        ('monk_native_selection_call', CALL_VA, CALL_OLD,
         b'\xE8' + struct.pack('<i', CODE_VA - CALL_VA - 5)),
    )


def legacy_encodings(va):
    return (code(8),) if va == CODE_VA else ()
