"""Build one isolated Foundry 13 effect laboratory; never rewrites the crypt."""
import argparse,hashlib,json,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw,ImageFont
from wowmap.models import RawAssets,preview
from wowmap.effect_loops import write_smoke_loop
from wowmap.foundry import export_bundle


def build(packages,out):
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Output must be empty')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.void-lab-',dir=out.parent) as temporary:
        stage=Path(temporary);render=stage/'rendered';render.mkdir();media=stage/'media';media.mkdir()
        evidence=[]
        with RawAssets(packages) as assets:
            for filename,model in [('vessel','world/expansion01/doodads/generic/ethereal/cage/et_cagebase.m2'),('collector','world/expansion01/doodads/generic/ethereal/collector/et_collector01.m2')]:
                image,meta=preview(assets,model,512);image.save(media/(filename+'.png'));evidence.append(dict(model=model,model_sha256=hashlib.sha256(assets.read(model)).hexdigest(),render=meta))
            effect=write_smoke_loop(assets,'world/expansion01/doodads/netherstorm/crackeffects/smoke01_flip.blp',media)
        prefix='wowmap/content/effects/void-lab/'
        plan=dict(format='wowmap.scene/1',name='Лаборатория — статичные объекты и дымка',seed=28,size_cells=[12,9],pixels_per_cell=80,distance_per_cell=5,units='ft',base=dict(asset='technical-neutral-canvas.png',id='lab'),walls=[],foundry=dict(key='void-lab',global_light=True,darkness=.25,grid_alpha=.12,
            lights=[dict(id='pulse',position=[4,4.5],bright=1,dim=4,color='#7950a8',alpha=.25,animation=dict(type='pulse',speed=2,intensity=2))],
            tiles=[dict(id='vessel',path=prefix+'vessel.png',position=[1.5,2],size_cells=[5,5]),dict(id='collector',path=prefix+'collector.png',position=[7,2.5],size_cells=[4,4]),dict(id='mist',path=prefix+'void-mist.webm',position=[1.5,2],size_cells=[5,5],opacity=.85,video=dict(autoplay=True,loop=True,volume=0))]))
        canvas=Image.new('RGB',(960,720),'#302b36');draw=ImageDraw.Draw(canvas)
        try:font=ImageFont.truetype('DejaVuSans.ttf',19)
        except OSError:font=ImageFont.load_default(size=19)
        draw.text((70,50),'STATIC PROP + TRANSPARENT WEBM',font=font,fill='#e2d6ef');draw.text((570,50),'STATIC BC COLLECTOR',font=font,fill='#e2d6ef')
        draw.text((70,650),'Technical effect test. No campaign scene is replaced.',font=font,fill='#b5a7be')
        canvas.save(render/'map-vtt.webp',lossless=True)
        (render/'scene-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
        (render/'render.json').write_text(json.dumps(dict(plan_sha256=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest(),width=960,height=720,vtt_image='map-vtt.webp',kind='authored neutral technical canvas; no map generator quality claim')))
        bundle=stage/'foundry-void-effects-lab';result=export_bundle([render],bundle,'void-effects-lab')
        target=bundle/'wowmap/content/effects/void-lab';target.mkdir(parents=True)
        for name in ['vessel.png','collector.png','void-mist.webm']:shutil.copy2(media/name,target/name)
        # A still for inspection; the Foundry file remains a video tile.
        still=canvas.convert('RGBA')
        for name,x,y,size in [('vessel',120,160,400),('collector',560,200,320)]:
            im=Image.open(media/(name+'.png')).resize((size,size),Image.Resampling.LANCZOS);still.alpha_composite(im,(x,y))
        im=Image.open(media/'void-mist-first.png').resize((400,400),Image.Resampling.LANCZOS);still.alpha_composite(im,(120,160));still.convert('RGB').save(bundle/'Lab_Preview.jpg',quality=95)
        (bundle/'model-evidence.json').write_text(json.dumps(evidence,indent=2))
        (bundle/'effect-provenance.json').write_text(json.dumps(effect,indent=2))
        (bundle/'START_HERE_RU.md').write_text('''# Техническая лаборатория эффектов

Это одна отдельная тестовая сцена, не новая версия крипты и не готовая карта.
Слева — статичный предмет из BC, отдельный прозрачный WebM и пульсирующий свет
Foundry. Справа — статичная геометрия эфирного коллектора. Его оригинальные
WoW-частицы не воспроизводятся. Дымка слева — авторский 2D-цикл из настоящей
текстуры WoW, с выбранным фиолетовым оттенком; это не эмулятор M2-эмиттеров.

Скопировать папку wowmap в Data, выполнить Script-макрос из import-foundry.js.
Путь: wowmap/void-effects-lab/bundle.json. Затем открыть сцену от мастера.
Проверить прозрачность дымки, плавность зацикливания и пульсацию света.
Повторный импорт не заменяет существующую сцену. Крипта не затрагивается.

Варианты ошибок импорта и доступность WebM проверяются стандартным импортёром.
Само воспроизведение в настоящем Foundry ещё не проверено. Декодирование видео
с прозрачностью проверено отдельно через libvpx-vp9. Для пересборки нужен ffmpeg.
''')
        if out.exists():out.rmdir()
        shutil.move(str(bundle),out)
    result["output"]=str(out)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--packages',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    try:print(json.dumps(build(a.packages,a.out)))
    except (OSError,ValueError) as e:p.exit(1,'ERROR: '+str(e)+'\n')
