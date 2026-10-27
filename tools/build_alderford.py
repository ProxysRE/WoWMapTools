"""Author three playable village excerpts; only the northern gate shows the palisade.

No game assets are embedded. Run from any directory to create reproducible plans
and canonical Builder inputs. Resource ZIPs are required for rendering, not authoring.
"""
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = 'world/generic/human/passive doodads/'
P = 'world/generic/passivedoodads/'
E = 'world/azeroth/elwynn/passivedoodads/'
D = 'world/azeroth/duskwood/passivedoodads/'
GRASS = 'tileset/elwynn/elwynngrassbase.blp'
DIRT = 'tileset/elwynn/elwynndirtmud02.blp'
STONE = 'tileset/elwynn/elwynncobblestonebase.blp'
WOOD = 'dungeons/textures/floor/mm_inn_wood floor_01.blp'
WALL = 'world/azeroth/elwynn/buildings/blacksmith/blacksmithwood04.blp'
MODELS = {
    'table': H+'tables/inntable.m2', 'chair': H+'chairs/generalchairloend01.m2',
    'bench': H+'benches/duskwoodbench.m2', 'bed': H+'beds/duskwoodbed.m2',
    'shelf': H+'bookshelves/duskwoodbookshelf01.m2', 'counter': H+'shopcounter/duskwoodshopcounter.m2',
    'keg': H+'beerkegs/beerkeg01.m2', 'barrel': P+'barrel/barrel01.m2', 'crate': P+'crate01/crate01.m2',
    'bucket': H+'buckets/bucket.m2', 'plate': H+'plates/generaldirtyplate01.m2',
    'bread': H+'food/breadloaf01.m2', 'cheese': H+'food/cheesewedge01.m2',
    'fish': H+'food/fishplatter01.m2', 'book': H+'books/booklargeopen01.m2',
    'mug': H+'mugs/mug01.m2', 'stove': H+'stoves/potbellystove.m2',
    'cauldron': H+'cauldrons/cauldronempty.m2', 'logs': H+'firewood/firewoodpile03.m2',
    'planter': H+'planterboxes/stormwindplanter.m2', 'well': P+'well/well.m2',
    'hay': E+'haystacks/haystack01.m2', 'wagon': D+'duskwoodhaywagon/duskwoodhaywagon.m2',
    'lamp': H+'lampposts/duskwoodlamppost.m2', 'anvil': E+'anvil/anvil.m2',
    'tree': D+'spooklesstrees/duskwoodtreespookless01.m2',
    'pine': E+'trees/elwynntree01/elwynnpine02.m2',
    'palisade': H+'outposts/generaloutpost01.m2',
    'wheelbarrow': P+'misc/wheelbarrow/caveminewheelbarrow01.m2',
}


def rect(bounds, **options):
    return dict(type='rectangle', bounds=bounds, **options)


def obj(p, key, model, x, y, size=1, rotation=0, order=10, shadow=True):
    value=dict(id=key, model=MODELS.get(model,model), position=[x,y], position_anchor='bounds-center',
               size_cells=size, rotation=rotation, order=order, layer='props')
    if shadow:value['shadow']=dict(opacity=.2,blur_cells=.07,offset_cells=[.07,.1])
    p['objects'].append(value)
    return value


def detail(p,key,kind,**fields):
    p['details'].append(dict(id=key,type=kind,**fields))


def line(p,key,points,color='#6a5034',width=.07):
    detail(p,key,'line',points=points,stroke=color,width_cells=width)


def floor(p,key,bounds,asset=WOOD,tile=1.4,tint=None):
    f=dict(id=key,asset=asset,tile_cells=tile,shape=rect(bounds,feather=0))
    if tint:f['tint']=tint
    p['floors'].append(f)


def path(p,key,points,width=2.2,asset=DIRT):
    p['layers'].append(dict(id=key,asset=asset,tile_cells=3.2,
        shape=dict(type='path',points=points,width=width,smooth=True,feather=.35,roughness=.1)))


def wall(p,key,a,b,openings=(),thickness=.27,asset=WALL):
    p['walls'].append(dict(id=key,points=[a,b],asset=asset,thickness=thickness,
                           tile_cells=1,openings=list(openings)))


def door(key,at,width=1.4,state='closed',kind='door'):
    return dict(id=key,at=at,width=width,type=kind,state=state,asset=WALL)


def lamp(p,key,x,y):
    obj(p,key,'lamp',x,y,.7,shadow=False)
    p['foundry']['lights'].append(dict(id=key,position=[x,y],bright=2,dim=5,color='#ffc885',alpha=.22))


def location(p,name,x,y):
    p['locations'].append(dict(name=name,position=[x,y]))


def building(p,key,bounds,entry='s',offset=None,name=None):
    x0,y0,x1,y1=bounds;cx=(x0+x1)/2;cy=(y0+y1)/2
    floor(p,key+'-foundation',[x0-.25,y0-.25,x1+.25,y1+.25],STONE,1.1,'#b9b1a1')
    floor(p,key+'-floor',bounds)
    edges={'n':([x0,y0],[x1,y0],x1-x0),'s':([x0,y1],[x1,y1],x1-x0),
           'w':([x0,y0],[x0,y1],y1-y0),'e':([x1,y0],[x1,y1],y1-y0)}
    for side,(a,b,length) in edges.items():
        if side==entry:
            opening=door(key+'-entry',offset if offset is not None else length/2,1.6,'open')
        else:
            opening=door(key+'-'+side+'-window',length/2,1.2,kind='window')
        wall(p,key+'-'+side,a,b,[opening])
    for i,(x,y) in enumerate([(x0,y0),(x1,y0),(x0,y1),(x1,y1)]):
        detail(p,key+f'-post-{i}','rectangle',bounds=[x-.18,y-.18,x+.18,y+.18],fill='#453021')
    # A worn apron at the actual doorway makes its access visible from the street.
    length=edges[entry][2];at=offset if offset is not None else length/2
    ex,ey={'n':(x0+at,y0-.6),'s':(x0+at,y1+.6),'w':(x0-.6,y0+at),'e':(x1+.6,y0+at)}[entry]
    p['layers'].append(dict(id=key+'-threshold-wear',asset=DIRT,tile_cells=2,
        shape=dict(type='ellipse',bounds=[ex-1.5,ey-1.15,ex+1.5,ey+1.15],feather=.4,roughness=.12)))
    if name:location(p,name,cx,cy)
    return cx,cy


def table(p,key,x,y,size=2,rotation=90,food=False):
    obj(p,key,'table',x,y,size,rotation,order=14)
    obj(p,key+'-chair-a','chair',x,y-.95,.65,90)
    obj(p,key+'-chair-b','chair',x,y+.95,.65,270)
    if food:
        for model,dx in [('bread',-.35),('cheese',.3),('mug',.7)]:
            obj(p,key+'-'+model,model,x+dx,y,.32 if model!='mug' else .2,order=30,shadow=False)


def garden(p,key,bounds):
    floor(p,key+'-soil',bounds,DIRT,2.3,'#a49c7a')
    x0,y0,x1,y1=bounds
    for i in range(4):
        y=y0+.5+i*(y1-y0-1)/3
        line(p,key+f'-row-{i}',[[x0+.3,y],[x1-.3,y]],'#50442a',.13)
        for j in range(7):
            x=x0+.6+j*(x1-x0-1.2)/6
            detail(p,key+f'-plant-{i}-{j}','ellipse',bounds=[x-.13,y-.14,x+.13,y+.14],fill='#47713a')


def basic(key,name,index):
    p=dict(format='wowmap.scene/1',name='Ольховый Брод — '+name,seed=7301+index,
        size_cells=[48,36],pixels_per_cell=80,distance_per_cell=5,units='ft',export_format='webp',
        surface_variation=.035,base=dict(id='base',asset=GRASS,tile_cells=4.8,tint='#a2b2a0'),
        layers=[],floors=[],walls=[],objects=[],details=[],locations=[],
        architecture=dict(outline_cells=.025,shadow_cells=.12,shadow_opacity=.28),
        foundry=dict(key=key,global_light=True,darkness=.12,grid_alpha=.12,lights=[],regions=[],barriers=[]))
    path(p,'main-road',[[24,-2],[24,18],[24,38]],6.4)
    # Cropped neighbourhood continues beyond the frame; no perimeter on inner scenes.
    for i,(x,y) in enumerate([(1.5,4),(46,5),(1,32),(46.8,33)]):
        tree=obj(p,'edge-tree-'+str(i),'tree',x-.7 if x<24 else x+.7,y,2.7+(i%2),i*73,order=80)
        tree['layer']='overhead'
    return p


def gate():
    p=basic('gate','северные ворота',0)
    for a,b in [(0,20.8),(27.2,48)]:
        length=b-a;count=math.ceil(length/3.1)
        for i in range(count):
            x=a+(i+.5)*length/count
            obj(p,f'palisade-{a}-{i}','palisade',x,10,length/count+.12,90,order=50)
    # Native collision and door follow the same gap as the actual log models.
    wall(p,'palisade-north',[0,10],[48,10],[door('north-gate',24,6.4,'open')],.07)
    for i,x in enumerate([18.7,29.3]):
        building(p,f'gate-post-{i}',[x-1.8,10.2,x+1.8,15],entry='s',name='Пост стражи')
        table(p,f'post-desk-{i}',x,11.8,1.35,food=False)
        obj(p,f'post-ledger-{i}','book',x,11.8,.4,order=30,shadow=False)
    building(p,'barracks',[4,18,15,30],entry='e',offset=4,name='Караульный дом')
    for i,(x,y) in enumerate([(6,20),(6,23),(6,26),(10,28)]):obj(p,f'guard-bed-{i}','bed',x,y,2.2,90)
    table(p,'barracks-table',11.5,21,2,food=True)
    obj(p,'guard-shelf','shelf',13.8,28,2,0)
    obj(p,'barracks-stove','stove',12.5,25.5,1)
    path(p,'barracks-access',[[15,22],[20,22],[24,21]],2.2)
    building(p,'stable',[33,19,44,29],entry='w',offset=4.8,name='Конюшня и фураж')
    for i,y in enumerate([21,24,27]):
        obj(p,f'stable-hay-{i}','hay',41.9,y,1.6,25*i)
        obj(p,f'stable-bucket-{i}','bucket',40.6,y+.7,.4)
        line(p,f'stable-stall-{i}',[[39.8,y+1.15],[43.7,y+1.15]],'#624a2e',.1)
    obj(p,'stable-crate','crate',35.5,20.5,1)
    obj(p,'stable-barrel','barrel',35.5,27,.9)
    path(p,'stable-access',[[24,24],[29,24],[33,24]],2.5)
    path(p,'inspection-yard',[[28,15],[31,17],[30,31]],3.8)
    obj(p,'waiting-wagon','wagon',28.5,5,3.8,25)
    obj(p,'inspection-crate-a','crate',29.8,19,1.1)
    obj(p,'inspection-crate-b','crate',31,20.2,.9,20)
    obj(p,'inspection-barrel','barrel',29.7,21,.8)
    obj(p,'wood-reserve','logs',16.8,29,2.2,0)
    obj(p,'water-cart','wheelbarrow',17.5,18,1.5,40)
    garden(p,'gate-herbs',[5,32,13,35])
    floor(p,'guard-rug',[9.7,23,13.8,26],WOOD,.9,'#c38d67')
    for i,(x,y) in enumerate([(7.5,29),(13.5,19.5),(34.5,28),(42,19.8)]):
        obj(p,'gate-extra-stock-'+str(i),'barrel' if i%2 else 'crate',x,y,.7,23*i)
    # Training equipment is placed away from the through road.
    for i in range(3):line(p,'practice-rack-'+str(i),[[17.5+i*.4,23],[17.5+i*.4,25]],'#6e5738',.06)
    floor(p,'practice-yard',[16.5,21,20,27.5],DIRT,2.5,'#ac9b7e')
    location(p,'Осмотр повозок',29,17)
    location(p,'Северная дорога',24,4)
    for i,(x,y) in enumerate([(21,13),(27,13),(19,28),(29,31)]):lamp(p,'gate-lamp-'+str(i),x,y)
    return p


def stall(p,key,x,y,color,goods):
    floor(p,key+'-deck',[x-2,y-1.6,x+2,y+1.5])
    # Cloth band occupies only the rear of the booth; trade space remains visible.
    for i in range(8):
        detail(p,key+f'-cloth-{i}','rectangle',bounds=[x-2+i*.5,y-1.6,x-1.5+i*.5,y-.8],
               fill=color if i%2 else '#d6c4a0')
    obj(p,key+'-table','table',x,y,2.8,90,order=15)
    for i in range(4):obj(p,key+f'-goods-{i}',goods,x-.8+i*.53,y,.34,order=30,shadow=False)
    for i,dx in enumerate([-1.7,1.7]):
        detail(p,key+f'-post-{i}','ellipse',bounds=[x+dx-.1,y-1.55,x+dx+.1,y-1.35],fill='#42301f')
    obj(p,key+'-stock','crate',x+1.45,y+1,.65)


def market():
    p=basic('market','торговая площадь',1)
    floor(p,'market-cobbles',[13,7,35,30],STONE,2.2,'#c4bba6')
    p['floors'][-1]['shape']=rect([12.6,6.6,35.4,30.4],feather=.38,roughness=.06)
    path(p,'market-crossroad',[[-2,18],[24,18],[50,18]],3.8)
    building(p,'bakery',[1,4,11,14],entry='e',offset=6,name='Пекарня')
    obj(p,'bakery-stove','stove',3,6,1.45)
    obj(p,'bakery-prep','counter',6,6,2.8,90)
    for i in range(4):obj(p,'loaf-'+str(i),'bread',5.2+i*.5,6,.4,order=25,shadow=False)
    obj(p,'bakery-flour','barrel',3,11,.9)
    table(p,'bakery-table',7.5,11,1.8)
    building(p,'smith',[37,4,47,15],entry='w',offset=6,name='Кузница')
    floor(p,'smith-hearth',[43,5,46,8],STONE,1,'#777575')
    obj(p,'smith-stove','stove',44.5,6,1.8)
    obj(p,'smith-anvil','anvil',40,7,1.25,90)
    obj(p,'smith-water','bucket',41.5,7.5,.6)
    obj(p,'smith-workbench','table',44,11,2.8,0)
    obj(p,'smith-logs','logs',46,13.8,1.7,90)
    obj(p,'smith-crates','crate',39,13,1)
    for i,(x,y,color,goods) in enumerate([(17,11,'#a74a38','bread'),(31,11,'#4c7186','fish'),
        (17,22,'#707b42','cheese'),(31,22,'#8a5b79','plate')]):stall(p,'stall-'+str(i),x,y,color,goods)
    location(p,'Хлебный ряд',17,12.5);location(p,'Рыбный ряд',31,12.5)
    location(p,'Сыр и молочные продукты',17,23.5);location(p,'Посуда и мелочи',31,23.5)
    building(p,'warehouse',[37,23,47,35],entry='w',offset=5,name='Склад артели')
    for i,(x,y) in enumerate([(44.5,25),(44.5,27),(44.5,29),(44.5,32),(40,33)]):
        obj(p,'warehouse-box-'+str(i),'crate' if i%2 else 'barrel',x,y,1.2,10*i)
    obj(p,'warehouse-wagon','wagon',39,19.5,3.5,90)
    building(p,'weaver-home',[1,23,11,35],entry='e',offset=5,name='Дом ткачихи')
    obj(p,'weaver-bed','bed',3,25.5,2.3,90);table(p,'weaver-table',7.5,26,1.8)
    obj(p,'weaver-storage','shelf',3,31.7,2.5)
    garden(p,'market-herbs',[13,31,20,35])
    for i,(x,y) in enumerate([(14.3,14.8),(19.3,14.8),(29,14.8),(33.5,25.5),(35,20.5)]):
        obj(p,'market-stock-'+str(i),'barrel' if i%2 else 'crate',x,y,.75,i*19)
    for i,(x,y) in enumerate([(12,3.3),(36,3.3),(12,26),(36,26)]):obj(p,'market-planter-'+str(i),'planter',x,y,.85)
    obj(p,'smith-reserve-water','barrel',46,9.2,.8)
    obj(p,'bakery-deliveries','crate',1.9,13,.7)
    path(p,'baker-approach',[[11,10],[12,12],[13,15]],1.6)
    path(p,'warehouse-approach',[[35,28],[37,28]],2)
    for i,(x,y) in enumerate([(12,7),(36,7),(12,29),(36,29)]):lamp(p,'market-lamp-'+str(i),x,y)
    obj(p,'market-bench','bench',17,28.7,3,90)
    return p


def civic():
    p=basic('civic','площадь ратуши',2)
    floor(p,'civic-cobbles',[13,4,35,19],STONE,2,'#c5c0ad')
    p['floors'][-1]['shape']=rect([12.7,3.7,35.3,19.3],feather=.35,roughness=.05)
    # The road terminates at the public steps instead of passing through the hall.
    p['layers'][0]['shape']['points']=[[24,-2],[24,8],[24,17.5]]
    building(p,'hall',[15,19,33,34],entry='n',name='Ратуша')
    wall(p,'hall-rear-divider',[15,28],[33,28],[door('hall-office-door',4,1.6),door('hall-archive-door',13,1.6)])
    wall(p,'hall-office-partition',[24,28],[24,34])
    table(p,'council-table',24,23.5,4,90)
    for i,x in enumerate([20.5,23,25.5,28]):obj(p,'hall-bench-'+str(i),'bench',x,25.5,1.7,90)
    table(p,'mayor-desk',19.5,31,2.4)
    obj(p,'mayor-book','book',19.5,31,.6,order=30,shadow=False)
    obj(p,'archive-shelf-a','shelf',25.1,31.7,2.8)
    obj(p,'archive-shelf-b','shelf',31.8,31.7,2.8)
    obj(p,'archive-book','book',28.5,30,.6,order=30,shadow=False)
    detail(p,'hall-runner','rectangle',bounds=[22.1,19.2,25.9,25.4],fill='#854c37',stroke='#c5a76c',width_cells=.06)
    for i in range(3):line(p,'hall-step-'+str(i),[[21.5,18.1+i*.27],[26.5,18.1+i*.27]],'#857864',.13)
    for i,x in enumerate([17,31]):obj(p,'hall-planter-'+str(i),'planter',x,18,.9)
    building(p,'inn',[0,6,11,21],entry='e',offset=8,name='Постоялый дом «Три ольхи»')
    for i,y in enumerate([9.5,15]):table(p,'inn-table-'+str(i),6.5,y,2.4,food=True)
    obj(p,'inn-counter','counter',2,17,3.2)
    obj(p,'inn-keg','keg',2.5,8,1.3)
    obj(p,'inn-stove','stove',2,11.5,1.1)
    obj(p,'civic-well','well',30.5,10,2.5,15)
    obj(p,'well-bucket','bucket',31.8,11,.5)
    p['foundry']['barriers'].append(dict(id='well-rim',closed=True,
        points=[[30.5+math.cos(i*math.pi/4),10+math.sin(i*math.pi/4)] for i in range(8)],
        move='normal',sight='none',light='none',sound='none'))
    location(p,'Колодец',30.5,10)
    p['locations'][-1]['access_position']=[28.3,10]
    building(p,'shrine',[38,5,48,16],entry='w',offset=7,name='Часовня Света')
    floor(p,'shrine-stone',[38,5,48,16],STONE,1.3,'#c6c3b7')
    obj(p,'shrine-altar','table',44,7.5,2.6,90)
    obj(p,'shrine-book','book',44,7.5,.65,order=30,shadow=False)
    for i,x in enumerate([40,43,46]):obj(p,'shrine-bench-'+str(i),'bench',x,11.5,1.9,90)
    building(p,'home-a',[0,27,10,36],entry='e',offset=4,name='Жилой дом')
    obj(p,'home-a-bed','bed',2.2,29.3,2.1,90);table(p,'home-a-table',6.5,32,1.8,food=True)
    garden(p,'civic-garden',[37,23,46,29])
    building(p,'home-b',[38,31,48,39],entry='n',offset=5,name='Дом у сада')
    obj(p,'home-b-table','table',43,34,2.2,90)
    for i,(x,y) in enumerate([(13,7),(35,7),(13.5,18),(34.5,18)]):lamp(p,'civic-lamp-'+str(i),x,y)
    for i,x in enumerate([16,20]):obj(p,'civic-bench-'+str(i),'bench',x,9,2,0)
    # Notice board represented with real timber and paper-like geometry, not baked labels.
    floor(p,'notice-board',[13,13,13.7,15],WOOD,.6)
    for i in range(3):detail(p,'notice-paper-'+str(i),'rectangle',bounds=[13.1,13.15+i*.5,13.55,13.5+i*.5],fill='#d5c49d')
    location(p,'Доска объявлений',13.5,14)
    for i,(x,y) in enumerate([(14,5),(34,5),(12,21.8),(36,17.5)]):obj(p,'civic-planter-'+str(i),'planter',x,y,.85)
    for i,(x,y) in enumerate([(2,19.4),(8.8,19.4),(25.5,33),(32,29)]):
        obj(p,'civic-storage-'+str(i),'crate',x,y,.7,20*i)
    path(p,'inn-approach',[[11,14],[13,14]],2)
    path(p,'shrine-approach',[[35,12],[38,12]],2)
    path(p,'garden-walk',[[35,22],[35,30],[43,30],[43,31]],1.2)
    return p


def connect(plans):
    for left,right in [('gate','market'),('market','civic')]:
        for key,other,south in [(left,right,True),(right,left,False)]:
            p=plans[key];side='south' if south else 'north';opposite='north' if south else 'south'
            p['foundry']['regions'].append(dict(id='exit-'+side,name='К '+('рынку' if other=='market' else 'воротам' if other=='gate' else 'ратуше'),
                shapes=[rect([21,34.8,27,36] if south else [21,0,27,1.2])],behaviors=[dict(type='teleportToken',choice=True,
                destination=dict(scene=other,region='arrival-'+opposite))]))
            p['foundry']['regions'].append(dict(id='arrival-'+side,name='Место прибытия',
                shapes=[rect([22,32.2,26,33.5] if south else [22,2.5,26,3.8])],behaviors=[]))


def npc_sources():
    templates=json.loads((ROOT/'foundry_builder/templates.json').read_text(encoding='utf-8-sig'))['templates']
    definitions=[
        ('guard','Страж Ольхового Брода',164,16,11,'2d8+2',[13,12,12,10,11,10],.125,
         'Дежурный на воротах. Проверяет груз и пропускает мирных путников; не начинает бой без причины. При тревоге зовёт капитана.',None),
        ('captain','Капитан Роланд Вейл',164,17,27,'5d8+5',[14,12,12,11,13,12],.25,
         'Старший караула. Говорит спокойно, записывает спорные пошлины в журнал. Хочет найти пропавшую повозку, не запугивая торговцев.',None),
        ('farmer','Йорен — возчик',102,10,9,'2d8',[12,10,10,10,11,10],0,
         'Привёз муку и сыр. Узнал на дороге свежие следы тяжёлого обоза, но опасается опоздать на рынок. При угрозе прячется за повозку.','gate'),
        ('baker','Марта — пекарь',95,10,9,'2d8',[10,10,10,11,12,12],0,
         'Торгует хлебом у пекарни. За недорогой ужин расскажет, кто приходил в деревню до рассвета. Защищает подмастерьев.','market'),
        ('trader','Элина — торговка',96,11,9,'2d8',[10,12,10,12,11,13],0,
         'Продаёт рыбу и посуду от речной артели. Знает, что складской замок вскрывали, но не хочет обвинять людей без доказательств.','market'),
        ('smith','Борен — кузнец',242,12,15,'2d8+6',[14,10,16,10,10,9],0,
         'Чинит инструменты и скобы для ворот. Вчера заметил на чужой подкове красную глину из старого карьера. В бою защищает дверь мастерской.','market'),
        ('mayor','Староста Адриан Холт',103,11,13,'3d8',[10,12,10,14,12,14],0,
         'Принимает жалобы в ратуше. Скрывает недостачу общих запасов, пока писарь сверяет книги. Предлагает работу без публичной огласки.','civic'),
        ('innkeeper','Вера — хозяйка «Трёх ольх»',95,10,9,'2d8',[10,10,10,11,13,12],0,
         'Держит постоялый дом. Запомнила гостя, который расплачивался свежими серебряными монетами и не снял перчаток.','civic'),
        ('scribe','Писарь Мартен',211,10,9,'2d8',[9,10,10,14,12,10],0,
         'Ведёт архив ратуши. Сопоставляет вес муки на воротах с накладными; обнаружил разные подписи одного возчика.','civic'),
    ]
    documents=[]
    for key,name,display,ac,hp,formula,abilities,cr,bio,scene in definitions:
        actor=copy.deepcopy(templates['npc']);actor.update(name=name,img='icons/svg/mystery-man.svg',items=[])
        s=actor['system'];s['attributes']['ac'].update(calc='flat',flat=ac,formula='')
        s['attributes']['hp'].update(value=hp,max=hp,formula=formula)
        s['attributes']['movement']['walk']=30
        s['details'].update(race='Человек',alignment='Нейтральный',cr=cr,
            type=dict(value='humanoid',subtype='человек',custom=''),
            biography=dict(value='<p>'+bio+'</p><p>Авторский NPC для кампании WoW. CR ориентировочный.</p>',public=''))
        s['traits']['languages'].update(value=['common'],custom='');s['traits']['size']='med'
        s['skills']={};s['resources']={}
        for ability,value in zip(['str','dex','con','int','wis','cha'],abilities):s['abilities'][ability]['value']=value
        actor['prototypeToken'].update(name=name,width=1,height=1,actorLink=key!='guard',disposition=1)
        actor['prototypeToken'].setdefault('sight',{}).update(enabled=True,range=0,visionMode='basic')
        icons={}
        if key in ('guard','captain'):
            spear=key=='guard';item=copy.deepcopy(templates['weapon'])
            label='Копьё' if spear else 'Длинный меч';identifier='village-spear' if spear else 'captain-sword'
            bonus=1 if spear else 2;die=6 if spear else 8;attack=3 if spear else 4;damage='piercing' if spear else 'slashing'
            item.update(name=label)
            item['system'].update(identifier=identifier,equipped=True,proficient=True,magicalBonus=0)
            item['system']['type'].update(value='simpleM' if spear else 'martialM',baseItem='spear' if spear else 'longsword')
            item['system']['damage']['base'].update(number=1,denomination=die,bonus=str(bonus),types=[damage])
            item['system']['range'].update(reach=5,units='ft')
            item['system']['description']['value']=f'<p>Действие. Рукопашная атака оружием: +{attack} к попаданию, досягаемость 5 фт., одно существо. Урон: 1d{die}+{bonus} '+('колющего' if spear else 'рубящего')+' урона. Здесь используется только одноручный рукопашный вариант.</p>'
            item['mechanics']=dict(attack=dict(ability='none',bonus=str(attack),flat=True,type='melee',classification='weapon'),
                damage=[dict(formula=f'1d{die}+{bonus}',type=damage)],range=dict(reach=5,units='ft',count=1,target_type='creature'),
                activation=dict(type='action',value=1))
            actor['items'].append(item);icons[identifier]='inv_spear_04' if spear else 'inv_sword_04'
        folder=ROOT/'requests/builder/sources/alderford';folder.mkdir(parents=True,exist_ok=True)
        source=folder/(key+'.json');source.write_text(json.dumps(actor,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        entry=dict(id=key,mode='npc',source=source.relative_to(ROOT).as_posix(),appearance=dict(display_id=display,size=384,portrait_size=640))
        if icons:entry['item_icons']=icons
        documents.append(entry)
    placements=[]
    def place(key,actor,scene,x,y,**fields):
        placements.append(dict(id=key,actor=actor,scene=scene,position=[x,y],**fields))
    for key,scene,x,y in [('gate-west','gate',22,13),('gate-east','gate',26,13),('gate-yard','gate',28.3,17),
        ('market-patrol','market',25.5,16.5),('hall-watch','civic',27.5,17)]:
        place(key,'guard',scene,x,y,actor_link=False)
    for key,scene,x,y in [('captain','gate',11.5,24),('farmer','gate',28.5,7.5),('baker','market',17,9),
        ('trader','market',31,9),('smith','market',40,9),('mayor','civic',19.5,32.5),
        ('innkeeper','civic',3.5,17),('scribe','civic',28.5,31)]:place(key,key,scene,x,y)
    # Additional shoppers share a sheet but have independent token state.
    for i,(x,y) in enumerate([(21,14),(26,24),(28,28)]):place('shopper-'+str(i),'farmer','market',x,y,actor_link=False,name='Житель деревни')
    return dict(format='foundry-builder.batch/1',documents=documents,placements=placements)


def main():
    plans={k:f() for k,f in [('gate',gate),('market',market),('civic',civic)]}
    connect(plans)
    for key,plan in plans.items():
        (ROOT/'examples'/('alderford-'+key+'.json')).write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    request=npc_sources()
    (ROOT/'requests/builder/alderford.json').write_text(json.dumps(request,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({key:dict(objects=len(p['objects']),walls=len(p['walls']),details=len(p['details'])) for key,p in plans.items()})


if __name__=='__main__':main()
