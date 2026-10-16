"""Prepare exact story portraits in a separate bundle; never mutate an installed client."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import lumineos_codec as codec
import port_lumineos_resources as io
from prepare_story_catalog import require, encoded

ROOT=Path(__file__).resolve().parents[1]
RECIPE=ROOT/'manifest/story_portrait_resources.json'


def validate_story_scope(recipe, package):
    require(package['schema']=='openNanaimo.chapter-story.v1', 'Unknown chapter schema')
    require(package['activation_allowed'] is False and package['runtime_acceptance'] is False,
            'Unreviewed chapter activation')
    require(recipe['source_catalog_sha256']==package['source_catalog_sha256'], 'Stale portrait source')
    needed={(s['npc_uid'],int(s['source_attributes']['expression']))
            for q in package['chapters'] for d in q['dialogue'] for s in d['speeches']}
    require({(e['npc_uid'],e['expression']) for e in recipe['effects']}==needed,
            'Incomplete chapter portrait coverage')


def derive(source,client,recipe):
    source,client=map(io.clean_root,(source,client))
    require(recipe['schema']=='openNanaimo.story-portraits.v1','Unknown portrait schema')
    require(recipe['activation_allowed'] is False and recipe['runtime_acceptance'] is False,'Unreviewed portrait activation')
    require(set(recipe['npc_scope']).isdisjoint(range(62,66)),'Monk portraits are not owned here')
    require(len(set(recipe['npc_scope']))==len(recipe['npc_scope']), 'Duplicate NPC identity')
    require({e['npc_uid'] for e in recipe['effects']}==set(recipe['npc_scope']), 'Missing NPC effect')
    rows={r['path']:r for r in recipe['files']}
    require(len(rows)==len(recipe['files']),'Duplicate portrait path')
    files={};dependencies=set();effects=set()
    for e in recipe['effects']:
        npc,expression=e['npc_uid'],e['expression']
        require(npc in recipe['npc_scope'] and expression==0,'Unsupported portrait identity')
        expected=f'effs/interface/NPC_{npc}_{expression}.eff'
        require(e['path']==expected and expected not in effects,'Wrong effect binding')
        effects.add(expected)
    for rel,row in rows.items():
        p=Path(rel)
        require(p.as_posix()==rel and p.parent.as_posix()=='effs/interface' and p.suffix in ('.eff','.im3'),
                'Unsupported portrait path')
        require(any(p.name in (f'NPC_{n}_0.eff',f'NPC_{n}.im3',f'NPC_{n}_b.im3') for n in recipe['npc_scope']),
                'Portrait outside owned scope')
        raw=io.safe(source,rel).read_bytes()
        require(len(raw)==row['size'] and io.digest(raw)==row['sha256'],'Portrait source differs: '+rel)
        if p.suffix=='.eff':
            model=codec.eff2(raw)
            require(model['duration']==60 and all(r[:2]==(5,6) for r in model['rows']),'Unsupported EFF layout')
            for name in model['refs']:
                require(Path(name).name==name and '\\' not in name,'Unsafe image reference')
                dependencies.add('effs/interface/'+name)
        else:
            header=struct.unpack_from('<9I',raw)
            require(header[:2]==(0,2) and header[2]+8==len(raw) and list(header)==row['image_header'],
                    'Unsupported IM3 layout')
        files[rel]=raw
    require(set(files)==effects|dependencies,'Unclosed portrait dependencies')
    dispositions=[]
    for rel,raw in files.items():
        target=io.safe(client,rel)
        if target.exists():
            require(target.is_file() and target.read_bytes()==raw,'Existing client resource differs; refuse overwrite: '+rel)
            status='reuse-identical'
        else:status='additive-candidate'
        dispositions.append(dict(path=rel,size=len(raw),sha256=io.digest(raw),disposition=status))
    manifest=dict(schema=recipe['schema']+'.bundle',recipe_sha256=io.digest(encoded(recipe)),
                  status='prepared-not-installed',runtime_acceptance=False,activation_allowed=False,
                  files=dispositions)
    return files,manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','verify'])
    p.add_argument('--source',required=True,type=Path);p.add_argument('--client',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    out=io.clean_root(a.output)
    require(not out.exists() or a.command=='verify','Output exists; preserve previous evidence')
    for source in (io.clean_root(a.source),io.clean_root(a.client)):
        require(not out.is_relative_to(source) and not source.is_relative_to(out),'Output overlaps source/client')
    recipe=json.loads(RECIPE.read_text('utf-8'))
    validate_story_scope(recipe,json.loads((ROOT/'release/components/story_chapters/chapters.json').read_text('utf-8')))
    files,manifest=derive(a.source,a.client,recipe)
    files={'payload/'+k:v for k,v in files.items()};files['manifest.json']=encoded(manifest)
    if a.command=='build':
        out.mkdir(parents=True)
        for rel,raw in files.items():
            path=io.safe(out,rel);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:stream.write(raw)
    else:
        require({p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}==set(files),'Bundle coverage differs')
        for rel,raw in files.items():require(io.safe(out,rel).read_bytes()==raw,'Bundle differs: '+rel)
    print(json.dumps(dict(status=a.command,files=len(files)-1,reused=sum(r['disposition']=='reuse-identical' for r in manifest['files']),runtime_acceptance=False,activation_allowed=False)))

if __name__=='__main__':main()
