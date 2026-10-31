"""DEV2-R3 art pass using inspected original models and recovered materials.

Idempotent on the canonical DEV2-R2 plans. Topology and Region IDs are retained.
Solid props use measured M2 XY hulls; tree collisions use only the lower trunk.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wowmap.models import RawAssets,array_at,inspect_model

DW='world/azeroth/duskwood/passivedoodads/'
HUM='world/generic/human/passive doodads/'
COFFIN=DW+'coffin/coffin.m2';LID=DW+'coffinlid/coffinlid.m2'
SARC=HUM+'sarcophagi/sarcophagus.m2'
MONUMENT=DW+'tombs/tombstonemonument01.m2'
COLUMN='world/azeroth/theblastedlands/passivedoodads/column/blastedlandsbrokencolumn01.m2'
ALTAR=HUM+'altars/altar01.m2'
CANDLE=HUM+'candelabras/candelabratall01.m2'
TREE=DW+'trees/duskwoodtree05.m2'
GRASS=DW+'detail/duskwoodgrass01/duskwoodgrass01.m2'
BUSH=DW+'bush/duskwoodbush01.m2'
ROOTS='world/kalimdor/diremaul/passivedoodads/rubble/diremaultreeroot02.m2'
RUBBLE='world/azeroth/karazahn/passivedoodads/rubble/karazahnrockrubble01.m2'
RUNE='world/goober/g_scourgerunecirclecrystal.m2'
GEOMETRY={}

def hull(points):
    pts=sorted(set((round(x,6),round(y,6)) for x,y in points))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    low=[];high=[]
    for p in pts:
        while len(low)>=2 and cross(low[-2],low[-1],p)<=0:low.pop()
        low.append(p)
    for p in pts[::-1]:
        while len(high)>=2 and cross(high[-2],high[-1],p)<=0:high.pop()
        high.append(p)
    return low[:-1]+high[:-1]

def geometry(raw,model):
    if model not in GEOMETRY:
        data=raw.read(model);n,start=array_at(data,60,48)
        xyz=[struct.unpack_from('<3f',data,start+48*i) for i in range(n)]
        lo=[min(p[k] for p in xyz) for k in range(3)];hi=[max(p[k] for p in xyz) for k in range(3)]
        GEOMETRY[model]=(xyz,lo,hi)
    return GEOMETRY[model]

def barrier(raw,obj,key=None,tall=False,trunk=False):
    xyz,lo,hi=geometry(raw,obj['model']);span=max(hi[0]-lo[0],hi[1]-lo[1])
    pts=xyz if not trunk else [p for p in xyz if p[2]<=lo[2]+(hi[2]-lo[2])*.12]
    cx=(lo[0]+hi[0])/2;cy=(lo[1]+hi[1])/2
    scale=obj['size_cells']*obj.get('scale',1)/span
    a=math.radians(obj.get('rotation',0));c,s=math.cos(a),math.sin(a);x,y=obj['position']
    screen=[((p[0]-cx)*scale,-(p[1]-cy)*scale) for p in pts]
    outline=hull(screen)
    if len(outline)<3:raise ValueError('Degenerate collision hull: '+obj['model'])
    # Foundry stores integer pixel endpoints. Collapse subpixel hull edges before
    # export, so close source vertices cannot become zero-length native walls.
    points=hull([(round((x+px*c-py*s)*80)/80,round((y+px*s+py*c)*80)/80) for px,py in outline])
    if len(points)<3:raise ValueError('Subpixel collision hull: '+obj['model'])
    return dict(id=key or obj['id']+'-footprint',points=points,closed=True,
                sight='normal' if tall else 'none',light='normal' if tall else 'none',sound='none')

def prop(plan,key,model,xy,size,rotation=0,layer='props',order=15,role='decoration',raw=None,solid=False,tall=False,trunk=False):
    row=dict(id='r3-'+key,model=model,position=list(xy),position_anchor='bounds-center',size_cells=size,rotation=rotation,
             layer=layer,order=order,art_role=role,shadow=dict(opacity=.3,blur_cells=.075,offset_cells=[.10,.12]))
    if role=='ground_decal':row['shadow']=False
    plan['objects'].append(row)
    if solid:plan['foundry']['barriers'].append(barrier(raw,row,tall=tall,trunk=trunk))
    return row

def closed_lid(plan,parent,raw,key):
    _,a,b=geometry(raw,parent['model']);_,la,lb=geometry(raw,LID)
    size=parent['size_cells']*max(lb[0]-la[0],lb[1]-la[1])/max(b[0]-a[0],b[1]-a[1])
    prop(plan,key,LID,parent['position'],size,parent.get('rotation',0),order=parent.get('order',12)+1,role='coffin_lid')

def weather(plan,key,bounds,tint='#897a63',opacity=.33):
    a,b,c,d=bounds
    plan['floors'].append(dict(id='r3-'+key,asset='dungeons/textures/floor/mm_duskwood_stonefloor_01.blp',tile_cells=1.2,
                              tint=tint,opacity=opacity,shape=dict(type='polygon',points=[[a,b+.18],[c-.2,b],[c,d-.35],[c-.6,d],[a+.15,d-.2]],feather=.2,roughness=.23)))

def prepare(packages,database):
    plans={key:json.loads((ROOT/'examples'/('void-crypt-'+key+'.json')).read_text(encoding='utf-8')) for key in ('entrance','passages','sanctum')}
    for p in plans.values():
        for field in ('objects','floors','details'):
            p[field]=[r for r in p.get(field,[]) if not r['id'].startswith('r3-')]
        p['foundry']['barriers']=[r for r in p['foundry'].get('barriers',[]) if not r['id'].startswith('r3-')]
        p['art_revision']='DEV2-R3';p['art_notes']='Original WoW models; recovered Interface textures; passable loose lids and small debris; measured solid/trunk footprints.'
    with RawAssets(packages) as raw:
        p=plans['entrance'];p['navigation']=dict(base_walkable=True)
        p['details']=[r for r in p['details'] if r['id']!='memorial-plaque']
        p['foundry']['barriers']=[r for r in p['foundry']['barriers'] if not r['id'].startswith(('west-sarc-','east-bier-'))]
        for o in p['objects']:
            if o['id'] in ('west-sarc-0-stone','west-sarc-2-stone'):
                o.update(model=COFFIN,size_cells=2.2,position_anchor='bounds-center',art_role='coffin')
                if o['id']=='west-sarc-0-stone':closed_lid(p,o,raw,'west-closed-lid')
            if o['id'].endswith('-stone'):
                p['foundry']['barriers'].append(barrier(raw,o,key=o['id'].removesuffix('-stone')+'-footprint'))
        prop(p,'loose-west-lid',LID,[8.25,23.6],1.7,18,role='walkable_debris')
        prop(p,'memorial-altar',ALTAR,[16,20.5],3.4,0,role='altar',raw=raw,solid=True)
        for i,o in enumerate([o for o in p['objects'] if 'spooklesstrees/' in o['model'] or o.get('art_role')=='canopy']):
            o.update(model=TREE,size_cells=[6.5,7.0,6.2,7.0][i%4],rotation=[8,47,112,193][i%4],position_anchor='bounds-center',art_role='canopy')
            p['foundry']['barriers'].append(barrier(raw,o,key='r3-tree-trunk-'+str(i),tall=True,trunk=True))
        for i,xy in enumerate([[9,2.5],[31.5,8.5]]):prop(p,'extra-canopy-'+str(i),TREE,xy,5.6,75+i*91,layer='overhead',role='canopy',raw=raw,solid=True,tall=True,trunk=True)
        for i,xy in enumerate([[11.6,11],[28,11.2],[10.4,15.7],[29.6,15.9],[3,17],[37,20],[13,26.5],[27,27.5]]):prop(p,'bush-'+str(i),BUSH,xy,1.4+(i%3)*.15,i*43,role='vegetation')
        for i,xy in enumerate([[16,8],[24,8],[15.5,10],[24.5,10],[12,12],[28,12],[11,16],[29,16],[4.8,9],[7.5,10],[33,8],[35,12],[3,23],[37,26],[15,28],[25,28]]):prop(p,'dead-grass-'+str(i),GRASS,xy,.9+(i%3)*.15,i*37,layer='ground',role='vegetation')
        for i,xy in enumerate([[14.1,12.2],[25.7,16.4],[9.9,22.7],[30.4,24.3]]):prop(p,'roots-'+str(i),ROOTS,xy,2.2,25+i*63,role='walkable_debris')
        for i,xy in enumerate([[17.7,21.2],[22.3,21.2],[5,23.9],[34.8,18.3]]):prop(p,'candle-'+str(i),CANDLE,xy,.7,i*90,role='small_furnishing')
        for i,b in enumerate([[10,17.5,12.2,20],[27.4,22,29.9,24.6],[4.2,17.7,7.8,19],[30.2,21.5,35.8,24.3]]):weather(p,'floor-age-'+str(i),b)

        p=plans['passages']
        # Earlier corridor preparation wrote singular 'shape', ignored by export.
        # Normalize the intended updated zones to Foundry's actual shapes array.
        bounds={'arrival-from-entrance':[5,18,7,20],'to-entrance':[2.5,20.5,4.5,22.5],
                'arrival-from-sanctum':[64.5,19,66.5,21],'to-sanctum':[68,21,70,23]}
        for region in p['foundry']['regions']:
            region['shapes']=[dict(type='rectangle',bounds=bounds[region['id']])]
            region.pop('shape',None)
        network=json.loads((ROOT/'resources/void-crypt-corridors.json').read_text())
        selected={'north-memorial-burial','southern-crypt-burial','old-west-crypt-burial','collapsed-south-burial'}
        p['foundry']['barriers']=[r for r in p['foundry']['barriers'] if r['id'] not in {k+'-footprint' for k in selected}]
        for o in p['objects']:
            if o['id'] in selected:
                o.update(model=COFFIN,art_role='coffin')
                p['foundry']['barriers'].append(barrier(raw,o))
                closed_lid(p,o,raw,o['id']+'-lid')
            if 'rockwallrubble' in o['model'] and o['id'].endswith(('0','2','rubble')):o['model']=RUBBLE
        for i,room in enumerate(network['rooms']):
            if room['id'] in ('arrival','sanctum-approach'):continue
            a,b,c,d=room['bounds']
            if i%2==0:
                xy,rotation=([c-.55,d-1],90) if room['id']=='eastern-fork' else ([c-.95,d-.8],0)
                o=prop(p,room['id']+'-side-coffin',COFFIN,xy,1.4,rotation,role='coffin',raw=raw,solid=True)
                if i%4==0:closed_lid(p,o,raw,room['id']+'-side-lid')
                else:prop(p,room['id']+'-shifted-lid',LID,[c-1.1,d-1.5],1.1,27,role='walkable_debris')
            prop(p,room['id']+'-candle',CANDLE,[c-.45,b+.6],.55,i*90,role='small_furnishing')
            prop(p,room['id']+'-chips',RUBBLE,[a+.55,d-.7],.7,i*31,role='walkable_debris')
            if i in (2,8,12):prop(p,room['id']+'-memorial',MONUMENT,[a+.65,d-1.6],1.05,i*90,role='monument',raw=raw,solid=True)
            weather(p,room['id']+'-dust',[a+.15,b+.15,c-.25,b+1.3],tint='#81715b' if a<40 else '#716078',opacity=.27)
            if a>40:prop(p,room['id']+'-void-rune',RUNE,[c-1.25,b+1.0],.85,i*23,layer='ground',order=1,role='ground_decal')
        # Ground textures and stepped entrance geometry remain the traversal layer.
        p=plans['sanctum']
        p['details']=[r for r in p['details'] if not r['id'].startswith(('pillar-stone-','pillar-cap-','floor-masonry-chip-','scattered-void-pools-')) and r['id'] not in ('void-heart','original-ritual-circle')]
        p['foundry']['barriers']=[r for r in p['foundry']['barriers'] if not r['id'].startswith('pillar-collision-')]
        for i,xy in enumerate([[15.5,12],[26.5,12],[15.5,24],[26.5,24]]):prop(p,'ancestral-column-'+str(i),COLUMN,xy,1.7,i*45,role='pillar',raw=raw,solid=True,tall=True)
        prop(p,'void-ritual',RUNE,[21,18],6.3,0,layer='ground',order=2,role='ground_decal')
        for i,xy in enumerate([[13.1,10],[28.6,11.1],[13.0,26.5],[28.6,25.5]]):prop(p,'edge-memorial-'+str(i),MONUMENT,xy,1.25,i*37,role='monument',raw=raw,solid=True)
        for i in range(12):
            a=math.radians(i*30+10);xy=[21+11.3*math.cos(a),18+11.3*math.sin(a)]
            prop(p,'fallen-masonry-'+str(i),RUBBLE,xy,.65+(i%3)*.12,i*47,role='walkable_debris')
            if i%2==0:weather(p,'void-soil-'+str(i),[xy[0]-.7,xy[1]-.5,xy[0]+.7,xy[1]+.5],tint='#6d5181',opacity=.38)
        for i,xy in enumerate([[14,12],[28,12],[14,24],[28,24]]):prop(p,'ritual-candle-'+str(i),CANDLE,xy,.65,i*90,role='small_furnishing')
        for key,p in plans.items():
            (ROOT/'examples'/('void-crypt-'+key+'.json')).write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        wanted=set()
        from wowmap.render import resource_names
        for p in plans.values():
            wanted.update(resource_names(p))
            for o in p['objects']:
                info=inspect_model(raw,o['model']);wanted.update([o['model'],*info['required_skins'],*info['required_textures']])
        db=sqlite3.connect(database);packs={}
        for name in sorted(wanted):
            row=db.execute('SELECT r.package,p.drive_url FROM resources r JOIN packages p ON p.name=r.package WHERE r.path=?',(name,)).fetchone()
            if not row:raise ValueError('Resource absent from updated inventory: '+name)
            packs.setdefault(row[0],dict(file=row[0],url=row[1],resources=[]))['resources'].append(name)
        manifest=dict(format='wowmap.scene-assets/1',revision='DEV2-R3',packages=list(packs.values()))
        (ROOT/'resources/void-crypt-r3-assets.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(scenes={k:len(p['objects']) for k,p in plans.items()},packages=sorted(packs))))
    return plans

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages',required=True);ap.add_argument('--database',required=True);a=ap.parse_args()
    prepare(a.packages,a.database)
