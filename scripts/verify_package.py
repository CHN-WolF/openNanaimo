"""Verify project sources and, by default, the complete local runtime contract.

This is NOT a license audit or a claim that the entire working tree is public.
Use export_patch.py for a deny-by-default distribution tree.
"""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
import re
from pathlib import Path

TEXT_EXT = {'.ps1', '.py', '.md', '.json', '.ini', '.yaml', '.yml', '.bat', '.c', '.h', '.inc', '.txt', '.csv', '.tsv'}
PUBLIC_DIRS = ('release', 'adapter', 'gui_launcher', 'knowledge', 'docs', 'scripts', 'manifest')
ABSOLUTE_HOST_PATH = re.compile(r'(?i)(?<![a-z0-9])[a-z]:[\\/]')
HOME_PATH = re.compile(r'(?i)/(?:home|Users)/[^/\s<>]+')
IPV4 = re.compile(r'(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])')
LEGACY_LABEL = re.compile(r'GUI[ _-]*\d+', re.IGNORECASE)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest().upper()


def safe_file(root, rel):
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts or ':' in rel or '\\' in rel:
        raise ValueError(f'unsafe manifest path: {rel}')
    q = root / p
    if not q.resolve().is_relative_to(root):
        raise ValueError(f'manifest escapes root: {rel}')
    if any(part.is_symlink() for part in (q, *q.parents)):
        raise ValueError(f'symlink is not a release artifact: {rel}')
    if not q.is_file():
        raise ValueError(f'missing file: {rel}')
    return q


def verify_records(root, records):
    for rel, record in records:
        p = safe_file(root, rel)
        if p.stat().st_size != record['size'] or sha(p) != record['sha256'].upper():
            raise ValueError(f'content mismatch: {rel}')


def scan_public_text(root):
    hits = []
    paths = [root / 'README.md', root / 'start_nanaimo_launcher.bat']
    for directory in PUBLIC_DIRS:
        if (root / directory).is_dir():
            paths.extend((root / directory).rglob('*'))
    for p in paths:
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
            continue
        if '__pycache__' in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        # The inventory describes private local assets, not distributable text.
        if rel == 'manifest/package_files.tsv':
            continue
        text = p.read_text('utf-8-sig', errors='strict')
        if LEGACY_LABEL.search(text):
            hits.append((rel, 'internal numbered GUI label'))
        if ABSOLUTE_HOST_PATH.search(text) or HOME_PATH.search(text):
            hits.append((rel, 'absolute host path'))
        for candidate in IPV4.findall(text):
            try:
                ip = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            # Loopback, wildcard and broadcast are protocol configuration, not identity.
            if str(ip) not in {'0.0.0.0', '255.255.255.255'} and not ip.is_loopback:
                private_network = (str(ip).startswith(('10.', '192.168.')) or
                                   ip in ipaddress.ip_network((2886729728, 12)))
                if private_network:
                    hits.append((rel, 'private network address'))
        if rel.startswith('knowledge/'):
            if any(word in text for word in ('\u56fd\u670d', 'Fly Island', '\u817e\u8baf', '\u98de\u884c\u5c9b')):
                hits.append((rel, 'obsolete regional project description'))
        if (rel.startswith(('release/', 'gui_launcher/')) or
                rel.startswith('adapter/') and p.suffix == '.c'):
            if LEGACY_LABEL.search(p.name):
                hits.append((rel, 'versioned active filename'))
    if hits:
        raise ValueError('public-text review failed: ' + repr(hits[:40]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--source-only', action='store_true', help='Do not require locally supplied client/resources/binaries')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    closure = json.loads((root / 'manifest/source_closure.json').read_text('utf-8-sig'))
    files = closure['files']
    if closure['count'] != len(files) or len({f['path'] for f in files}) != len(files):
        raise ValueError('source closure count/duplicate mismatch')
    verify_records(root, ((f['path'], f) for f in files))
    from refresh_source_manifest import collect
    reachable = {p.relative_to(root).as_posix() for p in collect(root)}
    if reachable != {f['path'] for f in files}:
        raise ValueError('source manifest does not match reachable include closure')
    critical_count = 0
    if not args.source_only:
        manifest = json.loads((root / 'manifest/open_release_manifest.json').read_text('utf-8-sig'))
        verify_records(root, manifest['critical_files'].items())
        critical_count = len(manifest['critical_files'])
        for rel, record in closure.get('build_outputs', {}).items():
            if manifest['critical_files'].get(rel) != record:
                raise ValueError('source/runtime build contract disagreement: ' + rel)
        if manifest.get('runtime_acceptance') is not False:
            raise ValueError('this consolidation has no fresh original-client acceptance')
        from verify_client_baseline import verify as verify_client
        verify_client((root / 'game.exe').read_bytes())
    scan_public_text(root)
    print('PACKAGE_STRUCTURE_PASS', 'source_files=' + str(len(files)),
          'critical_files=' + str(critical_count), 'runtime_acceptance=false',
          'scope=project-text-and-declared-files-not-whole-workspace')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
