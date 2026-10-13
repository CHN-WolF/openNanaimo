"""Derive a local CN monk scene preview, NOT an interactive entrance installer.

CN VIL consumption: 0x9DBA60, standard entry setters: 0xA74450 / 0x50A240 /
0x50A260 / 0x50A280. No CN NPC._D39/action._S1 loader is claimed. Preserve
all other pack records, collision/transport/action fields and existing text IDs.
Outputs are isolated user-derived assets; no apply command or runtime acceptance.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import struct

try:
    from . import lumineos_scenes as scenes
    from . import prepare_hero_dragon as crypto
    from . import prepare_monk_resources as monk
except ImportError:
    import lumineos_scenes as scenes
    import prepare_hero_dragon as crypto
    import prepare_monk_resources as monk

PACK = 'Village_map_image/Village_map_image.pack'
SCENE_KEY = 10027
EFFECT = 'openNanaimo_monk01.eff'
SPRITE = 'openNanaimo_monk01.im3'
SHADOW = 'openNanaimo_monk_shadow.im3'
LABEL = 'openNanaimo_monk_name.im3'
MONK_NAME_FONT_SIZE = 13
# Native 0x9DCA40 inserts layer 1 by world Y, shared with town actors.
# Foreground layer 2 bypasses player/NPC depth ordering.
MONK_LAYER = 1
MONK_ENGLISH_GAP = 2
MONK_ENGLISH_FONT_SIZE = 9
MONK_NAME_STROKE = 1
MONK_OUTLINE_COLOR = (90, 24, 0, 255)
SOURCE_ROW = ('62', '\uc218\ub3c4\uc2b9', '1', '0', '27', '10', 'NPC_62.im3',
              'effs\\village\\vill01_npc_monk.eff', '-', '-', '-', '-',
              '293', '157', '48', '96', '4000')


def require(ok, message):
    if not ok:
        raise ValueError(message)


class VillageScene:
    """Bounded v5/type1 VIL parser; keep opaque header and trailing bytes intact."""
    def __init__(self, raw):
        self.raw = bytes(raw)
        require(len(raw) >= 300, 'truncated VIL header')
        require(struct.unpack_from('<2I', raw) == (5, 1), 'unsupported VIL version/layer mode')
        require(struct.unpack_from('<4I', raw, 16) == (16, 16, 50, 36), 'unsupported VIL dimensions')
        self.floor, cursor = self.table(raw, 296)
        self.grid_start = cursor
        cursor += 50 * 36 * 36
        require(cursor <= len(raw), 'truncated VIL grid')
        self.textures, cursor = self.table(raw, cursor)
        self.layers = []
        known = {uid for uid, _ in self.textures}
        for _ in range(3):
            require(cursor + 4 <= len(raw), 'truncated VIL layer count')
            count = struct.unpack_from('<I', raw, cursor)[0]
            cursor += 4
            require(count <= (len(raw) - cursor) // 16, 'truncated VIL placements')
            rows = [raw[cursor + i * 16:cursor + (i + 1) * 16] for i in range(count)]
            for row in rows:
                uid, x, y, z = struct.unpack('<I3f', row)
                require(uid in known, 'unknown VIL decoration index')
                require(all(math.isfinite(v) for v in (x, y, z)), 'nonfinite VIL placement')
            self.layers.append(rows)
            cursor += count * 16
        self.tail = raw[cursor:]

    @staticmethod
    def table(raw, cursor):
        rows, known = [], set()
        # Native loader has 64 iterations: reserve one for the -1 sentinel.
        for _ in range(64):
            require(cursor + 4 <= len(raw), 'truncated VIL texture table')
            uid = struct.unpack_from('<i', raw, cursor)[0]
            cursor += 4
            if uid == -1:
                return rows, cursor
            require(0 <= uid < 64 and uid not in known, 'invalid VIL texture index')
            require(cursor + 260 <= len(raw), 'truncated VIL texture name')
            name = raw[cursor:cursor + 260]
            require(b'\0' in name and name[0] != 0, 'unterminated/empty VIL texture name')
            known.add(uid)
            rows.append((uid, name))
            cursor += 260
        raise ValueError('VIL table exceeds native sentinel capacity')

    def derive(self):
        name = ('effs/village/' + EFFECT).encode('ascii').lower()
        matches = [uid for uid, raw in self.textures
                   if raw.split(b'\0', 1)[0].replace(b'\\', b'/').lower() == name]
        require(len(matches) <= 1, 'duplicate monk texture')
        textures = list(self.textures)
        if matches:
            uid = matches[0]
        else:
            require(len(textures) < 63, 'no native VIL decoration slot available')
            occupied = {uid for uid, _ in textures}
            uid = next(i for i in range(64) if i not in occupied)
            textures.append((uid, name.replace(b'/', b'\\').ljust(260, b'\0')))
        expected = struct.pack('<I3f', uid, 293., 157., 0.)
        placements = [(layer, row) for layer, rows in enumerate(self.layers) for row in rows
                      if struct.unpack_from('<I', row)[0] == uid]
        layers = [[row for row in rows if struct.unpack_from('<I', row)[0] != uid]
                  for rows in self.layers]
        if placements:
            require(all(row in (expected,) for _, row in placements), 'conflicting monk scene placement')
        # Dynamic actors and decorations share the layer-1 Y ordering.
        layers[MONK_LAYER].append(expected)
        output = bytearray(self.raw[:self.grid_start + 50 * 36 * 36])
        for uid, raw in textures:
            output += struct.pack('<i', uid) + raw
        output += struct.pack('<i', -1)
        for rows in layers:
            output += struct.pack('<I', len(rows)) + b''.join(rows)
        output += self.tail
        result = bytes(output)
        VillageScene(result)
        return result


def derive_pack(data):
    rows = scenes.records(data)  # Strict extent/overlap/gap validation.
    require(SCENE_KEY in dict(rows), 'missing first-village exit scene 10027')
    replacement = VillageScene(dict(rows)[SCENE_KEY][4:]).derive()
    rebuilt = [(key, struct.pack('<I', len(replacement)) + replacement if key == SCENE_KEY else body)
               for key, body in rows]
    offset = 13 + len(rows) * 8
    output = bytearray(b'NANA_PACK' + struct.pack('<I', len(rows)))
    for key, body in rebuilt:
        output += struct.pack('<II', key, offset)
        offset += len(body)
    output += b''.join(body for _, body in rebuilt)
    checked = scenes.records(bytes(output))
    require([k for k, _ in checked] == [k for k, _ in rows], 'pack order changed')
    require(all(body == dict(rows)[key] for key, body in checked if key != SCENE_KEY),
            'unrelated village record changed')
    # Idempotence must preserve a noncanonical input directory order as well.
    return data if rebuilt == rows else bytes(output)


def merge_catalog(raw, name, extra):
    require(name in ('QS._D31', 'GS._D20'), 'unsupported text catalog')
    start = 3 if name == 'QS._D31' else 2
    fields = crypto.decrypt(raw, crypto.CN_KEY).decode('gbk').split('#')
    magic = 'NANA_QUEST_TEXT' if start == 3 else 'NANA_TEXT'
    require(len(fields) >= start + 1 and fields[0] == magic and fields[-1] == '', 'invalid text catalog')
    values = fields[start:-1]
    require(len(values) % 2 == 0, 'incomplete text pair')
    pairs = list(zip(values[::2], values[1::2]))
    require(all(uid.isascii() and uid.isdigit() for uid, _ in pairs), 'invalid text UID')
    require(len({int(uid) for uid, _ in pairs}) == len(pairs), 'duplicate text UID')
    if start == 3:
        require(fields[2].isascii() and fields[2].isdigit() and int(fields[2]) == len(pairs),
                'QS declared count mismatch')
    existing = dict(pairs)
    for uid, text in sorted(extra.items(), key=lambda item: int(item[0])):
        require(uid.isascii() and uid.isdigit() and str(int(uid)) == uid, 'invalid added text UID')
        require(text and not any(x in text for x in ('#', '\0')), 'invalid added text')
        text.encode('gbk')
        require(int(uid) not in {int(k) for k in existing} or existing.get(uid) == text,
                'existing text collision: ' + uid)
        if uid not in existing:
            pairs.append((uid, text))
            existing[uid] = text
    if pairs == list(zip(values[::2], values[1::2])):
        return raw
    head = fields[:start]
    if start == 3:
        head[2] = str(len(pairs))
    return monk.encrypt_cn(('#'.join(head + [x for pair in pairs for x in pair]) + '#').encode('gbk'))


def effect(raw):
    """Rename EFF2 fixed resource names without touching authored tracks/info."""
    model = monk.codec_module().eff2(raw)
    renames = {'vill01_npc_monk.im3': SPRITE, 'qz_village_npc_shadow_black.im3': SHADOW,
               'vill_npc_monkname.im3': LABEL}
    require(set(model['refs']) == set(renames), 'unrecognized monk EFF references')
    result, count = monk.rewrite_names(raw, 'effs/village/' + EFFECT, renames)
    require(count == 3, 'EFF rewrite coverage differs')
    require(set(monk.codec_module().eff2(result)['refs']) == set(renames.values()), 'EFF rewrite mismatch')
    return result


def name_image(font, text, template_raw):
    from PIL import Image, ImageDraw, ImageFont
    kind, version, size, width, height, fw, fh, fmt, sequences = struct.unpack_from('<9I', template_raw)
    require((kind, version, width, height, fw, fh, fmt, sequences) == (0, 2, 39, 19, 39, 19, 8, 0),
            'source monk name geometry differs')
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    cursor = 44
    for y in range(height):
        words, runs = struct.unpack_from('<Hh', template_raw, cursor)
        end = cursor + words * 2
        cursor += 4
        x = 0
        for _ in range(1 if runs == -1 else runs):
            gap, length = struct.unpack_from('<HH', template_raw, cursor)
            cursor += 4
            x += gap
            for i in range(length):
                value = struct.unpack_from('<H', template_raw, cursor)[0]
                cursor += 2
                red = ((value >> 10) & 31) * 255 // 31
                green = ((value >> 5) & 31) * 255 // 31
                blue = (value & 31) * 255 // 31
                alpha = 255 if value & 0x8000 else 0
                image.putpixel((x + i, y), (red, green, blue, alpha))
            x += length
        cursor = end
    # Authored MONK occupies x=9..30 / y=12..18. Row 11 still contains
    # the Korean heading outline: do not include or horizontally rescale it.
    # Keep the installed English 22x8 box; only stretch seven rows to eight.
    english = image.crop((9, 12, 31, 19))
    require(english.getbbox() is not None, 'source English monk label is empty')
    english = english.resize((22, 8), Image.Resampling.NEAREST)
    face = ImageFont.truetype(str(font), MONK_NAME_FONT_SIZE)
    draw = ImageDraw.Draw(image)
    box = draw.textbbox((0, 0), text, font=face, stroke_width=MONK_NAME_STROKE)
    text_width, text_height = box[2] - box[0], box[3] - box[1]
    require(0 < text_width <= 128 and 0 < text_height <= 32, 'monk name exceeds label bounds')
    width = max(english.width + 4, text_width + 4)
    # Keep an integer translation for the 22-pixel English line.
    width += (width - english.width) % 2
    top_height = max(14, text_height) + MONK_ENGLISH_GAP
    height = top_height + english.height
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    image.alpha_composite(english, ((width - english.width) // 2, top_height))
    draw = ImageDraw.Draw(image)
    draw.text(((width - text_width) // 2 - box[0],
               0 - box[1]), text, font=face, fill=(255, 255, 255, 255),
              stroke_width=MONK_NAME_STROKE, stroke_fill=MONK_OUTLINE_COLOR)
    body = bytearray()
    for y in range(height):
        runs, x, previous = [], 0, 0
        while x < width:
            if image.getpixel((x, y))[3] < 128:
                x += 1
                continue
            start_x, pixels = x, []
            while x < width and image.getpixel((x, y))[3] >= 128:
                r, g, b, _ = image.getpixel((x, y))
                pixels.append(0x8000 | (r >> 3 << 10) | (g >> 3 << 5) | (b >> 3))
                x += 1
            runs.append((start_x - previous, pixels))
            previous = x
        body += struct.pack('<Hh', 2 + sum(2 + len(v) for _, v in runs), len(runs))
        for gap, pixels in runs:
            body += struct.pack('<HH', gap, len(pixels)) + struct.pack('<' + 'H' * len(pixels), *pixels)
    data = struct.pack('<9I2f', 0, 2, 36 + len(body), width, height, width, height, 8, 0,
                       width / 2, height / 2) + body
    try:
        from .dungeon7_visuals import verify_im3
    except ImportError:
        from dungeon7_visuals import verify_im3
    verify_im3(data, width, height, 8)
    return image, bytes(data)


def build(source, client, output, font):
    source, client, output = map(monk.io.clean_root, (source, client, output))
    font = Path(font).resolve()
    require(source != client and not source.is_relative_to(client) and not client.is_relative_to(source),
            'source/client roots overlap')
    # Like the base port, allow a fresh isolated repository build under the host tree.
    nested = output.is_relative_to(monk.ROOT / 'build') and client != monk.ROOT
    require(not output.is_relative_to(source) and not source.is_relative_to(output)
            and not client.is_relative_to(output) and (not output.is_relative_to(client) or nested),
            'output/source/client roots overlap')
    require(not output.exists(), 'output already exists; use a fresh directory')
    inputs = []
    def read(root, rel):
        path = monk.io.safe(root, rel)
        raw = path.read_bytes()
        inputs.append(dict(path=str(path), size=len(raw), sha256=monk.io.digest(raw)))
        return raw
    npc = crypto.decrypt(read(source, 'NPC._D39'), crypto.SOURCE_KEY).decode('cp949').split('#')
    require(npc[:3] == ['NPC', '20080909', '4'] and len(npc) == 72 and npc[-1] == '', 'NPC source format differs')
    require(tuple(npc[3:20]) == SOURCE_ROW, 'first monk source row differs')
    local = monk.io.load(monk.LOCALIZATION)
    payload = {PACK: derive_pack(read(client, PACK)),
               'QS._D31': merge_catalog(read(client, 'QS._D31'), 'QS._D31', local['quest_strings']),
               'GS._D20': merge_catalog(read(client, 'GS._D20'), 'GS._D20', local['game_strings']),
               'effs/village/' + EFFECT: effect(read(source, 'effs/village/vill01_npc_monk.eff')),
               'effs/village/' + SPRITE: read(source, 'effs/village/vill01_npc_monk.im3'),
               'effs/village/' + SHADOW: read(source, 'effs/village/qz_village_npc_shadow_black.im3')}
    label_template = read(source, 'effs/village/vill_npc_monkname.im3')
    require(struct.unpack_from('<9I2f', label_template)[3:] == (39, 19, 39, 19, 8, 0, 19.5, 9.5),
            'source monk name geometry differs')
    font_raw = font.read_bytes()
    image, payload['effs/village/' + LABEL] = name_image(font, local['npc_name'], label_template)
    inputs.append(dict(path=str(font), size=len(font_raw), sha256=monk.io.digest(font_raw)))
    manifest = dict(schema='openNanaimo.monk-entry-preview.v1', runtime_accepted=False,
                    entry=dict(status='scene-preview-unbound', interactive=False,
                               source_npc_uid=62, proposed_script_uid=24000,
                               scene_key=SCENE_KEY, position=[293, 157], layer=MONK_LAYER,
                               name_font_size=MONK_NAME_FONT_SIZE, name_image_size=list(image.size),
                               stage_identity=[0, 24, 0, 0]), inputs=inputs,
                    localization_sha256=monk.io.digest(monk.LOCALIZATION.read_bytes()), files=[],
                    limits=['VIL decoration is not a clickable NPC.',
                            'No CN NPC table row, action loader, hit region or click callback is installed.',
                            'No executable/server/account/save changes. Do not deploy as a playable entrance.'])
    for rel, raw in payload.items():
        before = monk.io.file_hash(monk.io.safe(client, rel))
        require(before is None or rel in (PACK, 'QS._D31', 'GS._D20', 'effs/village/openNanaimo_monk01.eff', 'effs/village/openNanaimo_monk01.im3', 'effs/village/openNanaimo_monk_shadow.im3', 'effs/village/openNanaimo_monk_name.im3') or before == monk.io.digest(raw),
                'independent resource name conflict: ' + rel)
        manifest['files'].append(dict(path=rel, before_sha256=before, size=len(raw), sha256=monk.io.digest(raw)))
    manifest['id'] = monk.io.digest(monk.io.encoded(manifest))
    output.mkdir(parents=True)
    for rel, raw in payload.items():
        monk.io.atomic(monk.io.safe(output / 'payload', rel), raw)
    image.save(output / 'monk-name-preview.png')
    monk.io.atomic(output / 'manifest.json', monk.io.encoded(manifest))
    return dict(bundle=str(output), id=manifest['id'], files=len(payload),
                entry_status=manifest['entry']['status'], runtime_accepted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.client, args.output, args.font), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

