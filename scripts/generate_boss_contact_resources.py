"""Build complete Boss contact identities independently of kill eligibility."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct
import generate_lumineos_combat as tables
import lumineos_codec as codec
from normalize_combat_score_resources import Resources, digest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path("release/components/stage_damage/boss_contact_registry.json")


def derive(client_root, root=ROOT):
    resources = Resources(client_root)
    text = (root / tables.BOSS).read_text("utf8")
    profiles = tables.numeric_rows(text, "boss_component_boss_profiles")
    modes = tables.numeric_rows(text, "boss_component_boss_modes")
    components = tables.numeric_rows(text, "boss_component_boss_components")
    hp = (root / tables.DATA).read_text("utf8")
    percentages = {(p[1], p[0], p[2], p[3], p[6]): p[7]
                   for p in tables.numeric_rows(hp, "hp_sync_profiles")}
    scopes, definitions = [], {}
    for profile in profiles:
        scope = tuple(profile[:5])
        entries = resources.stage(scope)
        hd, ep, dg, st, slot = scope
        stage = codec.sstg(resources.read(f"hd{hd}_ep{ep:02}_dg{dg:02}_st{st:02}.sstg"))
        smmo = codec.xor(resources.read(stage["slots"][slot][0]), 40)
        count = struct.unpack_from("<I", smmo)[0]
        if len(smmo) != 4 + count * 16 + 260:
            raise ValueError("Invalid Boss placement range")
        scheduled = {struct.unpack_from("<I", smmo, 12 + i*16)[0] for i in range(count)}
        def matches(name):
            candidates = resources.boss(name)
            if len(candidates) != profile[5]:
                return False
            for index, names in enumerate(candidates):
                mode = modes[profile[8] + index]
                expected = components[mode[0]:mode[0]+mode[2]]
                actual = []
                for child, resource in enumerate(names):
                    _, rows = resources.mmo(resource)
                    for ordinal, row in enumerate(rows):
                        raw_hp = struct.unpack_from("<i", row, 8)[0]
                        basis = struct.unpack_from("<i", row, 20)[0]
                        actual.append((max(0,raw_hp)*percentages[scope]//100, basis, child, ordinal, row[4], 0))
                if actual != expected:
                    return False
            return True
        bosses = [(uid, entries[uid][1]) for uid in sorted(scheduled) if entries[uid][0] == 3 and matches(entries[uid][1])]
        if not bosses:
            raise ValueError("Boss profile identity must be unique: " + str((scope, bosses)))
        attacks = {tuple(struct.unpack_from("<i", row, 12)[0]
                         for names in resources.boss(name) for child_name in names
                         for row in resources.mmo(child_name)[1]) for _, name in bosses}
        if len(attacks) != 1:
            raise ValueError("Ambiguous Boss contact attack: " + str(scope))
        uid, boss_name = bosses[0]
        children = resources.boss(boss_name)
        bindings = []
        for mode_index, names in enumerate(children):
            mode = modes[profile[8] + mode_index]
            expected = {(c[2], c[3]): c for c in components[mode[0]:mode[0]+mode[2]]}
            actual = set()
            for child, name in enumerate(names):
                raw, rows = resources.mmo(name)
                key = Path(name.replace("\\", "/")).name
                values = []
                for ordinal, row in enumerate(rows):
                    raw_hp, attack, _, basis = struct.unpack_from("<4i", row, 8)
                    if not 0 <= attack <= 65535:
                        raise ValueError("Contact attack outside unsigned16: " + key)
                    identity = (child, ordinal)
                    c = expected.get(identity)
                    scaled = max(0, raw_hp) * percentages[scope] // 100
                    if c is None or (scaled, basis, row[4]) != (c[0], c[1], c[4]):
                        raise ValueError("Boss component identity differs: " + str((scope, mode_index, child, ordinal, c, scaled, basis, row[4])))
                    actual.add(identity)
                    values.append([raw_hp, row[4], attack])
                definition = dict(resource=key, sha256=digest(raw), rows=values)
                if key in definitions and definitions[key] != definition:
                    raise ValueError("Conflicting Boss contact resource: " + key)
                definitions[key] = definition
                bindings.append([mode_index, child, key])
            if actual != set(expected):
                raise ValueError("Incomplete Boss component coverage: " + str(scope))
        scopes.append(dict(key=list(scope), boss_uid=uid, parts=bindings))
    return dict(schema=1, resources=[definitions[k] for k in sorted(definitions)],
                scopes=sorted(scopes, key=lambda s:s["key"]))


def rows(registry):
    if registry["schema"] != 1:
        raise ValueError("Unsupported Boss contact registry")
    resources = {r["resource"]: r for r in registry["resources"]}
    if len(resources) != len(registry["resources"]):
        raise ValueError("Duplicate Boss contact resource")
    result = {}
    for scope in registry["scopes"]:
        for mode, child, name in scope["parts"]:
            for ordinal, (hp, kind, attack) in enumerate(resources[name]["rows"]):
                key = (*scope["key"], mode, child, ordinal)
                if key in result or not 0 <= attack <= 65535:
                    raise ValueError("Invalid Boss contact identity")
                result[key] = attack
    return [(*key, value) for key, value in sorted(result.items())]


def render(registry):
    lines = ['{', '  "schema": 1,', '  "resources": [']
    for i, value in enumerate(registry["resources"]):
        lines.append('    ' + json.dumps(value, separators=(',', ':')) + (',' if i+1<len(registry["resources"]) else ''))
    lines += ['  ],', '  "scopes": [']
    for i, value in enumerate(registry["scopes"]):
        lines.append('    ' + json.dumps(value, separators=(',', ':')) + (',' if i+1<len(registry["scopes"]) else ''))
    return '\n'.join(lines + ['  ]', '}', ''])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    registry = derive(args.client_root)
    if args.check:
        if registry != json.loads((ROOT/REGISTRY).read_text("utf8")):
            raise ValueError("Boss contact registry differs")
    else:
        (ROOT/REGISTRY).write_text(render(registry), encoding="ascii", newline="\n")
    print("BOSS_CONTACT_RESOURCES_PASS scopes=" + str(len(registry["scopes"])) + " rows=" + str(len(rows(registry))))


if __name__ == "__main__":
    main()
