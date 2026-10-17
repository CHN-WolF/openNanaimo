"""Resolve client text records and their encoded representations."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_client_compatibility import _va_offset  # noqa: E402

DEFAULT_CLIENT = Path(__file__).resolve().parents[1].parent / 'game.exe'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=DEFAULT_CLIENT)
    parser.add_argument('--at', nargs='+', required=True, help='virtual addresses')
    parser.add_argument('--len', type=int, default=160, help='max bytes to read')
    args = parser.parse_args(argv)

    data = Path(args.client).read_bytes()
    for token in args.at:
        va = int(token, 0)
        raw = data[_va_offset(data, va, 8):][:args.len]
        text = raw.split(b'\0')[0]
        try:
            decoded = text.decode('gbk')
        except UnicodeDecodeError:
            decoded = text.decode('latin-1')
        print('%#010x  %r' % (va, decoded))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
