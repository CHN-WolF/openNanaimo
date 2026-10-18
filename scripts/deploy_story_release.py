"""Install the release and complete chapter resources on a stopped CN client.

The executable is derived locally by the shipped managed compatibility tool.
No donor client, compiler, Korean tree, account database or save is copied.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import struct
import tempfile
import uuid
import zipfile

import port_lumineos_resources as io
import package_story_resource_kit as kit
import deploy_adapter_runtime as release
import install_story_portraits as portraits
import prepare_monk_dialogue as dialogue
import prepare_monk_challenges as challenges
import story_qt_patch as qt
import story_qs_patch as qs
import story_window_accept as window
import prepare_client_compatibility as compatibility
import lumineos_scenes as scenes

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'openNanaimo.story-release-install.v1'
PREFIX = '.openNanaimo-resource-backups/story-release-'
DATA = 'adapter_runtime/\u8d44\u6e90/\u6570\u636e/'
FLAGS = ('adapter_data/story_chapters.flag', 'adapter_data/story_chapters_start.flag')
REVIEW = 'adapter_data/chapter_reward_review.json'
COMPAT = ('character-creation', 'furniture', 'native-state', 'dungeon-state',
          'inventory-gift-display', 'land-purchase', 'apartment-exterior',
          'apartment-recommendation', 'dungeon7', 'monk-dialogue')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def run_tool(args):
    result = subprocess.run([str(ROOT / 'adapter_runtime/Nanaimo.Adapter.exe'), *args],
                            capture_output=True, encoding='utf-8', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(result.returncode == 0, 'Managed tool refused: ' + result.stdout + result.stderr)
    return result.stdout


def chapters_enabled(client):
    profile = io.safe(client, 'nanaimo_launcher_profile.ini')
    values = {}
    if profile.exists():
        for line in profile.read_text('utf-8-sig').splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().lower()
    return any(io.safe(client, name).exists() for name in FLAGS) or any(
        values.get(key) in ('1', 'true', 'yes', 'on') for key in window.PROFILE_KEYS)


def checked_table(name, before, after):
    """Permit chapter replacement only when every non-chapter row is preserved."""
    if before == after:
        return
    old_text, new_text = qt.decrypt_qt(before), qt.decrypt_qt(after)
    if name == 'QT._D30':
        old, new = qt.parse_qt(old_text), qt.parse_qt(new_text)
        chapters = [r for r in new['quests'] if 73000000 <= int(r['header'][0]) < 73000016]
        objectives = {int(n) for r in chapters for n in r['objective_ids']}
        for group in ('objectives', 'quests'):
            def ident(row):
                return int(row['header'][0] if group == 'quests' else row[0])
            owned = objectives if group == 'objectives' else {int(r['header'][0]) for r in chapters}
            left = [r for r in old[group] if ident(r) not in owned]
            right = [r for r in new[group] if ident(r) not in owned]
            require(left == right, 'Non-chapter QT rows differ: ' + group)
    else:
        old, new = qs.parse_qs(old_text), qs.parse_qs(new_text)
        owned = {int(r['qs_id']) for r in io.load(ROOT / 'manifest/story_localization.json')['texts']}
        target = dict(new['entries'])
        require(all(k in owned or target.get(k) == v for k, v in old['entries']),
                'Non-chapter QS rows differ')
    require(old['header'][:2] == new['header'][:2], 'Table version differs: ' + name)


def receipts(client, payload):
    recipe = io.load(dialogue.RECIPE)
    marker = dict(recipe, recipe_sha256=io.digest(io.encoded(recipe)), files=[
        dict(r, before_sha256=io.file_hash(io.safe(client, r['path']))) for r in recipe['files']])
    marker['id'] = io.digest(io.encoded(marker))
    candidates = {dialogue.MARKER: marker}
    monk = challenges.configure()
    recipe = io.load(monk.RECIPE)
    marker = dict(schema=monk.SCHEMA, recipe_sha256=io.file_hash(monk.RECIPE),
                  localization_sha256=io.file_hash(monk.LOCALIZATION), runtime_accepted=False,
                  entry_binding='village-dialogue-bound', preserve_cn=recipe['preserve_cn'], files=[
                      dict(path=r['path'], size=r['output_size'], sha256=r['output_sha256'],
                           transform=r['transform'], before_sha256=io.file_hash(io.safe(client, r['path'])))
                      for r in recipe['files']])
    marker['id'] = io.digest(io.encoded(marker))
    monk.validate_manifest(marker)
    candidates[monk.MARKER] = marker
    rows, identity = portraits.recipe_rows()
    candidates[portraits.MARKER] = portraits.preview_marker(rows, identity)
    for name, candidate in candidates.items():
        path = io.safe(client, name)
        if path.exists():
            old = io.load(path)
            if name == dialogue.MARKER:
                dialogue.validate_manifest(old, io.load(dialogue.RECIPE))
            elif name == monk.MARKER:
                monk.validate_manifest(old)
            else:
                require(old == candidate, 'Portrait receipt differs')
            if old.get('recipe_sha256') == candidate.get('recipe_sha256'):
                candidate = old
        payload[name] = io.encoded(candidate)


def resource_baseline(client, payload):
    parent = io.load(dialogue.RECIPE)['parent_files']
    l7 = io.load(ROOT / 'manifest/lumineos_resource_port.json')
    known = {r['path']: {r['baseline_sha256'], r['output_sha256']}
             for r in l7['files'] if r['path'] == dialogue.PACK}
    for name, digest in parent.items():
        known.setdefault(name, set()).add(digest)
    recipe = io.load(ROOT / 'manifest/monk_challenge_resources.json')
    for revision in recipe.get('compatible_localizations', {}).values():
        for row in revision['files']:
            known.setdefault(row['path'], set()).add(row['output_sha256'])
    for name, raw in payload.items():
        before = io.file_hash(io.safe(client, name))
        if name == dialogue.PACK and before != io.digest(raw):
            current = io.safe(client, name).read_bytes()
            merged = scenes.merge(current, raw)
            merged, _ = compatibility.patch_village_pack(merged)
            checked_scene(dialogue.derive_pack(merged), raw)
            continue
        require(before in (None, io.digest(raw)) or before in known.get(name, set()),
                'Unknown existing resource: ' + name)
    for row in recipe['preserve_cn']:
        kit.checked(io.safe(client, row['path']).read_bytes(), row)


def checked_scene(derived, target):
    """Allow only path casing and unused retired fifth-village texture entries."""
    old, new = dict(scenes.records(derived)), dict(scenes.records(target))
    require(old.keys() == new.keys(), 'Village record coverage differs')
    for key, raw in old.items():
        if raw == new[key]:
            continue
        before = dialogue.scene.VillageScene(raw[4:])
        after = dialogue.scene.VillageScene(new[key][4:])
        a, b = dict(before.textures), dict(after.textures)
        require(set(a) <= set(b) and all(a[i].lower() == b[i].lower() for i in a),
                'Village texture conflict: ' + str(key))
        extra = set(b) - set(a)
        require(not extra or key in (50009, 50010, 50012), 'Unexpected village texture addition')
        for uid in extra:
            require(b[uid].split(b'\0', 1)[0].replace(b'\\', b'/').lower()
                    == b'effs/village/village_inout_01.eff'
                    and all(struct.unpack_from('<I', row)[0] != uid for layer in after.layers for row in layer),
                    'Retired village texture is not unused')
        before.textures = after.textures
        require(dialogue.scene_bytes(before) == dialogue.scene_bytes(after),
                'Village changes outside supported scene recipe: ' + str(key))


def parent_payload(client):
    if io.safe(client, window.LUMINEOS).exists():
        window.verify_launcher_resources(client)
        return {}, io.load(io.safe(client, window.LUMINEOS))
    archive = ROOT / 'resource-packs/nanaimo-korean-resource-kit.zip'
    baselines = io.load(ROOT / 'manifest/story_deployment_baselines.json')
    require(baselines['schema'] == 'openNanaimo.story-deployment-baselines.v1'
            and baselines['recipe_sha256'] == io.file_hash(io.RECIPE), 'Upgrade baseline recipe differs')
    upgrades = {r['path']: r for r in baselines['files']}
    require(len(upgrades) == len(baselines['files']), 'Duplicate upgrade baseline')
    payload = {}
    with zipfile.ZipFile(archive) as z:
        require(len(z.namelist()) == len(set(z.namelist())), 'Duplicate parent archive members')
        ledger = json.loads(z.read('l7-l8-bundle/manifest.json'))
        io.validate_manifest(ledger)
        for row in ledger['files']:
            raw = kit.checked(z.read('l7-l8-bundle/payload/' + row['path']), row)
            before = io.file_hash(io.safe(client, row['path']))
            if row['path'] != dialogue.PACK:
                prior = upgrades.get(row['path'], {})
                approved = (prior.get('sha256') == row['sha256'] and prior.get('size') == row['size']
                            and before == prior.get('before_sha256') and before is not None
                            and io.safe(client, row['path']).stat().st_size == prior.get('before_size'))
                require(before in (None, row['before_sha256'], row['sha256']) or approved,
                        'L7/L8 baseline differs: ' + row['path'])
            payload[row['path']] = raw
    for row in ledger['preserve_l7_combat']:
        require(io.file_hash(io.safe(client, row['path'])) == row['sha256'],
                'Preserved L7 resource differs: ' + row['path'])
    return payload, ledger


def reward_review(stage, supplied, enable):
    template = stage / 'reward-template.json'
    run_tool(['--chapter-story-reward-review', str(template)])
    expected = io.load(template)
    require(expected['package_sha256'].lower() == io.file_hash(
        ROOT / 'release/components/story_chapters/chapters.json'), 'Embedded chapter package differs')
    if supplied is None:
        require(not enable, '--enable-chapters requires --reward-review with all sixteen approvals')
        return None
    raw = supplied.read_bytes()
    review = json.loads(raw.decode('utf-8-sig'))
    require(review.get('schema') == expected['schema']
            and review.get('package_sha256', '').lower() == expected['package_sha256'].lower(),
            'Reward review belongs to another chapter package')
    for row in review['reviews']:
        require(type(row.get('quest_id')) is int and type(row.get('approved')) is bool
                and isinstance(row.get('review_id'), str) and len(row['review_id']) <= 128,
                'Reward review field types or identifier length differ')
    actual = {r['quest_id']: r for r in review['reviews']}
    require(len(actual) == len(review['reviews']) == len(expected['reviews']), 'Reward review coverage differs')
    for row in expected['reviews']:
        item = actual.get(row['quest_id'], {})
        require(all(io.encoded(item.get(k)) == io.encoded(row[k]) for k in ('source_rewards', 'duration_days')),
                'Reward triples or durations differ: ' + str(row['quest_id']))
        if enable:
            require(row['catalog_identity_complete'] and item.get('approved') is True
                    and bool(item['review_id'].strip()),
                    'Reward is not reviewed: ' + str(row['quest_id']))
    return raw


def prepare(client, archive, enable=False, review=None, snapshot=None):
    manifest, source = release.verify_root(ROOT)
    names = set(manifest['critical_files']) | {r['path'] for r in source['files']} | {
        'manifest/open_release_manifest.json', 'manifest/source_closure.json'}
    embedded = io.load(ROOT / 'managed-host/Resources/client-compatibility.json')
    watched = names | {r['path'] for r in kit.inventory()['files']} | {
        'game.exe', 'MT._D18', 'QT._D30', 'QS._D31', window.LUMINEOS, dialogue.MARKER,
        '.openNanaimo-monk-challenges.json', portraits.MARKER, REVIEW,
        'nanaimo_launcher_profile.ini', *FLAGS}
    for name in ('monk_challenge_resources.json', 'lumineos_resource_port.json'):
        recipe = io.load(ROOT / 'manifest' / name)
        for group in ('files', 'preserve_cn', 'preserve_l7_combat'):
            watched.update(r['path'] for r in recipe.get(group, []))
    watched.update(r[k] for r in embedded['aliases'] for k in ('source', 'target'))
    initial = {name: io.file_hash(io.safe(client, name)) for name in watched}
    if snapshot is not None:
        snapshot.update(initial)
    story = kit.read(archive)
    resource_baseline(client, story)
    payload, ledger = parent_payload(client)
    payload.update(story)
    receipts(client, payload)
    require(not any(n == 'game.exe' or n.startswith(('adapter_data/', 'adapter-data/',
                'nanaimo_launcher_profile.', 'knowledge/evidence/')) for n in names), 'Private release payload')
    known = set()
    if io.safe(client, 'manifest/open_release_manifest.json').exists():
        old, closure = release.verify_root(client)
        known = set(old['critical_files']) | {r['path'] for r in closure['files']} | {
            'manifest/open_release_manifest.json', 'manifest/source_closure.json'}
    for name in sorted(names):
        raw = io.safe(ROOT, name).read_bytes()
        current = io.file_hash(io.safe(client, name))
        require(name in known or current in (None, io.digest(raw)), 'Unmanaged release conflict: ' + name)
        payload[name] = raw
    for name in ('QT._D30', 'QS._D31'):
        raw = io.safe(ROOT, DATA + name).read_bytes()
        checked_table(name, io.safe(client, name).read_bytes(), raw)
        payload[name] = raw
    with tempfile.TemporaryDirectory(prefix='nanaimo-story-stage-') as temp:
        stage = Path(temp)
        inputs, output = stage / 'client', stage / 'overlay'
        required = {'game.exe', 'MT._D18', dialogue.PACK, dialogue.MARKER,
                    '.openNanaimo-monk-challenges.json'}
        required.update(r['source'] for r in embedded['aliases'])
        required.update(story)
        for row in ledger['files']:
            if row['path'] in payload:
                raw = payload[row['path']]
                row.update(size=len(raw), sha256=io.digest(raw))
        ledger.pop('id')
        ledger['id'] = io.digest(io.encoded(ledger))
        payload[window.LUMINEOS] = io.encoded(ledger)
        required.add(window.LUMINEOS)
        required.update(r['path'] for r in ledger['files'] + ledger['preserve_l7_combat'])
        for name in sorted(required):
            raw = payload[name] if name in payload else io.safe(client, name).read_bytes()
            path = io.safe(inputs, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        run_tool(['--tools', 'compatibility', '--source-root', str(inputs),
                  '--output-root', str(output), *('--' + f for f in COMPAT)])
        report = io.load(output / 'nanaimo_compatibility_report.json')
        require(report['verification']['all_pass'], 'Compatibility generation failed')
        for row in report['overlay_writes']:
            name = row['path']
            require(row['status'] != 'remove_on_apply', 'Unexpected compatibility removal')
            payload[name] = io.safe(output, name).read_bytes()
            if name in story:
                require(payload[name] == story[name], 'Compatibility changes pinned story resource: ' + name)
        current_review = io.safe(client, REVIEW)
        supplied = reward_review(stage, review or (current_review if current_review.exists() else None), enable)
        if supplied is not None:
            payload[REVIEW] = supplied
    if enable:
        for name in FLAGS:
            payload[name] = b'1\n'
        profile = io.safe(client, 'nanaimo_launcher_profile.ini')
        if profile.exists():
            lines = profile.read_text('utf-8-sig').splitlines()
            lines = [line for line in lines if line.split('=', 1)[0].strip() != 'story_chapters_reward']
            payload['nanaimo_launcher_profile.ini'] = ('\n'.join(window.with_profile_keys(lines)) + '\n').encode('utf-8')
    require(set(payload) <= set(initial), 'Unwatched deployment output')
    for name, expected in initial.items():
        require(io.file_hash(io.safe(client, name)) == expected, 'Concurrent preparation edit: ' + name)
    return payload


def validate_receipt(client, receipt):
    require(re.fullmatch(re.escape(PREFIX) + r'[0-9a-f]{32}/receipt.json', receipt), 'Invalid receipt path')
    journal = io.load(io.safe(client, receipt))
    require(journal.get('schema') == SCHEMA and journal.get('client') == str(client)
            and journal.get('receipt') == receipt and journal.get('status') in
            ('applying', 'installed', 'rolled-back'), 'Receipt ownership differs')
    seen = set()
    for row in journal['files']:
        name = row['path']
        io.safe(client, name)
        require(name.lower() not in seen and row['backup'] == receipt.rsplit('/', 1)[0] + '/original/' + name,
                'Receipt paths differ')
        seen.add(name.lower())
    return journal


def restore(client, receipt):
    journal = validate_receipt(client, receipt)
    io.assert_not_running(client)
    for row in journal['files']:
        require(io.file_hash(io.safe(client, row['path'])) in (row['before'], row['after']),
                'Edited deployment file: ' + row['path'])
        if row['before'] is not None:
            require(io.file_hash(io.safe(client, row['backup'])) == row['before'], 'Damaged deployment backup')
    for row in reversed(journal['files']):
        path = io.safe(client, row['path'])
        if row['before'] is None:
            path.unlink(missing_ok=True)
        else:
            io.atomic(path, io.safe(client, row['backup']).read_bytes())
    journal['status'] = 'rolled-back'
    io.atomic(io.safe(client, receipt), io.encoded(journal))
    return dict(status='rolled-back', receipt=receipt)


def verify(client, archive=kit.ARCHIVE):
    release.verify_root(client)
    for name, raw in kit.read(archive).items():
        require(io.file_hash(io.safe(client, name)) == io.digest(raw), 'Installed resource differs: ' + name)
    for name in ('QT._D30', 'QS._D31'):
        require(io.file_hash(io.safe(client, name)) == io.file_hash(io.safe(client, DATA + name)),
                'Client/runtime table differs: ' + name)
    portraits.verify(client)
    dialogue.verify(client)
    challenges.configure().verify(client)
    window.verify_launcher_resources(client)
    with tempfile.TemporaryDirectory(prefix='nanaimo-story-check-') as temp:
        result = json.loads(run_tool(['--tools', 'compatibility', '--source-root', str(client),
            '--output-root', temp, '--dry-run', *('--' + f for f in COMPAT)]))
        require(result['verification']['all_pass']
                and not any(r.get('changed') for r in result['operations']), 'Compatibility is not installed')
        if chapters_enabled(client):
            reward_review(Path(temp), io.safe(client, REVIEW), True)
    return dict(status='verified', resource_files=len(kit.inventory()['files']), runtime_acceptance=False)


def install(client, archive=kit.ARCHIVE, apply=False, enable=False, review=None):
    client = io.clean_root(client)
    require(client != ROOT and not client.is_relative_to(ROOT),
            'Use an installed client root outside the source workspace')
    io.assert_not_running(client)
    with io.client_lock(client):
        enable = enable or chapters_enabled(client)
        for path in client.glob(PREFIX + '*/receipt.json'):
            require(io.load(path)['status'] != 'applying', 'Unfinished deployment; rollback first')
        snapshot = {}
        data = prepare(client, archive, enable, review, snapshot)
        before = {n: snapshot[n] if snapshot else io.file_hash(io.safe(client, n)) for n in data}
        changed = [n for n, raw in data.items() if before[n] != io.digest(raw)]
        if not apply:
            return dict(status='dry-run', files=len(data), changed=len(changed), paths=changed,
                        chapters_enabled=enable, runtime_acceptance=False)
        if not changed:
            return dict(verify(client, archive), status='already-installed')
        receipt = PREFIX + uuid.uuid4().hex + '/receipt.json'
        journal = dict(schema=SCHEMA, client=str(client), receipt=receipt, status='applying', files=[])
        for name in changed:
            backup = receipt.rsplit('/', 1)[0] + '/original/' + name
            if before[name] is not None:
                raw = io.safe(client, name).read_bytes()
                require(io.digest(raw) == before[name], 'Concurrent edit before backup: ' + name)
                io.atomic(io.safe(client, backup), raw)
            journal['files'].append(dict(path=name, before=before[name], after=io.digest(data[name]), backup=backup))
        io.atomic(io.safe(client, receipt), io.encoded(journal))
        try:
            io.assert_not_running(client)
            for name, expected in (snapshot or before).items():
                require(io.file_hash(io.safe(client, name)) == expected, 'Concurrent edit: ' + name)
            for row in journal['files']:
                require(io.file_hash(io.safe(client, row['path'])) == row['before'], 'Concurrent write')
                io.atomic(io.safe(client, row['path']), data[row['path']])
            result = verify(client, archive)
            journal['status'] = 'installed'
            io.atomic(io.safe(client, receipt), io.encoded(journal))
        except Exception:
            restore(client, receipt)
            raise
        return dict(result, status='installed', receipt=receipt, changed=len(changed), chapters_enabled=enable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'apply', 'verify', 'rollback'):
        p = sub.add_parser(name)
        p.add_argument('--client', type=Path, required=True)
        if name == 'rollback':
            p.add_argument('--receipt', required=True)
        else:
            p.add_argument('--archive', type=Path, default=kit.ARCHIVE)
        if name in ('plan', 'apply'):
            p.add_argument('--enable-chapters', action='store_true')
            p.add_argument('--reward-review', type=Path)
    a = parser.parse_args()
    if a.command == 'verify':
        result = verify(io.clean_root(a.client), a.archive)
    elif a.command == 'rollback':
        client = io.clean_root(a.client)
        with io.client_lock(client):
            result = restore(client, a.receipt)
    else:
        result = install(a.client, a.archive, a.command == 'apply', a.enable_chapters, a.reward_review)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
