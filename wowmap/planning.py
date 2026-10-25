"""Deterministic constrained placement; the assistant still authors the scene plan."""
import copy
import hashlib
import math
import numpy as np
from .geometry import validate_shape,signed_distance,segment_distance
from .objects import finite


def expand(plan):
    result=copy.deepcopy(plan);objects=result.setdefault('objects',[]);ids={o['id'] for o in objects}
    occupied=[(o['position'],o.get('keepout_radius',o['size_cells']*o.get('scale',1)*.25)) for o in objects]
    report=[]
    scatters=plan.get('scatter',[])
    scatter_ids=set()
    for group in scatters:
        identifier=group['id']
        if identifier in scatter_ids:raise ValueError('Scatter ids must be unique')
        scatter_ids.add(identifier)
        region=group['region'];validate_shape(region)
        exclusions=group.get('exclude',[])
        for exclusion in exclusions:validate_shape(exclusion)
        count=group['count']
        if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<=1000:raise ValueError('scatter count must be 0..1000')
        prototypes=group['prototypes']
        if not prototypes:raise ValueError('scatter prototypes cannot be empty')
        low,high=group.get('size_range',[2,3]);radius=group.get('radius',.8)
        if finite(low,'size_range')<=0 or finite(high,'size_range')<low or finite(radius,'radius')<0:raise ValueError('Invalid scatter size or radius')
        attempts=group.get('attempts',max(100,count*100))
        if not isinstance(attempts,int) or not 1<=attempts<=100000:raise ValueError('scatter attempts must be 1..100000')
        seed=int.from_bytes(hashlib.sha256(f"{plan['seed']}:{identifier}".encode()).digest()[:8],'little')
        rng=np.random.default_rng(seed);placed=0;tried=0
        width,height=plan['size_cells']
        while placed<count and tried<attempts:
            tried+=1;point=[float(rng.uniform(0,width)),float(rng.uniform(0,height))]
            if signed_distance(region,point)<radius:continue
            if any(signed_distance(shape,point)>-radius for shape in exclusions):continue
            if group.get('avoid_floors',True) and any(signed_distance(f['shape'],point)>-radius for f in plan.get('floors',[])):continue
            if any(math.dist(point,other)<radius+other_radius for other,other_radius in occupied):continue
            if any(segment_distance(point,w['points'][0],w['points'][1])<radius+w['thickness']/2 for w in plan.get('walls',[])):continue
            obj=copy.deepcopy(prototypes[int(rng.integers(len(prototypes)))])
            obj.update(id=f'{identifier}-{placed+1}',position=point,size_cells=float(rng.uniform(low,high)),rotation=float(rng.uniform(0,360)))
            if obj['id'] in ids:raise ValueError('Scatter-generated object id conflicts with explicit object')
            ids.add(obj['id']);objects.append(obj);occupied.append((point,radius));placed+=1
        if placed<count and group.get('strict',True):
            raise ValueError(f'Scatter {identifier}: placed {placed}/{count}; constraints cannot be satisfied. Change the plan.')
        report.append(dict(id=identifier,requested=count,placed=placed,attempts=tried))
    if len(objects)>2000:raise ValueError('Expanded scene exceeds 2000 objects')
    return result,report
