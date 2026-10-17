"""Compile sixteen chapters into an isolated catalog and localization package.

Reward definitions and scene selectors retain their catalog identities.
Activation and client acceptance are explicit package fields.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from prepare_story_catalog import encoded, require, validate_translation

SCHEMA = 'openNanaimo.chapter-story.v1'
FIRST, LAST = 73000000, 73000015


def load_catalog(directory):
    manifest = json.loads((directory / 'manifest.json').read_text('utf-8'))
    require(manifest['schema'] == 'openNanaimo.story-catalog.v1.build', 'Unknown source manifest')
    records = {row['path']: row for row in manifest['files']}
    require('catalog.json' in records, 'Missing catalog identity')
    raw = (directory / 'catalog.json').read_bytes()
    require(len(raw) == records['catalog.json']['size'] and
            hashlib.sha256(raw).hexdigest() == records['catalog.json']['sha256'], 'Catalog identity differs')
    catalog = json.loads(raw)
    require(catalog['schema'] == 'openNanaimo.story-catalog.v1', 'Unknown catalog schema')
    require(catalog['inputs'] == manifest['inputs'], 'Source identities differ')
    return catalog, hashlib.sha256(raw).hexdigest()


def unique(rows, key):
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), 'Duplicate ' + key)
    return result


def mapped_rewards(chapter, mapping=None):
    rewards = chapter['rewards']
    if mapping is None:
        return rewards
    require(mapping['quest_id'] == chapter['id'] and mapping['source_rewards'] == rewards,
            'Stale KR reward mapping')
    mapped = mapping['cn_rewards']
    require(len(mapped) == len(rewards) and all(
        len(r) == 3 and all(type(v) is int and 0 <= v <= 4294967295 for v in r)
        and r[0] == source[0] and r[2] == source[2]
        and (r[0] not in (1, 7) or r[1] == 0)
        for r, source in zip(mapped, rewards)), 'Invalid CN reward mapping')
    return mapped


def compile_package(catalog, digest, localization):
    require(localization['schema'] == 'openNanaimo.chapter-story-localization.v1', 'Unknown localization schema')
    require(localization['source_catalog_sha256'] == digest, 'Stale localization source')
    require(localization['scope'] == dict(first_episode=1, last_episode=16), 'Wrong port scope')
    require(localization.get('activation_allowed') is False and
            localization.get('runtime_acceptance') is False, 'Unreviewed localization activation')
    require(localization['monk_owner'] == 'manifest/monk_localization.json', 'Wrong monk owner')
    for collision in catalog['cn_collisions']:
        require(collision['namespace'] == 'qs' and 6000 <= collision['id'] <= 6011
                and collision.get('resolution') == 'reuse-existing-monk-localization',
                'Unresolved CN namespace collision')
    chapters = unique(catalog['chapters'], 'id')
    objectives = unique(catalog['objectives'], 'id')
    scripts = unique(catalog['scripts'], 'uid')
    require(set(scripts)==set(range(10000,10036)), 'Script coverage differs')
    source_text = unique(catalog['texts'], 'qs_id')
    text = unique(localization['texts'], 'qs_id')
    titles = unique(localization['titles'], 'quest_id')
    names = unique(localization['objective_names'], 'objective_id')
    reward_mappings = unique(localization.get('reward_mappings', []), 'quest_id')
    require(set(reward_mappings) <= set(chapters), 'Unknown chapter reward mapping')
    require(set(chapters) == set(range(FIRST, LAST+1)), 'Chapter coverage differs')
    require(set(objectives) == set(range(75100000, 75100052)), 'Source objective coverage differs')
    require(set(titles) == set(range(FIRST, LAST+1)), 'Title coverage differs')
    needed_text, needed_names = set(), set()
    result = []
    for uid in range(FIRST, LAST+1):
        q = chapters[uid]
        episode = uid - 73000000 + 1
        require(q['type'] == 2, 'Not a type2 chapter')
        require(int(q['next_fields'][0]) == (uid+1 if uid < LAST else 0), 'Broken successor')
        expected = [39, 40, 39] + ([1] if episode % 4 == 0 else [])
        rows = [objectives[oid]['raw_fields'] for oid in q['objective_ids']]
        require([int(o[2]) for o in rows] == expected, 'Wrong objective order')
        require(int(rows[1][4]) == episode, 'Wrong source episode selector')
        require(int(rows[0][4]) == episode*2-1 and int(rows[2][4]) == episode*2-1,
                'Wrong source dialogue scene')
        title = titles[uid]
        require(title['source_ko'] == q['title'], 'Stale title')
        validate_translation(q['title'], title['translation_zh'], 39)
        require(isinstance(title['approved'], bool), 'Invalid title approval')
        dialogue = []
        for index in (0, 2):
            source_script = int(rows[index][19])
            require(source_script == 10000 + (episode-1)*2 + (index//2), 'Wrong script binding')
            actions = scripts[source_script]['actions']
            require(actions[-1] == dict(type='COMPLETE', step_clear='1'), 'Wrong terminal action')
            require(all(a['type'] == 'SPEECH' for a in actions[:-1]) and len(actions)>1,
                    'Unsupported chapter action')
            speeches = []
            for action in actions[:-1]:
                qs = int(action['string_uid']); needed_text.add(qs)
                require(not 6000 <= qs <= 6011, 'Monk dialogue must not be copied')
                require(qs in text, 'Missing dialogue translation')
                speeches.append(dict(qs_id=qs, npc_uid=int(action['npc_uid']),
                                     source_attributes=action, text=text[qs]['translation_zh']))
            dialogue.append(dict(objective_index=index, source_script_uid=source_script,
                                 source_scene_selector=int(rows[index][4]), speeches=speeches,
                                 source_actions=actions))
        converted = []
        for index, row in enumerate(rows):
            oid = int(row[0]); needed_names.add(oid)
            require(oid in names and names[oid]['source_ko'] == row[1], 'Missing or stale objective name')
            validate_translation(row[1], names[oid]['translation_zh'], 39)
            require(isinstance(names[oid]['approved'], bool), 'Invalid objective approval')
            converted.append(dict(id=oid, kind=int(row[2]), name=names[oid]['translation_zh'], raw_fields=row))
        need_monk = episode % 4 == 0
        dependency = None
        if need_monk:
            monk_index = episode//4-1
            require(int(rows[3][4]) == 62+monk_index and int(rows[3][19]) == 10032+monk_index,
                    'Wrong existing monk reference')
            actions=scripts[10032+monk_index]['actions']
            reused_text=[int(a['string_uid']) for a in actions if a['type']=='SPEECH']
            require(reused_text==[6000+3*monk_index,6002+3*monk_index,6001+3*monk_index],
                    'Wrong existing monk text order')
            dependency = dict(source_objective_id=int(rows[3][0]), npc_uid=62+monk_index,
                              source_script_uid=10032+monk_index, source_actions=actions,
                              reused_text_ids=reused_text,
                              existing_script_uid=24000+monk_index, existing_episode=24+monk_index,
                              clear_mask=1<<monk_index, owner='CharacterMonkChallenges.ClearMask',
                              localization_owner='manifest/monk_localization.json')
        needed_text.update((int(q['header'][9]), q['reward_text_id']))
        rewards = mapped_rewards(q, reward_mappings.get(uid))
        result.append(dict(quest_id=uid, episode=episode, village_index=(episode-1)//4,
                           next_quest_id=uid+1 if uid<LAST else 0, title=title['translation_zh'],
                           description_qs_id=int(q['header'][9]), reward_qs_id=q['reward_text_id'],
                           objectives=converted, dialogue=dialogue, existing_monk=dependency,
                           source_rewards=rewards, rewards_resolved=False))
    require(set(text) == needed_text, 'Text coverage differs or includes out-of-scope/monk text')
    require(set(names) == needed_names, 'Objective coverage differs')
    for uid, row in text.items():
        require(row['source_ko'] == source_text[uid]['source_ko'], 'Stale source text')
        validate_translation(row['source_ko'], row['translation_zh'])
        require(isinstance(row['approved'], bool), 'Invalid approval flag')
    return dict(schema=SCHEMA, source_catalog_sha256=digest,
                localization_sha256=hashlib.sha256(encoded(localization)).hexdigest(),
                runtime_acceptance=False, activation_allowed=False,
                status='host-candidate-not-client-installed',
                counts=dict(chapters=len(result),objectives=sum(len(q['objectives']) for q in result),
                    scripts=len(scripts),story_speeches=sum(len(d['speeches']) for q in result for d in q['dialogue']),
                    reused_monk_speeches=sum(len(q['existing_monk']['reused_text_ids']) for q in result if q['existing_monk'])),
                first_quest_id=FIRST, last_quest_id=LAST,
                policies=dict(entry='explicit-new-story-start-at-episode-1-no-backfill',
                    clear='super-boss-bit-3-after-entry-any-difficulty',
                    monk='reuse-existing-clearmask-only-after-own-chapter-dialogues',
                    reward='fail-closed-until-reviewed-CN-mapping',
                    localization='draft-human-review-required'),
                chapters=result, texts=[text[uid] for uid in sorted(text)],
                unresolved_gates=['cn-story-executor-and-confirmation', 'cn-scene-and-portrait-mapping',
                    'reviewed-gbk-localization', 'cn-reward-mapping-and-atomic-transaction',
                    'type40-settlement-condition', 'first-grant-and-legacy-save-policy',
                    'transactional-client-install-and-rollback', 'original-client-episode-1-acceptance'])


def derive(catalog_dir, localization):
    catalog, digest = load_catalog(catalog_dir)
    local = json.loads(localization.read_text('utf-8'))
    from audit_story_localization import audit_translations, TERMS
    require(not audit_translations(local, json.loads(TERMS.read_text('utf-8'))), 'Unresolved CN terminology aliases')
    package = compile_package(catalog, digest, local)
    raw = encoded(package)
    manifest = encoded(dict(schema=SCHEMA+'.build', runtime_acceptance=False, activation_allowed=False,
        files=[dict(path='chapters.json', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())]))
    return {'chapters.json':raw, 'manifest.json':manifest}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','verify'])
    p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--localization',type=Path,default=Path(__file__).resolve().parents[1]/'manifest/story_localization.json')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); payload=derive(a.catalog,a.localization)
    output=a.output.resolve()
    require(not output.is_relative_to(a.catalog.resolve()), 'Output overlaps source catalog')
    require(not a.localization.resolve().is_relative_to(output), 'Output contains localization input')
    if a.command=='build':
        require(not output.exists(),'Output exists; preserve prior results')
        output.mkdir(parents=True)
        for name,raw in payload.items():
            with (output/name).open('xb') as stream:stream.write(raw)
    else:
        require({p.name for p in output.iterdir()}==set(payload),'Output coverage differs')
        for name,raw in payload.items():require((output/name).read_bytes()==raw,'Output differs: '+name)
    package=json.loads(payload['chapters.json'])
    print(json.dumps(dict(status=a.command,chapters=len(package['chapters']),texts=len(package['texts']),monk_texts_copied=0,
                         activation_allowed=False,runtime_acceptance=False)))

if __name__=='__main__':main()
