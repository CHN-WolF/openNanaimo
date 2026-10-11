"""Compare all L7 target identities with a verified installed resource overlay.

This is a resource/schema audit, not original-client gameplay acceptance.
"""
import argparse
import json
from pathlib import Path
import generate_lumineos_combat as tables
import lumineos_codec as codec
import port_lumineos_resources as port


def audit(client, root=tables.ROOT):
    identity = port.verify(client)
    resources = tables.Resources(client)
    text = (root / tables.DATA).read_text("utf8")
    profiles = tables.numeric_rows(text, "hp_sync_profiles")
    targets = tables.numeric_rows(text, "hp_sync_target_defs")
    names = tables.re.findall(r'\{"([^"]+)","([A-F0-9]{64})",(\d+)u\}',
                              tables.array(text, "hp_sync_resources")[1])
    scopes = []
    for stage in (0, 1):
        model = codec.sstg(resources.read(f"flying/hd0_ep22_dg00_st{stage:02}.sstg"))
        monsters = {uid: (kind, name) for uid, kind, name in model["monsters"]}
        for slot, (smmo, percent, _) in enumerate(model["slots"]):
            profile = next(p for p in profiles if p[:6] == (22, 0, stage, stage, slot // 3, slot % 3))
            expected = []
            for placement, (_, _, uid, _) in enumerate(resources.placements(smmo)):
                kind, name = monsters[uid]
                if kind != 0:
                    continue
                rows, _ = resources.mmo(name)
                digest = tables.sha(resources.read(name))
                start = len(expected)
                for mem, _ in rows:
                    expected.append((Path(name.replace(chr(92), "/")).name.lower(), digest,
                                     tables.i32(mem, 8), tables.i32(mem, 8) * percent // 100,
                                     tables.i32(mem, 20), tables.i32(mem, 408), placement,
                                     len(expected), start, mem[4], mem[24]))
            old = targets[profile[9]:profile[9] + profile[10]]
            mismatches = []
            for selector in range(max(len(old), len(expected))):
                before = None
                if selector < len(old):
                    t = old[selector]
                    before = (names[t[4]][0].lower(), names[t[4]][1], *t[:4], *t[5:10])
                after = expected[selector] if selector < len(expected) else None
                if before != after:
                    mismatches.append(dict(selector=selector, catalog=before, installed=after))
            scopes.append(dict(stage=stage, slot=slot, smmo=smmo, catalog_count=len(old),
                               installed_count=len(expected), mismatch_count=len(mismatches),
                               examples=mismatches[:5]))
    return dict(resource_identity=identity, runtime_accepted=False, scopes=scopes,
                matches=all(s["mismatch_count"] == 0 for s in scopes), inputs=resources.inputs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=tables.ROOT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit(args.client, args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf8")
    print(json.dumps({k: v for k, v in result.items() if k != "inputs"}, ensure_ascii=False))
    raise SystemExit(0 if result["matches"] else 1)
