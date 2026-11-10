"""Build an offline effect/dependency catalog. Does not alter resources or Foundry."""
import argparse,json,sqlite3,struct,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wowmap.models import RawAssets,model_info,array_at
from wowmap.dbc import DBC

def build(base,resources,out):
 if out.exists():raise ValueError('Output database already exists')
 src=sqlite3.connect(base.resolve().as_uri()+'?mode=ro',uri=True);src.row_factory=sqlite3.Row
 assets={r['path']:dict(r) for r in src.execute('select * from assets')};byname={}
 for p,a in assets.items():
  if a['available']:byname.setdefault(p.rsplit('/',1)[-1],[]).append(p)
 def resolve(raw):
  p=raw.strip().replace('\\','/').lower()
  if not p:return '', 'empty'
  if p in assets:return p,'exact'
  if p.endswith(('.mdx','.mdl')) and p[:-4]+'.m2' in assets:return p[:-4]+'.m2','legacy_model_extension'
  candidates=[]
  for x in [p,p[:-4]+'.blp' if p.endswith('.tga') else p,p+'.blp' if '.' not in p.rsplit('/',1)[-1] else p]:
   for y in [x.lstrip('/'),x.split('/data/',1)[-1]]:
    if y in assets:candidates.append(y)
   candidates+=byname.get(x.rsplit('/',1)[-1],[])
  candidates=sorted(set(candidates))
  return (candidates[0],'candidate') if len(candidates)==1 else ('','ambiguous' if candidates else 'unresolved')
 db=sqlite3.connect(out);db.executescript('''
 create table effects(id integer primary key,name text,raw_path text,path text,resolution text);
 create table models(path text primary key,metadata_json text,basis text);
 create table dependencies(model text,target text,relation text,basis text,primary key(model,target,relation));
 create table assets(path text primary key,available integer,package text,member text,drive_url text,sha256 text);
 create table chains(id integer primary key,raw_texture text,path text,resolution text);
 create table spells(id integer primary key,name text,fold text,visual1 integer,visual2 integer);
 create table links(source_type text,source_id integer,role text,target_type text,target_id integer);
 create table sounds(id integer,name text,directory text);
 create table sound_files(sound_id integer,raw_path text,available integer);
 create table procedures(kit_id integer,slot integer,type integer,params_json text);
 create table areas(id integer,raw_path text,path text,resolution text,enum_id integer);
 create table provenance(name text primary key,metadata_json text);
 create index spell_fold on spells(fold);create index links_source on links(source_type,source_id);
 ''')
 needed=set();models=set();used=[]
 def asset(p):
  if p and p in assets:needed.add(p)
 for r in src.execute("select model,target,relation,basis from dependencies where basis='M2_bytes'"):
  db.execute('insert or ignore into dependencies values(?,?,?,?)',tuple(r));asset(r['target'])
 with RawAssets(resources) as raw:
  def table(name,fields,size=None):
   path='dbfilesclient/'+name.lower()+'.dbc';data=raw.read(path);t=DBC(data)
   if (t.fields,t.record_size)!=(fields,size or 4*fields):raise ValueError('Wrong schema '+name)
   db.execute('insert into provenance values(?,?)',(name,json.dumps({'path':path,'sha256':hashlib.sha256(data).hexdigest(),'records':t.records})))
   def text(row,i,offset=False):
    pos=struct.unpack_from('<I',row,i if offset else i*4)[0]
    if pos>=t.string_bytes:raise ValueError('DBC string outside file')
    start=t.string_start+pos;return data[start:data.index(b'\0',start)].decode('utf-8')
   return [(data[20+i*t.record_size:20+(i+1)*t.record_size]) for i in range(t.records)],text
  def u(r,i):return struct.unpack_from('<I',r,i*4)[0]
  def link(st,sid,role,tt,tid):
   if 0<tid<0x7fffffff:db.execute('insert into links values(?,?,?,?,?)',(st,sid,role,tt,tid))
  rows,text=table('SpellVisualEffectName',7)
  for r in rows:
   name,filename=text(r,1),text(r,2);p,res=resolve(filename);asset(p);db.execute('insert into effects values(?,?,?,?,?)',(u(r,0),name,filename,p,res))
   if p.endswith('.m2') and assets[p]['available']:models.add(p)
  rows,text=table('SpellChainEffects',48,177)
  for r in rows:
   filename=text(r,28,True);p,res=resolve(filename);asset(p);db.execute('insert into chains values(?,?,?,?)',(u(r,0),filename,p,res))
  rows,_=table('SpellVisual',32)
  for r in rows:
   for i in [1,2,3,4,5,6,14,15,22,23,24,25]:link('visual',u(r,0),str(i),'kit',u(r,i))
   link('visual',u(r,0),'missile','effect',u(r,8))
   for i in (11,12):link('visual',u(r,0),str(i),'sound',u(r,i))
  rows,_=table('SpellVisualKit',38)
  for r in rows:
   for i in range(3,15):link('kit',u(r,0),str(i),'effect',u(r,i))
   link('kit',u(r,0),'sound','sound',u(r,15))
   for i in range(4):
    if 0<u(r,17+i)<0x7fffffff:db.execute('insert into procedures values(?,?,?,?)',(u(r,0),i,u(r,17+i),json.dumps([struct.unpack_from('<f',r,(21+i+4*j)*4)[0] for j in range(4)])))
  rows,_=table('SpellVisualKitModelAttach',10)
  for r in rows:link('kit',u(r,1),'attachment:'+str(u(r,3)),'effect',u(r,2))
  rows,text=table('SpellVisualKitAreaModel',3)
  for r in rows:
   filename=text(r,1);p,res=resolve(filename);asset(p);db.execute('insert into areas values(?,?,?,?,?)',(u(r,0),filename,p,res,u(r,2)))
   if p.endswith('.m2') and p in assets and assets[p]['available']:models.add(p)
  rows,text=table('Spell',234)
  for r in rows:
   name=next((text(r,136+i) for i in [8,0]+[k for k in range(16) if k not in (8,0)] if u(r,136+i)), '')
   db.execute('insert into spells values(?,?,?,?,?)',(u(r,0),name,name.casefold(),u(r,131),u(r,132)))
  sound_ids={r[0] for r in db.execute("select distinct target_id from links where target_type='sound'")}
  rows,text=table('SoundEntries',30)
  for r in rows:
   if u(r,0) not in sound_ids:continue
   directory=text(r,23);db.execute('insert into sounds values(?,?,?)',(u(r,0),text(r,2),directory))
   for i in range(3,13):
    fn=text(r,i)
    if fn:
     target=(directory.rstrip('\\/')+'/'+fn).replace('\\','/').lower();db.execute('insert into sound_files values(?,?,?)',(u(r,0),target,int(bool(target in assets and assets[target]['available']))))
  models.update(p for p in assets if p.startswith('spells/') and p.endswith('.m2') and assets[p]['available'])
  pending=list(sorted(models));seen=set()
  while pending:
   p=pending.pop()
   if p in seen:continue
   seen.add(p);asset(p)
   if raw.has(p):
    data=raw.read(p);info=model_info(data,p);basis='M2_bytes_2026-11-10'
    db.execute('delete from dependencies where model=?',(p,))
    for target,relation in [(t['path'],'declared_texture') for t in info['textures'] if t['path']]+[(s,'declared_skin') for s in info['skins']]:
     db.execute('insert or ignore into dependencies values(?,?,?,?)',(p,target,relation,basis));asset(target)
    n,start=array_at(data,28,64)
    for i in range(n):
     off=start+i*64;aid,var=struct.unpack_from('<HH',data,off);flags=struct.unpack_from('<I',data,off+12)[0]
     if not flags&0x60:
      target=p[:-3]+f'{aid:04d}-{var:02d}.anim';db.execute('insert or ignore into dependencies values(?,?,?,?)',(p,target,'external_animation_reference',basis));asset(target)
    if not struct.unpack_from('<I',data,16)[0]&0x200:
     n,start=array_at(data,296,476);children=[]
     for i in range(n):
      for field,relation in [(24,'particle_model'),(32,'particle_recursion_model')]:
       length,off=array_at(data,start+i*476+field,1)
       raw_name=data[off:off+length].rstrip(b'\0').decode('utf-8')
       if raw_name:
        target,res=resolve(raw_name)
        if target.endswith('.m2') and assets[target]['available'] and target not in seen:pending.append(target)
        children.append({'raw':raw_name,'path':target,'resolution':res})
        db.execute('insert or ignore into dependencies values(?,?,?,?)',(p,target or raw_name,relation,basis));asset(target)
     info['particle_children']=children

   else:
    old=src.execute('select metadata_json from inspected_models where path=?',(p,)).fetchone();info=json.loads(old[0]) if old else {};basis='prior_inventory_2026-11-06' if old else 'catalog_only'
   db.execute('insert into models values(?,?,?)',(p,json.dumps(info,ensure_ascii=False),basis))
 for p in sorted(needed):
  a=assets[p];r=src.execute('select member from occurrences where path=? and on_drive=1 limit 1',(p,)).fetchone()
  db.execute('insert into assets values(?,?,?,?,?,?)',(p,a['available'],a['package'],r[0] if r else p,a['drive_url'],a['sha256']))
 db.execute('insert into provenance values(?,?)',('base_inventory',json.dumps({'sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'notice':'Catalog availability is not a full client archive audit; no NPC ownership inferred; unknown procedures retained.'})))
 db.commit();assert db.execute('pragma integrity_check').fetchone()[0]=='ok';db.close();src.close()

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--assets',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();build(a.base,a.assets,a.out)
