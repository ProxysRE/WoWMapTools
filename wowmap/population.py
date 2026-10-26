"""Link validated Builder actors to rendered scene bundles without touching game assets."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
from .foundry import uid,number,boolean
from .objects import pair
from .icons import PREFIX, relative_file


def slug(value,label):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',value):raise ValueError(f'{label} must be an ASCII slug')
    return value


def validate_population(population):
    if population.get('format')!='wowmap.population/1':raise ValueError('Expected wowmap.population/1')
    actors=population.get('actors',[]);placements=population.get('placements',[])
    if not isinstance(actors,list) or not isinstance(placements,list) or len(actors)>200 or len(placements)>2000:raise ValueError('Invalid population size')
    keys=set();ids=set()
    media=population.get('media',[])
    if not isinstance(media,list) or len(media)>2000:raise ValueError('Invalid population media list')
    files=set()
    for row in media:
        digest=row.get('sha256','');path=row.get('file','')
        if not re.fullmatch(r'[0-9a-f]{64}',digest) or path not in (PREFIX+digest+'.webp','wowmap/content/tokens/'+digest+'.webp'):raise ValueError('Invalid population media path or hash')
        if path in files:raise ValueError('Duplicate population media path')
        files.add(path)
    for actor in actors:
        key=slug(actor['key'],'Actor key')
        if key in keys:raise ValueError('Duplicate actor key')
        keys.add(key);doc=actor['document']
        if doc.get('type')!='npc' or not doc.get('name'):raise ValueError('Population actors must be named NPC documents')
        if doc.get('_stats',{}).get('systemId')!='dnd5e':raise ValueError('Population targets dnd5e')
        if 'mechanics' in doc or any('mechanics' in i for i in doc.get('items',[])):raise ValueError('Run source NPC through the Builder first')
    for p in placements:
        key=slug(p['id'],'Placement id');slug(p['scene'],'Scene key')
        if key in ids:raise ValueError('Duplicate placement id')
        ids.add(key)
        if p['actor'] not in keys:raise ValueError('Unknown placement actor')
        pair(p['position'],'Token centre')
        for k in ('width','height'):number(p.get(k,1),k,.25,20)
        if p.get('disposition','neutral') not in ('friendly','neutral','hostile'):raise ValueError('Invalid token disposition')
        for k,default in [('actor_link',True),('hidden',False)]:boolean(p.get(k,default),k)
    return keys


def populate(bundle,population):
    validate_population(population)
    result=copy.deepcopy(bundle)
    if result.get('format')!='wowmap.foundry/1' or not result.get('scenes'):raise ValueError('Expected a rendered Foundry scene bundle')
    if result.get('actors') or any(s.get('tokens') for s in result['scenes']):raise ValueError('Bundle already has actors or tokens; use an unpopulated export')
    scenes={s['flags']['wowmap']['key']:s for s in result['scenes']}
    if len(scenes)!=len(result['scenes']):raise ValueError('Scene keys must be unique')
    packages={s['flags']['wowmap']['package'] for s in scenes.values()}
    if len(packages)!=1:raise ValueError('Population needs one package namespace')
    package=packages.pop();actors={}
    for actor in population['actors']:
        doc=copy.deepcopy(actor['document']);doc['_id']=uid(package,'actor',actor['key'])
        doc['folder']=None
        doc.setdefault('flags',{}).setdefault('wowmap',{}).update(package=package,key=actor['key'])
        actors[actor['key']]=doc
    for p in population['placements']:
        if p['scene'] not in scenes:raise ValueError(f"Unknown placement scene: {p['scene']}")
        scene=scenes[p['scene']];ppc=scene['grid']['size'];actor=actors[p['actor']]
        prototype=copy.deepcopy(actor.get('prototypeToken',{}))
        # Native prototype fields remain intact; only placement and identity are assigned here.
        prototype.pop('_id',None);prototype.pop('actorId',None)
        width=number(p.get('width',prototype.get('width',1)),'width',.25,20)
        height=number(p.get('height',prototype.get('height',1)),'height',.25,20)
        cx,cy=p['position'];x=(cx-width/2)*ppc;y=(cy-height/2)*ppc
        if x<0 or y<0 or x+width*ppc>scene['width'] or y+height*ppc>scene['height']:raise ValueError(f"Token {p['id']} lies outside its scene")
        prototype.update(_id=uid(package,'token',p['id']),name=p.get('name',actor['name']),actorId=actor['_id'],
                         actorLink=p.get('actor_link',True),x=x,y=y,width=width,height=height,
                         hidden=p.get('hidden',False),disposition={'friendly':1,'neutral':0,'hostile':-1}[p.get('disposition','neutral')],
                         elevation=number(p.get('elevation',0),'token elevation'))
        if not prototype.setdefault('texture',{}).get('src'):prototype['texture']['src']=actor.get('img','icons/svg/mystery-man.svg')
        prototype.setdefault('flags',{}).setdefault('wowmap',{})['placement']=p['id']
        scene.setdefault('tokens',[]).append(prototype)
    result['actors']=list(actors.values())
    if population.get('media'):
        result['externalMedia']=sorted(set(result.get('externalMedia',[])) | {r['file'] for r in population['media']})
    result['targets']={**result.get('targets',{}),'dnd5e':population.get('targets',{}).get('dnd5e','5.3.3')}
    return result


def write_population(bundle_path,population_path):
    bundle_path=Path(bundle_path);population_path=Path(population_path)
    if bundle_path.name!='bundle.json' or bundle_path.parent.parent.name!='wowmap':raise ValueError('Expected <export>/wowmap/<package>/bundle.json')
    population=json.loads(population_path.read_text(encoding='utf-8-sig'))
    result=populate(json.loads(bundle_path.read_text(encoding='utf-8-sig')),population)
    macro=Path(__file__).with_name('import_foundry.js').read_text(encoding='utf-8').replace('__BUNDLE_URL__',result['mediaRoot']+'/bundle.json')
    # All validation happens before file writes. Keep standalone scene exports consistent.
    for scene in result['scenes']:
        key=slug(scene['flags']['wowmap']['key'],'Scene key')
        dest=bundle_path.parent/key/'scene.json'
        if not dest.is_file():raise ValueError('Expected native per-scene export beside bundle.json')
    media=[]
    for row in population.get('media',[]):
        source=relative_file(population_path.parent,row['file'])
        if source.stat().st_size>4*1024*1024:raise ValueError('Population image exceeds 4 MiB')
        data=source.read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Population media checksum mismatch')
        target=relative_file(bundle_path.parent.parent.parent,row['file'])
        if target.exists() and target.read_bytes()!=data:raise ValueError('Existing population image differs')
        media.append((target,data))
    for target,data in media:
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    for scene in result['scenes']:
        (bundle_path.parent/scene['flags']['wowmap']['key']/'scene.json').write_text(json.dumps(scene,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    bundle_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Export layout is <root>/wowmap/<package>/bundle.json.
    (bundle_path.parent.parent.parent/'import-foundry.js').write_text(macro,encoding='utf-8')
    return dict(actors=len(result['actors']),tokens=sum(len(s.get('tokens',[])) for s in result['scenes']))


def main():
    p=argparse.ArgumentParser(description='Attach Builder NPCs to a rendered Foundry bundle')
    p.add_argument('--bundle',required=True);p.add_argument('--population',required=True);a=p.parse_args()
    try:print(json.dumps(write_population(a.bundle,a.population)))
    except (OSError,ValueError,KeyError) as error:p.exit(1,f'ERROR: {error}\n')


if __name__=='__main__':main()
