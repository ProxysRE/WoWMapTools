"""Real-DBC diversity checks and a complete wardrobe proof batch; no Foundry needed."""
import argparse,json,random,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wowmap.characters import CharacterDB,RACES
from wowmap.character_variants import candidate_character,build_variants

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dbc-assets',required=True);p.add_argument('--model-assets',required=True);p.add_argument('--request',type=Path,default=ROOT/'requests/character-wardrobe.json');p.add_argument('--out',type=Path,required=True);p.add_argument('--samples',type=int,default=1000);a=p.parse_args()
 if not 1<=a.samples<=10000:p.error('samples must be 1..10000')
 request=json.loads(a.request.read_text(encoding='utf-8-sig'));db=CharacterDB(a.dbc_assets);rows=[]
 for body in request['bodies']:
  unique=set();fields={k:Counter() for k in ['skin','face','hair_style','hair_color','facial_hair']};dk=0
  for i in range(a.samples):
   c=candidate_character(db,body,random.Random(i));race=next(k for k,v in RACES.items() if v==c['race']);sex=0 if c['gender']=='male' else 1
   keys=[(race,sex,0,0,c['skin']),(race,sex,1,c['face'],c['skin']),(race,sex,2,c['facial_hair'],c['hair_color']),(race,sex,3,c['hair_style'],c['hair_color'])]
   dk+=sum(bool(db.tables['charsections'].cell(db.sections[k],7)&4) for k in keys if k in db.sections)
   unique.add(tuple(c[k] for k in fields))
   for k in fields:fields[k][c[k]]+=1
  assert dk==0,body
  rows.append({'body':body['id'],'samples':a.samples,'unique_parameter_combinations':len(unique),'dk_sections':dk,'histograms':{k:dict(v) for k,v in fields.items()}});print(body['id'],len(unique),'unique parameter combinations',flush=True)
 result=build_variants(request,a.dbc_assets,a.model_assets,a.out)
 summary={'format':'wowmap.customization-audit/1','algorithm':result['algorithm'],'bodies':rows,'rendered_pairs':len(result['variants']),'coverage':result['coverage'],'rejections':result['rejections'],'same_rendered_images':result['same_rendered_images'],'seed':request['seed'],'dbc_sha256':db.hashes,'live_foundry_tested':False}
 (a.out/'audit-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print('Wardrobe proof passed:',summary['rendered_pairs'],'pairs',flush=True)
if __name__=='__main__':main()
