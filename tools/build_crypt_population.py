"""Combine inspected DEV2-R3 maps with built crypt actors into DEV2-R4.

No NPC statblocks are repaired after Builder. Only visual bindings, placements,
GM documents and package references are added here.
"""
import argparse,copy,hashlib,html,io,json,re,shutil,subprocess,sys
from pathlib import Path
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wowmap.foundry import export_bundle,uid
from wowmap.models import RawAssets,preview
from wowmap.population import write_population
from wowmap.navigation import walk_mask,find_path
from wowmap.foundry import compile_scene
from tools.build_void_crypt import archive_export

PACKAGE='void-crypt-dev2-r4'
KEYS=['crypt-entrance','crypt-passages','crypt-sanctum']


def verify_delivery_document(doc):
    """Check the serialized import payload, not just in-memory build counters."""
    actors=doc.get('actors',[]);scenes=doc.get('scenes',[])
    if len(actors)!=12 or len(scenes)!=3 or sum(len(s.get('tokens',[])) for s in scenes)!=24:
        raise ValueError('Delivery bundle lost population: expected 12 Actors, 3 scenes, 24 tokens')
    if len(doc.get('journals',[]))!=1 or len(doc.get('macros',[]))!=1:
        raise ValueError('Delivery bundle lost GM documents')
    ids={a['_id'] for a in actors}
    if len(ids)!=12:raise ValueError('Duplicate Actor IDs in delivery bundle')
    for scene in scenes:
        for token in scene.get('tokens',[]):
            if token['actorId'] not in ids or token['actorLink']:
                raise ValueError('Broken or shared token Actor reference')
    for actor in actors:
        for item in actor.get('items',[]):
            if not item.get('img','').startswith('wowmap/content/icons/'):
                raise ValueError('Delivery item has no WoW icon: '+actor['name']+' / '+item['name'])
            if any(a.get('img')!=item['img'] for a in item.get('system',{}).get('activities',{}).values()):
                raise ValueError('Activity icon differs from selected ability icon')
    return True

GUIDE='''# Крипта Бездны — DEV2-R4 с обитателями

Пять персонажей 6 уровня; авторский тест под основу D&D 5e и классы Warcraft.
Версия хака «Герои Азерота» пока не подтверждена; использована общая механика 5e.
Предварительный баланс, без игрового прогона. CR не заменяет проверку вашей группы.

## Исправления R4.1: иконки и ракурсы

Все 66 способностей получили оригинальные иконки WoW, включая кнопки действий.
Для моделей выбраны явные ракурсы: портреты в три четверти, токены по диагонали.
Модели, позы, характеристики и правила боя сохранены. Известные лишние наручи
стража разлома не исправлялись.

Если DEV2-R4 УЖЕ импортирован: скопировать папку wowmap из обновлённого архива
в Data, затем создать Script-макрос из UPDATE_EXISTING_RU.js и выполнить от GM.
Он обновляет только изображения NPC, способностей и токенов, включая независимые
токены на сценах. Хиты, заряды, эффекты и состояние боя не сбрасываются.
Повторный запуск допустим. Не нужно удалять сцены или повторять полный импорт.
Для первого импорта использовать обычный порядок ниже.

## Импорт одним макросом

1. Распаковать архив. Скопировать ВСЮ папку wowmap в Data сервера Foundry.
2. Создать Script-макрос из import-foundry.js и выполнить от мастера.
3. Оставить путь wowmap/void-crypt-dev2-r4/bundle.json. Импортируются три сцены,
   двенадцать Actor, 24 размещённых токена, журнал и помощник Ваэлиса.
4. Открыть журнал «Крипта Бездны — руководство мастера DEV2-R4».

Требуются Foundry 13 и dnd5e 5.3.3. Идентификаторы DEV2-R4 отличаются от DEV2-R3:
старые сцены сохраняются. Повторный импорт этого же пакета останавливается.
Фоновые изображения трёх карт сохранены из принятой DEV2-R3. Лестничные
ориентиры на второй сцене пока не добавлены, как было согласовано для теста.

## Что создано

11 игровых типов: волк, паук, медведь, аколит, заклинатель, страж разлома,
пожиратель эха, безликий смотритель, малый отголосок, паучонок и Ваэлис.
Двенадцатый Actor — разрушаемый разлом ритуала, не боевой монстр и не источник XP.
У всех размещённых и призываемых врагов actorLink=false: хиты и эффекты независимы.
Кнопки атак, урона, спасбросков, временных хитов и расходов созданы Builder.
Перемещения, условные бонусы, отсрочки, укрытия и сложные эффекты проверяет мастер.
Без Midi-QOL/DAE броски доступны, но применение и снятие эффектов требует ручной работы.

## Группы и отдых

E1: четыре волка на подходе. E2: три паука у западного крыла, часть снаружи.
E3 (необязательная): медведь и два волка у восточного крыла.
G1: страж и два аколита в западном узле.
G2: заклинатель и два пожирателя в южных гробницах.
G3: страж и аколит в восточной развилке.
G4: один безликий смотритель перед финалом; он может вызвать двух отголосков.
G5 (необязательная): заклинатель и аколит в северной часовне.
G6 (необязательная): пожиратель и аколит в забытой восточной камере.
Реальные встречи зависят от выбранного пути; весь лабиринт не активируется сразу.
Два окна короткого отдыха: после зачистки входа и после смотрителя перед боссом.
Для ПЕРВОГО отдельного теста босса лучше начать на полных ресурсах, чтобы оценить
его механику отдельно от накопленного истощения.

## Ваэлис: ведение боя

300 хитов, КД 16, атаки +7, основные Сл 15. Средний эльф, не гигантский токен.
Фаза I выше 150 хитов. Фаза II при 150 или меньше, только если босс жив.
Переход не лечит, не обрезает избыточный урон, не возвращает ресурсы и не даёт хода.
Огромная тень — образ и аура; размер занимаемой клетки остаётся прежним.
Два легендарных действия в раунд, восстановление в начале хода. Не более одного
разряда и одного смещения за раунд. Две легендарных устойчивости за долгий отдых.

Фаза I: обычные два снаряда, неподвижная подготовленная линия, две отражающие копии,
детонация с укрытием за колоннами. У копий нет отдельных ходов или токенов:
это счётчик из двух подмен. Площадной эффект уничтожает обе копии.
Фаза II: психические снаряды, две волны, один сменяющийся опасный сектор,
связанные метки на двух персонажах и усиленная детонация.

Каждая подготовка требует действия. Выпуск линии, колодца, детонации или волны
на следующем ходу также занимает действие: не прибавлять в этот ход мультиатаку.
Для линии и детонации применять указанные в листе способы прерывания.
Во время подготовки детонации босс не двигается, не использует легендарные действия
и не создаёт новые опасные секторы. Цели за полным каменным укрытием исключаются
мастером из шаблона. Детонация I — 4d8 силового, II — 5d8 психического; не оба броска.
Психические снаряды II имеют отдельную кнопку: не менять формулы вручную.

Пример последовательности, не жёсткий скрипт: I — линия, выпуск, снаряды/отражения,
затем детонация по ситуации. II — подготовка волны, выпуск, сектор или снаряды,
следующая волна не раньше двух раундов после предыдущей подготовки. Между крупными
механиками оставлять возможность атаковать; не пытаться показать весь список за три хода.

## Помощник мастера «Крипта — Ваэлис DEV2-R4»

Макрос создаётся при импорте. Работает только от GM в финальном зале DEV2-R4.
Он помогает со сменой фазы, разломами и волнами; НЕ выбирает атаки и НЕ ведёт бой сам.
Никаких постоянно работающих hooks; состояние сохраняется во флагах токена.

1. При достижении ≤150 хитов выбрать «Включить фазу II».
2. На ходу босса выбрать «Подготовить следующую волну». Это уже расходует
   его действие и использование способности. Не расходовать заряд второй раз из листа.
3. Появятся два разрушаемых токена-руны с независимыми хитами: КД 13, 12 хитов.
   Их можно атаковать, рассеять как эффект 3 круга или закрыть действием из соседней
   клетки успешной Магией Сл 14. После проверки/рассеивания выбрать закрытие нужного
   разлома в помощнике. Урон до 0 помощник распознает при выпуске автоматически.
4. В начале СЛЕДУЮЩЕГО хода босса выбрать «Начало хода». Открытые разломы выпускают
   волну; закрытые ничего не выпускают. Выпуск занимает действие Ваэлиса.
5. В начале ещё одного следующего хода выбрать «Начало хода» снова: существам
   назначается инициатива непосредственно после босса. До этого они не атакуют.
   При ручном добавлении в инициативу соблюдайте тот же срок.
6. Волна I — два малых отголоска. Волна II — страж слева и отголосок справа.
   Всего две волны; одновременно максимум три живых подкрепления этого босса.
   Избыток при выпуске теряется, не становится отложенной третьей волной.
7. Если место занято, выпуск останавливается ДО появления существ: освободить
   место возле руны и повторить. Помощник не ставит токен поверх другого токена.
8. После смерти босса выбрать «Закрыть незавершённый ритуал». Существующие
   подкрепления остаются; новых волн больше не будет.

Смотритель и паук призывают вручную: перетащить Actor «Отголосок разлома» либо
«Паучонок чернильного выводка» из каталога, соблюдать лимит и отложенный первый ход.
Изменение секторов, парадокс, условный урон, отталкивания и гибель ядер ведёт мастер.
Они имеют полные тексты и отдельные кнопки бросков в листах.

## Приёмка

Проверить импорт, независимость хитов двух одинаковых врагов, броски атак и Сл,
доступность всех переходов, укрытие за колоннами, включение второй фазы и обе волны.
Полноценный тест в настоящей Foundry этой средой не выполнен.
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--builder',required=True);ap.add_argument('--rendered',required=True);ap.add_argument('--packages',required=True);ap.add_argument('--out',required=True)
    args=ap.parse_args();work=Path(args.out).resolve();work.mkdir(parents=True,exist_ok=True)
    builder=Path(args.builder).resolve();rendered=Path(args.rendered).resolve();bundle=work/('foundry-'+PACKAGE)
    request=json.loads((ROOT/'requests/builder/void-crypt.json').read_text());population=json.loads((builder/'population.json').read_text())
    population['placements']=request['placements']
    for entry in request['documents']:
        report=json.loads((builder/(entry['id']+'.report.json')).read_text())
        assert not report['source_contract']['errors'] and not report['midi_compatibility']['errors'],entry['id']
    # A walkable original ground rune represents the targetable ritual rift.
    with RawAssets(args.packages) as raw:
        name='world/goober/g_scourgerunecirclecrystal.m2';im,meta=preview(raw,name,512)
        buf=io.BytesIO();im.save(buf,format='WEBP',lossless=True,exact=True);data=buf.getvalue();digest=hashlib.sha256(data).hexdigest()
        path='wowmap/content/tokens/'+digest+'.webp';dest=builder/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        population['media'].append(dict(file=path,sha256=digest,bytes=len(data),source_model=name,render=meta))
        for row in population['actors']:
            if row['key']=='rift':row['document']['img']=path;row['document']['prototypeToken'].setdefault('texture',{})['src']=path
    intermediate=work/'population.json';intermediate.write_text(json.dumps(population,ensure_ascii=False,indent=2)+'\n')
    # write_population resolves media beside its population input.
    for row in population['media']:
        dest=work/row['file'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(builder/row['file'],dest)
    original=export_bundle([rendered/k for k in KEYS],bundle,PACKAGE)
    populated=write_population(bundle/'wowmap'/PACKAGE/'bundle.json',intermediate)
    bundle_path=bundle/'wowmap'/PACKAGE/'bundle.json';doc=json.loads(bundle_path.read_text())
    actors={r['flags']['wowmap']['key']:r for r in doc['actors']}
    arena=next(s for s in doc['scenes'] if s['flags']['wowmap']['key']=='crypt-sanctum')
    plans={k:json.loads((ROOT/'examples'/('void-'+k+'.json')).read_text()) for k in KEYS}
    region_keys={k:{r['id'] for r in p['foundry']['regions']} for k,p in plans.items()}
    p=plans['crypt-sanctum'];mask_scene=compile_scene(p,PACKAGE,'crypt-sanctum',region_keys,'wowmap/'+PACKAGE+'/crypt-sanctum')
    safe={};rifts=[[15,18],[27,18]]
    for size in (1,2):
        m,step=walk_mask(p,mask_scene,token_cells=size);safe[str(size)]=[]
        for x,y in rifts:
            points=[[x+dx*.5,y+dy*.5] for dx in range(-4,5) for dy in range(-4,5) if dx*dx+dy*dy<=16]
            points.sort(key=lambda q:(abs(q[0]-x)+abs(q[1]-y),q))
            points=[q for q in points if m[int(q[1]/step),int(q[0]/step)] and find_path(m,step,(21,18),q)]
            assert points;safe[str(size)].append(points)
    cfg=dict(package=PACKAGE,actors={k:a['_id'] for k,a in actors.items()},rifts=rifts,safePoints=safe)
    command=(ROOT/'wowmap/crypt_encounter.js').read_text().replace('__CRYPT_CONFIG__',json.dumps(cfg,ensure_ascii=False))
    bestiary=(ROOT/'VOID_CRYPT_BESTIARY.md').read_text()
    journal_id=uid(PACKAGE,'journal','gm-guide');macro_id=uid(PACKAGE,'macro','vaelis')
    links='<p>'+ ' | '.join('@UUID[Actor.'+a['_id']+']{'+html.escape(a['name'])+'}' for a in doc['actors'])+'</p>'
    doc['journals']=[dict(_id=journal_id,name='Крипта Бездны — руководство мастера DEV2-R4',ownership=dict(default=0),folder=None,flags=dict(wowmap=dict(package=PACKAGE)),pages=[
        dict(_id=uid(PACKAGE,'journal','guide-page'),name='Импорт, встречи и Ваэлис',type='text',sort=100000,text=dict(format=1,content=links+'<pre style="white-space:pre-wrap">'+html.escape(GUIDE)+'</pre>')),
        dict(_id=uid(PACKAGE,'journal','bestiary-page'),name='Полный бестиарий',type='text',sort=200000,text=dict(format=1,content='<pre style="white-space:pre-wrap">'+html.escape(bestiary)+'</pre>'))])]
    doc['macros']=[dict(_id=macro_id,name='Крипта — Ваэлис DEV2-R4',type='script',scope='global',command=command,img='icons/svg/dice-target.svg',ownership=dict(default=0),flags=dict(wowmap=dict(package=PACKAGE)))]
    doc['visualRevision']='R4.1'
    shutil.copy2(ROOT/'wowmap/update_crypt_visuals.js',bundle/'UPDATE_EXISTING_RU.js')
    bundle_path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    verify_delivery_document(json.loads(bundle_path.read_text()))
    (bundle/'vaelis-helper.js').write_text(command,encoding='utf-8')
    (bundle/'START_HERE_RU.md').write_text(GUIDE,encoding='utf-8');(bundle/'BESTIARY_RU.md').write_text(bestiary,encoding='utf-8')
    source=bundle/'source';source.mkdir();verification=bundle/'verification';verification.mkdir();previews=bundle/'previews';previews.mkdir()
    shutil.copy2(ROOT/'requests/builder/void-crypt.json',source/'void-crypt-request.json')
    shutil.copytree(ROOT/'requests/builder/sources/void-crypt',source/'npc-sources')
    (source/'population.json').write_text(json.dumps(population,ensure_ascii=False,indent=2)+'\n')
    for k in KEYS:shutil.copy2(ROOT/'examples'/('void-'+k+'.json'),source/(k+'-plan.json'))
    for name in ('prepare_crypt_population.py','build_crypt_population.py'):shutil.copy2(ROOT/'tools'/name,source/name)
    shutil.copy2(ROOT/'wowmap/crypt_encounter.js',source/'crypt_encounter-template.js')
    for file in builder.glob('*.report.json'):shutil.copy2(file,verification/file.name)
    shutil.copy2(builder/'build-report.json',verification/'actor-build-report.json')
    shutil.copy2(ROOT/'output/crypt-dev2-r4-tests.log',verification/'tests.log')
    for file in builder.glob('icon-review-*.png'):shutil.copy2(file,previews/file.name)
    shutil.copy2(builder/'icon-bindings.json',verification/'icon-bindings.json')
    shutil.copy2(ROOT/'resources/void-crypt-item-icons.json',source/'void-crypt-item-icons.json')
    # Original renderer evidence remains distinguishable from NPC placement overlays.
    report=dict(revision='DEV2-R4',package_id=PACKAGE,foundry=original,population=populated,journals=1,macros=1,
                map_art='Approved DEV2-R3 image pixels reused, no rerender',in_game_test=False,
                targets=dict(foundry='13.351',dnd5e='5.3.3'),rules='5e foundation; exact Warcraft class hack unconfirmed',
                notes=['Spawn points statically checked against native walls and movement footprints','All repeated NPC tokens are unlinked with independent ActorDelta','Phase and waves use a GM helper, not automatic combat AI'])
    tests=(ROOT/'output/crypt-dev2-r4-tests.log').read_text();match=re.search(r'Ran (\d+) tests',tests);report['python_tests_run']=int(match[1]) if match else None
    (verification/'release-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (verification/'media-provenance.json').write_text(json.dumps(population['media'],ensure_ascii=False,indent=2)+'\n')
    # Full source diff, including the restored R2 and R3 changes, applies to base.
    patch=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=ROOT)
    for name in subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0'):
        if name:
            result=subprocess.run(['git','diff','--no-index','--binary','--','/dev/null',name],cwd=ROOT,capture_output=True)
            if result.returncode not in (0,1):raise RuntimeError('Cannot capture '+name)
            patch+=result.stdout
    (source/'DEV2_R4.patch').write_bytes(patch)
    (source/'BASE_COMMIT.txt').write_text('06583bf011a5bc4db1265d67eaf0305bd2bd0f37\nApply patch on a clean checkout of this exact commit.\n')
    # Preview contact sheets and scene overlays use the actual delivered token pixels.
    from PIL import Image,ImageDraw,ImageFont
    font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font=ImageFont.truetype(font_path,15);small=ImageFont.truetype(font_path,12)
    sheet=Image.new('RGB',(1440,4*370),'#252a35');draw=ImageDraw.Draw(sheet)
    for i,(key,actor) in enumerate(actors.items()):
        x=(i%3)*480;y=(i//3)*370
        portrait=Image.open(bundle/actor['img']).convert('RGBA');portrait.thumbnail((300,290));sheet.paste(portrait,(x+6+(300-portrait.width)//2,y+20),portrait)
        token=Image.open(bundle/actor['prototypeToken']['texture']['src']).convert('RGBA');n=actor['prototypeToken']['width'];token.thumbnail((80*n,80*n));sheet.paste(token,(x+318+(160-token.width)//2,y+90+(160-token.height)//2),token)
        draw.text((x+10,y+315),actor['name'][:48],font=font,fill='white')
        draw.text((x+10,y+340),f"КД {actor['system']['attributes']['ac']['flat']} | HP {actor['system']['attributes']['hp']['max']} | {len(actor['items'])} способностей",font=small,fill='#c3ccdb')
    sheet.save(previews/'VoidCrypt_DEV2_R4_Bestiary.jpg',quality=95)
    for scene in doc['scenes']:
        k=scene['flags']['wowmap']['key'];im=Image.open(rendered/k/'map.webp').convert('RGBA');draw=ImageDraw.Draw(im)
        for t in scene['tokens']:
            tok=Image.open(bundle/t['texture']['src']).convert('RGBA').resize((round(t['width']*80),round(t['height']*80)),Image.Resampling.LANCZOS)
            im.alpha_composite(tok,(round(t['x']),round(t['y'])))
            draw.rectangle((t['x'],t['y'],t['x']+t['width']*80,t['y']+t['height']*80),outline='#ba83ff',width=2)
        im.thumbnail((1800,1800));im.convert('RGB').save(previews/('VoidCrypt_DEV2_R4_'+k+'.jpg'),quality=95)
    checksums={str(p.relative_to(bundle)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(bundle.rglob('*')) if p.is_file()}
    (bundle/'SHA256.json').write_text(json.dumps(checksums,ensure_ascii=False,indent=2)+'\n')
    archive=work/'VoidCrypt_Foundry13_DEV2_R4_Populated.zip';archive_export(bundle,archive)
    with ZipFile(archive) as z:
        assert z.testzip() is None
        verify_delivery_document(json.loads(z.read(bundle.name+'/wowmap/'+PACKAGE+'/bundle.json')))
    print(json.dumps(dict(archive=str(archive),bytes=archive.stat().st_size,actors=len(doc['actors']),tokens=sum(len(s.get('tokens',[])) for s in doc['scenes']),scenes=len(doc['scenes']),journal=journal_id,macro=macro_id)))


if __name__=='__main__':main()
