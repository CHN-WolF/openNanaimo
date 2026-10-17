"""Read a bounded client memory range with explicit process-read access."""
from __future__ import annotations

import argparse
import ctypes
import sys


def open_reader(pid: int):
    if sys.platform != 'win32':
        raise OSError('Windows read-only process access required')
    from ctypes import wintypes as w
    ptr = ctypes.c_void_p
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = ptr
    kernel.CloseHandle.argtypes = [ptr]
    kernel.ReadProcessMemory.argtypes = [ptr, ptr, ptr, ctypes.c_size_t,
                                         ctypes.POINTER(ctypes.c_size_t)]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def read(address: int, count: int) -> bytes:
        data = ctypes.create_string_buffer(count)
        actual = ctypes.c_size_t()
        if not kernel.ReadProcessMemory(handle, ptr(address), data, count,
                                        ctypes.byref(actual)):
            raise ctypes.WinError(ctypes.get_last_error())
        if actual.value != count:
            raise OSError('short read at 0x%X' % address)
        return data.raw
    return read, lambda: kernel.CloseHandle(handle)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--va', required=True, help='start virtual address')
    parser.add_argument('--len', default='0x40', help='byte count')
    parser.add_argument('--compare', help='file to compare the same bytes against')
    args = parser.parse_args(argv)

    va = int(args.va, 0)
    count = int(args.len, 0)
    read, close = open_reader(args.pid)
    try:
        alive = read(va, count)
    finally:
        close()
    for offset in range(0, count, 16):
        chunk = alive[offset:offset + 16]
        print('%08X  %-47s  %s' % (va + offset, chunk.hex(' '),
                                   ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)))
    if args.compare:
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from prepare_client_compatibility import _va_offset
        raw = Path(args.compare).read_bytes()
        disk = raw[_va_offset(raw, va, count):][:count]
        print('\ndisk == memory: %s' % (disk == alive))
        if disk != alive:
            for offset in range(count):
                if disk[offset] != alive[offset]:
                    print('first difference at %08X  disk %02X  memory %02X'
                          % (va + offset, disk[offset], alive[offset]))
                    break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
