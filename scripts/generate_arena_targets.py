"""Derive arena target identities from authored SSTG/SMMO/MMO resources."""
import argparse
import json
import struct
from pathlib import Path
from generate_lumineos_combat import Resources
from lumineos_codec import sstg, mmo_model

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'release/components/target_resources/arena_target_catalog.json'

def derive(client):
    resources = Resources(client)
    profiles = []
    names = []
    definitions = {}
    for stage in range(6):
        model = sstg(resources.read(f'flying/arena00_st{stage:02}.sstg'))
        monsters = {uid: (kind, name) for uid, kind, name in model['monsters']}
        for slot in range(3):
            rows = []
            smmo, percent, _ = model['slots'][slot]
            def append(name):
                if name not in names:
                    names.append(name)
                if name not in definitions:
                    eff, definitions[name], _ = mmo_model(resources.read('flying/mmo/' + name), client, False)
                    resources.read('effs/game/shootinggamebasic/' + eff.decode('ascii'))
                for ordinal, (mem, _) in enumerate(definitions[name]):
                    hp = struct.unpack_from('<i', mem, 8)[0]
                    attack = struct.unpack_from('<i', mem, 12)[0]
                    defense = struct.unpack_from('<i', mem, 20)[0]
                    if min(hp, attack, defense) < 0:
                        raise ValueError(f'Unsupported arena target fields: {name}/{ordinal}')
                    rows.append([mem[4], hp * percent // 100, attack, defense,
                                 names.index(name), ordinal])
            for _, _, uid, _ in resources.placements(smmo):
                kind, name = monsters[uid]
                if kind == 0:
                    append(name)
            ordinary = len(rows)
            for name in model['extra'][slot]:
                append(name)
            profiles.append(dict(stage=stage, slot=slot, smmo=smmo,
                                 ordinary=ordinary, rows=rows))
    return dict(schema=1, row_fields=['type', 'hp', 'contact', 'defense', 'resource', 'ordinal'],
                resources=names, profiles=profiles, inputs=resources.inputs)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client-root', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    model = derive(args.client_root) if args.client_root else json.loads(OUTPUT.read_text('utf-8'))
    text = json.dumps(model, separators=(',', ':')) + '\n'
    if args.check:
        if OUTPUT.read_text('utf-8') != text:
            raise ValueError('Arena catalog differs from reviewed resources')
    else:
        OUTPUT.write_text(text, encoding='utf-8', newline='\n')
    print('ARENA_TARGET_CATALOG_PASS profiles=', len(model['profiles']),
          'targets=', sum(len(p['rows']) for p in model['profiles']))

if __name__ == '__main__':
    main()
