"""WotLK display ID -> model/skins -> separate static token and frontal portrait.

Schemas: wowdev/WoWDBDefs CreatureDisplayInfo (16 fields), CreatureModelData
(28 fields), build 3.3.5.12340. Replacement texture types 11..13 correspond to
GAMEOBJECT1..3 in wowmodelviewer/src/games/wow/wow_enums.h.
Humanoid assembly, animation sampling and special geosets are deliberately rejected.
"""
import argparse
from contextlib import contextmanager, ExitStack
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath

from .dbc import DBC
from .icons import relative_file
from .models import RawAssets, inspect_model, preview
from .pack import normalize

PREFIX='wowmap/content/tokens/'
PORTRAIT_PREFIX='wowmap/content/portraits/'
SCHEMA='3.3.5.12340'


def index_table(table, fields):
    if table.fields!=fields or table.record_size!=fields*4:
        raise ValueError('Appearance table layout does not match supported 3.3.5 schema')
    index={}
    for row in range(table.records):
        key=table.cell(row,0)
        if key in index:raise ValueError('Duplicate appearance table ID')
        index[key]=row
    return index


class AppearanceDB:
    def __init__(self, folder):
        with RawAssets(folder) as assets:
            display=assets.read('dbfilesclient/creaturedisplayinfo.dbc')
            model=assets.read('dbfilesclient/creaturemodeldata.dbc')
        self.display=DBC(display);self.model=DBC(model)
        self.displays=index_table(self.display,16);self.models=index_table(self.model,28)
        self.hashes=dict(creaturedisplayinfo=hashlib.sha256(display).hexdigest(),
                         creaturemodeldata=hashlib.sha256(model).hexdigest())

    def appearance(self, display_id):
        if type(display_id) is not int or display_id<=0 or display_id not in self.displays:
            raise ValueError('Unknown positive CreatureDisplayInfo ID')
        row=self.displays[display_id];d=self.display;model_id=d.cell(row,1)
        if model_id not in self.models:raise ValueError('Display references an unknown model ID')
        mrow=self.models[model_id];raw_path=self.model.cell(mrow,2,'string')
        path=normalize(raw_path)
        if path.endswith('.mdx'):path=path[:-4]+'.m2'
        if not path.endswith('.m2'):raise ValueError('Display model is not an M2 path')
        textures={}
        for i in range(3):
            name=d.cell(row,6+i,'string')
            if name:
                name=normalize(name)
                if not PurePosixPath(name).suffix:name+='.blp'
                textures[11+i]=normalize(str(PurePosixPath(path).parent/name) if '/' not in name else name)
        scale=d.cell(row,4,'float32');model_scale=self.model.cell(mrow,4,'float32')
        if not all(math.isfinite(v) and v>0 for v in (scale,model_scale)):
            raise ValueError('Invalid creature display/model scale')
        return dict(display_id=display_id,model_id=model_id,model=path,textures=textures,
                    extended_display_id=d.cell(row,3),alpha=d.cell(row,5),
                    geoset_data=d.cell(row,14),display_scale=scale,model_scale=model_scale)

    def search(self, query, limit=30):
        if not isinstance(query,str) or not query.strip() or not 1<=limit<=100:
            raise ValueError('Search needs text and limit 1..100')
        words=query.lower().split();matches=[]
        for key,row in self.displays.items():
            model_id=self.display.cell(row,1)
            if model_id not in self.models:continue
            path=self.model.cell(self.models[model_id],2,'string').lower()
            textures=[self.display.cell(row,6+i,'string') for i in range(3)]
            text=path+' '+' '.join(textures).lower()
            if all(word in text for word in words):
                matches.append(dict(display_id=key,model=path,skins=textures,
                                    humanoid=bool(self.display.cell(row,3))))
        return dict(matches=len(matches),displays=sorted(matches,key=lambda r:r['display_id'])[:limit])


class TokenAssets:
    def __init__(self, dbc_folder, model_folder):
        self.db=AppearanceDB(dbc_folder);self.model_folder=model_folder
        self.images={};self.media={};self.selected={}
        self._stack=None;self._assets=None

    @contextmanager
    def session(self):
        """Lazily index model ZIPs once; close them even when a build fails."""
        if self._stack is not None:
            yield self
            return
        with ExitStack() as stack:
            self._stack=stack
            try:
                yield self
            finally:
                self._stack=None;self._assets=None

    def select(self, options, view='top'):
        if view not in ('top','front'):raise ValueError('Token view must be top or front')
        if not isinstance(options,dict) or set(options)-{'display_id','size','yaw','actor_image','portrait_size','portrait_yaw'}:
            raise ValueError('Appearance supports display_id, size, yaw, actor_image, portrait_size and portrait_yaw only')
        display_id=options.get('display_id')
        size=options.get('size',512) if view=='top' else options.get('portrait_size',768)
        yaw=options.get('yaw',-90) if view=='top' else options.get('portrait_yaw',0)
        if type(size) is not int or not 64<=size<=2048:raise ValueError('Token size must be an integer from 64 to 2048')
        if isinstance(yaw,bool) or not isinstance(yaw,(int,float)) or not math.isfinite(yaw) or not -360<=yaw<=360:
            raise ValueError('Token yaw must be finite degrees between -360 and 360')
        if type(options.get('actor_image',True)) is not bool:raise ValueError('actor_image must be boolean')
        appearance=self.db.appearance(display_id)
        if appearance['extended_display_id'] or appearance['model'].startswith('character/'):
            raise ValueError('Humanoid appearance assembly is not implemented yet')
        if appearance['geoset_data']:raise ValueError('Creature geoset selection is not implemented yet')
        if appearance['alpha']!=255:raise ValueError('Translucent creature displays are not implemented yet')
        key=(display_id,size,yaw,view)
        if key in self.selected:return self.selected[key]
        if len(self.selected)>=400:raise ValueError('At most 400 creature views per batch')
        with self.session():
            if self._assets is None:self._assets=self._stack.enter_context(RawAssets(self.model_folder))
            assets=self._assets
            info=inspect_model(assets,appearance['model'])
            replacements={k:v for k,v in appearance['textures'].items() if k in info['used_replaceable_texture_types']}
            image,render=preview(assets,appearance['model'],size,replacements,yaw,view)
            deps={appearance['model'],info['skins'][0],*render['used_textures']}
            sources=[dict(path=p,sha256=hashlib.sha256(assets.read(p)).hexdigest()) for p in sorted(deps)]
        buffer=io.BytesIO();image.save(buffer,format='WEBP',lossless=True,exact=True)
        data=buffer.getvalue();digest=hashlib.sha256(data).hexdigest()
        path=(PREFIX if view=='top' else PORTRAIT_PREFIX)+digest+'.webp'
        self.images[path]=data
        variant=dict(**appearance,view=view,schema=SCHEMA,dbc_sha256=self.db.hashes,render=render,sources=sources)
        self.media.setdefault(path,dict(file=path,sha256=digest,bytes=len(data),appearances=[]))['appearances'].append(variant)
        self.selected[key]=path
        return path

    def pair(self, options):
        with self.session():
            token=self.select(options)
            portrait=self.select(options,'front') if options.get('actor_image',True) else None
        return dict(token=token,portrait=portrait)

    def write(self, root):
        for path,data in self.images.items():
            target=relative_file(root,path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)


def main():
    parser=argparse.ArgumentParser(description='Resolve WotLK creature appearances and render static transparent tokens')
    parser.add_argument('command',choices=['search','render'])
    parser.add_argument('--dbc-assets',required=True)
    parser.add_argument('--model-assets')
    parser.add_argument('--query',default='wolf')
    parser.add_argument('--limit',type=int,default=30)
    parser.add_argument('--display-id',type=int)
    parser.add_argument('--size',type=int,default=512)
    parser.add_argument('--yaw',type=float,default=-90)
    parser.add_argument('--portrait-size',type=int,default=768)
    parser.add_argument('--portrait-yaw',type=float,default=0)
    parser.add_argument('--out',default='output/token')
    args=parser.parse_args()
    try:
        if args.command=='search':
            result=AppearanceDB(args.dbc_assets).search(args.query,args.limit)
        else:
            if not args.model_assets:raise ValueError('--model-assets is required for rendering')
            out=Path(args.out)
            if out.exists() and any(out.iterdir()):raise ValueError('Token output directory must be empty')
            tokens=TokenAssets(args.dbc_assets,args.model_assets)
            pair=tokens.pair(dict(display_id=args.display_id,size=args.size,yaw=args.yaw,
                                 portrait_size=args.portrait_size,portrait_yaw=args.portrait_yaw))
            tokens.write(out);result=dict(format='wowmap.tokens/1',image=pair['token'],portrait=pair['portrait'],media=list(tokens.media.values()))
            (out/'token-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError) as error:parser.exit(1,f'ERROR: {error}\n')


if __name__=='__main__':main()
