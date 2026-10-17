"""Read chapter window state after validating the exact payload identity."""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chapter_dialogue_patch as patch  # noqa: E402


def u32(blob: bytes, offset: int) -> int:
    return struct.unpack_from('<I', blob, offset)[0]


def read_probe(pid: int) -> dict:
    """Read the payload window: cave head .. text-table start."""
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
    handle = kernel.OpenProcess(0x410, False, pid)  # QUERY_INFORMATION | VM_READ only
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

    try:
        state = read(patch.CAVE, patch.NAME + patch.NAME_BYTES - patch.CAVE)
        hook = read(patch.HOOK_SITE, 5)
        tag = read(patch.CAVE + patch.SPAN - len(patch.TAG), len(patch.TAG))
        selector = read(patch.SELECT, patch.TEXT - patch.SELECT)
        return dict(state=state, hook=hook, tag=tag, selector=selector)
    finally:
        kernel.CloseHandle(handle)


def describe(raw: bytes) -> dict:
    base = patch.CAVE

    def at(va: int) -> int:
        return va - base

    def dword(va: int) -> int:
        return u32(raw, at(va))

    probe = {}
    if at(patch.PROBE) + 0x40 <= len(raw):
        base_probe = raw[at(patch.PROBE):at(patch.PROBE) + 0x40]
        probe['village'] = u32(base_probe, 0)
        probe['village_fields'] = {hex(off): u32(base_probe, 4 + i * 4)
                                   for i, off in enumerate(patch.PROBE_OFFSETS)}
        probe['guide'] = u32(base_probe, 0x20)
        probe['guide_fields'] = {hex(off): u32(base_probe, 0x24 + i * 4)
                                 for i, off in enumerate(patch.PROBE_OFFSETS)}

    return {
        'mark': dword(patch.MARK),
        'armed': dword(patch.ARMED),
        'last': dword(patch.LAST),
        'status': dword(patch.GUARD),
        'saved_esp': dword(patch.SAVED_ESP),
        'our_window': dword(patch.OUR_WINDOW),
        'segment': dword(patch.SEG),
        'matched_quest': dword(patch.QUEST_SLOT),
        'last_quest': dword(patch.LAST_QUEST),
        'active_quest': dword(patch.ACTIVE_QUEST),
        'active_phase': dword(patch.ACTIVE_PHASE),
        'owner_pages': dword(patch.OWNER + patch.OWNER_PAGES),
        'owner_count': dword(patch.OWNER + patch.OWNER_COUNT),
        'page': dword(patch.PAGE_SLOT),
        'counter': dword(patch.COUNTER),
        'arm_frame': dword(patch.ARM_FRAME),
        'gate_frame': dword(patch.GATE_FRAME),
        'gate_flag': dword(patch.GATE_FLAG),
        'suppress': raw[at(patch.SUPPRESS)],
        'probe': probe,
        'name': raw[at(patch.NAME):at(patch.NAME) + patch.NAME_BYTES].split(b'\0')[0].decode('gbk', 'replace'),
        'portrait_path': raw[at(patch.PORTRAIT_PATH):at(patch.PORTRAIT_PATH) + 64]
                                .split(b'\0')[0].decode('ascii', 'replace'),
    }


STAGES = {1: 'enter hook', 2: 'task record found', 3: 'objective matched',
          0xFF: 'stack breadcrumb pushed', 0x0A: 'done, chained to the native call'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    data = read_probe(args.pid)
    expected = patch.build(patch.default_texts(), patch.default_triggers())
    expected_hook = b'\xE8' + struct.pack('<i', patch.UPDATE - patch.HOOK_SITE - 5)
    installed = {
        'hook': data['hook'].hex() == expected_hook.hex(),
        'tag': data['tag'] == patch.TAG,
        'update': data['state'][:expected['report']['update_bytes']] ==
                  expected['payload'][:expected['report']['update_bytes']],
        'selector': data['selector'] ==
                    expected['payload'][patch.SELECT - patch.CAVE:patch.TEXT - patch.CAVE],
    }
    if not all(installed.values()):
        print(json.dumps(dict(pid=args.pid, installed=installed, live=None)))
        print('patch version differs; state not interpreted', file=sys.stderr)
        return 2
    live = describe(data['state'])
    result = dict(pid=args.pid, cave=hex(patch.CAVE), installed=installed,
                  stage=STAGES.get(live['mark'], 'unknown'), live=live)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print('pid %d  cave 0x%X' % (args.pid, patch.CAVE))
        print('installed: ' + ', '.join('%s=%s' % (k, 'yes' if v else 'NO')
                                        for k, v in installed.items()))
        print('stage: %s (mark %#x)' % (result['stage'], live['mark']))
        for key, value in live.items():
            if isinstance(value, int):
                shown = hex(value)
            else:  # console codepage may not carry the GBK name
                shown = ascii(value)
            print('  %-14s %s' % (key, shown))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
