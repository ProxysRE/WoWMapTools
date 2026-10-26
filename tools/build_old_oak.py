"""Author the Old Oak inn plans using only WoWMapTools primitives and WotLK assets.

Run from the repository root. The generator needs no game files; rendering does.
"""
import copy
import json
from pathlib import Path

H='world/generic/human/passive doodads/'
P='world/generic/passivedoodads/'
A={
 'table':H+'tables/inntable.m2','diningtable':H+'tables/duskwoodtable01.m2',
 'chair':H+'chairs/generalchairloend01.m2','bench':H+'benches/duskwoodbench.m2',
 'bed':H+'beds/duskwoodbed.m2','shelf':H+'bookshelves/abbeyshelf01.m2','shelf2':H+'bookshelves/duskwoodbookshelf01.m2',
 'counter':H+'shopcounter/duskwoodshopcounter.m2','keg':H+'beerkegs/beerkeg01.m2','keg2':H+'beerkegs/beerkeg02.m2',
 'barrel':P+'barrel/barrel01.m2','crate':P+'crate01/crate01.m2','bucket':H+'buckets/bucket.m2',
 'mug':H+'mugs/mug01.m2','stein':H+'mugs/stein01.m2','plate':H+'plates/generaldirtyplate01.m2',
 'bread':H+'food/breadloaf01.m2','cheese':H+'food/cheesewedge01.m2','fish':H+'food/fishplatter01.m2',
 'book':H+'books/booklargeopen01.m2','candle':P+'lights/candleoff01.m2','stove':H+'stoves/potbellystove.m2',
 'cauldron':H+'cauldrons/cauldronempty.m2','rug':H+'rugs/karazahnrugred.m2','ruggreen':H+'rugs/karazahnruggreen.m2',
 'bearrug':H+'rugs/generalbearskinrug01.m2','stairs':H+'woodenstairs/woodenstairs01.m2',
 'logs':H+'firewood/firewoodpile03.m2','flowers':H+'flowers/flowersbunch03.m2','planter':H+'planterboxes/stormwindplanter.m2',
 'well':P+'well/well.m2',
 'hay':'world/azeroth/elwynn/passivedoodads/haystacks/haystack01.m2',
 'tree1':'world/kalimdor/ashenvale/passivedoodads/ashenvaletrees/ashenvaletree01.m2',
 'tree2':'world/kalimdor/ashenvale/passivedoodads/ashenvaletrees/ashenvaletree02.m2',
}
WOOD='dungeons/textures/floor/mm_inn_wood floor_01.blp'
STONE='dungeons/textures/floor/mm_duskwood_stonefloor_01.blp'
KITCHEN='dungeons/textures/floor/bm_shdwfang_kchnflr_01.blp'
WALL='dungeons/textures/blackfathom/bm_bf_stonewall01.blp'
GRASS='tileset/ashenvale/ashenvalemossbase.blp'
DIRT='tileset/ashenvale/ashenvaledirt.blp'
ROAD='tileset/ashenvale/ashenvaleroad.blp'
ROOMS={}


def rect(bounds,**kw): return dict(type='rectangle',bounds=bounds,**kw)


def obj(plan,key,kind,x,y,size,rot=0,order=10,shadow=True):
    o=dict(id=key,model=A.get(kind,kind),position=[x,y],position_anchor='bounds-center',size_cells=size,rotation=rot,order=order,layer='props')
    if shadow:o['shadow']=dict(opacity=.24,blur_cells=.055,offset_cells=[.05,.075])
    plan['objects'].append(o);return o


def detail(plan,key,kind,**kw):plan['details'].append(dict(id=key,type=kind,**kw))


def line(plan,key,pts,color='#4a3424',width=.055,opacity=1):detail(plan,key,'line',points=pts,stroke=color,width_cells=width,opacity=opacity)


def floor(plan,key,bounds,asset=WOOD,tile=1.05,tint=None):
    f=dict(id=key,asset=asset,tile_cells=tile,texture_variation=.07,shape=rect(bounds,feather=0))
    if tint:f['tint']=tint
    plan['floors'].append(f)


def wall(plan,key,a,b,openings=(),outer=False):
    w=dict(id=key,points=[a,b],asset=WALL if outer else WOOD,thickness=.42 if outer else .23,tile_cells=.85,openings=list(openings))
    plan['walls'].append(w)


def opening(key,at,width=1.3,kind='door',state='closed'):return dict(id=key,at=at,width=width,type=kind,state=state,asset=WOOD)


def lamp(plan,key,x,y,bright=2,dim=5):
    plan['foundry']['lights'].append(dict(id=key,position=[x,y],bright=bright,dim=dim,color='#ffd49a',alpha=.24))


def candle(plan,key,x,y,light=False):
    obj(plan,key,'candle',x,y,.22,order=30,shadow=False)
    if light:lamp(plan,key+'-light',x,y,1.5,4)


def place_setting(plan,key,x,y,rotation=0):
    obj(plan,key+'-plate','plate',x,y,.32,rotation,order=24,shadow=False)
    obj(plan,key+'-mug','mug',x+.27,y+.08,.19,rotation+25,order=26,shadow=False)


def table(plan,key,x,y,size=2.7,rot=90,seats=4,served=True):
    # Table is 0.72*size wide and size long in its unrotated pose.
    obj(plan,key,'table',x,y,size,rot,order=15)
    if rot==90:
        for j,dx in enumerate([-.68,.68]):
            obj(plan,key+f'-north-{j}','chair',x+dx,y-1.08,.64,90,order=12)
            obj(plan,key+f'-south-{j}','chair',x+dx,y+1.08,.64,270,order=12)
            if served:
                place_setting(plan,key+f'-n{j}',x+dx,y-.55)
                place_setting(plan,key+f'-s{j}',x+dx,y+.55,180)
    else:
        for j,dy in enumerate([-.68,.68]):
            obj(plan,key+f'-west-{j}','chair',x-1.05,y+dy,.64,0,order=12)
            obj(plan,key+f'-east-{j}','chair',x+1.05,y+dy,.64,180,order=12)
            if served:
                place_setting(plan,key+f'-w{j}',x-.55,y+dy)
                place_setting(plan,key+f'-e{j}',x+.55,y+dy,180)
    candle(plan,key+'-candle',x,y,light=True)
    if served:
        obj(plan,key+'-bread','bread',x-.3,y,.36,12,order=24,shadow=False)
        obj(plan,key+'-cheese','cheese',x+.32,y,.27,-15,order=24,shadow=False)


def exterior(plan,upper=False):
    plan['layers']=[dict(id='road',asset=ROAD,tile_cells=1.7,shape=dict(type='path',points=[[0,28],[12,27.1],[25,27.5],[36,29]],width=4.2,smooth=True,feather=.65,roughness=.18)),
      dict(id='front-yard',asset=DIRT,tile_cells=3,shape=dict(type='ellipse',bounds=[3,20,31,28],feather=1,roughness=.16)),
      dict(id='delivery-path',asset=DIRT,tile_cells=2.5,shape=dict(type='path',points=[[34,28],[32,20],[32,9],[29,8.5]],width=2.3,smooth=True,feather=.6,roughness=.14)),
      dict(id='rear-garden',asset=DIRT,tile_cells=2,shape=rect([6,1.5,19,3.8],feather=.6,roughness=.14))]
    floor(plan,'foundation',[5.6,4.6,29.4,24.4],STONE,.9,'#c5bdac')
    floor(plan,'interior',[6,5,29,24],WOOD,1.15,'#e4caa5')
    floor(plan,'porch',[10.5,24,16,26],WOOD,1.05,'#c9b599')
    for y in [24.1,25.7]:line(plan,'porch-beam-'+str(y),[[10.6,y],[15.9,y]],'#5c4431',.11)
    for x in [10.8,15.7]:
        detail(plan,'porch-post-'+str(x),'rectangle',bounds=[x-.15,24.4,x+.15,24.7],fill='#493525',stroke='#241d16',width_cells=.04)
    for i in range(3):line(plan,'porch-step-'+str(i),[[10.55,26+i*.16],[16,26+i*.16]],'#89745a',.11)
    # Crops, a service yard and stacked deliveries connect the back entrance to the road.
    for row in range(3):
        line(plan,'garden-furrow-'+str(row),[[7,1.9+row*.55],[17.5,1.9+row*.55]],'#55462d',.22,.85)
        for col in range(12):
            x=7.2+col*.85;y=1.9+row*.55
            detail(plan,f'herb-{row}-{col}','ellipse',bounds=[x-.11,y-.1,x+.11,y+.1],fill='#647151',stroke='#455338',width_cells=.025)
    for i,(x,y,kind,size) in enumerate([(30.5,10.4,'crate',.95),(31.65,10.5,'crate',.8),(31.3,11.5,'barrel',.85),(30.3,12,'barrel',.7),(33.3,16.3,'hay',1.6)]):obj(plan,'yard-'+str(i),kind,x,y,size,10*i)
    # Well made as a stone-lined water basin; no missing model substituted silently.
    floor(plan,'well-apron',[30,18,33.5,21.5],STONE,.8)
    obj(plan,'well','well',31.75,19.75,2.15,15,order=15)
    import math
    plan['foundry']['barriers'].append(dict(id='well-rim',closed=True,points=[[31.75+math.cos(i*math.pi/4)*.95,19.75+math.sin(i*math.pi/4)*.95] for i in range(8)],move='normal',sight='none',light='none',sound='none'))
    obj(plan,'well-bucket','bucket',32.8,20.9,.48)
    for i,(x,y,size,model) in enumerate([(2.6,3.5,5.7,'tree1'),(3.4,13.3,5.5,'tree2'),(35,1.6,4.3,'tree1'),(1.8,22.5,5.2,'tree1'),(34.2,23,4.2,'tree2')]):
        tree=obj(plan,'oak-'+str(i),model,x,y,size,i*57,order=80);tree['layer']='overhead'
    # Two seats by the entrance, away from the double door.
    for i,x in enumerate([8.1,18.7]):obj(plan,'porch-bench-'+str(i),'bench',x,24.9,2.1,90)
    for i,x in enumerate([10,16.6]):
        obj(plan,'entrance-planter-'+str(i),'planter',x,24.8,.78,order=16)
    # A detached two-stall privy, reached from the delivery yard rather than through the kitchen.
    floor(plan,'privy-floor',[30.6,3.5,34.5,6.5],WOOD,.85,'#b7a286')
    wall(plan,'privy-north',[30.6,3.5],[34.5,3.5])
    wall(plan,'privy-west',[30.6,3.5],[30.6,6.5])
    wall(plan,'privy-east',[34.5,3.5],[34.5,6.5])
    wall(plan,'privy-divider',[32.55,3.5],[32.55,6.5])
    wall(plan,'privy-south',[30.6,6.5],[34.5,6.5],[opening('privy-door-a',.95,1),opening('privy-door-b',2.9,1)])
    for i,x in enumerate([31.55,33.5]):
        detail(plan,'privy-seat-'+str(i),'rectangle',bounds=[x-.48,3.9,x+.48,4.55],fill='#72573c',stroke='#352b20',width_cells=.06)
        detail(plan,'privy-hole-'+str(i),'ellipse',bounds=[x-.2,4.02,x+.2,4.4],fill='#24201a')
    plan['layers'].append(dict(id='privy-path',asset=DIRT,tile_cells=2,shape=dict(type='path',points=[[33.5,6.7],[33.5,8],[32,9]],width=.9,feather=.2,smooth=True)))
    for i,y in enumerate([12.8,13.9,15]):obj(plan,'yard-wood-stack-'+str(i),'logs',30.1,y,1.05,90,order=13)

    # Raised vegetable garden fence, never across the service route.
    for i,(a,b) in enumerate([([5.8,1.2],[19.2,1.2]),([5.8,1.2],[5.8,3.6]),([19.2,1.2],[19.2,3.6])]):
        line(plan,'garden-fence-'+str(i),[a,b],'#715e44',.13)


def shell(plan,upper=False):
    wall(plan,'exterior-north',[6,5],[29,5],[opening('north-window-1',3,1.8,'window'),opening('north-window-2',8.5,1.8,'window'),opening('north-window-3',16.5,1.7,'window')],True)
    wall(plan,'exterior-east',[29,5],[29,24],[opening('delivery-door',3.7,1.5) if not upper else opening('east-window-1',3.7,1.5,'window'),opening('east-window-2',9.1,1.4,'window'),opening('east-window-3',15.4,1.7,'window')],True)
    wall(plan,'exterior-south',[6,24],[29,24],([opening('front-double-door',7.3,2.2,state='open')] if not upper else [])+[opening('south-window-1',2.2,1.6,'window'),opening('south-window-2',12.8,1.6,'window'),opening('south-window-3',17.1,1.6,'window')],True)
    wall(plan,'exterior-west',[6,5],[6,24],[opening('west-window-1',2.5,1.8,'window'),opening('west-window-2',8,1.8,'window'),opening('west-window-3',13.5,1.8,'window')],True)
    # Shared masonry chimney footprints, identical on both levels.
    for key,x in [('hall',17.7),('kitchen',27.3)]:
        floor(plan,key+'-hearth-stone',[x-1.2,5.25,x+1.2,7.6] if not upper else [x-.75,5.1,x+.75,6],STONE,.7)
        if upper:
            detail(plan,key+'-chimney-shaft','rectangle',bounds=[x-.65,5.1,x+.65,5.9],fill='#746c5a',stroke='#373229',width_cells=.08)
            continue
        detail(plan,key+'-firebox','rectangle',bounds=[x-.8,5.32,x+.8,6.05],fill='#211b17',stroke='#746351',width_cells=.12)
        for i in range(3):
            line(plan,key+'-log-'+str(i),[[x-.55,5.53+i*.13],[x+.5,5.58+i*.13]],'#70503a',.1)
        if not upper:
            for i in range(7):
                detail(plan,key+'-coal-'+str(i),'ellipse',bounds=[x-.45+i*.13,5.57,x-.36+i*.13,5.69],fill='#c66d32',opacity=.7)
            lamp(plan,key+'-fire',x,6.1,3,7)
    # Corner posts and timber supports distinguish the cut walls from floors.
    for i,(x,y) in enumerate([(6,5),(29,5),(6,24),(29,24),(14,10),(21,12),(21,17)]):
        detail(plan,'post-'+str(i),'rectangle',bounds=[x-.22,y-.22,x+.22,y+.22],fill='#453225',stroke='#251c17',width_cells=.045)


def stairs(plan,upper=False):
    floor(plan,'stairwell',[25.5,18,28.3,22.7],STONE,.8,'#77736a')
    # Two flights of the same asset form a readable straight stair, same XY on both levels.
    obj(plan,'stairs-lower','stairs',26.9,21.4,2.7,0,order=16)
    obj(plan,'stairs-upper','stairs',26.9,19.25,2.7,0,order=17)
    line(plan,'stair-handrail-west',[[25.75,18],[25.75,22.6]],'#6a5036',.11)
    line(plan,'stair-handrail-east',[[28.07,18],[28.07,22.6]],'#6a5036',.11)
    # The same move-only barriers appear on both floors; arrivals land outside the flights.
    for i,x in enumerate([25.65,28.2]):
        plan['foundry']['barriers'].append(dict(id='stairs-rail-'+str(i),points=[[x,18.4],[x,22.7]],move='normal',sight='none',light='none',sound='none'))
    source=rect([25.95,17.2,27.85,18.35]) if upper else rect([25.95,22.7,27.85,23.65])
    plan['foundry']['regions'].append(dict(id='stairs-down' if upper else 'stairs-up',name='Лестница вниз' if upper else 'Лестница наверх',shapes=[source],
      behaviors=[dict(type='teleportToken',choice=True,destination=dict(scene='ground' if upper else 'upper',region='stairs-up' if upper else 'stairs-down'))]))
    lamp(plan,'stairs-lamp',24.7,20.5,2.5,5)


def basic(upper=False):
    p=dict(format='wowmap.scene/1',name='«Старый дуб» — '+('гостевые комнаты' if upper else 'таверна'),seed=6041+int(upper),size_cells=[36,30],pixels_per_cell=96,
      distance_per_cell=5,units='ft',export_format='webp',surface_variation=.06,
      base=dict(id='base',asset=GRASS,tile_cells=3,texture_variation=.16,tint='#c2cfba'),layers=[],floors=[],walls=[],objects=[],details=[],
      architecture=dict(outline_cells=.035,shadow_cells=.2,shadow_opacity=.48),
      foundry=dict(key='upper' if upper else 'ground',darkness=.18,global_light=True,grid_alpha=.12,lights=[],regions=[],barriers=[]))
    exterior(p,upper);shell(p,upper);stairs(p,upper)
    p['foundry']['regions'].append(dict(id='inside',name='Под крышей',shapes=[rect([6,5,29,24])],behaviors=[dict(type='suppressWeather')]))
    return p


def ground():
    p=basic()
    floor(p,'kitchen',[21,5,29,12],KITCHEN,1.05,'#e2d3bd')
    floor(p,'pantry',[25,12,29,17],STONE,.95,'#c3b6a0')
    # Private parlour, kitchen, pantry and stair hall have genuine connecting doors.
    wall(p,'parlour-south',[6,10],[14,10],[opening('parlour-entry',5.8,1.5,state='open')])
    wall(p,'parlour-east',[14,5],[14,10],[opening('parlour-service',3.4,1.1)])
    wall(p,'kitchen-west',[21,5],[21,12],[opening('kitchen-hall',4.5,1.25)])
    wall(p,'kitchen-south',[21,12],[29,12],[opening('kitchen-bar',2.15,1.35,state='open')])
    wall(p,'pantry-west',[25,12],[25,17],[opening('pantry-door',2.5,1.2)])
    wall(p,'service-south',[21,17],[29,17],[opening('service-stairs',2.05,1.15)])
    wall(p,'stairs-west',[21,17],[21,24],[opening('guest-stairs-door',4.4,1.55,state='open')])
    # Counter has a working lane behind it, and does not masquerade as an opaque wall.
    for i,y in enumerate([13.35,15.75]):obj(p,'bar-counter-'+str(i),'counter',20.75,y,2.45,order=16)
    p['foundry']['barriers'].append(dict(id='bar-counter',points=[[20.75,12.15],[20.75,16.95]],move='normal',sight='none',light='none',sound='none'))
    for i,y in enumerate([13,14.25,15.5,16.6]):obj(p,'bar-stool-'+str(i),'chair',19.65,y,.6,0)
    for i,(x,y) in enumerate([(24.2,12.95),(24.2,16.1),(22.1,16.1)]):obj(p,'tap-keg-'+str(i),'keg2',x,y,.83,90,order=15)
    for i,y in enumerate([12.8,13.6,15,16.15]):obj(p,'bar-mug-'+str(i),'stein',20.72,y,.22,i*30,order=30,shadow=False)
    obj(p,'bar-ledger','book',20.7,16.5,.48,90,order=31,shadow=False)
    candle(p,'bar-candle',20.8,14.65,True)
    # Common-room tables are grouped around a clear north/south route from the entrance.
    obj(p,'main-rug','rug',13.25,17.35,7.7,90,order=-8,shadow=False)
    for key,x,y in [('west-1',9.3,13.1),('west-2',9.3,18.1),('east-1',16.6,12.6),('east-2',16.6,18.2)]:table(p,key,x,y,2.65)
    # Long shared table near the hearth with benches, distinct from the four-seat tables.
    obj(p,'shared-table','diningtable',17.3,8.6,3.8,90,order=15)
    for key,y in [('north',7.28),('south',9.9)]:obj(p,'shared-bench-'+key,'bench',17.3,y,3.9,90,order=12)
    for i,x in enumerate([15.9,16.8,17.7,18.6]):
        place_setting(p,'shared-n-'+str(i),x,8.08)
        place_setting(p,'shared-s-'+str(i),x,9.12,180)
    obj(p,'shared-fish','fish',17.2,8.6,.8,90,order=27,shadow=False)
    # Parlour seats a merchant party away from the traffic and the kitchen.
    obj(p,'parlour-rug','ruggreen',10,7.45,6.3,order=-8,shadow=False)
    table(p,'parlour-table',10,7.45,2.7,served=True)
    obj(p,'parlour-sideboard','shelf',7.75,5.7,2.4,order=13)
    obj(p,'parlour-book','book',7.7,5.7,.5,15,order=27,shadow=False)
    obj(p,'parlour-flowers','flowers',10.1,7.45,.45,30,order=32,shadow=False)
    # A wall-side booth gives the south-west corner a purpose without blocking the entry aisle.
    obj(p,'south-booth-table','diningtable',9,22,2.5,90,order=15)
    obj(p,'south-booth-bench','bench',9,23.05,2.8,90,order=12)
    for i,x in enumerate([8.4,9.6]):
        obj(p,'south-booth-chair-'+str(i),'chair',x,20.95,.62,90)
        place_setting(p,'south-booth-setting-'+str(i),x,21.5)
    candle(p,'south-booth-candle',9,22,True)
    # Mantel and firewood make the common hearth readable in top view.
    line(p,'hall-mantel',[[16.7,6.1],[18.7,6.1]],'#907452',.13)
    obj(p,'hall-firewood','logs',19.5,6.45,1.05,20)
    obj(p,'kitchen-firewood','logs',26.15,7.3,.85,-20)

    # Kitchen: hot work against the north chimney, prep in centre, washing at east.
    obj(p,'kitchen-stove','stove',27.1,6.65,1.6,90,order=14)
    obj(p,'kitchen-pot','cauldron',27.1,6.7,.68,order=28)
    obj(p,'prep-table','diningtable',24.1,8.45,2.7,90,order=15)
    for i,(kind,x,y,size) in enumerate([('bread',23.4,8.2,.55),('cheese',24.25,8.4,.4),('fish',24.9,8.55,.7),('plate',23.55,8.85,.38)]):obj(p,'prep-'+str(i),kind,x,y,size,20*i,order=27,shadow=False)
    obj(p,'wash-bench','counter',28.15,10.7,2.0,order=14)
    for i,y in enumerate([10.3,11.1]):obj(p,'washing-bucket-'+str(i),'bucket',28.1,y,.58,order=25)
    obj(p,'kitchen-shelf','shelf',23.2,5.65,2.8,order=14)
    for i,x in enumerate([22.3,23,23.7,24.2]):obj(p,'kitchen-shelf-dish-'+str(i),'plate',x,5.7,.35,order=25,shadow=False)
    lamp(p,'kitchen-lamp',24.3,10.6,3,6)
    # Store supplies along the walls; leave a full two-cell central aisle.
    for i,y in enumerate([12.85,14.1,15.45]):obj(p,'pantry-crate-'+str(i),'crate',28.15,y,.95,i*90)
    for i,y in enumerate([12.95,16.05]):obj(p,'pantry-barrel-'+str(i),'barrel',25.85,y,.73,i*25)
    obj(p,'pantry-top-shelf','shelf',27,12.6,1.6,order=14)
    obj(p,'pantry-bottom-shelf','shelf',27.3,16.5,2.1,order=14)
    obj(p,'pantry-cheese','cheese',27.1,16.5,.42,order=26,shadow=False)
    lamp(p,'pantry-lamp',27.1,14.4,1.5,3)
    # Reception at the foot of the stairs; a guest can go upstairs without crossing the bar.
    obj(p,'reception-desk','table',23.2,18.8,1.85,90,order=15)
    obj(p,'reception-chair','chair',23.2,17.8,.63,90)
    obj(p,'guest-register','book',23,18.8,.62,5,order=28,shadow=False)
    candle(p,'reception-candle',23.7,18.8,True)
    obj(p,'entry-mat','ruggreen',13.3,22.75,3.2,order=-9,shadow=False)
    obj(p,'stairs-mat','rug',23.8,21.8,3,90,order=-9,shadow=False)
    lamp(p,'entrance-light',13.3,24.8,2.5,5)
    ROOMS['ground']=[('Общий зал',[6,10,21,24]),('Тихая гостиная',[6,5,14,10]),('Кухня',[21,5,29,12]),('Кладовая',[25,12,29,17]),('Стойка и рабочий проход',[20,12,25,17]),('Приёмная и лестница',[21,17,29,24])]
    return p


def guest_room(p,key,bounds,beds=2,luxury=False):
    a,b,c,d=bounds;cx=(a+c)/2
    floor(p,key+'-floor',[a+.15,b+.15,c-.15,d-.15],WOOD,1.1,'#d9c0a0')
    obj(p,key+'-rug','ruggreen' if luxury else 'rug',cx,(b+d)/2,3.4 if luxury else 2.9,90,order=-8,shadow=False)
    # Beds run north/south, with headboards towards the north wall and clear access on the inside.
    for i,x in enumerate([a+1.25,c-1.25] if beds==2 else [cx]):
        obj(p,key+'-bed-'+str(i),'bed',x,b+2.5,2.05,90,order=12)
        obj(p,key+'-bedside-'+str(i),'crate',x+(1 if i==0 else -1),b+1.5,.55,order=13)
        candle(p,key+'-bed-candle-'+str(i),x+(1 if i==0 else -1),b+1.5)
    obj(p,key+'-writing-table','table',c-1.5,d-1.7,1.65,90,order=14)
    obj(p,key+'-writing-chair','chair',c-1.5,d-2.65,.61,90)
    obj(p,key+'-book','book',c-1.6,d-1.7,.46,order=28,shadow=False)
    obj(p,key+'-washstand','shelf',a+1.4,d-1.3,1.5,order=15)
    obj(p,key+'-basin','bucket',a+1.3,d-1.3,.45,order=28,shadow=False)
    # A closed chest is represented with the same verified storage crate model, not an unsupported chest.
    obj(p,key+'-luggage','crate',a+.75,b+4.2,.82,order=12)
    lamp(p,key+'-lamp',cx,(b+d)/2,2.8,5)
    obj(p,key+'-flowers','flowers',c-1.25,d-1.72,.36,25,order=32,shadow=False)
    if luxury:
        obj(p,key+'-armchair','chair',a+1.5,b+3.8,.8,30)
        obj(p,key+'-extra-table','table',a+1.5,b+5,1.15,order=15)
        obj(p,key+'-extra-mug','stein',a+1.5,b+5,.22,order=28,shadow=False)



def upper():
    p=basic(True)
    # The north wing sits above the parlour/kitchen; service shafts remain aligned.
    floor(p,'corridor',[6,13,29,16],WOOD,1,'#d2b894')
    wall(p,'north-corridor',[6,13],[29,13],[opening('room-a-door',3.1),opening('room-b-door',7.0),opening('room-c-door',14.2),opening('room-d-door',20.4)])
    for i,x in enumerate([11.7,16.2,23]):wall(p,'north-room-divider-'+str(i),[x,5],[x,13])
    wall(p,'south-corridor',[6,16],[29,16],[opening('dorm-door',3.4,1.4),opening('owners-door',11,1.25),opening('upper-stair-door',17.8,1.5,state='open')])
    wall(p,'south-divider-1',[13.5,16],[13.5,24])
    wall(p,'south-divider-2',[21,16],[21,24])
    guest_room(p,'room-a',[6,5,11.7,13],2)
    guest_room(p,'room-b',[11.7,5,16.2,13],1)
    # The narrow room is deliberately single occupancy; keep a continuous west-side aisle.
    for item in p['objects']:
        if item['id']=='room-b-washstand':item.update(position=[12.35,6.2],size_cells=1.0,rotation=90)
        elif item['id']=='room-b-basin':item['position']=[12.35,6.2]
        elif item['id']=='room-b-luggage':item.update(position=[15.55,9.05],size_cells=.65)

    guest_room(p,'room-c',[16.2,5,23,13],1,True)
    guest_room(p,'room-d',[23,5,29,13],2)
    # Move writing furniture away from the aligned masonry chimney footprints.
    # Room C and D fireplaces occupy the same north-wall position as downstairs.
    # Four individual beds form the affordable dorm, with a wide middle aisle.
    obj(p,'dorm-rug','rug',9.75,20,4.5,90,order=-8,shadow=False)
    for i,(x,y) in enumerate([(7.25,18.3),(12.1,18.3),(7.25,21.8),(12.1,21.8)]):
        obj(p,'dorm-bed-'+str(i),'bed',x,y,2.0,90,order=12)
        obj(p,'dorm-locker-'+str(i),'crate',x,y+1.35,.62,order=13)
    obj(p,'dorm-washstand','shelf',9.8,23.25,1.7,order=14)
    obj(p,'dorm-basin','bucket',9.7,23.2,.5,order=27)
    lamp(p,'dorm-light',9.8,20.3,3,6)
    # Owner's suite sits beside the stair, so access to guests does not cross a bedroom.
    obj(p,'owner-rug','ruggreen',17.25,20.3,4.9,90,order=-8,shadow=False)
    obj(p,'owner-bed','bed',15.2,22.25,2.3,90)
    obj(p,'owner-desk','table',18.6,18.1,2.0,90,order=14)
    obj(p,'owner-chair','chair',18.6,19.2,.65,270)
    obj(p,'owner-ledger','book',18.35,18.1,.55,order=28,shadow=False)
    obj(p,'owner-shelf','shelf2',20.35,21.4,2.5,order=14)
    obj(p,'owner-luggage','crate',18.5,23.2,.85)
    candle(p,'owner-candle',19.2,18.1,True)
    lamp(p,'owner-lamp',17,20.5,3,6)
    # Linen cupboard by the landing, away from the top of the flight.
    obj(p,'linen-shelf','shelf2',21.7,20.6,2.6,order=14)
    obj(p,'linen-crate-1','crate',23.5,22.8,.85)
    obj(p,'linen-crate-2','crate',24.5,22.8,.75)
    for i,y in enumerate([19.85,20.55,21.2]):
        detail(p,'folded-linen-'+str(i),'rectangle',bounds=[21.48,y-.2,21.95,y+.2],fill='#c7bda4',stroke='#91846e',width_cells=.035)
        line(p,'linen-fold-'+str(i),[[21.55,y],[21.9,y]],'#a89b83',.025)

    obj(p,'landing-bench','bench',23.2,18.2,1.9,90)
    for i,x in enumerate([8.8,14.4,20,25.5]):
        obj(p,'hall-runner-'+str(i),'rug',x,14.5,5.4,order=-8,shadow=False)
        lamp(p,'corridor-lamp-'+str(i),x,14.5,2,4)
    ROOMS['upper']=[('Комната 1 — два гостя',[6,5,11.7,13]),('Комната 2 — отдельная',[11.7,5,16.2,13]),('Комната 3 — отдельная',[16.2,5,23,13]),('Комната 4 — два гостя',[23,5,29,13]),('Общая спальня — четыре места',[6,16,13.5,24]),('Комната хозяина',[13.5,16,21,24]),('Лестница и бельевая',[21,16,29,24])]
    return p


def main():
    for key,plan in [('ground',ground()),('upper',upper())]:
        path=Path('examples')/('old-oak-'+key+'.json')
        path.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(path, 'objects',len(plan['objects']),'walls',len(plan['walls']))
    Path('examples/old-oak-rooms.json').write_text(json.dumps(ROOMS,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
