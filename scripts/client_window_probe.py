"""Read the native window registry, object types and linked window records."""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client_memory_probe import open_reader  # noqa: E402

HOLDER_GLOBAL = 0xD730D0
HOLDER_FLAG = 0xD730CE
LIST_OFFSET = 8
LINK_OFFSET = 0x18            # draw-list link (what the late draw walks)
CATEGORY_LINK_OFFSET = 0x1C   # category lookup walks this link instead

KNOWN = {
    0x6E4000: 'guide/dialogue window class (kind 9, size 0x400, paged text + portrait)',
    0xC597F8: 'native panel class (ctor 0x62E800, init writes kind at +4)',
    0x48C23C: 'chapter payload window (only in a chapter-patched build)',
}


def u32(blob: bytes, offset: int = 0) -> int:
    return struct.unpack_from('<I', blob, offset)[0]


def enumerate_windows(read, limit: int = 64) -> dict:
    flag = read(HOLDER_FLAG, 1)[0]
    holder = u32(read(HOLDER_GLOBAL, 4))
    result = dict(holder_flag=flag, holder=holder, registry=0, head=0, windows=[])
    if not flag or not holder:
        result['note'] = 'registry singleton not created yet'
        return result
    registry = u32(read(holder, 4))
    result['registry'] = registry
    if not registry:
        result['note'] = 'holder has no registry object'
        return result
    head = u32(read(registry + LIST_OFFSET, 4))
    result['head'] = head
    seen = set()
    node = head
    while node and node not in seen and len(result['windows']) < limit:
        seen.add(node)
        raw = read(node, 0x38)
        vtable = u32(raw, 0)
        row = dict(address=node, vtable=vtable,
                   name=KNOWN.get(vtable, ''),
                   kind=u32(raw, 4), next=u32(raw, LINK_OFFSET),
                   category_next=u32(raw, CATEGORY_LINK_OFFSET),
                   word_34=struct.unpack_from('<H', raw, 0x34)[0])
        result['windows'].append(row)
        node = row['next']
    if node and node in seen:
        result['note'] = 'list loops back to %#x' % node
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--limit', type=int, default=64)
    parser.add_argument('--raw', nargs='*', type=lambda t: int(t, 0),
                        help='extra window offsets to print, e.g. 0x200 0x250')
    parser.add_argument('--name', action='store_true',
                        help='also decode the GBK display name at window+0x200')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    read, close = open_reader(args.pid)
    try:
        snapshot = enumerate_windows(read, args.limit)
        extra = {}
        for offset in args.raw or []:
            for row in snapshot['windows']:
                extra.setdefault(row['address'], {})[hex(offset)] = \
                    u32(read(row['address'] + offset, 4))
        if args.name:
            for row in snapshot['windows']:
                raw = read(row['address'] + 0x200, 16).split(b'\0')[0]
                row['display_name'] = raw.decode('gbk', 'replace')
    finally:
        close()
    for address, fields in extra.items():
        for row in snapshot['windows']:
            if row['address'] == address:
                row['extra'] = fields
    if args.json:
        print(json.dumps(snapshot, indent=2))
        return 0
    print('holder flag %d  holder %#x  registry %#x  head %#x'
          % (snapshot['holder_flag'], snapshot['holder'],
             snapshot['registry'], snapshot['head']))
    if snapshot.get('note'):
        print('note: ' + snapshot['note'])
    print('%d window(s) in the draw list' % len(snapshot['windows']))
    for row in snapshot['windows']:
        label = row['name']
        if row.get('display_name'):
            label = (label + ' ' if label else '') + ascii(row['display_name'])
        print('  %08X  vtable %08X  kind %-4d word34 %-3d next %08X  %s'
              % (row['address'], row['vtable'], row['kind'], row['word_34'],
                 row['next'], label))
        for key, value in (row.get('extra') or {}).items():
            print('            %-8s %#x' % (key, value))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
