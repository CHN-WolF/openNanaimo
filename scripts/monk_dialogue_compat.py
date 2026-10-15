"""Four village-exit dialogue controllers using the native CN window lifecycle."""
from pathlib import Path
import json
import struct

ROOT = Path(__file__).resolve().parents[1]
BASE, SPAN = 0x6E3800, 8192
UPDATE, DIALOGUE, PAGE, RETURN = BASE, BASE + 0x300, BASE + 0x600, BASE + 0x700
READY = BASE + 0x200
VTABLE, ORIGIN, TABLE, TEXT = BASE + 0x800, BASE + 0x840, BASE + 0x900, BASE + 0x1000
HIT, HOVER, DRAW, DESTROY = BASE + 0xA00, BASE + 0xB00, BASE + 0xC00, BASE + 0xD00
CLOSED = BASE + 0xE00
GUIDE, WINDOW_SIZE, PAGE_SIZE = 0x200, 0x400, 204
PROFILE = 0xD869D4
LEGACY_ENTRIES = ((0, 27, 293, 157), (1, 26, 282, 425), (2, 12, 127, 416), (3, 6, 186, 255))
CLICK_ENTRIES = (*LEGACY_ENTRIES[:2], (2, 12, 223, 416), LEGACY_ENTRIES[3])
ENTRIES = ((0, 27, 293, 189), LEGACY_ENTRIES[1], (2, 12, 223, 376), LEGACY_ENTRIES[3])


class Code:
    def __init__(self, base):
        self.base, self.data, self.labels, self.fixups = base, bytearray(), {}, []
    def emit(self, value):
        self.data.extend(bytes.fromhex(value) if isinstance(value, str) else value)
    def u32(self, value):
        self.emit(struct.pack('<I', value))
    def call(self, target):
        self.emit(b'\xE8' + struct.pack('<i', target - self.base - len(self.data) - 5))
    def branch(self, opcode, label):
        self.emit(opcode); self.fixups.append((len(self.data), label)); self.emit(b'\0' * 4)
    def label(self, name):
        self.labels[name] = len(self.data)
    def finish(self):
        for at, label in self.fixups:
            struct.pack_into('<i', self.data, at, self.labels[label] - at - 4)
        return bytes(self.data)


def dialogue_pages(text):
    lines = []
    for paragraph in text.split('^&'):
        line = ''
        for char in paragraph:
            if len((line + char).encode('gbk')) > 36:
                lines.append(line); line = ''
            line += char
        if line: lines.append(line)
    lines.append('\u73b0\u5728\u5f00\u59cb\u6311\u6218\u5417\uff1f')
    return [b''.join(line.encode('gbk').ljust(132, b'\0') for line in (lines[i:i+3] + ['']*3)[:3])
            for i in range(0, len(lines), 3)]


def localization(legacy_names=False):
    local = json.loads((ROOT / 'manifest/monk_localization.json').read_text('utf-8'))
    if legacy_names:
        # Reproduce released bytes only for exact old-patch migration.
        names = {'\u574e\u6cfd\u5ce1\u8c37': '\u574e\u624e\u5ce1\u8c37',
                 '\u8e0f\u5766\u5ce1\u8c37': '\u5854\u5766\u5361\u5ce1\u8c37',
                 '\u767d\u8c79\u5c71': '\u767d\u675c\u9a6c\u5c71',
                 '\u666e\u62c9\u5854\u8bfa\u65af\u6751': '\u68a7\u6850\u6751'}
        for catalog in ('quest_strings', 'game_strings'):
            for uid, text in local[catalog].items():
                for current, old in names.items():
                    text = text.replace(current, old)
                local[catalog][uid] = text
    return local


def legacy_payload(mark_return=False, legacy_names=False):
    """Exact released confirmation-window encoding, accepted only for migration."""
    TEXT = BASE + 0xA00
    local = localization(legacy_names)
    data = bytearray(b'\xCC' * SPAN)
    def put(at, value, limit):
        if len(value) > limit: raise ValueError('monk dialogue region overflow')
        data[at-BASE:at-BASE+len(value)] = value
    put(VTABLE, struct.pack('<8I', 0x40E903, 0x403247, DIALOGUE, 0x40EC50,
                           0x402D51, 0x417BFC, 0x41AE92, 0x4066F9), 32)
    put(ORIGIN, b'\0' * 32, 32)
    cursor = TEXT
    for index, (village, page, x, y) in enumerate(LEGACY_ENTRIES):
        pages = dialogue_pages(local['quest_strings'][str(6000+index*3)])
        put(TABLE+index*32, struct.pack('<8I', village, page, x-24, y-48, x+24, y+48, cursor, len(pages)), 32)
        raw = b''.join(pages); put(cursor, raw, BASE+SPAN-cursor); cursor += len(raw)

    c = Code(UPDATE)
    c.emit('5356578BF1'); c.call(0x52A3E0)
    c.emit('5083BE3403000000'); c.branch('0F84', 'done')
    c.call(0x406F82); c.emit('8BC8'); c.call(0x7EBC20)
    c.emit('85C0'); c.branch('0F84', 'done')
    c.emit('8B0D'); c.u32(PROFILE); c.call(0x411379)
    c.emit('83F803'); c.branch('0F87', 'done')
    c.emit('8BD8C1E30581C3'); c.u32(TABLE)
    c.emit('6AFF8B0D'); c.u32(PROFILE); c.call(0x41DE8A)
    c.emit('3B4304'); c.branch('0F85', 'done')
    c.call(0x414A6F); c.emit('8B908C8D00008B88908D0000')
    for instruction, branch in (('3B5308','0F8C'),('3B5310','0F8D'),('3B4B0C','0F8C'),('3B4B14','0F8D')):
        c.emit(instruction); c.branch(branch, 'done')
    c.emit('6A00'); c.call(0x40ED77); c.emit('8BC8'); c.call(0x415ED3)
    c.emit('85C0'); c.branch('0F84', 'done')
    c.emit('8B8E34030000'); c.call(0x4043D6); c.call(0xB4CA30)
    c.emit('A3'); c.u32(ORIGIN+12)
    c.emit('8B8E34030000'); c.call(0x417184); c.call(0xB4CA30)
    c.emit('A3'); c.u32(ORIGIN+16)
    c.emit('8B0353A3'); c.u32(ORIGIN+4)
    c.emit('8B4304A3'); c.u32(ORIGIN+8)
    c.emit('68F0010000'); c.call(0xB479CC); c.emit('83C40485C0'); c.branch('0F84','allocated_done')
    c.emit('8BC8'); c.call(0x4064FB)
    c.emit('8BF86A098BCF'); c.call(0x41759E)
    c.emit('6AFF8BCF'); c.call(0x408F5D)
    c.emit('C707'); c.u32(VTABLE)
    c.emit('C647409A58894744C74748000000008BCF'); c.call(PAGE)
    c.emit('57'); c.call(0x406F82); c.emit('8BC8'); c.call(0x410299)
    for reset in (0x418B83,0x419B0A):
        c.call(0x40ED77); c.emit('8BC8'); c.call(reset)
    c.branch('E9','done')
    c.label('allocated_done'); c.emit('58')
    c.label('done'); c.emit('585F5E5BC3')
    put(UPDATE,c.finish(),0x200)

    c = Code(READY)
    c.emit('9C52833D'); c.u32(ORIGIN); c.emit('01'); c.branch('0F85','native')
    c.emit('8B914CE501008B05'); c.u32(ORIGIN+4)
    c.emit('83C0083BD0'); c.branch('0F85','native')
    c.emit('C744240C64000000')
    c.label('native'); c.emit('5A9D')
    c.emit(b'\xE9'+struct.pack('<i',0x73AFE0-READY-len(c.data)-5))
    put(READY,c.finish(),0x100)

    c = Code(PAGE)
    c.emit('5356578BF98B77448B474869C08C0100000346188BF08D7F64B963000000FCF3A55F5E5BC3')
    put(PAGE,c.finish(),0x100)

    c = Code(DIALOGUE)
    c.emit('5356578BF1'); c.call(0x4D77B0)
    c.emit('66837E3402'); c.branch('0F85','waiting')
    c.emit('66837E3601'); c.branch('0F85','close')
    c.emit('8B7E44FF46488B46483B471C'); c.branch('0F83','enter')
    c.emit('8BCE'); c.call(PAGE)
    c.emit('66C74634010066C746360200'); c.branch('E9','waiting')
    c.label('enter')
    c.emit('8B0D'); c.u32(PROFILE); c.call(0x411379)
    c.emit('3B07'); c.branch('0F85','close')
    c.emit('6AFF8B0D'); c.u32(PROFILE); c.call(0x41DE8A)
    c.emit('3B4704'); c.branch('0F85','close')
    c.emit('8B070508000000508B0D'); c.u32(PROFILE); c.call(0x404A52)
    for target in (0x4079AA,0x404296,0x4170D5):
        c.emit('6A00'); c.call(0x419BBE); c.emit('8BC8'); c.call(target)
    c.emit('6A008B0D'); c.u32(PROFILE); c.call(0x40D69D)
    c.emit('C705'); c.u32(ORIGIN); c.u32(1)
    c.emit('6A098B0D'); c.u32(0xD6F280); c.call(0x402EF0)
    c.label('close'); c.emit('B802000000'); c.branch('E9','done')
    c.label('waiting'); c.emit('B801000000')
    c.label('done'); c.emit('5F5E5BC3')
    put(DIALOGUE,c.finish(),0x300)

    c = Code(RETURN)
    c.emit('9C60833D'); c.u32(ORIGIN); c.emit('01'); c.branch('0F85','native')
    c.emit('8B0D'); c.u32(PROFILE); c.call(0x411379)
    c.emit('3B05'); c.u32(ORIGIN+4); c.branch('0F85','clear')
    c.emit('8B0D'); c.u32(PROFILE); c.call(0x403D19)
    c.emit('0FB6C08B15'); c.u32(ORIGIN+4); c.emit('83C2083BC2'); c.branch('0F85','clear')
    c.emit('6AFF8B0D'); c.u32(PROFILE); c.call(0x41DE8A)
    c.emit('3B05'); c.u32(ORIGIN+8); c.branch('0F85','clear')
    c.emit('A1'); c.u32(ORIGIN+12); c.emit('8945E4')
    c.emit('A1'); c.u32(ORIGIN+16); c.emit('8945E8')
    if mark_return:
        c.call(MARK_RETURN)
    c.label('clear'); c.emit('C705'); c.u32(ORIGIN); c.u32(0)
    c.label('native'); c.emit('619DDB45E48B8554F8FFFF')
    c.emit(b'\xE9'+struct.pack('<i',0x53CE19-RETURN-len(c.data)-5))
    put(RETURN,c.finish(),0x100)
    return bytes(data)


def guide_pages(text):
    lines = []
    for paragraph in text.split('^&'):
        line = ''
        for char in paragraph:
            if len((line + char).encode('gbk')) > 48:
                lines.append(line); line = ''
            line += char
        if line:
            lines.append(line)
    lines.append('\u51c6\u5907\u597d\u4e86\uff0c\u5c31\u51fa\u53d1\u5427\uff01')
    return [b''.join(line.encode('gbk').ljust(51, b'\0')
                    for line in (lines[i:i+4] + ['']*4)[:4])
            for i in range(0, len(lines), 4)]


def payload(legacy_guide=False, legacy_lifetime=False, legacy_scene=False, legacy_gameplay=False,
            legacy_portrait=False, legacy_names=False):
    legacy_gameplay = legacy_gameplay or legacy_guide or legacy_lifetime or legacy_scene
    legacy_portrait = legacy_portrait or legacy_gameplay
    legacy_scene = legacy_scene or legacy_guide or legacy_lifetime
    local = localization(legacy_names)
    data = bytearray(b'\xCC' * SPAN)
    def put(at, value, limit):
        if len(value) > limit:
            raise ValueError('monk dialogue region overflow')
        data[at-BASE:at-BASE+len(value)] = value
    # Own the window lifetime; the embedded native guide owns only its UI assets.
    close_test = DRAW+0x80 if legacy_guide or legacy_lifetime else CLOSED
    put(VTABLE, struct.pack('<8I', DESTROY, 0x403247, DIALOGUE, close_test,
                           DRAW, 0x41B50E, 0x41AE92, DRAW+0x80), 32)
    put(ORIGIN, b'\0' * 32, 32)
    cursor = TEXT
    for index, (village, page, x, y) in enumerate(LEGACY_ENTRIES if legacy_guide else CLICK_ENTRIES if legacy_scene else ENTRIES):
        pages = guide_pages(local['quest_strings'][str(6000+index*3)])
        put(TABLE+index*32, struct.pack('<8I', village, page, x-24, y-48,
                                      x+24, y+48, cursor, len(pages)), 32)
        raw = b''.join(pages)
        put(cursor, raw, BASE+SPAN-cursor)
        cursor += len(raw)

    # Shared hit test returns the village row, never a cached previous-room index.
    c = Code(HIT)
    c.emit('53568BF183BE3403000000'); c.branch('0F84', 'miss')
    c.call(0x406F82); c.emit('8BC8'); c.call(0x7EBC20)
    c.emit('85C0'); c.branch('0F84', 'miss')
    c.emit('8B0D'); c.u32(PROFILE); c.call(0x411379)
    c.emit('83F803'); c.branch('0F87', 'miss')
    c.emit('8BD8C1E30581C3'); c.u32(TABLE)
    c.emit('6AFF8B0D'); c.u32(PROFILE); c.call(0x41DE8A)
    c.emit('3B4304'); c.branch('0F85', 'miss')
    c.call(0x414A6F); c.emit('8B908C8D00008B88908D0000')
    for instruction, branch in (('3B5308','0F8C'),('3B5310','0F8D'),('3B4B0C','0F8C'),('3B4B14','0F8D')):
        c.emit(instruction); c.branch(branch, 'miss')
    c.emit('8BC3'); c.branch('E9', 'done')
    c.label('miss'); c.emit('33C0')
    c.label('done'); c.emit('5E5BC3')
    put(HIT, c.finish(), 0x100)

    c = Code(UPDATE)
    c.emit('5356578BF1'); c.call(0x52A3E0); c.emit('508BCE'); c.call(HIT)
    c.emit('85C0'); c.branch('0F84', 'done')
    if legacy_guide:
        c.emit('8BD86A00'); c.call(0x40ED77); c.emit('8BC8'); c.call(0x415ED3)
        c.emit('85C0'); c.branch('0F84', 'done')
    else:
        # Native mouse snapshot: +0x21C current left, +0x22C previous left.
        # Open on the press edge, before the native village consumes input.
        c.emit('8BD8'); c.call(0x40ED77)
        c.emit('80B81C02000080'); c.branch('0F85', 'done')
        c.emit('80B82C02000080'); c.branch('0F84', 'done')
    if legacy_gameplay:
        c.emit('8B8E34030000'); c.call(0x4043D6); c.call(0xB4CA30)
        c.emit('A3'); c.u32(ORIGIN+12)
        c.emit('8B8E34030000'); c.call(0x417184); c.call(0xB4CA30)
        c.emit('A3'); c.u32(ORIGIN+16)
    else:
        c.emit('8BCE'); c.call(CAPTURE_ORIGIN)
        c.emit('85C0'); c.branch('0F84', 'done')
    c.emit('8B03A3'); c.u32(ORIGIN+4)
    c.emit('8B4304A3'); c.u32(ORIGIN+8)
    c.emit('68'); c.u32(WINDOW_SIZE); c.call(0xB479CC)
    c.emit('83C40485C0'); c.branch('0F84', 'done')
    c.emit('8BC8'); c.call(0x4064FB); c.emit('8BF8')
    c.emit('6A098BCF'); c.call(0x41759E)
    c.emit('C707'); c.u32(VTABLE)
    c.emit('895F44C747480000000066C747340100')
    if not legacy_gameplay:
        c.emit('C7474C00000000')
    c.emit('FFB6340300008D8F00020000'); c.call(0x4163BF)
    # Initialize the frame without looking up an unrelated CN NPC name.
    c.emit('6A006A008D8F00020000'); c.call(0xA12CC0)
    if not legacy_portrait:
        c.emit('8B138D8F00020000'); c.call(INIT_PORTRAIT)
    c.emit('C78700020000'); c.emit('\u4fee\u9053'.encode('gbk'))
    c.emit('C78704020000'); c.emit(('\u50e7'.encode('gbk') + b'\0\0'))
    c.emit('8BCF'); c.call(PAGE)
    c.emit('57'); c.call(0x406F82); c.emit('8BC8'); c.call(0x410299)
    for reset in (0x418B83, 0x419B0A):
        c.call(0x40ED77); c.emit('8BC8'); c.call(reset)
    c.label('done'); c.emit('585F5E5BC3')
    put(UPDATE, c.finish(), 0x200)

    c = Code(READY)
    c.emit('9C515253833D'); c.u32(ORIGIN); c.emit('01'); c.branch('0F85', 'native')
    c.emit('8B0D'); c.u32(PROFILE); c.call(0x411379)
    c.emit('3B05'); c.u32(ORIGIN+4); c.branch('0F85', 'native')
    c.emit('8BD883C3088B0D'); c.u32(PROFILE); c.call(0x403D19)
    c.emit('0FB6C03BC3'); c.branch('0F85', 'native')
    c.emit('C744241464000000')
    c.label('native'); c.emit('5B5A599D')
    c.emit(b'\xE9'+struct.pack('<i', 0x73AFE0-READY-len(c.data)-5))
    put(READY, c.finish(), 0x100)

    c = Code(PAGE)
    c.emit('5356578BD98B73448B434869C0CC0000000346188BF08DBB28020000B933000000FCF3A5')
    # Native renderer uses four NUL-terminated 51-byte rows; no quest lookup.
    for offset, value in ((0x354,1),(0x35C,1),(0x360,0),(0x350,0),(0x368,1)):
        c.emit('C783'); c.u32(offset); c.u32(value)
    c.emit('8B43448B5348423B501C0F94C00FB6C0898364030000')
    c.emit('6A018D8B00020000'); c.call(0x405F7E)
    c.emit('5F5E5BC3')
    put(PAGE, c.finish(), 0x100)

    c = Code(DIALOGUE)
    c.emit('5356578BF1')
    c.call(0x40ED77); c.emit('8BC8'); c.call(0x407DCE)
    c.emit('85C0'); c.branch('0F85', 'close')
    if not legacy_portrait:
        # The authored entrance animation starts transparent; advance it once/frame.
        c.emit('8B8EF402000085C9'); c.branch('0F84', 'frame')
        c.emit('8B01FF5010'); c.label('frame')
    c.emit('8B8EFC0200008B01FF5010')
    c.emit('8BBE0403000083BE6403000000'); c.branch('0F84', 'button')
    c.emit('8BBE08030000')
    c.label('button'); c.emit('8BCF'); c.call(0x414353)
    c.emit('8BCF'); c.call(0x4169A0)
    c.emit('83F805'); c.branch('0F84', 'advance')
    c.emit('83F801'); c.branch('0F84', 'hover')
    c.emit('83F802'); c.branch('0F85', 'keyboard')
    c.label('hover'); c.emit('6A018B8E00030000'); c.call(0x402770)
    c.label('keyboard'); c.call(0x40ED77); c.emit('8BC8'); c.call(0x415064)
    c.emit('85C0'); c.branch('0F84', 'waiting')
    c.label('advance')
    for reset in (0x418B83, 0x419B0A):
        c.call(0x40ED77); c.emit('8BC8'); c.call(reset)
    c.emit('8B7E44FF46488B46483B471C'); c.branch('0F83', 'enter')
    c.emit('8BCE'); c.call(PAGE); c.branch('E9', 'waiting')
    c.label('enter')
    if not legacy_gameplay:
        c.emit('837E4C00'); c.branch('0F85', 'close')
    c.emit('8B0D'); c.u32(PROFILE); c.call(0x411379)
    c.emit('3B07'); c.branch('0F85', 'close')
    c.emit('6AFF8B0D'); c.u32(PROFILE); c.call(0x41DE8A)
    c.emit('3B4704'); c.branch('0F85', 'close')
    c.emit('8B070508000000508B0D'); c.u32(PROFILE); c.call(0x404A52)
    for target in (0x4079AA,0x404296,0x4170D5):
        c.emit('6A00'); c.call(0x419BBE); c.emit('8BC8'); c.call(target)
    c.emit('6A008B0D'); c.u32(PROFILE); c.call(0x40D69D)
    c.emit('C705'); c.u32(ORIGIN); c.u32(1)
    c.emit('6A098B0D'); c.u32(0xD6F280); c.call(0x402EF0)
    c.label('close'); c.emit('66C746340200B802000000'); c.branch('E9', 'done')
    c.label('waiting'); c.emit('B801000000')
    c.label('done'); c.emit('5F5E5BC3')
    put(DIALOGUE, c.finish(), 0x300)

    # The ordinary village update can reset the cursor, so set it afterward.
    c = Code(HOVER)
    c.emit('568BF1'); c.call(0x527C80); c.emit('508BCE')
    if not legacy_portrait:
        c.call(OPEN_RESULT); c.emit('8BCE')
    c.call(HIT)
    c.emit('85C0'); c.branch('0F84', 'done')
    c.emit('6A05' if legacy_guide else '6A01')
    c.emit('8B8E34030000'); c.call(0x402770)
    c.label('done'); c.emit('585EC3')
    put(HOVER, c.finish(), 0x100)

    c = Code(DRAW)
    if not legacy_portrait:
        c.emit('C3')  # entry and outcome guides both draw in their final UI pass
    elif not legacy_gameplay:
        c.emit('83794C007501C3')  # outcome guide draws in native result window pass
    elif not legacy_scene:
        c.emit('C3')  # only the late village UI pass renders this owned guide
    c.emit('81C100020000')
    c.emit(b'\xE9'+struct.pack('<i',0xA13630-DRAW-len(c.data)-5))
    put(DRAW, c.finish(), 0x80)
    put(DRAW+0x80, bytes.fromhex('B801000000C3'), 0x80)
    c = Code(DESTROY)
    c.emit('568BF181C100020000'); c.call(0x41B6A8)
    c.emit('8BCE5E')
    c.emit(b'\xE9'+struct.pack('<i',0x4D7830-DESTROY-len(c.data)-5))
    put(DESTROY, c.finish(), 0x100)
    if not legacy_guide and not legacy_lifetime:
        # Native 0x7EC5C0 sweeps vtable+12 every frame, before drawing.
        # Only explicit close/entry marks +0x34 as 2; an open page is 1.
        put(CLOSED, bytes.fromhex('66837934020F94C00FB6C0C3'), 0x100)
    old = legacy_payload(mark_return=not legacy_portrait, legacy_names=legacy_names)
    put(RETURN, old[RETURN-BASE:RETURN-BASE+0x100], 0x100)
    return bytes(data)


def dialogue_sites():
    return (('monk_dialogue_controller',BASE,b'\xCC'*SPAN,payload()),
            ('monk_village_update',0x527CCD,bytes.fromhex('E8F821EFFF'),
             b'\xE8'+struct.pack('<i',UPDATE-0x527CCD-5)),
            ('monk_ready_episode',0x72F20D,bytes.fromhex('E834F4CEFF'),
             b'\xE8'+struct.pack('<i',READY-0x72F20D-5)),
            ('monk_origin_restore',0x53CE10,bytes.fromhex('DB45E48B8554F8FFFF'),
             b'\xE9'+struct.pack('<i',RETURN-0x53CE10-5)+b'\x90'*4),
            ('monk_hover_update',0x52A751,bytes.fromhex('E88B54EEFF'),
             b'\xE8'+struct.pack('<i',HOVER-0x52A751-5)))


# Isolated gameplay UI extension. No shared manager identity is rewritten.
EXT_BASE, EXT_SPAN = 0x6E5800, 0x1600
IS_CHALLENGE, VILLAGE_GATE, HD_GATE = EXT_BASE, EXT_BASE+0x80, EXT_BASE+0x100
LATE_DRAW = EXT_BASE+0x400
RESULT_TITLE, DRAW_TITLE = EXT_BASE+0x600, EXT_BASE+0x700
READY_TITLE, TITLE_STRINGS = EXT_BASE+0x800, EXT_BASE+0x1320
RESULT_RETRY_INPUT, RESULT_RETRY_DRAW = EXT_BASE+0x980, EXT_BASE+0xA00
ROOM_TITLE = EXT_BASE+0xF00
ROOM_NAME, ROOM_BOSS = EXT_BASE+0x1000, EXT_BASE+0x1080
ROOM_NUMBER, BOSS_STRINGS = EXT_BASE+0x13A0, EXT_BASE+0x13C0


RANK_INIT, RANK_GET, RANK_SET = EXT_BASE+0x1100, EXT_BASE+0xB00, EXT_BASE+0xB80
RANK_DRAW, RANK_TEXT = EXT_BASE+0xC80, EXT_BASE+0x1440


def gameplay_payload(legacy_gameplay=False, legacy_portrait=False, legacy_room=False, legacy_names=False, legacy_ranking=False):
    legacy_room = legacy_room or legacy_portrait
    data = bytearray(b'\xCC' * EXT_SPAN)
    local = localization(legacy_names)
    def put(at, raw, limit):
        if len(raw)>limit: raise ValueError(f'gameplay region overflow {at:x}: {len(raw)} > {limit}')
        data[at-EXT_BASE:at-EXT_BASE+len(raw)] = raw
    def jump(c, target):
        c.emit(b'\xE9'+struct.pack('<i',target-c.base-len(c.data)-5))
    c=Code(IS_CHALLENGE)
    c.emit('5152'); c.call(0x419BBE); c.emit('83B830E5010000'); c.branch('0F85','no')
    c.emit('8B9034E5010083EA1883FA03'); c.branch('0F87','no')
    c.emit('83B838E5010000'); c.branch('0F85','no')
    if not legacy_portrait:
        c.emit('83B840E5010000'); c.branch('0F85','no')
    c.emit('B801000000'); c.branch('E9','done')
    c.label('no'); c.emit('33C0'); c.label('done'); c.emit('5A59C3');put(IS_CHALLENGE,c.finish(),0x80)
    for at,native,fake in ((VILLAGE_GATE,0x411379,4),(HD_GATE,0x403D2D,1)):
        c=Code(at); c.emit('51'); c.call(IS_CHALLENGE); c.emit('59');c.emit('85C0');c.branch('0F84','native')
        c.emit('B8');c.u32(fake);c.emit('C3');c.label('native');jump(c,native);put(at,c.finish(),0x80)
    for village in range(4):
        put(TITLE_STRINGS+village*32,local['game_strings'][str(2504+village)].encode('gbk')+b'\0',32)
    # Native windows are drawn before village chat/HUD. Draw only our owned
    # guide after those panels, then the original final cursor pass.
    c=Code(LATE_DRAW);c.emit('53568BD9');c.call(0x406F82);c.emit('8B008B7008')
    c.label('loop');c.emit('85F6');c.branch('0F84','done');c.emit('813E');c.u32(VTABLE);c.branch('0F85','next')
    c.emit('66837E3401');c.branch('0F85','next');c.emit('8D8E00020000');c.call(0xA13630)
    c.label('next');c.emit('8B7618');c.branch('E9','loop')
    c.label('done');c.emit('8BCB5E5B');jump(c,0x41CB16);put(LATE_DRAW,c.finish(),0x100)
    # Scoped result header replacement. Keep tuple identity and all controllers.
    c=Code(RESULT_TITLE);c.emit('9C60');c.call(IS_CHALLENGE);c.emit('85C0');c.branch('0F84','native')
    c.emit('6A456A1F');c.call(DRAW_TITLE);c.emit('83C408619D');jump(c,0x764E22)
    c.label('native');c.emit('619D');c.call(0x419BBE);jump(c,0x764C9B);put(RESULT_TITLE,c.finish(),0x100)
    c=Code(DRAW_TITLE);c.emit('558BEC53');c.call(0x419BBE);c.emit('8B8034E5010083E818C1E00505');c.u32(TITLE_STRINGS);c.emit('8BD8')
    # Native 13-argument text method; same ABI as 0x764Fxx callsites.
    c.emit('6A006A006A006A006A006A006A016A006A0068FFFFFF0053FF750CFF7508')
    c.call(0x414A6F);c.emit('8BC8');c.call(0x40DA1C);c.emit('5B8BE55DC3');put(DRAW_TITLE,c.finish(),0x100)
    c=Code(READY_TITLE)
    if legacy_room:
        c.emit('9C60');c.call(IS_CHALLENGE);c.emit('85C0');c.branch('0F84','done')
        c.emit('6A28682C010000');c.call(DRAW_TITLE);c.emit('83C408')
        c.label('done');c.emit('619D');c.call(0x411379);c.emit('C3')
    else:
        jump(c,0x411379)
    put(READY_TITLE,c.finish(),0x80)
    if not legacy_portrait:
        # Keep the native availability gates and retry/exit, without any sequel.
        for at,original,native,retry in (
            (RESULT_RETRY_INPUT,'8B4DEC83792000',0x762F7B,0x763C69),
            (RESULT_RETRY_DRAW,'8B856CFFFFFF',0x765240,0x7653A7)):
            c=Code(at);c.emit('9C60');c.call(IS_CHALLENGE)
            c.emit('85C0');c.branch('0F84','native')
            c.emit('619D');jump(c,retry)
            c.label('native');c.emit('619D');c.emit(original);jump(c,native)
            put(at,c.finish(),0x80)
        # Bitmap labels already supply dungeon/stage; keep native number positions.
        c=Code(ROOM_TITLE);c.emit('9C60');c.call(IS_CHALLENGE)
        c.emit('85C0');c.branch('0F84','native')
        if legacy_room:
            c.emit('6A0B687C010000');c.call(DRAW_TITLE);c.emit('83C408')
        else:
            for xpos,color in ((380,0xFFE088),(458,0x0FFFB3)):
                c.emit('6A006A006A006A006A006A006A016A006A0068');c.u32(color)
                c.emit('68');c.u32(ROOM_NUMBER);c.emit('6A0B68');c.u32(xpos)
                c.call(0x414A6F);c.emit('8BC8');c.call(0x40DA1C)
        c.emit('619D');jump(c,0x70FA0B)
        c.label('native');c.emit('619D6A006A006A00');jump(c,0x70F76F)
        put(ROOM_TITLE,c.finish(),0x100)
    if not legacy_room:
        put(ROOM_NUMBER,b'01\0',0x20)
        for village in range(4):
            put(BOSS_STRINGS+village*32,local['game_strings'][str(2500+village)].encode('gbk')+b'\0',32)
        # Substitute only the native text pointer. Preserve controller records,
        # all other registers and the flags produced by the original ADD.
        for at,original,strings,native in (
            (ROOM_NAME,'8B45940538040000',TITLE_STRINGS,0x70F758),
            (ROOM_BOSS,'8B4594053C050000',BOSS_STRINGS,0x70FA2A)):
            c=Code(at);c.emit(original);c.emit('9C60');c.call(IS_CHALLENGE)
            c.emit('85C0');c.branch('0F84','native');c.call(0x419BBE)
            c.emit('8B8034E5010083E818C1E00505');c.u32(strings)
            c.emit('8944241C')
            c.label('native');c.emit('619D');jump(c,native);put(at,c.finish(),0x80)
    if not legacy_ranking and not legacy_room and not legacy_names:
        # Popup51 is local-cache only. Leave the original object lifecycle,
        # vtable, close buttons and draw loop intact; replace initialization
        # only for the exact four solo challenge tuples.
        c=Code(RANK_INIT);c.emit('9C60');c.call(IS_CHALLENGE)
        c.emit('85C0');c.branch('0F84','native');c.emit('619D60')
        c.emit('8B7DA0');c.call(0x419BBE);c.emit('8B35');c.u32(PROFILE)
        c.emit('8BB6A4260000')
        c.emit('6844010000');c.call(0xB479CC);c.emit('83C40485C0');c.branch('0F84','allocated')
        c.emit('8BC8');c.call(0x41BE00)
        c.label('allocated');c.emit('89472885C0');c.branch('0F84','badges')
        c.emit('6A00682C01000068900100006A0068');c.u32(0xCA5AA4)
        c.emit('8BC8');c.call(0x404232)
        c.label('badges');c.emit('33DB')
        c.label('loop');c.emit('8BC333D2B903000000F7F1')
        c.emit('8BC86BC92681C10C01000051') # y=268+38*challenge
        c.emit('8BCA03C90FB6440644D3E883E003')
        c.emit('69D28C00000081C2EE00000052508BCF');c.call(0x41E67D)
        c.emit('89449F2C4383FB0C');c.branch('0F82','loop')
        c.emit('61');jump(c,0x8C2DDE)
        c.label('native');c.emit('619D8B0D');c.u32(PROFILE);c.call(0x411379);jump(c,0x8C25B3)
        put(RANK_INIT,c.finish(),0x220)
        # CF88's existing B/A/S update must address our reserved cache row,
        # not index episode24..27 beyond the ordinary 60-byte table.
        c=Code(RANK_GET);c.emit('9C60');c.call(IS_CHALLENGE)
        c.emit('85C0');c.branch('0F84','native');c.emit('619D51');c.call(0x419BBE)
        c.emit('598B8034E5010083E8180FB64401448B54240C83FA03');c.branch('0F83','zero')
        c.emit('D1E2518BCAD3E85983E003C21000')
        c.label('zero');c.emit('33C0C21000')
        c.label('native');c.emit('619D');jump(c,0x40EDC2);put(RANK_GET,c.finish(),0x80)
        c=Code(RANK_SET);c.emit('9C60');c.call(IS_CHALLENGE)
        c.emit('85C0');c.branch('0F84','native');c.emit('619D5356578BF1');c.call(0x419BBE)
        c.emit('8B8034E5010083E8188D7406448B4C241883F903');c.branch('0F83','done')
        c.emit('D1E18B7C242083FF01');c.branch('0F82','done')
        c.emit('83FF03');c.branch('0F87','done')
        c.emit('0FB606D3E883E0033BC7');c.branch('0F83','done')
        c.emit('BB03000000D3E3F7D30FB60623C3D3E70BC78806')
        c.label('done');c.emit('5F5E5BC21400')
        c.label('native');c.emit('619D');jump(c,0x4103D9);put(RANK_SET,c.finish(),0x100)
        # The original last draw block labels ordinary dungeon rows. Draw
        # our four localized challenge names instead, with the same text ABI.
        c=Code(RANK_DRAW);c.emit('9C60');c.call(IS_CHALLENGE)
        c.emit('85C0');c.branch('0F84','native');c.emit('619D60')
        for row in range(4):
            c.emit('6A006A006A006A006A006A006A016A006A0068FFFFFF0068');c.u32(TITLE_STRINGS+row*32)
            c.emit('68');c.u32(268+38*row);c.emit('6880000000');c.call(0x414A6F)
            c.emit('8BC8');c.call(0x40DA1C)
        c.emit('61');jump(c,0x8C3182)
        c.label('native');c.emit('619D');c.call(0x419BBE);jump(c,0x8C30F2)
        put(RANK_DRAW,c.finish(),0x240)
    return bytes(data)


def sites():
    result=list(dialogue_sites())
    result.append(('monk_gameplay_ui',EXT_BASE,b'\xCC'*EXT_SPAN,gameplay_payload()))
    for name,at,native,target in (
        ('monk_ready_update_guard',0x737C49,0x411379,VILLAGE_GATE),
        ('monk_ready_map_guard',0x737DBE,0x403D2D,HD_GATE),
        ('monk_ready_icons_guard',0x737DED,0x403D2D,HD_GATE),
        ('monk_late_guide_draw',0x5278F1,0x41CB16,LATE_DRAW),
        ('monk_result_named_header',0x764C96,0x419BBE,RESULT_TITLE),
        ('monk_ready_named_header',0x737DAD,0x411379,0x411379)):
        opcode = b'\xE9' if target == RESULT_TITLE else b'\xE8'
        result.append((name,at,b'\xE8'+struct.pack('<i',native-at-5),opcode+struct.pack('<i',target-at-5)))
    for name,at,native,target in (
        ('monk_rank_result_read',0x6FA50D,0x40EDC2,RANK_GET),
        ('monk_rank_result_write',0x6FA591,0x4103D9,RANK_SET),
        ('monk_rank_popup_draw',0x8C30ED,0x419BBE,RANK_DRAW)):
        result.append((name,at,b'\xE8'+struct.pack('<i',native-at-5),
                       b'\xE8'+struct.pack('<i',target-at-5) if target != RANK_DRAW else b'\xE9'+struct.pack('<i',target-at-5)))
    result.append(('monk_rank_popup_init',0x8C25A8,bytes.fromhex('8B0DD469D800E8C6EDB4FF'),
                   b'\xE9'+struct.pack('<i',RANK_INIT-0x8C25A8-5)+b'\x90'*6))
    result.extend(followup_sites())
    for name,at,original,target in (
        ('monk_room_named_header',0x70F769,'6A006A006A00',ROOM_TITLE),
        ('monk_room_stage_name',0x70F750,'8B45940538040000',ROOM_NAME),
        ('monk_room_boss_name',0x70FA22,'8B4594053C050000',ROOM_BOSS),
        ('monk_result_retry_only_input',0x762F74,'8B4DEC83792000',RESULT_RETRY_INPUT),
        ('monk_result_retry_only_draw',0x76523A,'8B856CFFFFFF',RESULT_RETRY_DRAW)):
        old=bytes.fromhex(original)
        result.append((name,at,old,b'\xE9'+struct.pack('<i',target-at-5)+b'\x90'*(len(old)-5)))
    return tuple(result)


# The reserved int3 range 0x73893C..0x73AFA0 contains the compatibility
# code and its writable state.
FOLLOW_BASE, FOLLOW_SPAN = 0x738A00, 0x2000
CAPTURE_ORIGIN, ARM_RESULT = FOLLOW_BASE, FOLLOW_BASE+0x180
CAPTURE_RESULT, OPEN_RESULT = FOLLOW_BASE+0x240, FOLLOW_BASE+0x380
PUMP_RESULT = FOLLOW_BASE+0x580
MARK_RETURN = PUMP_RESULT
INIT_PORTRAIT, PORTRAIT_PATHS = FOLLOW_BASE+0x680, FOLLOW_BASE+0x800
RESULT_STATE, OUTCOME_TABLE, OUTCOME_TEXT = FOLLOW_BASE+0x900, FOLLOW_BASE+0xA00, FOLLOW_BASE+0xC00
# State DWORDs: armed, pending row, episode, UID, returned, origin village/page.


def followup_payload(legacy_portrait=False, legacy_names=False):
    data=bytearray(b'\xCC'*FOLLOW_SPAN)
    def put(at, raw, limit):
        if len(raw)>limit: raise ValueError(f'followup region overflow {at:x}: {len(raw)} > {limit}')
        data[at-FOLLOW_BASE:at-FOLLOW_BASE+len(raw)]=raw
    def jump(c,at): c.emit(b'\xE9'+struct.pack('<i',at-c.base-len(c.data)-5))
    put(RESULT_STATE,b'\0'*64,64)
    local=localization(legacy_names)
    cursor=OUTCOME_TEXT
    for village in range(4):
        for outcome in range(2):
            # Existing translated success/failure text, without entry invitation.
            text=local['quest_strings'][str(6001+3*village+outcome)]
            lines=[]
            for paragraph in text.split('^&'):
                line=''
                for ch in paragraph:
                    if len((line+ch).encode('gbk'))>48: lines.append(line);line=''
                    line+=ch
                if line: lines.append(line)
            pages=[b''.join(x.encode('gbk').ljust(51,b'\0') for x in (lines[i:i+4]+['']*4)[:4]) for i in range(0,len(lines),4)]
            raw=b''.join(pages)
            at=OUTCOME_TABLE+32*(village*2+outcome)
            put(at,struct.pack('<8I',village,ENTRIES[village][1],0,0,0,0,cursor,len(pages)),32)
            put(cursor,raw,FOLLOW_BASE+FOLLOW_SPAN-cursor);cursor+=len(raw)

    # Village+0x3B0 is assigned only by MakeChar(isMy) at 0x535530.
    # The old +0x334 is the mouse object. Both actor getters return world floats.
    c=Code(CAPTURE_ORIGIN);c.emit('5356578BF18BBEB003000085FF');c.branch('0F84','no')
    c.emit('8BCF');c.call(0x41B5D1);c.emit('8BD86AFF8B0D');c.u32(PROFILE);c.call(0x40B744)
    c.emit('3BC3');c.branch('0F85','no')
    c.emit('8BCF');c.call(0x4043D6);c.call(0xB4CA30);c.emit('50')
    c.emit('8BCF');c.call(0x417184);c.call(0xB4CA30);c.emit('508BFC')
    # Reject an absent/blocked map sample rather than freeze a cursor or guessed point.
    c.emit('8B0D');c.u32(0xD732C4);c.emit('85C9');c.branch('0F84','blocked')
    c.emit('6A01FF37FF7704');c.call(0x4157CB);c.emit('85C0');c.branch('0F85','blocked')
    c.emit('8B4704A3');c.u32(ORIGIN+12);c.emit('8B07A3');c.u32(ORIGIN+16)
    c.emit('83C408B801000000');c.branch('E9','done')
    c.label('blocked');c.emit('83C408')
    c.label('no');c.emit('33C0');c.label('done');c.emit('5F5E5BC3');put(CAPTURE_ORIGIN,c.finish(),0x180)

    # Actual CF80 dispatcher entry; only a new battle arms the next own result.
    c=Code(ARM_RESULT);c.emit('9C60C705');c.u32(RESULT_STATE);c.u32(0)
    c.emit('C705');c.u32(RESULT_STATE+4);c.u32(0)
    if not legacy_portrait:
        c.emit('C705');c.u32(RESULT_STATE+16);c.u32(0)
    c.call(IS_CHALLENGE);c.emit('85C0');c.branch('0F84','done')
    c.emit('833D');c.u32(ORIGIN);c.emit('01');c.branch('0F85','done')
    c.call(0x419BBE);c.emit('8B8034E50100A3');c.u32(RESULT_STATE+8)
    if not legacy_portrait:
        c.emit('83E8183B05');c.u32(ORIGIN+4);c.branch('0F85','done')
    c.emit('6AFF8B0D');c.u32(PROFILE);c.call(0x40B744);c.emit('A3');c.u32(RESULT_STATE+12)
    if not legacy_portrait:
        for source,target in ((ORIGIN+4,RESULT_STATE+20),(ORIGIN+8,RESULT_STATE+24)):
            c.emit('A1');c.u32(source);c.emit('A3');c.u32(target)
    c.emit('C705');c.u32(RESULT_STATE);c.u32(1)
    c.label('done');c.emit('619D');jump(c,0x419BBE);put(ARM_RESULT,c.finish(),0xC0)

    # CF88 row+0 is UID; BYTE+0xA4 is wire rating (0 F, 1..5 D..S).
    # Duplicate/foreign/stale rows are still passed to the native result handler.
    c=Code(CAPTURE_RESULT);c.emit('9C608B742428833D');c.u32(RESULT_STATE);c.emit('01');c.branch('0F85','done')
    c.call(IS_CHALLENGE);c.emit('85C0');c.branch('0F84','done')
    c.call(0x419BBE);c.emit('8B8034E501003B05');c.u32(RESULT_STATE+8);c.branch('0F85','done')
    c.emit('8B063B05');c.u32(RESULT_STATE+12);c.branch('0F85','done')
    c.emit('6AFF8B0D');c.u32(PROFILE);c.call(0x40B744);c.emit('3B06');c.branch('0F85','done')
    c.emit('0FB686A400000083F805');c.branch('0F87','done')
    c.emit('85C00F94C10FB6C98B15');c.u32(RESULT_STATE+8)
    c.emit('83EA18D1E201CAC1E20581C2');c.u32(OUTCOME_TABLE)
    c.emit('8915');c.u32(RESULT_STATE+4);c.emit('C705');c.u32(RESULT_STATE);c.u32(0)
    c.label('done');c.emit('619D');jump(c,0x407ACC);put(CAPTURE_RESULT,c.finish(),0x140)

    # CF88 only records. A matching return authorizes the later village tick.
    c=Code(OPEN_RESULT);c.emit('5356578BF18B1D');c.u32(RESULT_STATE+4);c.emit('85DB');c.branch('0F84','no')
    if legacy_portrait:
        c.emit('837E3C01');c.branch('0F85','no');c.call(IS_CHALLENGE);c.emit('85C0');c.branch('0F84','no')
        c.call(0x419BBE);c.emit('8B8034E501003B05');c.u32(RESULT_STATE+8);c.branch('0F85','no')
    else:
        c.emit('833D');c.u32(RESULT_STATE+16);c.emit('01');c.branch('0F85','no')
        c.emit('8B0D');c.u32(PROFILE);c.call(0x411379)
        c.emit('3B05');c.u32(RESULT_STATE+20);c.branch('0F85','discard')
        c.emit('6AFF8B0D');c.u32(PROFILE);c.call(0x41DE8A)
        c.emit('3B05');c.u32(RESULT_STATE+24);c.branch('0F85','discard')
        c.emit('6AFF8B0D');c.u32(PROFILE);c.call(0x40B744)
        c.emit('3B05');c.u32(RESULT_STATE+12);c.branch('0F85','discard')
        c.emit('8B8EB003000085C9');c.branch('0F84','no');c.call(0x41B5D1)
        c.emit('3B05');c.u32(RESULT_STATE+12);c.branch('0F85','discard')
        c.emit('83BE3403000000');c.branch('0F84','no')
    c.call(0x406F82);c.emit('8BC8');c.call(0x7EBC20);c.emit('85C0');c.branch('0F84','no')
    c.emit('68');c.u32(WINDOW_SIZE);c.call(0xB479CC);c.emit('83C40485C0');c.branch('0F84','no')
    c.emit('8BC8');c.call(0x4064FB);c.emit('8BF86A098BCF');c.call(0x41759E)
    c.emit('C707');c.u32(VTABLE);c.emit('895F44C7474800000000C7474C0100000066C747340100')
    c.emit('FF764C' if legacy_portrait else 'FFB634030000')
    c.emit('8D8F00020000');c.call(0x4163BF)
    c.emit('6A006A008D8F00020000');c.call(0xA12CC0)
    if not legacy_portrait:
        c.emit('8B138D8F00020000');c.call(INIT_PORTRAIT)
    c.emit('C78700020000');c.emit('修道'.encode('gbk'));c.emit('C78704020000');c.emit('僧'.encode('gbk')+b'\0\0')
    c.emit('8BCF');c.call(PAGE);c.emit('57');c.call(0x406F82);c.emit('8BC8');c.call(0x410299)
    c.emit('C705');c.u32(RESULT_STATE+4);c.u32(0)
    if not legacy_portrait:
        c.emit('C705');c.u32(RESULT_STATE+16);c.u32(0)
    for target in (0x418B83,0x419B0A):c.call(0x40ED77);c.emit('8BC8');c.call(target)
    c.emit('B801000000');c.branch('E9','done')
    if not legacy_portrait:
        c.label('discard')
        for at in (RESULT_STATE,RESULT_STATE+4,RESULT_STATE+16):
            c.emit('C705');c.u32(at);c.u32(0)
    c.label('no');c.emit('33C0');c.label('done');c.emit('5F5E5BC3')
    put(OPEN_RESULT,c.finish(),0x200)
    if legacy_portrait:
        c=Code(PUMP_RESULT);c.emit('9C608B4DEC');c.call(OPEN_RESULT);c.emit('85C0');c.branch('0F84','native')
        c.emit('619D');jump(c,0x763FEA)
        c.label('native');c.emit('619D8B55EC837A3C01');jump(c,0x762F10);put(PUMP_RESULT,c.finish(),0x100)
    else:
        c=Code(MARK_RETURN)
        for at in (RESULT_STATE,RESULT_STATE+16):
            c.emit('C705');c.u32(at);c.u32(0)
        c.emit('833D');c.u32(RESULT_STATE+4);c.emit('00');c.branch('0F84','done')
        for source,target in ((ORIGIN+4,RESULT_STATE+20),(ORIGIN+8,RESULT_STATE+24)):
            c.emit('A1');c.u32(source);c.emit('3B05');c.u32(target);c.branch('0F85','discard')
        c.emit('6AFF8B0D');c.u32(PROFILE);c.call(0x40B744)
        c.emit('3B05');c.u32(RESULT_STATE+12);c.branch('0F85','discard')
        c.emit('C705');c.u32(RESULT_STATE+16);c.u32(1);c.branch('E9','done')
        c.label('discard');c.emit('C705');c.u32(RESULT_STATE+4);c.u32(0)
        c.label('done');c.emit('C3');put(MARK_RETURN,c.finish(),0x100)
    if not legacy_portrait:
        # Native guide owns +0xF4: A13630 draws it; A12790 releases it.
        # Reuse the original effect ABI without A12EC0's CN name-table lookup.
        c=Code(INIT_PORTRAIT);c.emit('56578BF183FA03');c.branch('0F87','done')
        c.emit('C1E20681C2');c.u32(PORTRAIT_PATHS);c.emit('8BFA')
        c.emit('6844010000');c.call(0xB479CC);c.emit('83C40485C0');c.branch('0F84','done')
        c.emit('8BC8');c.call(0x41BE00);c.emit('8986F4000000')
        c.emit('6A00FFB630010000FFB62C0100006A00578BC8');c.call(0x404232)
        c.label('done');c.emit('5F5EC3');put(INIT_PORTRAIT,c.finish(),0x180)
        for village in range(4):
            put(PORTRAIT_PATHS+village*64, f'interface\\NPC_{62+village}_0.eff'.encode('ascii')+b'\0',64)
    return bytes(data)


def followup_sites():
    out=[('monk_gameplay_followup',FOLLOW_BASE,b'\xCC'*FOLLOW_SPAN,followup_payload())]
    for name,at,native,target in [('monk_result_arm',0x6F749D,0x419BBE,ARM_RESULT),
                                  ('monk_result_capture',0x6FA2CF,0x407ACC,CAPTURE_RESULT)]:
        out.append((name,at,b'\xE8'+struct.pack('<i',native-at-5),b'\xE8'+struct.pack('<i',target-at-5)))
    out.append(('monk_result_dialogue_pump',0x762F09,
                b'\xE9'+struct.pack('<i',PUMP_RESULT-0x762F09-5)+b'\x90'*2,
                bytes.fromhex('8B55EC837A3C01')))
    return tuple(out)
