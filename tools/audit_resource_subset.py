"""Recheck the original three regression models without modifying game assets."""
import argparse,hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wowmap.models import RawAssets,preview
from wowmap.creature_appearances import creature_display_skin

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--packages',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);rows=[]
 with RawAssets(a.packages,verify_archives=True) as raw:
  succ=creature_display_skin(raw,4162)
  assert succ['textures'][12].endswith('/succubusskinwing.blp')
  assert succ['textures'][13].endswith('/succubushair.blp')
  jobs=[('earth','creature/elementalearth/elementalearth.m2',{11:'creature/elementalearth/rockelementalskinbrown.blp'}),('voidwalker','creature/voidwalker/voidwalker.m2',{11:'creature/voidwalker/voidwalkerskin.blp'}),('succubus',succ['model'],succ['textures'])]
  for label,model,textures in jobs:
   for pose in [None,'idle',{'animation_id':16,'fraction':0}]:
    for view in ['top','front']:
     image,meta=preview(raw,model,256,textures,yaw=-90 if view=='top' else 25,view=view,pose=pose)
     if label=='earth':assert meta['hidden_material_batches']==[2,3],meta
     assert image.getbbox()
     name=f'{label}-{len(rows):02d}.webp';image.save(a.out/name,lossless=True,exact=True)
     rows.append({'model':model,'pose':pose,'view':view,'file':name,'sha256':hashlib.sha256((a.out/name).read_bytes()).hexdigest(),'metadata':meta})
 (a.out/'render-report.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'result':'passed','renders':len(rows),'earth_hidden_batches':[2,3],'succubus_display':4162,'live_foundry':False}))
if __name__=='__main__':main()
