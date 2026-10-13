#!/usr/bin/env python3
"""Verify complete docs-to-knowledge coverage, content and Markdown references."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
import gzip
import hashlib
import json
from pathlib import Path
import posixpath
import re
import unittest
from urllib.parse import unquote, urlsplit
import zlib

from verify_knowledge import LINK, Report, anchors, digest, safe_path, verify_links

MANIFEST = 'manifest/document_fusion.json'
MARKER = re.compile(
    r'<!-- FUSION BEGIN ([A-Za-z0-9][A-Za-z0-9_.:-]*) -->\n'
    r'([\s\S]*?)<!-- FUSION END \1 -->'
)


@dataclass
class FusionReport:
    sources: int = 0
    fragments: int = 0
    chars: int = 0
    links: int = 0
    edits: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def content_identity(text: str, mapping: dict[str, str], document_path: str | None = None,
                     routes: dict[str, str] | list[dict[str, str]] | None = None) -> str:
    """Canonicalize declared relocations; retain destinations and all other text.

    Local destinations retain their repository-relative identity, including
    queries and anchors. Markdown headings follow only declared routes. Code
    fences and inline examples are compared literally. File
    names quoted as repository paths may change only via the declared mapping.
    Everything else, including whitespace, examples and numbers, is compared.
    """
    route_map = {item['from']: item['to'] for item in routes} if isinstance(routes, list) else (routes or {})

    def local_link(match: re.Match) -> str:
        raw = match[1]
        url = urlsplit(raw.strip('<>'))
        if url.scheme or url.netloc:
            return match[0]
        if document_path is None:
            return match[0]
        destination = unquote(re.sub(r'\\([\\() ])', r'\1', url.path))
        base = '' if destination.startswith('/') else posixpath.dirname(document_path)
        canonical = posixpath.normpath(posixpath.join(base, destination.lstrip('/'))) if destination else document_path
        fragment = unquote(url.fragment)
        if posixpath.splitext(canonical)[1].lower() == '.md':
            canonical = mapping.get(canonical, canonical)
            route_key = canonical + ('#' + fragment if fragment else '')
            routed = urlsplit(route_map.get(route_key, route_key))
            canonical, fragment = routed.path, routed.fragment
        if url.query:
            canonical += '?' + url.query
        if fragment:
            canonical += '#' + fragment
        return match[0].replace(raw, '<local-reference:' + canonical + '>', 1)

    def prose(piece: str) -> str:
        # Match code spans first so link-looking code cannot be rewritten.
        pieces, position = [], 0
        for span in re.finditer(r'(`+)[\s\S]*?\1', piece):
            pieces.append(LINK.sub(local_link, piece[position:span.start()]))
            pieces.append(span[0])
            position = span.end()
        pieces.append(LINK.sub(local_link, piece[position:]))
        return ''.join(pieces)

    result, pending, fence = [], [], None
    for line in text.splitlines(keepends=True):
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence:
            result.append(line)
            if match and match[1][0] == fence[0] and len(match[1]) >= fence[1] and not match[2].strip():
                fence = None
        elif match:
            result.append(prose(''.join(pending)))
            pending.clear()
            result.append(line)
            fence = (match[1][0], len(match[1]))
        else:
            pending.append(line)
    result.append(prose(''.join(pending)))
    text = ''.join(result)
    # Two stages avoid accidental substitutions inside newly created tokens.
    paths = {}
    for index, (source, target) in enumerate(sorted(mapping.items())):
        token = f'\x00document-{index}\x00'
        paths[source] = token
        paths[target] = token
    for path in sorted(paths, key=len, reverse=True):
        text = text.replace(path, paths[path])
    return digest(text)


def verify_fragment_splits(data: dict, baseline: dict) -> None:
    """Check subdivision provenance without replacing historical parent hashes."""
    splits = data.get('fragment_splits', [])
    if not isinstance(splits, list):
        raise ValueError('fragment_splits must be a list')
    live = {item['id']: item for item in data['fragments']}
    parents, claimed = set(), set()
    for record in splits:
        parent, children = record['parent'], record['children']
        identity = parent['id']
        if identity in parents or identity in live:
            raise ValueError('split parent must be unique and retired: ' + identity)
        parents.add(identity)
        original = baseline[parent['source']]
        start, end = parent['start'], parent['end']
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(original)
                or digest(original[start:end]) != parent['source_sha256']):
            raise ValueError('split parent source identity mismatch: ' + identity)
        if not re.fullmatch(r'[0-9a-f]{64}', parent['content_sha256']):
            raise ValueError('invalid historical parent content SHA-256')
        if not isinstance(children, list) or len(children) < 2:
            raise ValueError('a split requires at least two children')
        position = start
        for child_id in children:
            if child_id in claimed:
                raise ValueError('split child is claimed more than once: ' + child_id)
            claimed.add(child_id)
            child = live[child_id]
            if (child.get('parent_id') != identity or child['source'] != parent['source']
                    or child['start'] != position or not position < child['end'] <= end):
                raise ValueError('split child has a gap, overlap or wrong parent: ' + child_id)
            position = child['end']
        if position != end:
            raise ValueError('split children do not cover parent: ' + identity)
    if {item['id'] for item in data['fragments'] if 'parent_id' in item} != claimed:
        raise ValueError('unregistered split child')


def verify(root: Path, *, strict: bool = False) -> FusionReport:
    root = root.resolve()
    report = FusionReport()
    try:
        data = json.loads(safe_path(root, MANIFEST).read_text('utf-8'))
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('fusion schema_version must be 1')
        archive = safe_path(root, data['baseline_archive']).read_bytes()
        if hashlib.sha256(archive).hexdigest() != data['baseline_archive_sha256']:
            raise ValueError('fusion baseline archive SHA-256 mismatch')
        baseline = json.loads(gzip.decompress(archive).decode('utf-8'))
        sources = data['source_files']
        mapping = data['path_mapping']
        fragments = data['fragments']
        if not isinstance(sources, dict) or not isinstance(mapping, dict) or not isinstance(fragments, list):
            raise ValueError('invalid source_files, path_mapping or fragments types')
        if not isinstance(baseline, dict) or set(baseline) != set(sources) or set(mapping) != set(sources):
            raise ValueError('fusion sources, baseline and path mapping differ')
        verify_fragment_splits(data, baseline)
        routes = data.get('heading_routes', [])
        if not isinstance(routes, list):
            raise ValueError('heading_routes must be a list')
        route_map, route_anchors = {}, {}
        for route in routes:
            if not isinstance(route, dict) or not all(isinstance(route.get(key), str) for key in ('from', 'to')):
                raise ValueError('invalid heading route')
            old, new = urlsplit(route['from']), urlsplit(route['to'])
            if any(url.scheme or url.netloc or url.query or not url.fragment for url in (old, new)):
                raise ValueError('heading routes must be local Markdown headings')
            safe_path(root, old.path, knowledge=True)
            new_path = safe_path(root, new.path, knowledge=True)
            if new_path not in route_anchors:
                route_anchors[new_path] = anchors(new_path.read_text('utf-8'))
            if new.fragment not in route_anchors[new_path]:
                raise ValueError(f'heading route has missing target anchor: {route["to"]}')
            if route['from'] in route_map:
                raise ValueError(f'duplicate heading route: {route["from"]}')
            route_map[route['from']] = route['to']
        report.sources = len(sources)
        report.fragments = len(fragments)
        if data['source_count'] != report.sources or data['fragment_count'] != report.fragments:
            raise ValueError('fusion source/fragment count mismatch')
        for source, record in sources.items():
            if not isinstance(record, dict):
                raise ValueError(f'{source}: invalid source record')
            path = safe_path(root, source)
            if not source.startswith('docs/') or not source.endswith('.md'):
                raise ValueError(f'invalid original document: {source}')
            if path.exists():
                report.errors.append(f'{source}: old document still exists')
            original = baseline[source]
            if not isinstance(original, str):
                raise ValueError(f'{source}: source text must be a string')
            if type(record['chars']) is not int or len(original) != record['chars'] or digest(original) != record['sha256']:
                report.errors.append(f'{source}: source text identity mismatch')
            safe_path(root, mapping[source], knowledge=True)
            report.chars += len(original)
        actual = defaultdict(list)
        for path in sorted((root / 'knowledge').rglob('*.md')):
            if path.is_relative_to(root / 'knowledge/evidence'):
                continue
            text = path.read_text('utf-8')
            for match in MARKER.finditer(text):
                actual[match[1]].append((path.relative_to(root).as_posix(), match[2]))
            if text.count('<!-- FUSION BEGIN ') != len(list(MARKER.finditer(text))):
                report.errors.append(f'{path.relative_to(root)}: unmatched fusion marker')
            if text.count('<!-- FUSION END ') != len(list(MARKER.finditer(text))):
                report.errors.append(f'{path.relative_to(root)}: unmatched fusion end marker')
        intervals = defaultdict(list)
        declared = set()
        for fragment in fragments:
            if not isinstance(fragment, dict):
                report.errors.append('invalid fragment record')
                continue
            identity = fragment.get('id', '<unknown>')
            try:
                if not isinstance(identity, str) or not re.fullmatch(r'df-\d{2}-\d{3}(?:-[A-Za-z0-9]+)?', identity):
                    raise ValueError('invalid fragment identity')
                if identity in declared:
                    raise ValueError('duplicate declared fragment')
                declared.add(identity)
                source = fragment['source']
                original = baseline[source]
                start, end = fragment['start'], fragment['end']
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(original):
                    raise ValueError('invalid character interval')
                piece = original[start:end]
                if digest(piece) != fragment['source_sha256']:
                    raise ValueError('source fragment SHA-256 mismatch')
                intervals[source].append((start, end, identity))
                target = fragment['target']
                safe_path(root, target, knowledge=True)
                occurrences = actual.get(identity, [])
                if len(occurrences) != 1:
                    raise ValueError(f'expected one live fragment, found {len(occurrences)}')
                current_target, body = occurrences[0]
                if current_target != target:
                    raise ValueError(f'fragment is at {current_target}, expected {target}')
                if digest(body) != fragment['content_sha256']:
                    report.edits.append(identity)
                    if strict:
                        raise ValueError('recorded live content SHA-256 changed')
                if content_identity(piece, mapping, source, route_map) != content_identity(body, mapping, target, route_map):
                    if identity not in report.edits:
                        report.edits.append(identity)
                    if strict:
                        raise ValueError('original information changed beyond local path relocation')
            except (KeyError, TypeError, ValueError, OSError) as exc:
                report.errors.append(f'{identity}: {exc}')
        for identity in sorted(set(actual) - declared):
            report.errors.append(f'{identity}: undeclared live fragment')
        for source, record in sources.items():
            position = 0
            for start, end, identity in sorted(intervals[source]):
                if start != position:
                    report.errors.append(f'{source}: character gap/overlap at {position} before {identity}')
                position = max(position, end)
            if position != record['chars']:
                report.errors.append(f'{source}: incomplete coverage {position}/{record["chars"]}')
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, EOFError, zlib.error) as exc:
        report.errors.append(f'fusion verification failed: {exc}')
    links = Report()
    verify_links(root, links)
    report.links = links.links
    report.errors.extend(links.errors)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--strict', action='store_true', help='require full original information and recorded content identity')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern='test_verify_document_fusion.py')
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    report = verify(args.root, strict=args.strict)
    for error in report.errors:
        print('ERROR ' + error)
    if report.edits:
        print(f'EDITED {len(report.edits)} fragment(s): ' + ', '.join(report.edits))
    print(f'{"PASS" if report.ok else "FAIL"} sources={report.sources} fragments={report.fragments} chars={report.chars} links={report.links} edited={len(report.edits)}')
    return 0 if report.ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
