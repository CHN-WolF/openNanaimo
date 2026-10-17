"""Locate requested byte patterns within readable client memory ranges."""
from __future__ import annotations

import argparse
import ctypes
import struct
import sys

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}   # RO / RW / WC / EXEC_RW / RW_*


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.c_ulong), ("RegionSize", ctypes.c_size_t),
                ("State", ctypes.c_ulong), ("Protect", ctypes.c_ulong),
                ("Type", ctypes.c_ulong)]


def open_reader(pid: int):
    from ctypes import wintypes as w
    ptr = ctypes.c_void_p
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = ptr
    kernel.CloseHandle.argtypes = [ptr]
    kernel.ReadProcessMemory.argtypes = [ptr, ptr, ptr, ctypes.c_size_t,
                                         ctypes.POINTER(ctypes.c_size_t)]
    kernel.VirtualQueryEx.argtypes = [ptr, ptr, ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                                      ctypes.c_size_t]
    kernel.VirtualQueryEx.restype = ctypes.c_size_t
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def read(address: int, count: int) -> bytes:
        buffer = ctypes.create_string_buffer(count)
        got = ctypes.c_size_t()
        if not kernel.ReadProcessMemory(handle, ptr(address), buffer, count, ctypes.byref(got)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw[:got.value]

    def regions():
        address = 0
        info = MEMORY_BASIC_INFORMATION()
        while True:
            if not kernel.VirtualQueryEx(handle, ptr(address), ctypes.byref(info),
                                         ctypes.sizeof(info)):
                break
            base, size = int(info.BaseAddress or 0), int(info.RegionSize or 0)
            if not size:
                break
            if (info.State == MEM_COMMIT and info.Protect not in (PAGE_NOACCESS, PAGE_GUARD)
                    and (info.Protect & 0xFF) in READABLE and info.Type != 0x1000000):
                yield base, size
            address = base + size
    return read, regions, lambda: kernel.CloseHandle(handle)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--gbk', help='text to encode as GBK')
    parser.add_argument('--hex', help='raw byte pattern')
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--window', default='0x30', help='bytes to dump before the match')
    args = parser.parse_args(argv)

    if args.gbk:
        needle = args.gbk.encode('gbk')
    elif args.hex:
        needle = bytes.fromhex(args.hex)
    else:
        parser.error('pass --gbk or --hex')

    read, regions, close = open_reader(args.pid)
    before = int(args.window, 0)
    hits = []
    try:
        for base, size in regions():
            try:
                blob = read(base, min(size, 8 << 20))
            except OSError:
                continue
            offset = blob.find(needle)
            while offset >= 0 and len(hits) < args.limit:
                hits.append((base + offset, blob, offset, base))
                offset = blob.find(needle, offset + 1)
            if len(hits) >= args.limit:
                break
    finally:
        close()

    print('%d match(es) for %d bytes' % (len(hits), len(needle)))
    for address, blob, offset, base in hits:
        start = max(0, offset - before)
        chunk = blob[start:offset + 16]
        print('\n%08X  (region %08X)' % (address, base))
        for line in range(0, len(chunk), 16):
            piece = chunk[line:line + 16]
            print('  %08X  %-47s  %s' % (address - (offset - start) + line,
                                         piece.hex(' '),
                                         ''.join(chr(b) if 32 <= b < 127 else '.' for b in piece)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
