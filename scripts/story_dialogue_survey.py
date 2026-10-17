"""Report image layout, text-table signatures and contiguous allocation regions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_qt_patch as shared  # noqa: E402

SCHEMA = 'openNanaimo.story-dialogue-survey.v1'
MEMORY_LIST = 5
LITERALS = (b'NANA_QUEST_TEXT', b'QT._D30', b'QS._D31')
KNOWN_FUNCTIONS = {0x98EE10: 'objective parser', 0x4D5ED0: 'C59C dispatcher'}
MINIMUM_CAVE = 4096


IMAGE_PROBE = 0x98EE10


def load_ranges(dump: Path) -> list[tuple[int, int, int]]:
    raw = Path(dump).read_bytes()
    shared.require(raw[:4] == b'MDMP', 'Not a minidump: ' + str(dump))
    _, _, count, directory = struct.unpack_from('<IIII', raw, 0)
    for index in range(count):
        stream_type, _, offset = struct.unpack_from('<III', raw, directory + index * 12)
        if stream_type != MEMORY_LIST:
            continue
        ranges, = struct.unpack_from('<I', raw, offset)
        return [struct.unpack_from('<QII', raw, offset + 4 + row * 16) for row in range(ranges)]
    raise ValueError('Dump has no memory list: ' + str(dump))


def pick_image(ranges: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """Prefer the range that holds the known objective parser, then the image base."""
    for row in ranges:
        if row[0] <= IMAGE_PROBE < row[0] + row[1]:
            return row
    for row in ranges:
        if row[0] in (0x400000, 0x401000):
            return row
    shared.require(ranges, 'Dump memory list is empty')
    return max(ranges, key=lambda row: row[1])


def load_image(dump: Path) -> tuple[int, bytes]:
    """Return (base, bytes) of the unpacked client image inside a minidump."""
    raw = Path(dump).read_bytes()
    start, size, rva = pick_image(load_ranges(dump))
    return start, raw[rva:rva + size]


def runs(image: bytes, byte: int, minimum: int) -> list[tuple[int, int]]:
    found, start = [], None
    for index, value in enumerate(image):
        if value == byte:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= minimum:
                found.append((start, index - start))
            start = None
    if start is not None and len(image) - start >= minimum:
        found.append((start, len(image) - start))
    return found


def survey(base: int, image: bytes, minimum: int = MINIMUM_CAVE, functions=None) -> dict:
    literals = {}
    for needle in LITERALS:
        positions, start = [], 0
        while True:
            at = image.find(needle, start)
            if at < 0:
                break
            positions.append(base + at)
            start = at + 1
        literals[needle.decode()] = positions[:6]
    caves = {}
    for byte, label in ((0xCC, 'int3'), (0x00, 'zero')):
        found = sorted(runs(image, byte, minimum), key=lambda row: -row[1])[:8]
        caves[label] = [dict(va=base + offset, size=size) for offset, size in found]
    inspected = {}
    for va, label in (functions or KNOWN_FUNCTIONS).items():
        offset = va - base
        inside = 0 <= offset < len(image) - 2
        prologue = image[offset:offset + 3].hex() if inside else None
        inspected[label] = dict(va=va, inside_image=inside, prologue=prologue,
                                looks_like_function=prologue == '558bec' if inside else False)
    return dict(schema=SCHEMA, image_base=base, image_size=len(image), literals=literals,
                caves=caves, functions=inspected, minimum_cave=minimum,
                activation_allowed=False, runtime_acceptance=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    parser.add_argument('--minimum-cave', type=int, default=MINIMUM_CAVE)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    base, image = load_image(args.dump)
    result = survey(base, image, args.minimum_cave)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        shared.require(not args.output.exists(), 'Output already exists: ' + str(args.output))
        args.output.write_text(payload, 'utf-8')
    print(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
