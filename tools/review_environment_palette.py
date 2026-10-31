"""Compare real map-scale views and declare unsupported M2 effects before selection."""
import argparse,hashlib,json,sys,textwrap
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw,ImageFont
from wowmap.models import RawAssets,preview
from wowmap.effects import effect_features


def review(packages,entries,out):
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('Output must be empty')
    if not isinstance(entries,list) or not 1<=len(entries)<=24:raise ValueError('Palette needs 1..24 explicit models')
    out.mkdir(parents=True,exist_ok=True)
    try:font=ImageFont.truetype('DejaVuSans.ttf',12)
    except OSError:font=ImageFont.load_default(size=12)
    sheet=Image.new('RGB',(1200,400*((len(entries)+1)//2)),'#252a35');draw=ImageDraw.Draw(sheet);rows=[]
    with RawAssets(packages) as raw:
        for i,entry in enumerate(entries):
            name=entry['model'];x=i%2*600;y=i//2*400
            row=dict(model=name,note=entry.get('note','No artistic selection recorded'))
            draw.text((x+8,y+8),Path(name).name[:78],font=font,fill='white')
            try:row.update(source_sha256=hashlib.sha256(raw.read(name)).hexdigest(),features=effect_features(raw.read(name)))
            except ValueError as e:row['inspection_error']=str(e)
            for col,view in enumerate(('top','front')):
                try:
                    im,meta=preview(raw,name,240,yaw=30 if view=='front' else 0,view=view)
                    filename=f'{i+1:02d}-{view}.png';im.save(out/filename);sheet.paste(im,(x+20+col*300,y+30),im)
                    row[view]=dict(file=filename,render=meta)
                except ValueError as e:
                    row[view]=dict(error=str(e));draw.text((x+8+col*300,y+130),str(e)[:40],font=font,fill='#ff9999')
            draw.text((x+8,y+275),'TOP                                  FRONT / QUARTER',font=font,fill='white')
            warning='; '.join(row.get('features',{}).get('warnings',[])) or 'No declared unsupported emitter/track features'
            for j,line in enumerate(textwrap.wrap(warning,85)[:3]):draw.text((x+8,y+295+j*15),line,font=font,fill='#dabaff')
            for j,line in enumerate(textwrap.wrap(row['note'],85)[:3]):draw.text((x+8,y+345+j*15),line,font=font,fill='#b5c7d5')
            rows.append(row)
    sheet.save(out/'Void_Palette_Review.jpg',quality=95)
    (out/'palette.json').write_text(json.dumps(rows,indent=2)+'\n');return rows

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--packages',required=True);p.add_argument('--request',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    try:print(json.dumps(dict(models=len(review(a.packages,json.loads(Path(a.request).read_text()),a.out)))))
    except (ValueError,OSError) as e:p.exit(1,'ERROR: '+str(e)+'\n')
