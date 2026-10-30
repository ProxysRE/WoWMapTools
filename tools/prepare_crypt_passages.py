"""Author the DEV2 maze from its explicit corridor network; no random topology."""
import copy
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wowmap.corridors import compile_network


def build():
    path=ROOT/'examples/void-crypt-passages.json';plan=json.loads(path.read_text(encoding='utf-8'))
    network=json.loads((ROOT/'resources/void-crypt-corridors.json').read_text(encoding='utf-8'))
    floors,walls,metrics=compile_network(network,[72,40])
    plan.update(name='Крипта Бездны — лабиринт погребальных ходов',floors=floors,walls=walls,objects=[],details=[],layers=[],burials=[])
    plan['corridor_design']=dict(source='resources/void-crypt-corridors.json',metrics=metrics)
    sarc='world/generic/human/passive doodads/sarcophagi/sarcophagus.m2'
    rubble='world/azeroth/duskwood/passivedoodads/fence/rockwallrubble.m2'
    markers='world/azeroth/duskwood/passivedoodads/tombs/'
    plan['foundry']['barriers']=[]
    for key,x,y in [('old-crypt-door',11.5,8),('east-crypt-door',65.5,32)]:
        plan['walls'].append(dict(id=key,points=[[x-1,y],[x+1,y]],thickness=.22,asset=network['wall_asset'],openings=[dict(id=key+'-leaf',type='door',at=1,width=2,state='open',asset=network['wall_asset'])]))
    def prop(key,model,xy,size,rotation=0,solid=False):
        obj=dict(id=key,model=model,position=xy,position_anchor='bounds-center',size_cells=size,rotation=rotation,layer='props',order=12,shadow=dict(opacity=.28,blur_cells=.07,offset_cells=[.1,.12]))
        plan['objects'].append(obj)
        if solid:
            # This model's measured footprint, not its square PNG margin.
            half=size/2;short=half*.3596;c=math.cos(math.radians(rotation));s=math.sin(math.radians(rotation))
            points=[[xy[0]+x*c-y*s,xy[1]+x*s+y*c] for x,y in [(-half,-short),(half,-short),(half,short),(-half,short)]]
            plan['foundry']['barriers'].append(dict(id=key+'-footprint',points=points,closed=True,sight='none',light='none',sound='none'))
    # Keep the middle of each small chamber free, including 2x2 turn reserves.
    for i,room in enumerate(network['rooms']):
        if room['id'] in ('arrival','sanctum-approach'):continue
        a,b,c,d=room['bounds'];width=c-a
        if i%3==1:
            plan['burials'].append(dict(id=room['id']+'-open-burial',asset='world/generic/human/passive doodads/altars/basestone.blp',bounds=[a+.25,b+.3,a+1.9,b+1.2],state='broken' if i%2 else 'open'))
        else:prop(room['id']+'-burial',sarc,[a+.95,b+.7],1.65,0,True)
        prop(room['id']+'-memorial',markers+f'tombstone0{5+i%4}.m2',[a+.6,d-.65],.9,90*(i%2))
        if i%3==0:prop(room['id']+'-rubble',rubble,[c-.7,d-.7],.9,i*37)
    # Physical blockage at the end of the former central axis.
    for i in range(3):prop('buried-axis-rubble-'+str(i),rubble,[37.6+i*.35,18+(i%2)*.9],1.3,25+i*53)
    plan['foundry']['barriers'].append(dict(id='buried-axis-collapse',points=[[36.8,17.1],[36.8,19.9]],closed=False))
    # Reproducible cracks/dust concentrate at walls and the eastern chambers.
    for i,room in enumerate(network['rooms']):
        a,b,c,d=room['bounds'];x=a+.4;y=d-.45
        plan['details'].append(dict(id='stone-fracture-'+str(i),type='line',points=[[x,y],[x+.6,y-.25],[x+1.1,y-.05]],stroke='#302c2b',width_cells=.06,opacity=.8))
        if a>39:
            plan['details'].append(dict(id='void-vein-'+str(i),type='line',points=[[c-.35,b+.4],[c-.65,b+1],[c-.45,b+1.6],[c-1,b+2]],stroke='#51415f',width_cells=.11,opacity=.7))
        plan['details'].append(dict(id='silt-'+str(i),type='polygon',points=[[a+.2,b+.2],[a+1.5,b+.3],[a+.7,b+.85]],fill='#5b5148',opacity=.4))
        if i%3==0 or a>47:
            plan['floors'].append(dict(id='weathered-floor-'+str(i),asset='dungeons/textures/floor/mm_duskwood_stonefloor_01.blp',tile_cells=1.3,opacity=.55,tint='#8b7d69' if a<45 else '#69536f',shape=dict(type='polygon',points=[[a+.25,b+.25],[c-.5,b+.5],[c-.2,d-.75],[(a+c)/2,d-.2],[a+.4,d-1.2]],feather=.12,roughness=.18)))
    regions=plan['foundry']['regions']
    bounds={'arrival-from-entrance':[5,18,7,20],'to-entrance':[2.5,20.5,4.5,22.5],
            'arrival-from-sanctum':[64.5,19,66.5,21],'to-sanctum':[68,21,70,23]}
    for r in regions:
        r['shapes']=[dict(type='rectangle',bounds=bounds[r['id']])]
        r.pop('shape',None)
    lights=[]
    positions=[(5.5,20.5),(15.5,14.5),(25.5,8.5),(31.5,18.5),(23.5,29.5),(38.5,31.5),(45.5,21.5),(49.5,10.5),(59.5,15.5),(59.5,28.5),(67.5,20.5),(8.5,30.5),(11.5,4.5),(58.5,4.5),(49.5,17.5),(68.5,35.5)]
    template=plan['foundry']['lights'][0]
    for i,pos in enumerate(positions):
        light=copy.deepcopy(template);light.update(id='maze-light-'+str(i),position=list(pos),bright=.5,dim=3.6,color='#827495' if pos[0]>40 else '#9c9b91',alpha=.22+.08*(pos[0]/72));lights.append(light)
    plan['foundry']['lights']=lights
    plan['locations']=[dict(id=r['id'],name=r['id'],bounds=r['bounds']) for r in network['rooms']]
    path.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(metrics));return plan


if __name__=='__main__':build()
