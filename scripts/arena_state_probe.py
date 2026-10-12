"""Read arena state with bounded, version-checked process access."""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import time

from prepare_client_compatibility import _va_offset

# Exact signatures for singleton getters, reset and countdown.
SIGNATURES = {
    0x6658E0: 'd55f99a6dc95f856f8fff8ae72a1790f7b47e4cb6a27d0b15b114eb1b2bd0670',
    0x66E8A0: 'd34fd3d09db183292cf7cffd3dab081d21dcf5c72d827b9fd2f631c9c1d32578',
    0x74FFE0: '6d1389aa99b5689c17feb8b98131b90d1dc4701e59091e135d0c11efde6895b9',
    0x709C80: '2dde731fc8f1c2321ff7c3e4b2fffe5845e3f174577d081b1ea7c1f458e38f7f',
}


def decode_snapshot(read):
    """Separate pure bounded reads from Win32 access for fixture validation."""
    def u32(address): return struct.unpack('<I', read(address, 4))[0]
    def u8(address): return read(address, 1)[0]
    def f32(address): return struct.unpack("<f", read(address, 4))[0]
    result = {}
    definitions = {
        'manager': (0xD72CE4, 0xD72CE8, {'mode': (3, 1), 'consecutive_losses': (8, 4), 'page': (0x10F0, 4),
                              'leave_latch': (7, 1), 'world_enabled': (1, 1),
                              'previous_page': (0x10EC, 4),
                              'battle_limit': (0x1E5C8, 'f32'), 'battle_elapsed': (0x1E5CC, 'f32')}),
        'world': (0xD72D1E, 0xD72D20, {'running': (0, 4), 'update_gate': (4, 4), 'local_actor': (0x14, 4), 'stage': (0x24, 4)}),
        'arena': (0xD72FBE, 0xD72FC0, {'state': (0x1C, 4), 'previous_state': (0x18, 4),
                           'update_counter': (0xC, 4), 'end_latch': (0x124, 4), 'animation': (0x20, 4)}),
        'ready': (0xD72EB6, 0xD72EB8, {'state': (0x24, 4), 'previous_state': (0x20, 4),
                                     'start_requested': (0x10, 4), 'map_loaded': (0x14, 4)}),
        'countdown': (0xD72E8C, 0xD72E90, {'started': (0, 4), 'go_played': (4, 4),
                               'tick': (8, 4), 'start_tick': (12, 4), 'animation': (16, 4)}),
    }
    for name, (flag, slot, fields) in definitions.items():
        try:
            address = u32(slot)
            initialized = u8(flag)
            row = {'address': address, 'initialized': initialized}
            if initialized and address:
                row.update({key: ({'f32': f32, 1: u8, 4: u32}[width])(address + offset)
                            for key, (offset, width) in fields.items()})
            result[name] = row
        except (OSError, ValueError, struct.error, IndexError) as exc:
            result[name] = {'error': str(exc)}
    return result


def snapshot_process(pid):
    if os.name != 'nt': raise OSError('Windows read-only process access required')
    from ctypes import wintypes as w
    ptr = ctypes.c_void_p
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = ptr
    kernel.CloseHandle.argtypes = [ptr]
    kernel.ReadProcessMemory.argtypes = [ptr, ptr, ptr, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel.QueryFullProcessImageNameW.argtypes = [ptr, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    handle = kernel.OpenProcess(0x410, False, pid)  # QUERY_INFORMATION | VM_READ only
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        def read(address, count):
            data = ctypes.create_string_buffer(count); actual = ctypes.c_size_t()
            if not kernel.ReadProcessMemory(handle, ptr(address), data, count, ctypes.byref(actual)):
                raise ctypes.WinError(ctypes.get_last_error())
            if actual.value != count: raise OSError('short process-memory read')
            return data.raw
        path = ctypes.create_unicode_buffer(32768); length = w.DWORD(len(path))
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        image = Path(path.value); raw = image.read_bytes()
        for va, expected in SIGNATURES.items():
            off = _va_offset(raw, va, 32)
            if hashlib.sha256(raw[off:off+32]).hexdigest() != expected:
                raise ValueError(f'unsupported disk code at {va:#x}')
            if hashlib.sha256(read(va, 32)).hexdigest() != expected:
                raise ValueError(f'unsupported loaded code at {va:#x}; no state interpretation')
        return {'pid': pid, 'image': str(image), 'size': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'states': decode_snapshot(read)}
    finally:
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, action='append', required=True)
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--interval', type=float, default=1.0)
    args = parser.parse_args()
    if not 1 <= args.samples <= 300 or not 0.05 <= args.interval <= 60 or any(p <= 0 for p in args.pid):
        parser.error('require positive PIDs, samples 1..300 and interval 0.05..60 seconds')
    failed = False
    for index in range(args.samples):
        rows = []
        for pid in args.pid:
            try: rows.append(snapshot_process(pid))
            except (OSError, ValueError, struct.error) as exc:
                rows.append({'pid': pid, 'error': str(exc)}); failed = True
        print(json.dumps({'sample': index, 'utc': datetime.now(timezone.utc).isoformat(),
                          'monotonic_ns': time.monotonic_ns(), 'processes': rows}), flush=True)
        if index + 1 < args.samples: time.sleep(args.interval)
    return int(failed)


if __name__ == '__main__': raise SystemExit(main())
