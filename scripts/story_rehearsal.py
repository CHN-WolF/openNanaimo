"""Validate chapter catalog topology in an isolated runtime copy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_qt_patch as shared  # noqa: E402

SCHEMA = 'openNanaimo.story-rehearsal.v1'
DATA = Path('资源') / '数据'
TABLES = ('QT._D30', 'QS._D31')
EXPECTED_KINDS = ((39, 40, 39), (39, 40, 39, 1))


def judge(probe: dict, chapters: int) -> dict:
    """Check one catalog probe against the expected reviewed topology."""
    expectations = {'story_chapters': True, 'scrolls': 204, 'mainline': 13,
                    'quests': 217 + chapters}
    failures = [f"{key}={probe.get(key)!r} expected {value!r}"
                for key, value in expectations.items() if probe.get(key) != value]
    seen = [row for row in probe.get('chapters') or [] if row]
    if len(seen) != chapters:
        failures.append(f"resolved {len(seen)} chapter rows, expected {chapters}")
    for row in seen:
        kinds = tuple(objective['objective_type'] for objective in row['objectives'])
        index = row['quest_id'] - 73_000_000
        expected = EXPECTED_KINDS[1] if index % 4 == 3 else EXPECTED_KINDS[0]
        if kinds != expected:
            failures.append(f"chapter {row['quest_id']} kinds {kinds} expected {expected}")
    return dict(schema=SCHEMA, chapters=chapters, passed=not failures, failures=failures,
                observed={key: probe.get(key) for key in expectations},
                chapter_rows=seen, activation_allowed=False, runtime_acceptance=False)


def prepare(build: Path, bundle: Path, work: Path) -> Path:
    build, bundle, work = Path(build).resolve(), Path(bundle).resolve(), Path(work).resolve()
    shared.require(build.is_dir(), 'Build directory is missing: ' + str(build))
    shared.require((build / 'Nanaimo.Adapter.exe').is_file(), 'Build has no Nanaimo.Adapter.exe')
    shared.require(not work.exists(), 'Work directory already exists; preserve prior results')
    shutil.copytree(build, work)
    for name in TABLES:
        source = bundle / name
        shared.require(source.is_file(), 'Bundle is missing ' + name)
        (work / DATA).mkdir(parents=True, exist_ok=True)
        (work / DATA / name).write_bytes(source.read_bytes())
    return work


def probe(work: Path, story: bool) -> tuple[int, dict | None]:
    command = [str(work / 'Nanaimo.Adapter.exe'), '--quest-catalog-probe']
    if not story:
        command.append('--no-story-chapters')
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=300)
    if result.returncode != 0:
        return result.returncode, None
    start = result.stdout.find('{')
    if start < 0:
        return result.returncode, None
    return result.returncode, json.loads(result.stdout[start:])


def run(build: Path, bundle: Path, work: Path, chapters: int) -> dict:
    work = prepare(build, bundle, work)
    code, payload = probe(work, story=True)
    shared.require(code == 0 and payload is not None,
                   'The catalog probe rejected the candidate table (exit %d)' % code)
    verdict = judge(payload, chapters)
    refused_code, _ = probe(work, story=False)
    verdict['strict_gate_refused'] = refused_code != 0
    if refused_code == 0:
        verdict['passed'] = False
        verdict['failures'].append('the strict catalog gate accepted a patched table')
    verdict['work'] = str(work)
    return verdict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True, help='Publish directory to copy')
    parser.add_argument('--bundle', type=Path, required=True, help='Candidate table bundle')
    parser.add_argument('--work', type=Path, required=True, help='Fresh copy directory')
    parser.add_argument('--chapters', type=int, default=1, help='Chapters the bundle carries')
    args = parser.parse_args(argv)
    result = run(args.build, args.bundle, args.work, args.chapters)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
