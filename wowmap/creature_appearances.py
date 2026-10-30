"""Resolve creature skin slots from original WotLK 3.3.5 DBC records."""
from pathlib import PurePosixPath
from .dbc import DBC
from .models import model_info
from .pack import normalize

def creature_display_skin(assets,display_id):
    if type(display_id) is not int or display_id<=0:raise ValueError('display_id must be a positive integer')
    display=DBC(assets.read('dbfilesclient/creaturedisplayinfo.dbc'))
    model=DBC(assets.read('dbfilesclient/creaturemodeldata.dbc'))
    if display.fields!=16 or model.fields!=28:raise ValueError('Expected original 3.3.5 CreatureDisplayInfo/CreatureModelData schema')
    row=next((i for i in range(display.records) if display.cell(i,0)==display_id),None)
    if row is None:raise ValueError('Unknown creature display ID')
    if display.cell(row,3):raise ValueError('Character display requires CreatureDisplayInfoExtra and geoset assembly')
    mid=display.cell(row,1);mr=next((i for i in range(model.records) if model.cell(i,0)==mid),None)
    if mr is None:raise ValueError('Display references missing creature model')
    path=normalize(model.cell(mr,2,'string'));path=str(PurePosixPath(path).with_suffix('.m2'))
    info=model_info(assets.read(path),path);types={t['kind'] for t in info['textures']};textures={}
    for slot in range(3):
        name=display.cell(row,6+slot,'string')
        if not name:continue
        kind=11+slot
        if kind not in types:continue
        name=normalize(name)
        texture=str(PurePosixPath(path).parent/name) if '/' not in name else name
        if not texture.endswith('.blp'):texture+='.blp'
        if not assets.has(texture):raise ValueError('Missing display texture: '+texture)
        textures[kind]=texture
    return {'display_id':display_id,'model_id':mid,'model':path,'textures':textures}
