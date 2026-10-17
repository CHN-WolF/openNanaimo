"""Audit story draft terminology against explicit CN resource authorities."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from prepare_story_catalog import parse_qs, require

ROOT = Path(__file__).resolve().parents[1]
TERMS = ROOT / 'manifest/story_terms.json'


def audit_translations(localization, terminology):
    require(terminology['schema'] == 'openNanaimo.story-terms.v1', 'Unknown terminology schema')
    issues = []
    groups = [(group, key, localization[group]) for group, key in
              [('texts', 'qs_id'), ('titles', 'quest_id'), ('objective_names', 'objective_id')]]
    groups.append(('speaker_names', 'npc_uid',
                   [dict(npc_uid=int(uid), translation_zh=name)
                    for uid, name in localization.get('speaker_names', {}).items()]))
    for group, key, rows in groups:
        for row in rows:
            text = row['translation_zh']
            if re.search(r'[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]', text):
                issues.append(dict(group=group, id=row[key], issue='untranslated-korean'))
            for term in terminology['terms']:
                for alias in term['rejected_aliases']:
                    if alias in text:
                        issues.append(dict(group=group, id=row[key], issue='cn-term-alias',
                                           alias=alias, expected=term['translation_zh']))
            if re.search(r'黄金粉(?!末|卡片)', text):
                issues.append(dict(group=group, id=row[key], issue='cn-term-alias', expected='黄金粉末'))
            for alias in terminology.get('unsupported_names', {}):
                if alias in text:
                    issues.append(dict(group=group, id=row[key], issue='unsupported-client-name', alias=alias))
    for npc, expected in terminology.get('speaker_names', {}).items():
        if localization.get('speaker_names', {}).get(npc) != expected:
            issues.append(dict(group='speaker_names', id=int(npc), issue='speaker-identity', expected=expected))
    texts = {row['qs_id']: row['translation_zh'] for row in localization['texts']}
    for row in terminology.get('reward_bindings', []):
        if texts.get(row['qs_id']) != row['translation_zh']:
            issues.append(dict(group='texts', id=row['qs_id'], issue='reward-identity-or-quantity'))
    return issues


def verify_authorities(terminology, resources):
    identities = {}
    for term in terminology['terms']:
        rel = term['authority']
        path = ROOT / rel if rel.startswith(('manifest/', 'adapter_runtime/', 'gui_launcher/')) else resources / rel
        if not path.exists() and rel.startswith('cn-') and rel.endswith('.decoded.txt'):
            path = resources / rel[3:-len('.decoded.txt')]
        raw = path.read_bytes()
        identities[rel] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if rel.startswith('gui_launcher/'):
            rows = [r for r in json.loads(raw) if r['id'] == term['source_id']]
            require(len(rows) == 1, 'GUI authority identity differs')
            text = rows[0][term.get('field', 'name')]
        elif rel == 'manifest/monk_localization.json':
            text = '\n'.join(json.loads(raw)[term['source_id']])
        elif rel == 'adapter_runtime/资源/数据/ddakg._D4':
            from generate_inventory_card_catalog import fields
            decoded=fields(path)
            require(decoded[:2]==['PICTURECARD','20080221'], 'Invalid CN card authority')
            matches=[decoded[i:i+17] for i in range(3,3+630*17,17) if decoded[i]==str(term['source_id'])]
            require(len(matches)==1, 'CN card authority identity differs')
            text=matches[0][3]
        elif rel == 'cn-GS._D20.decoded.txt':
            fields = resource_text(path, raw).split('#')
            require(fields[0]=='NANA_TEXT' and fields[-1]=='' and len(fields[2:-1])%2==0,
                    'Invalid GS authority structure')
            rows = list(zip(fields[2:-1:2], fields[3:-1:2]))
            values = dict(rows)
            require(len(values)==len(rows), 'Duplicate GS authority ID')
            text = values[str(term['source_id'])]
        else:
            text = parse_qs(resource_text(path, raw))[term['source_id']]
        require(term.get('source_translation_zh', term['translation_zh']) in text,
                'CN authority differs: ' + term['translation_zh'])
    return identities


def resource_text(path, raw):
    if path.name.endswith('.decoded.txt'):
        return raw.decode('utf-8')
    from prepare_hero_dragon import decrypt, CN_KEY
    return decrypt(raw, CN_KEY).decode('gbk')


def audit_package(package, localization, terminology):
    issues = []
    texts = {r['qs_id']: r for r in localization['texts']}
    if package['texts'] != [texts[uid] for uid in sorted(texts)]:
        issues.append('package-texts-stale')
    names = {r['objective_id']: r['translation_zh'] for r in localization['objective_names']}
    rewards = {r['qs_id']: r for r in terminology['reward_bindings']}
    for chapter in package['chapters']:
        binding = rewards[chapter['reward_qs_id']]
        if chapter['source_rewards'] != binding['source_rewards']:
            issues.append('reward-triples-differ:%d' % chapter['episode'])
        for objective in chapter['objectives']:
            if objective['name'] != names[objective['id']]:
                issues.append('objective-stale:%d' % objective['id'])
        for dialogue in chapter['dialogue']:
            for speech in dialogue['speeches']:
                if speech['text'] != texts[speech['qs_id']]['translation_zh']:
                    issues.append('speech-stale:%d' % speech['qs_id'])
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True, help='Directory containing decoded localization resources')
    args = parser.parse_args()
    terminology = json.loads(TERMS.read_text('utf-8'))
    local = json.loads((ROOT / 'manifest/story_localization.json').read_text('utf-8'))
    identities = verify_authorities(terminology, args.resources)
    issues = audit_translations(local, terminology)
    package = json.loads((ROOT / 'release/components/story_chapters/chapters.json').read_text('utf-8'))
    issues.extend(audit_package(package, local, terminology))
    print(json.dumps(dict(issues=issues, authorities=identities, unresolved=terminology['unresolved'],
                          runtime_acceptance=False, activation_allowed=False), ensure_ascii=True, indent=2))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
