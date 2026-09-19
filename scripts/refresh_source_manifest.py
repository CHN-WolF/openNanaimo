"""Regenerate the reachable quoted-include closure, never a directory glob."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = ('adapter/nanaimo_adapter.c', 'adapter/nanaimo_adapter_testports.c')
INCLUDE = re.compile(r'^\s*#\s*include\s*"([^"\r\n]+)"', re.M)


def collect(root=ROOT):
    root = root.resolve()
    pending = [root / name for name in ENTRIES]
    seen = set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise ValueError('invalid source dependency: ' + str(path))
        seen.add(path)
        for rel in INCLUDE.findall(path.read_text('utf-8-sig')):
            candidates = [path.parent / rel, root / rel,
                          root / 'adapter' / rel, root / 'release' / rel]
            found = next((p.resolve() for p in candidates if p.is_file()), None)
            if found is None:
                raise ValueError('missing include ' + rel + ' from ' + path.relative_to(root).as_posix())
            pending.append(found)
    return sorted(seen, key=lambda p: p.relative_to(root).as_posix())


def main():
    files = [{'path': p.relative_to(ROOT).as_posix(), 'size': p.stat().st_size,
              'sha256': hashlib.sha256(p.read_bytes()).hexdigest().upper()} for p in collect()]
    previous_path = ROOT / 'manifest/source_closure.json'
    previous = json.loads(previous_path.read_text('utf-8-sig')) if previous_path.exists() else {}
    outputs = {}
    for name in ('nanaimo_adapter.exe', 'nanaimo_adapter_testports.exe'):
        rel = 'adapter/' + name
        path = ROOT / rel
        if path.is_file():
            outputs[rel] = {'size': path.stat().st_size,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest().upper()}
        elif rel in previous.get('build_outputs', {}):
            # A source-only package must retain the reviewed build contract,
            # even when the game and built executables are not supplied.
            outputs[rel] = previous['build_outputs'][rel]
        else:
            raise ValueError('missing reviewed build output contract: ' + rel)
    m = {'channel': 'release', 'count': len(files), 'entrypoints': list(ENTRIES),
         'build_outputs': outputs, 'files': files}
    (ROOT / 'manifest/source_closure.json').write_text(json.dumps(m, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('SOURCE_MANIFEST_REFRESHED', len(files))


if __name__ == '__main__':
    main()
