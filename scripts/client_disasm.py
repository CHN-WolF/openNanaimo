"""Decode PE32 instructions, address mappings and direct control-flow references."""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capstone  # noqa: E402
from prepare_client_compatibility import _va_offset, _pe_sections  # noqa: E402

DEFAULT_CLIENT = Path(__file__).resolve().parents[1].parent / 'game.exe'


def image_base(data: bytes) -> int:
    return _pe_sections(data)[0][0]


def read_va(data: bytes, va: int, count: int) -> bytes:
    offset = _va_offset(data, va, count)
    return data[offset:offset + count]


def decode(data: bytes, va: int, length: int):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(read_va(data, va, length), va))


def render(insn) -> str:
    return '%08X  %-22s  %s %s' % (insn.address, insn.bytes.hex(), insn.mnemonic,
                                   insn.op_str)


def direct_calls(instructions) -> list[int]:
    targets = []
    for insn in instructions:
        if insn.mnemonic == 'call' and insn.operands:
            target = insn.operands[0]
            if target.type == capstone.x86.X86_OP_IMM:
                targets.append(int(target.imm))
    return targets


def xrefs(data: bytes, target: int) -> list[dict]:
    """Call/jump/push references to one address, scanned over every section.

    References to a data address (a string, a vtable, a global) live in the code
    section, not in the section that holds the target, so the whole image has to
    be searched. Every hit is rechecked by decoding from the found instruction so
    a byte sequence inside another instruction is not reported as a reference.
    """
    hits = []
    for base, span, raw, raw_size in _pe_sections(data):
        blob = data[raw:raw + raw_size]
        for offset in range(len(blob) - 5):
            va = base + offset
            opcode = blob[offset]
            if opcode in (0xE8, 0xE9):                      # call/jmp rel32
                if va + 5 + struct.unpack_from('<i', blob, offset + 1)[0] == target:
                    hits.append(va)
            elif opcode == 0x68:                            # push imm32
                if struct.unpack_from('<I', blob, offset + 1)[0] == target:
                    hits.append(va)
    confirmed = []
    for va in hits:
        try:
            insn = next(iter(decode(data, va, 8)))
        except StopIteration:
            continue
        if insn.address == va:
            confirmed.append(dict(va=va, text=render(insn)))
    return confirmed


def find_dword(data: bytes, value: int) -> list[int]:
    """Every place the exact 32-bit value appears, as a virtual address."""
    hits = []
    needle = struct.pack('<I', value)
    for base, span, raw, raw_size in _pe_sections(data):
        blob = data[raw:raw + raw_size]
        start = 0
        while True:
            found = blob.find(needle, start)
            if found < 0:
                break
            hits.append(base + found)
            start = found + 1
    return hits


def disp_refs(data: bytes, disp: int) -> list[dict]:
    """Instructions that reference one displacement, e.g. `mov ecx, [eax+0x250]`.

    The 4-byte little-endian displacement is located first, then the enclosing
    instruction is decoded from a few candidate starts. Only a decoded
    instruction whose text really contains the displacement is reported.
    """
    needle = struct.pack('<I', disp)
    rows = []
    for base, span, raw, raw_size in _pe_sections(data):
        blob = data[raw:raw + raw_size]
        start = 0
        while True:
            found = blob.find(needle, start)
            if found < 0:
                break
            start = found + 1
            for back in range(1, 8):
                va = base + found - back
                try:
                    insn = next(iter(decode(data, va, 16)))
                except (StopIteration, Exception):     # noqa: BLE001
                    continue
                length = len(insn.bytes)
                if (va + length == base + found + 4
                        and ('0x%x' % disp) in insn.op_str):
                    rows.append(dict(va=va, insn=insn))
                    break
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=DEFAULT_CLIENT)
    parser.add_argument('--at', help='start virtual address')
    parser.add_argument('--len', default='0x80', help='byte count (hex or dec)')
    parser.add_argument('--xref', help='list call/push references to this address')
    parser.add_argument('--dword', help='list every dword equal to this value (vtables)')
    parser.add_argument('--vtable', help='dump a vtable: its slots and their thunks')
    parser.add_argument('--disp', help='list instructions referencing this displacement')
    parser.add_argument('--calls', action='store_true', help='follow direct call targets')
    parser.add_argument('--follow', default='0x20', help='instructions to print per callee')
    args = parser.parse_args(argv)
    if not args.at and not args.xref and not args.dword and not args.vtable and not args.disp:
        parser.error('pass --at, --xref, --dword, --vtable or --disp')

    data = Path(args.client).read_bytes()
    print('image base %#010x  %s  bytes %d' % (image_base(data), args.client.name, len(data)))
    if args.disp:
        disp = int(args.disp, 0)
        rows = disp_refs(data, disp)
        print('%d instruction(s) referencing displacement %#x' % (len(rows), disp))
        for row in rows:
            print(render(row['insn']))
        return 0
    if args.vtable:
        start = int(args.vtable, 0)
        for slot in range(64):
            value = struct.unpack('<I', read_va(data, start + slot * 4, 4))[0]
            inside = any(base <= value < base + span
                         for base, span, _, _ in _pe_sections(data))
            if not inside:
                print('  slot %2d  %#010x  <end of vtable>' % (slot, value))
                break
            try:
                first = next(iter(decode(data, value, 5)))
                body = '%s %s' % (first.mnemonic, first.op_str)
            except StopIteration:
                body = '?'
            print('  slot %2d  %#010x  %-24s %s' % (slot, value, first.bytes.hex(), body))
        return 0
    if args.dword:
        value = int(args.dword, 0)
        found = find_dword(data, value)
        print('%d dword slot(s) holding %#010x' % (len(found), value))
        for va in found:
            print('%08X' % va)
        return 0
    if args.xref:
        found = xrefs(data, int(args.xref, 0))
        print('%d reference(s) to %#010x' % (len(found), int(args.xref, 0)))
        for row in found:
            print(row['text'])
        return 0

    start = int(args.at, 0)
    length = int(args.len, 0)
    instructions = decode(data, start, length)
    for insn in instructions:
        print(render(insn))
    if args.calls:
        limit = int(args.follow, 0)
        for target in dict.fromkeys(direct_calls(instructions)):
            print('\n--- call %#010x ---' % target)
            try:
                for insn in decode(data, target, 0x40)[:limit]:
                    print(render(insn))
            except Exception as exc:            # noqa: BLE001 - report, never abort
                print('  <unavailable: %s>' % exc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
