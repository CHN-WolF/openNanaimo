"""Derive the challenge-only single-slot background from the native CN bitmap."""
import hashlib
import struct
from pathlib import Path

import prepare_monk_resources as resources
from prepare_monk_entry import require

IMAGE = 'effs/interface/openNanaimo_monk_rank.im3'
EFFECT = 'effs/interface/openNanaimo_monk_rank.eff'
SOURCE_IMAGE = 'effs/interface/nanaimo_cs_pop01.im3'
SOURCE_EFFECT = 'effs/interface/nanaimo_cs_pop.eff'
IMAGE_SHA256 = 'c9d855847eae50c9d66949958f00f912c3475901a4af1422dbf8779e25a1aaf7'
EFFECT_SHA256 = '7065891445798bbcf4d36b9e015c6e720724ebdcb78eb788a2af6f25a8ce6f89'


def single_slot_bitmap(raw):
    require(hashlib.sha256(raw).hexdigest() == IMAGE_SHA256, 'unknown monk ranking background')
    width, height = struct.unpack_from('<2I', raw, 12)
    require((width, height) == (554, 336), 'monk ranking background geometry differs')
    pixels = []
    cursor = 44
    for _ in range(height):
        words, runs = struct.unpack_from('<Hh', raw, cursor)
        end = cursor + words * 2
        cursor += 4
        row = [0] * width
        x = 0
        for _ in range(1 if runs == -1 else runs):
            gap, count = struct.unpack_from('<HH', raw, cursor)
            cursor += 4
            x += gap
            row[x:x+count] = struct.unpack_from('<' + 'H' * count, raw, cursor)
            cursor += count * 2
            x += count
        require(cursor == end, 'monk ranking scanline differs')
        pixels.append(row)
    require(cursor == len(raw), 'monk ranking trailing bytes')

    # Retain the native frame, Epi boxes, four row bevels and both close buttons.
    # Erase the baked difficulty/stage grid; centre one original circle per row.
    for y in range(84, 283):
        row = pixels[y]
        slot = row[114:147]
        row[112:534] = [row[147]] * 422
        if any(134 + i * 38 <= y < 169 + i * 38 for i in range(4)):
            row[306:339] = slot
    body = b''.join(struct.pack('<HhHH', width + 4, -1, 0, width)
                    + struct.pack('<' + 'H' * width, *row) for row in pixels)
    header = bytearray(raw[:44])
    struct.pack_into('<I', header, 8, len(body) + 36)
    return bytes(header) + body


def ranking_files(client):
    client = Path(client)
    raw = (client / SOURCE_EFFECT).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == EFFECT_SHA256, 'unknown monk ranking effect')
    effect, count = resources.rewrite_names(raw, EFFECT,
        {'nanaimo_cs_pop01.im3': Path(IMAGE).name})
    require(count == 1, 'monk ranking effect dependency differs')
    return {IMAGE: single_slot_bitmap((client / SOURCE_IMAGE).read_bytes()), EFFECT: effect}
