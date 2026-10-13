"""Build/apply/verify/rollback additive local monk trial resources.

The standard stage is (0,24,0,0), with nine independent selection/preload slots.
Independent Chinese catalogs and dtype0 action are unbound entry placeholders.
Resource preparation and client entrance acceptance have separate lifecycles.
Build uses PyCryptodome; deployment reuses the shared resource transaction.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import struct
import uuid
import xml.etree.ElementTree as ET

try:
    from . import port_lumineos_resources as io
except ImportError:
    import port_lumineos_resources as io

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / 'manifest/monk_resource_port.json'
LOCALIZATION = ROOT / 'manifest/monk_localization.json'
SCHEMA = 'openNanaimo.monk-resources.v1'
MARKER = '.openNanaimo-monk-resources.json'
EXTENSIONS = {'.sstg', '.smmo', '.sm2', '.mmo', '.pon', '.bmo', '.eff',
              '.crs', '.im3', '.wav', '.ogg'}
CN_KEY = bytes.fromhex('0123456789abcdef123456789abcdef0')
LOCALIZATION_METADATA_REVISIONS = frozenset({'fa73c1fc8c0c853cd646909ab214b3e5edc1909146f1ac70781e4c667525a5a6'})


def codec_module():
    try:
        from . import lumineos_codec
    except ImportError:
        import lumineos_codec
    return lumineos_codec


def checked(path, sha256, size=None):
    data = path.read_bytes()
    if io.digest(data) != sha256 or (size is not None and len(data) != size):
        raise ValueError('resource identity mismatch: ' + str(path))
    return data


def reference(value):
    return bool(value) and Path(value.replace('\\', '/')).suffix.lower() in EXTENSIONS


class ResourceIndex:
    def __init__(self, root):
        self.root = io.clean_root(root)
        self.names = defaultdict(list)
        for folder in ('flying', 'effs', 'images', 'sounds'):
            base = io.safe(self.root, folder)
            for path in sorted(base.rglob('*')):
                if path.is_file():
                    rel = path.relative_to(self.root).as_posix()
                    self.names[path.name.lower()].append(rel)

    def locate(self, name):
        name = name.replace('\\', '/')
        direct = io.safe(self.root, name)
        if direct.is_file():
            return name
        if '/' in name:
            raise ValueError('missing explicit resource: ' + name)
        folder = {'.bmo': 'flying/mmo', '.mmo': 'flying/mmo', '.pon': 'flying/mmo',
                  '.eff': 'effs/game/shootinggamebasic', '.smmo': 'flying',
                  '.sm2': 'flying/map', '.crs': 'images/game_images/shootinggamebasic/coll'}
        preferred = folder.get(Path(name).suffix.lower())
        if preferred and io.safe(self.root, preferred + '/' + name).is_file():
            return preferred + '/' + name
        choices = self.names.get(name.lower(), [])
        if not choices or len({io.file_hash(io.safe(self.root, p)) for p in choices}) != 1:
            raise ValueError('missing/ambiguous resource: ' + name)
        return choices[0]

    def read(self, name):
        return io.safe(self.root, self.locate(name)).read_bytes()


def bmo_model(raw):
    c = codec_module()
    r = c.Reader(c.xor(raw, 56))
    header = struct.unpack('<11I', r.read(44))
    if header[0] != 2 or header[10] >= 64:
        raise ValueError('unsupported BMO header')
    modes, fields = [], []
    for mode in range(header[10] + 1):
        offset = r.p
        prefix = r.read(308)
        if prefix[0] != 0:
            raise ValueError('unsupported BMO mode layout')
        count = struct.unpack_from('<I', prefix, 304)[0]
        if not 1 <= count <= 100:
            raise ValueError('invalid BMO child count')
        children = []
        effects = []
        for relative in (0, 104, 204):
            field = prefix[relative:relative + 100]
            value = field.split(b'\0', 1)[0].decode('ascii')
            if b'\0' not in field or (value and not value.lower().endswith('.eff')):
                raise ValueError('unsupported BMO effect field')
            if value: effects.append(value)
            fields.append((offset + relative, 100))
        for _ in range(count):
            offset = r.p
            field = r.read(208)
            name = field.split(b'\0', 1)[0].decode('ascii')
            if b'\0' not in field or not name.lower().endswith('.mmo'):
                raise ValueError('invalid BMO child reference')
            children.append(name)
            fields.append((offset, 208))
        modes.append(dict(mode=mode, children=children, effects=effects))
    r.end()
    return dict(version=2, string_uid=header[1], modes=modes), fields


def crs_model(raw):
    if len(raw) < 8:
        raise ValueError('truncated CRS bitmap')
    width, height = struct.unpack_from('<2I', raw)
    stride = ((width + 31) // 32) * 4
    if not (0 < width <= 65536 and 0 < height <= 65536) or len(raw) != 8 + stride * height:
        raise ValueError('unsupported CRS bitmap boundary')
    return dict(width=width, height=height, stride=stride, refs=[])


def smmo_model(raw):
    c = codec_module()
    r = c.Reader(c.xor(raw, 40))
    count = r.u32()
    if count > 1000000:
        raise ValueError('invalid SMMO count')
    placements = [struct.unpack('<4I', r.read(16)) for _ in range(count)]
    tail = r.fixed(260).decode('ascii')
    r.end()
    return placements, [tail] if reference(tail) else []


def parse_resource(raw, rel, root, *, kr):
    c = codec_module()
    ext = Path(rel).suffix.lower()
    if ext == '.sstg':
        model = c.sstg(raw)
        return model['refs'], model
    if ext == '.smmo':
        placements, refs = smmo_model(raw)
        return refs, dict(placement_count=len(placements))
    if ext == '.mmo':
        eff, rows, refs = c.mmo_model(raw, root, kr)
        return [v.decode('ascii') for v in refs], dict(rows=len(rows), eff=eff.decode('ascii'))
    if ext == '.pon':
        eff, _, rows, _, refs = c.pon_model(raw, root, kr)
        return [v.decode('ascii') for v in refs], dict(rows=len(rows), eff=eff.decode('ascii'))
    if ext == '.bmo':
        model, _ = bmo_model(raw)
        return [name for mode in model['modes'] for name in mode['children'] + mode['effects']], model
    if ext == '.eff':
        model = c.eff2(raw)
        return model['refs'], dict(rows=len(model['rows']))
    if ext == '.sm2':
        model = c.sm2(raw)
        return model['refs'] + ['images/game_images/shootinggamebasic/coll/tile_16_16.crs'], model
    if ext == '.crs':
        return [], crs_model(raw)
    if ext not in EXTENSIONS:
        raise ValueError('unsupported resource extension: ' + rel)
    return [], dict(terminal_asset=True)


def closure(source, stage):
    index = ResourceIndex(source)
    queue = deque([stage])
    nodes, edges = {}, []
    while queue:
        rel = index.locate(queue.popleft())
        if rel in nodes:
            continue
        raw = io.safe(index.root, rel).read_bytes()
        refs, model = parse_resource(raw, rel, index.root, kr=True)
        nodes[rel] = dict(size=len(raw), sha256=io.digest(raw), model=model)
        for name in sorted(set(refs)):
            if reference(name):
                target = index.locate(name)
                edges.append(dict(source=rel, reference=name, target=target))
                queue.append(target)
    return index, nodes, edges


def name_fields(raw, rel):
    """Enumerate bounded fixed-string fields of supported output formats."""
    c = codec_module()
    ext = Path(rel).suffix.lower()
    key = {'.sstg': 40, '.smmo': 40, '.mmo': 171, '.pon': 171, '.bmo': 56}.get(ext, 0)
    if ext == '.bmo':
        return c.xor(raw, key), [(off, size, 0) for off, size in bmo_model(raw)[1]], key
    plain = bytearray(raw if ext in ('.mmo', '.pon', '.sm2', '.eff') else c.xor(raw, key))
    r = c.Reader(plain)
    fields = []

    def field(size, mask=0):
        offset = r.p
        r.read(size)
        fields.append((offset, size, mask))

    if ext == '.sstg':
        r.read(8)
        def layer():
            field(260); field(260); r.read(4)
        for _ in range(r.u32()): layer()
        layer()
        for _ in range(r.u32()): layer()
        field(260); field(260)
        for _ in range(r.u32()): r.read(8); field(260)
        for _ in range(9): field(260); r.read(4); field(260)
        field(260)
        r.read(r.u32() * 12)
        for _ in range(9):
            for _ in range(r.u32()): field(260)
        r.read(16)
    elif ext == '.smmo':
        r.read(r.u32() * 16); field(260)
    elif ext == '.mmo':
        if r.u32() != 200: raise ValueError('expected MMO200')
        field(64, key)
        while r.p < len(plain):
            for _, size in c.SCALARS: r.read(size)
            for _ in range(3): field(64, key)
            for inner in (0, 8):
                for _ in range(r.u8()):
                    offset = r.p
                    r.read(72)
                    fields.append((offset + inner, 64, key))
            r.read(8)
            field(64, key); field(64, key); r.read(4); field(64, key)
            for _ in range(3): r.read(4); field(64, key)
            for _ in range(r.u8()):
                offset = r.p
                r.read(72)
                fields.append((offset, 64, key))
    elif ext == '.pon':
        if r.u32() != 106: raise ValueError('expected PON106')
        field(260, key); r.read(28)
        count, remainder = divmod(len(plain) - r.p - 260, 1612)
        if remainder or count < 0: raise ValueError('PON row boundary')
        for _ in range(count):
            offset = r.p
            r.read(1612)
            fields.extend((offset + off, 260, key) for off in (0, 280, 540, 800, 1060, 1340))
        field(260, key)
    elif ext == '.eff':
        r.read(16)
        for _ in range(r.u32()):
            r.read(8); field(260)
            for _ in range(12): r.read(r.u32() * 16)
            r.read(48)
    elif ext == '.sm2':
        def scalar(mask): return struct.unpack('<I', c.xor(r.read(5)[:4], mask))[0]
        version = scalar(40); scalar(40); scalar(19)
        cols = scalar(31); rows = scalar(163); count = scalar(33); r.read(5)
        for _ in range(count): field(261, 89)
        if version != 2: r.read(cols * rows * 30)
        for _ in range(scalar(40)): field(261, 40)
        r.read(scalar(40) * 14)
    else:
        return plain, [], 0
    r.end()
    return plain, fields, 0 if ext in ('.mmo', '.pon', '.sm2', '.eff') else key


def rename_value(value, renames):
    normalized = value.replace('\\', '/')
    replacement = renames.get(normalized.lower())
    if replacement is None:
        replacement = renames.get(Path(normalized).name.lower())
        if replacement and '/' in normalized:
            replacement = normalized.rsplit('/', 1)[0] + '/' + replacement
    if not replacement: return value
    return replacement.replace('/', '\\') if '\\' in value else replacement


def rewrite_names(raw, rel, renames):
    c = codec_module()
    plain, fields, outer = name_fields(raw, rel)
    plain = bytearray(plain)
    count = 0
    for offset, size, mask in fields:
        value = c.xor(plain[offset:offset + size], mask).split(b'\0', 1)[0].decode('ascii')
        replacement = rename_value(value, renames)
        if replacement != value:
            data = replacement.encode('ascii')
            if len(data) >= size: raise ValueError('renamed reference exceeds capacity')
            plain[offset:offset + size] = c.xor(data.ljust(size, b'\0'), mask)
            count += 1
    return c.xor(plain, outer) if outer else bytes(plain), count


def encrypt_cn(raw):
    from Crypto.Cipher import AES
    padding = 16 - len(raw) % 16
    return AES.new(CN_KEY, AES.MODE_CBC, bytes(16)).encrypt(raw + bytes([padding]) * padding)


def localized_resources(localization):
    io.encoded(localization).decode('utf-8').encode('gbk')
    qs = localization['quest_strings']
    gs = localization['game_strings']
    expected = {str(i) for i in (*range(2062, 2066), *range(4000, 4004), *range(6000, 6012))}
    if set(qs) != expected:
        raise ValueError('incomplete monk dialogue')
    for text in list(qs.values()) + list(gs.values()):
        if not text or any(x in text for x in ('#', '\0')):
            raise ValueError('invalid localized catalog text')
        text.encode('gbk')
    qfields = ['NANA_QUEST_TEXT', '80625.01', str(len(qs))]
    gfields = ['NANA_TEXT', 'CN00106.01']
    for uid, text in sorted(qs.items(), key=lambda pair: int(pair[0])):
        qfields.extend((uid, text))
    for uid, text in sorted(gs.items(), key=lambda pair: int(pair[0])):
        gfields.extend((uid, text))
    qraw = ('#'.join(qfields) + '#').encode('gbk')
    graw = ('#'.join(gfields) + '#').encode('gbk')
    root = ET.Element('SCRIPTS', target='0', version='20080904.01')
    for i in range(4):
        script = ET.SubElement(root, 'SCRIPT', uid=str(24000 + i))
        speech = dict(type='SPEECH', npc_uid=str(62 + i), expression='0', value='0', close='1', face_count='2')
        ET.SubElement(script, 'ACTION', **dict(speech, string_uid=str(6000 + 3 * i)))
        ET.SubElement(script, 'ACTION', type='D_START', dtype='0', episode=str(24 + i),
                      dungeon='0', level='0', condition='1')
        ET.SubElement(script, 'ACTION', type='CONDITION', value='1', goto='4')
        ET.SubElement(script, 'ACTION', **dict(speech, string_uid=str(6002 + 3 * i)))
        ET.SubElement(script, 'ACTION', type='COMPLETE', step_clear='0')
        ET.SubElement(script, 'ACTION', **dict(speech, string_uid=str(6001 + 3 * i)))
        ET.SubElement(script, 'ACTION', type='COMPLETE', step_clear='1')
    ET.indent(root, space='  ')
    xml = b'<?xml version="1.0" encoding="GBK"?>\n' + ET.tostring(root, encoding='unicode').encode('gbk') + b'\n'
    ET.fromstring(xml.decode('gbk').split('\n', 1)[1])
    prefix = '.openNanaimo-monk/'
    return {prefix + 'monk_qs._D31': encrypt_cn(qraw), prefix + 'monk_gs._D20': encrypt_cn(graw),
            prefix + 'monk_action.xml': xml, prefix + 'monk_action._S1': encrypt_cn(xml)}


def stage_summary(index, model):
    c = codec_module()
    entries = {uid: (kind, name) for uid, kind, name in model['monsters']}
    if len(entries) != len(model['monsters']):
        raise ValueError('duplicate stage monster UID')
    rows_cache = {}

    def rows(name):
        if name not in rows_cache:
            rows_cache[name] = c.mmo_model(index.read(name), index.root, True)[1]
        return rows_cache[name]

    slots = []
    for slot, (name, percent, option) in enumerate(model['slots']):
        placements, _ = smmo_model(index.read(name))
        names, types, positive, total = set(), Counter(), 0, 0
        for _, _, uid, _ in placements:
            if uid not in entries: raise ValueError('unknown SMMO monster UID')
            kind, resource = entries[uid]
            if kind != 0: continue
            names.add(resource)
            for mem, _ in rows(resource):
                total += 1
                types[mem[4]] += 1
                positive += struct.unpack_from('<i', mem, 8)[0] > 0
        slots.append(dict(slot=slot, smmo=name, percent=percent, option=option,
                          placements=len(placements), ordinary_rows=total, positive_hp_rows=positive,
                          target_types=dict(types), ordinary_resources=sorted(names),
                          preload=model['extra'][slot]))
    bosses = []
    for uid, kind, name in model['monsters']:
        if kind != 3: continue
        bmo, _ = bmo_model(index.read(name))
        modes = []
        for mode in bmo['modes']:
            children = []
            for child in mode['children']:
                components = [dict(ordinal=i, type=mem[4], hp=struct.unpack_from('<i', mem, 8)[0],
                                   parent=struct.unpack_from('<i', mem, 408)[0])
                              for i, (mem, _) in enumerate(rows(child))]
                children.append(dict(resource=child.replace('\\', '/'), components=components))
            modes.append(dict(mode=mode['mode'], child_count=len(children), children=children, effects=mode['effects']))
        bosses.append(dict(uid=uid, resource=name, mode_count=len(modes), modes=modes))
    return dict(identity=list(model['identity']), endframe=model['endframe'], slots=slots, bosses=bosses)


def plan(source, client, recipe, localization, *, check_pins=True):
    c = codec_module()
    source, client = map(io.clean_root, (source, client))
    for pin in recipe.get('source_inputs', []):
        checked(io.safe(source, pin['path']), pin['sha256'], pin['size'])
    stage = recipe['stage']
    checked(io.safe(source, stage['source_path']), stage['source_sha256'], stage['source_size'])
    index, nodes, edges = closure(source, stage['source_path'])
    if check_pins:
        expected = {r['source_path']: (r['source_sha256'], r['source_size'])
                    for r in recipe['files'] if r.get('source_scope', 'client') == 'client'}
        actual = {path: (node['sha256'], node['size']) for path, node in nodes.items()}
        if expected != actual:
            raise ValueError('source dependency coverage differs from pinned recipe')
    model = c.sstg(index.read(stage['source_path']))
    if list(model['identity']) != stage['source_identity']:
        raise ValueError('unexpected source stage identity')
    renames = {}
    for old, new in recipe['renames'].items():
        io.safe(source, old)
        io.safe(client, new)
        renames[old.lower()] = new
        basename = Path(old).name.lower()
        if basename in renames: raise ValueError('ambiguous rename')
        renames[basename] = Path(new).name
    targets = {rel: recipe['renames'].get(rel, rel) for rel in nodes}
    targets[stage['source_path']] = stage['path']
    data, records, preserved = {}, [], {}
    cn_index = ResourceIndex(client)
    for original in recipe['renames']:
        baseline = io.file_hash(io.safe(client, original))
        if baseline is not None:
            preserved[original] = baseline
    for rel, node in sorted(nodes.items()):
        raw = checked(io.safe(source, rel), node['sha256'], node['size'])
        target = targets[rel]
        transform = 'copy'
        if rel.endswith('.mmo'):
            raw, _ = c.convert_mmo(raw, source)
            transform = 'mmo200'
        elif rel.endswith('.pon'):
            raw, _ = c.convert_pon(raw, source)
            transform = 'pon106'
        elif rel == stage['source_path']:
            raw = c.patch_sstg_identity(raw, stage['identity'], (tuple(stage['source_identity']),))
            transform = 'sstg-standard'
        raw, changed_refs = rewrite_names(raw, target, renames)
        if changed_refs: transform += '+references'
        before = io.file_hash(io.safe(client, target))
        candidates = cn_index.names.get(Path(target).name.lower(), [])
        for other in candidates:
            if io.file_hash(io.safe(client, other)) != io.digest(raw):
                raise ValueError('unrenamed CN name conflict: ' + target)
            if other != target: preserved[other] = io.digest(raw)
        if before not in (None, io.digest(raw)):
            raise ValueError('CN target conflict: ' + target)
        if target != rel:
            original = io.file_hash(io.safe(client, rel))
            if original is not None: preserved[rel] = original
        parse_resource(raw, target, source, kr=False)
        data[target] = raw
        records.append(dict(path=target, source_path=rel, source_sha256=node['sha256'],
                            source_size=node['size'], output_sha256=io.digest(raw), output_size=len(raw),
                            transform=transform))
    for rel, raw in localized_resources(localization).items():
        if io.file_hash(io.safe(client, rel)) not in (None, io.digest(raw)):
            raise ValueError('standalone localization conflict: ' + rel)
        data[rel] = raw
        records.append(dict(path=rel, source_path='manifest/monk_localization.json',
                            source_scope='repository', source_sha256=io.digest(LOCALIZATION.read_bytes()),
                            source_size=LOCALIZATION.stat().st_size,
                            output_sha256=io.digest(raw), output_size=len(raw), transform='localized-cn-placeholder'))
    if len({rel.lower() for rel in data}) != len(data):
        raise ValueError('case-colliding output paths')
    for edge in edges:
        edge['output_source'] = targets[edge['source']]
        edge['output_target'] = targets[edge['target']]
    output_stage = c.sstg(data[stage['path']])
    expected_slots = [[rename_value(slot[0], renames), slot[1], rename_value(slot[2], renames)] for slot in model['slots']]
    expected_extra = [[rename_value(name, renames) for name in slot] for slot in model['extra']]
    if output_stage['slots'] != expected_slots or output_stage['extra'] != expected_extra:
        raise ValueError('nine-slot selection/preload changed')
    if check_pins and sorted(records, key=lambda r: r['path']) != recipe['files']:
        raise ValueError('resource closure differs from pinned recipe')
    preserved_rows = [dict(path=p, sha256=h, size=io.safe(client, p).stat().st_size)
                      for p, h in sorted(preserved.items())]
    if check_pins and preserved_rows != recipe['preserve_cn']:
        raise ValueError('CN preservation coverage differs from pinned recipe')
    summary = stage_summary(index, model)
    summary['identity'] = stage['identity']
    summary['counts'] = dict(resources=len(nodes), outputs=len(records), edges=len(edges),
                             extensions=dict(Counter(Path(rel).suffix.lower() for rel in nodes)))
    summary['renames'] = recipe['renames']
    summary['runtime_accepted'] = False
    summary['entry_binding'] = 'placeholder-unbound'
    summary['closure_scope'] = 'parsed resource references and fixed map collision tile; client loading is a separate acceptance item'
    return data, sorted(records, key=lambda r: r['path']), preserved_rows, dict(summary=summary, edges=edges)


def validate_manifest(manifest):
    if manifest.get('schema') != SCHEMA or manifest.get('runtime_accepted') is not False:
        raise ValueError('unsupported monk manifest')
    identity = dict(manifest)
    identifier = identity.pop('id', None)
    if io.digest(io.encoded(identity)) != identifier:
        raise ValueError('manifest identity mismatch')
    if manifest.get('recipe_sha256') != io.digest(RECIPE.read_bytes()):
        raise ValueError('unrecognized monk recipe/localization')
    recipe = io.load(RECIPE)
    if manifest.get('localization_sha256') != io.digest(LOCALIZATION.read_bytes()):
        if manifest.get('localization_sha256') not in LOCALIZATION_METADATA_REVISIONS:
            raise ValueError('unrecognized monk recipe/localization')
        pins = {row['path']: row for row in recipe['files']}
        for name, data in localized_resources(io.load(LOCALIZATION)).items():
            pin = pins.get(name)
            if pin is None or (io.digest(data), len(data)) != (pin['output_sha256'], pin['output_size']):
                raise ValueError('localized resource bytes differ from pinned recipe')
    if manifest['preserve_cn'] != recipe['preserve_cn']:
        raise ValueError('CN preservation recipe coverage mismatch')
    pinned = {row['path']: row for row in recipe['files']}
    paths = set()
    if len(manifest['files']) != len(pinned):
        raise ValueError('recipe coverage mismatch')
    for row in manifest['files']:
        name = row['path']
        io.safe(ROOT, name)
        if name.lower() in paths or name == MARKER:
            raise ValueError('duplicate/reserved resource path')
        paths.add(name.lower())
        pin = pinned.get(name)
        if pin is None or (row['sha256'], row['size'], row['transform']) != (pin['output_sha256'], pin['output_size'], pin['transform']):
            raise ValueError('resource differs from pinned recipe: ' + name)
        if row['before_sha256'] not in (None, row['sha256']):
            raise ValueError('non-additive monk resource')
    for row in manifest['preserve_cn']:
        io.safe(ROOT, row['path'])
        if row['path'].lower() in paths: raise ValueError('preserved/resource overlap')
        paths.add(row['path'].lower())


def build(source, client, output):
    source, client, output = map(io.clean_root, (source, client, output))
    nested_build = output.is_relative_to(ROOT / 'build') and client != ROOT
    if (source == client or output.is_relative_to(source) or source.is_relative_to(output)
            or client.is_relative_to(output) or (output.is_relative_to(client) and not nested_build)):
        raise ValueError('bundle/source/client roots overlap')
    if output.exists(): raise ValueError('output already exists; use a fresh bundle directory')
    recipe, localization = io.load(RECIPE), io.load(LOCALIZATION)
    data, _, preserved, report = plan(source, client, recipe, localization)
    manifest = dict(schema=SCHEMA, recipe_sha256=io.digest(RECIPE.read_bytes()),
                    localization_sha256=io.digest(LOCALIZATION.read_bytes()), runtime_accepted=False,
                    entry_binding='placeholder-unbound', files=[], preserve_cn=preserved,
                    dependency_report=report)
    for pin in recipe['files']:
        name = pin['path']
        manifest['files'].append(dict(path=name, before_sha256=io.file_hash(io.safe(client, name)),
                                     sha256=pin['output_sha256'], size=pin['output_size'], transform=pin['transform']))
    manifest['id'] = io.digest(io.encoded(manifest))
    validate_manifest(manifest)
    output.mkdir(parents=True)
    for rel, raw in data.items(): io.atomic(io.safe(output / 'payload', rel), raw)
    io.atomic(io.safe(output, 'manifest.json'), io.encoded(manifest))
    io.atomic(io.safe(output, 'dependency-report.json'), io.encoded(report))
    return dict(bundle=str(output), payload=str(output / 'payload'), id=manifest['id'],
                **report['summary']['counts'], runtime_accepted=False, entry_binding='placeholder-unbound')


def verify(client, manifest=None):
    client = io.clean_root(client)
    if manifest is None: manifest = io.load(io.safe(client, MARKER))
    validate_manifest(manifest)
    for row in manifest['files']:
        checked(io.safe(client, row['path']), row['sha256'], row['size'])
    for row in manifest['preserve_cn']:
        checked(io.safe(client, row['path']), row['sha256'], row['size'])
    return dict(id=manifest['id'], verified=len(manifest['files']), preserved_cn=len(manifest['preserve_cn']),
                runtime_accepted=False, entry_binding='placeholder-unbound')


def _rollback(client, receipt):
    path = io.safe(client, receipt)
    if not receipt.startswith('.openNanaimo-resource-backups/monk-') or not receipt.endswith('/receipt.json'):
        raise ValueError('not a monk transaction receipt')
    journal = io.load(path)
    if journal.get('overlay_schema') != SCHEMA or journal.get('client') != str(client):
        raise ValueError('rollback client/schema mismatch')
    validate_manifest(journal['manifest'])
    allowed = {row['path']: row for row in journal['manifest']['files']}
    marker = io.encoded(journal['manifest'])
    allowed[MARKER] = dict(sha256=io.digest(marker), before_sha256=None)
    seen = set()
    prefix = receipt.rsplit('/', 1)[0] + '/original/'
    for row in journal['files']:
        pin = allowed.get(row['path'])
        if pin is None or row['path'] in seen or (row['sha256'], row['before_sha256']) != (pin['sha256'], pin['before_sha256']) or row['backup'] != prefix + row['path']:
            raise ValueError('rollback resource contract mismatch')
        seen.add(row['path'])
    expected = {name for name, row in allowed.items() if row['before_sha256'] != row['sha256']}
    if seen != expected: raise ValueError('rollback coverage mismatch')
    return io._rollback(client, receipt)


def rollback(client, receipt):
    client = io.clean_root(client)
    with io.client_lock(client):
        return _rollback(client, receipt)


def apply(bundle, client):
    bundle, client = map(io.clean_root, (bundle, client))
    nested_build = bundle.is_relative_to(ROOT / 'build') and client != ROOT
    if client.is_relative_to(bundle) or (bundle.is_relative_to(client) and not nested_build):
        raise ValueError('bundle/client roots overlap')
    manifest = io.load(io.safe(bundle, 'manifest.json'))
    validate_manifest(manifest)
    with io.client_lock(client):
        backups = io.safe(client, '.openNanaimo-resource-backups')
        if backups.exists():
            for old in backups.glob('*/receipt.json'):
                if io.load(io.safe(client, old.relative_to(client).as_posix())).get('status') == 'applying':
                    raise ValueError('unfinished deployment; rollback first')
        marker = io.safe(client, MARKER)
        if marker.exists():
            installed = io.load(marker)
            if installed != manifest: raise ValueError('different monk overlay; rollback first')
            return dict(status='already-installed', **verify(client, manifest))
        work = []
        for row in manifest['files']:
            payload = checked(io.safe(bundle / 'payload', row['path']), row['sha256'], row['size'])
            if io.file_hash(io.safe(client, row['path'])) != row['before_sha256']:
                raise ValueError('install conflict: ' + row['path'])
            if row['before_sha256'] != row['sha256']: work.append((row, payload))
        for row in manifest['preserve_cn']:
            checked(io.safe(client, row['path']), row['sha256'], row['size'])
        marker_data = io.encoded(manifest)
        work.append((dict(path=MARKER, before_sha256=None, sha256=io.digest(marker_data)), marker_data))
        prefix = '.openNanaimo-resource-backups/monk-' + manifest['id'][:16] + '-' + uuid.uuid4().hex
        receipt = prefix + '/receipt.json'
        journal = dict(schema=io.SCHEMA, overlay_schema=SCHEMA, client=str(client),
                       id=manifest['id'], manifest=manifest, status='applying', files=[])
        for row, _ in work:
            saved = dict(row, backup=prefix + '/original/' + row['path'])
            if row['before_sha256'] is not None:
                original = checked(io.safe(client, row['path']), row['before_sha256'])
                io.atomic(io.safe(client, saved['backup']), original)
            journal['files'].append(saved)
        io.atomic(io.safe(client, receipt), io.encoded(journal))
        try:
            for row, payload in work:
                if io.file_hash(io.safe(client, row['path'])) != row['before_sha256']:
                    raise ValueError('baseline changed during deployment: ' + row['path'])
                io.atomic(io.safe(client, row['path']), payload)
            result = verify(client, manifest)
            journal['status'] = 'installed'
            io.atomic(io.safe(client, receipt), io.encoded(journal))
        except Exception:
            _rollback(client, receipt)
            raise
    return dict(status='installed', receipt=receipt, changed=len(work) - 1, **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('build')
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('apply')
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--client', type=Path, required=True)
    p = commands.add_parser('verify')
    p.add_argument('--client', type=Path, required=True)
    p = commands.add_parser('rollback')
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--receipt', required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        print(json.dumps(globals()[command](**args), ensure_ascii=False, indent=2))
    except (OSError, ValueError, AssertionError, KeyError) as exc:
        parser.exit(1, 'MONK_RESOURCE_REFUSED: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
