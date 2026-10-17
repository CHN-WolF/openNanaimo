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
WIDTH = 450
SHIFT = (554 - WIDTH) // 2
SLOT_X = 255


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

    # Keep the speech bubble and footer text intact, including native controls.
    # Each band loses only unused horizontal space, never scales its artwork.
    for y in range(84, 284):
        row = pixels[y]
        # An interior socket excludes the lower-left matrix frame's roundover.
        slot = row[148:181]
        # Keep the top rivet and true outer frame, not the old final column.
        # The last six scanlines follow the native lower-right rounded corner.
        right = 520 if y < 99 else 531 if y < 278 else (530, 530, 529, 529, 527, 524)[y - 278]
        row[112:right] = [row[147]] * (right - 112)
        if any(134 + i * 38 <= y < 169 + i * 38 for i in range(4)):
            row[SLOT_X:SLOT_X+33] = slot
    for y, row in enumerate(pixels):
        start = 300 if y < 30 else 350 if y >= 284 else 416 if y >= 84 else 430
        del row[start:start + 554 - WIDTH]
    width = WIDTH
    body = b''.join(struct.pack('<HhHH', width + 4, -1, 0, width)
                    + struct.pack('<' + 'H' * width, *row) for row in pixels)
    header = bytearray(raw[:44])
    struct.pack_into('<I', header, 8, len(body) + 36)
    struct.pack_into('<I', header, 12, width)
    struct.pack_into('<I', header, 20, width)
    struct.pack_into('<f', header, 36, width / 2)
    return bytes(header) + body


def ranking_files(client):
    client = Path(client)
    raw = (client / SOURCE_EFFECT).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == EFFECT_SHA256, 'unknown monk ranking effect')
    effect, count = resources.rewrite_names(raw, EFFECT,
        {'nanaimo_cs_pop01.im3': Path(IMAGE).name})
    require(count == 1, 'monk ranking effect dependency differs')
    # The first layer is the native translucent shadow, not the panel artwork.
    effect = bytearray(effect)
    struct.pack_into('<f', effect, 20 + 272 + 5 * 20, WIDTH / 554)
    effect = bytes(effect)
    return {IMAGE: single_slot_bitmap((client / SOURCE_IMAGE).read_bytes()), EFFECT: effect}
