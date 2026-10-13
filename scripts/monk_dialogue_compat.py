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
GUIDE, WINDOW_SIZE, PAGE_SIZE = 0x200, 0x400, 204
PROFILE = 0xD869D4
ENTRIES = ((0, 27, 293, 157), (1, 26, 282, 425), (2, 12, 127, 416), (3, 6, 186, 255))


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


def legacy_payload():
    """Exact released confirmation-window encoding, accepted only for migration."""
    TEXT = BASE + 0xA00
    local = json.loads((ROOT / 'manifest/monk_localization.json').read_text('utf-8'))
    data = bytearray(b'\xCC' * SPAN)
    def put(at, value, limit):
        if len(value) > limit: raise ValueError('monk dialogue region overflow')
        data[at-BASE:at-BASE+len(value)] = value
    put(VTABLE, struct.pack('<8I', 0x40E903, 0x403247, DIALOGUE, 0x40EC50,
                           0x402D51, 0x417BFC, 0x41AE92, 0x4066F9), 32)
    put(ORIGIN, b'\0' * 32, 32)
    cursor = TEXT
    for index, (village, page, x, y) in enumerate(ENTRIES):
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


def payload():
    local = json.loads((ROOT / 'manifest/monk_localization.json').read_text('utf-8'))
    data = bytearray(b'\xCC' * SPAN)
    def put(at, value, limit):
        if len(value) > limit:
            raise ValueError('monk dialogue region overflow')
        data[at-BASE:at-BASE+len(value)] = value
    # Own the window lifetime; the embedded native guide owns only its UI assets.
    put(VTABLE, struct.pack('<8I', DESTROY, 0x403247, DIALOGUE, DRAW+0x80,
                           DRAW, 0x41B50E, 0x41AE92, DRAW+0x80), 32)
    put(ORIGIN, b'\0' * 32, 32)
    cursor = TEXT
    for index, (village, page, x, y) in enumerate(ENTRIES):
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
    c.emit('8BD86A00'); c.call(0x40ED77); c.emit('8BC8'); c.call(0x415ED3)
    c.emit('85C0'); c.branch('0F84', 'done')
    c.emit('8B8E34030000'); c.call(0x4043D6); c.call(0xB4CA30)
    c.emit('A3'); c.u32(ORIGIN+12)
    c.emit('8B8E34030000'); c.call(0x417184); c.call(0xB4CA30)
    c.emit('A3'); c.u32(ORIGIN+16)
    c.emit('8B03A3'); c.u32(ORIGIN+4)
    c.emit('8B4304A3'); c.u32(ORIGIN+8)
    c.emit('68'); c.u32(WINDOW_SIZE); c.call(0xB479CC)
    c.emit('83C40485C0'); c.branch('0F84', 'done')
    c.emit('8BC8'); c.call(0x4064FB); c.emit('8BF8')
    c.emit('6A098BCF'); c.call(0x41759E)
    c.emit('C707'); c.u32(VTABLE)
    c.emit('895F44C747480000000066C747340100')
    c.emit('FFB6340300008D8F00020000'); c.call(0x4163BF)
    # No unrelated NPC portrait: native tutorial frame/next/end buttons only.
    c.emit('6A006A008D8F00020000'); c.call(0xA12CC0)
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
    c.emit('568BF1'); c.call(0x527C80); c.emit('508BCE'); c.call(HIT)
    c.emit('85C0'); c.branch('0F84', 'done')
    c.emit('6A058B8E34030000'); c.call(0x402770)
    c.label('done'); c.emit('585EC3')
    put(HOVER, c.finish(), 0x100)

    c = Code(DRAW)
    c.emit('81C100020000')
    c.emit(b'\xE9'+struct.pack('<i',0xA13630-DRAW-len(c.data)-5))
    put(DRAW, c.finish(), 0x80)
    put(DRAW+0x80, bytes.fromhex('B801000000C3'), 0x80)
    c = Code(DESTROY)
    c.emit('568BF181C100020000'); c.call(0x41B6A8)
    c.emit('8BCE5E')
    c.emit(b'\xE9'+struct.pack('<i',0x4D7830-DESTROY-len(c.data)-5))
    put(DESTROY, c.finish(), 0x100)
    old = legacy_payload()
    put(RETURN, old[RETURN-BASE:RETURN-BASE+0x100], 0x100)
    return bytes(data)


def sites():
    return (('monk_dialogue_controller',BASE,b'\xCC'*SPAN,payload()),
            ('monk_village_update',0x527CCD,bytes.fromhex('E8F821EFFF'),
             b'\xE8'+struct.pack('<i',UPDATE-0x527CCD-5)),
            ('monk_ready_episode',0x72F20D,bytes.fromhex('E834F4CEFF'),
             b'\xE8'+struct.pack('<i',READY-0x72F20D-5)),
            ('monk_origin_restore',0x53CE10,bytes.fromhex('DB45E48B8554F8FFFF'),
             b'\xE9'+struct.pack('<i',RETURN-0x53CE10-5)+b'\x90'*4),
            ('monk_hover_update',0x52A751,bytes.fromhex('E88B54EEFF'),
             b'\xE8'+struct.pack('<i',HOVER-0x52A751-5)))
