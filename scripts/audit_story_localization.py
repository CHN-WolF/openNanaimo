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
    for group, key in [('texts', 'qs_id'), ('titles', 'quest_id'), ('objective_names', 'objective_id')]:
        for row in localization[group]:
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
    return issues


def verify_authorities(terminology, resources):
    identities = {}
    for term in terminology['terms']:
        rel = term['authority']
        path = ROOT / rel if rel.startswith(('manifest/', 'adapter_runtime/')) else resources / rel
        raw = path.read_bytes()
        identities[rel] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if rel == 'manifest/monk_localization.json':
            text = '\n'.join(json.loads(raw)[term['source_id']])
        elif rel == 'adapter_runtime/资源/数据/ddakg._D4':
            from generate_inventory_card_catalog import fields
            decoded=fields(path)
            require(decoded[:2]==['PICTURECARD','20080221'], 'Invalid CN card authority')
            matches=[decoded[i:i+17] for i in range(3,3+630*17,17) if decoded[i]==str(term['source_id'])]
            require(len(matches)==1, 'CN card authority identity differs')
            text=matches[0][3]
        elif rel == 'cn-GS._D20.decoded.txt':
            fields = raw.decode('utf-8').split('#')
            require(fields[0]=='NANA_TEXT' and fields[-1]=='' and len(fields[2:-1])%2==0,
                    'Invalid GS authority structure')
            rows = list(zip(fields[2:-1:2], fields[3:-1:2]))
            values = dict(rows)
            require(len(values)==len(rows), 'Duplicate GS authority ID')
            text = values[str(term['source_id'])]
        else:
            text = parse_qs(raw.decode('utf-8'))[term['source_id']]
        require(term['translation_zh'] in text, 'CN authority differs: ' + term['translation_zh'])
    return identities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True, help='Directory containing decoded localization resources')
    args = parser.parse_args()
    terminology = json.loads(TERMS.read_text('utf-8'))
    local = json.loads((ROOT / 'manifest/story_localization.json').read_text('utf-8'))
    identities = verify_authorities(terminology, args.resources)
    issues = audit_translations(local, terminology)
    print(json.dumps(dict(issues=issues, authorities=identities, unresolved=terminology['unresolved'],
                          runtime_acceptance=False, activation_allowed=False), ensure_ascii=True, indent=2))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
