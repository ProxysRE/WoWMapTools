"""Read-only lookup of effects.sqlite; Python standard library only."""
import argparse,json,sqlite3
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('query',nargs='?',default='');p.add_argument('--db',type=Path,default=Path(__file__).with_name('effects.sqlite'));p.add_argument('--kind',choices=['spell','model','effect','chain'],default='spell');p.add_argument('--limit',type=int,default=20)
 m=p.add_mutually_exclusive_group();m.add_argument('--spell-id',type=int);m.add_argument('--inspect');m.add_argument('--missing',action='store_true')
 a=p.parse_args()
 if not 1<=a.limit<=2000:p.error('limit: 1..2000')
 if not a.db.is_file():p.error('Не найден effects.sqlite. Распакуйте архив целиком.')
 c=sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
 def rows(sql,args=()):return [dict(r) for r in c.execute(sql,args)]
 if a.spell_id is not None:
  spells=rows('select * from spells where id=?',(a.spell_id,));result={'spell':spells,'links':[]}
  if spells:
   for vid in [spells[0]['visual1'],spells[0]['visual2']]:
    for link in rows("select * from links where source_type='visual' and target_type in ('effect','kit') and source_id=?",(vid,)):
     targets=[link] if link['target_type']=='effect' else rows("select * from links where source_type='kit' and target_type='effect' and source_id=?",(link['target_id'],))
     for t in targets:result['links'].append({'visual':vid,'phase':link['role'],'slot':t['role'],'effect':rows('select * from effects where id=?',(t['target_id'],))})
  result['notice']='Только явные DBC-связи; неизвестные процедуры не расшифрованы. Наличие файла не гарантирует полный рендер.'
 elif a.inspect:
  path=a.inspect.lower().replace('\\','/');result={'model':rows('select * from models where path=?',(path,)),'asset':rows('select * from assets where path=?',(path,)),'dependencies':rows('select d.*,a.available,a.package,a.drive_url from dependencies d left join assets a on a.path=d.target where d.model=?',(path,))}
 elif a.missing:
  result={'dependencies':rows('select d.* from dependencies d left join assets a on a.path=d.target where a.path is null or a.available=0 limit ?',(a.limit,)),'chains':rows("select * from chains where resolution in ('unresolved','ambiguous') limit ?",(a.limit,))}
 else:
  q='%'+a.query.casefold()+'%'
  if a.kind=='spell':result=rows('select id,name,visual1,visual2 from spells where fold like ? order by id limit ?',(q,a.limit))
  elif a.kind=='model':result=rows('select m.path,m.basis,a.package,a.drive_url from models m left join assets a on a.path=m.path where m.path like ? limit ?',(q,a.limit))
  elif a.kind=='effect':result=rows('select * from effects where lower(name) like ? or lower(raw_path) like ? limit ?',(q,q,a.limit))
  else:result=rows('select * from chains where lower(raw_texture) like ? limit ?',(q,a.limit))
 print(json.dumps(result,ensure_ascii=False,indent=2));c.close()
if __name__=='__main__':main()
