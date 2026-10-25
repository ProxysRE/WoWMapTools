import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from PIL import Image
from wowmap.foundry import compile_scene, export_bundle, shape_data, uid


def plan():
    return dict(format='wowmap.scene/1', name='Test inn', seed=1, size_cells=[12,10], pixels_per_cell=72,
                distance_per_cell=5, units='ft', base=dict(id='grass',asset='grass.png'),
                walls=[dict(id='south', points=[[1,2],[11,2]], thickness=.2, asset='wall.png', openings=[
                    dict(id='door',type='door',at=2,width=1,state='locked',asset='wood.png',foundry=dict(secret=True)),
                    dict(id='window',type='window',at=5,width=2,asset='wood.png'),
                    dict(id='arch',type='passage',at=8,width=1)])],
                foundry=dict(key='ground',lights=[dict(id='hearth',position=[3,4],bright=2,dim=5,color='#ff9933')],
                             regions=[dict(id='stairs',shapes=[dict(type='rectangle',bounds=[8,7,10,9])],
                               behaviors=[dict(type='teleportToken',destination=dict(scene='upper',region='landing'))])]))


class FoundryTests(unittest.TestCase):
    def compile(self,p=None):
        return compile_scene(p or plan(),'inn','ground',dict(ground={'stairs'},upper={'landing'}),'wowmap/inn/ground')

    def test_door_window_and_passage_topology(self):
        scene=self.compile();walls=scene['walls']
        self.assertEqual(len(walls),6)  # four solid pieces, door and window, no barrier across passage
        door=next(w for w in walls if w['door'])
        self.assertEqual(door['c'],[180,144,252,144]);self.assertEqual((door['door'],door['ds']),(2,2))
        window=next(w for w in walls if w['flags']['wowmap']['sourceId']=='window')
        self.assertEqual((window['move'],window['sight'],window['light']),(20,0,0))
        self.assertFalse(any(w['c'][0]<648<w['c'][2] for w in walls))

    def test_lighting_units_and_grid_are_independent(self):
        s=self.compile();light=s['lights'][0]
        self.assertEqual((light['x'],light['y']),(216,288))
        self.assertEqual((light['config']['bright'],light['config']['dim']),(10,25))
        self.assertEqual((s['grid']['size'],s['grid']['distance']),(72,5))
        self.assertEqual(s['padding'],0)

    def test_cross_floor_uuid_stable_and_closed_door_state(self):
        a=self.compile();b=self.compile()
        self.assertEqual(a,b)
        behavior=a['regions'][0]['behaviors'][0]
        self.assertEqual(behavior['system']['destination'],f"Scene.{uid('inn','upper')}.Region.{uid('inn','upper','region','landing')}")
        self.assertTrue(behavior['system']['choice'])
        p=plan();p['walls'][0]['openings'][0]['state']='open'
        self.assertEqual(next(w for w in self.compile(p)['walls'] if w['door'])['ds'],1)

    def test_invalid_destination_and_duplicate_ids_rejected(self):
        p=plan();p['foundry']['regions'][0]['behaviors'][0]['destination']['region']='unknown'
        with self.assertRaisesRegex(ValueError,'Unknown teleport'):self.compile(p)
        p=plan();p['foundry']['lights']*=2
        with self.assertRaisesRegex(ValueError,'Duplicate light'):self.compile(p)
        p=plan();p['foundry']['lights'][0]['bright']=20
        with self.assertRaisesRegex(ValueError,'dim radius'):self.compile(p)

    def test_exact_region_hole_shapes(self):
        shapes=shape_data(dict(type='rectangle',bounds=[1,2,8,9],cutouts=[dict(type='ellipse',bounds=[3,4,5,6])]),72)
        self.assertEqual(shapes[0]['width'],504);self.assertTrue(shapes[1]['hole'])
        self.assertEqual((shapes[1]['radiusX'],shapes[1]['x']),(72,288))
        with self.assertRaisesRegex(ValueError,'outlined'):shape_data(dict(type='path',points=[[0,0],[1,1]],width=1),72)

    def test_sensory_thresholds_and_invisible_barrier(self):
        p=plan();p['foundry']['barriers']=[dict(id='ledge',points=[[2,2],[2,8]],move='normal',sight='none',light='none',sound='none')]
        self.assertEqual(self.compile(p)['walls'][-1]['sight'],0)
        p['foundry']['barriers'][0]['sight']='proximity'
        with self.assertRaisesRegex(ValueError,'threshold'):self.compile(p)
        p['foundry']['barriers'][0]['threshold']={'sight':10}
        self.assertEqual(self.compile(p)['walls'][-1]['threshold']['sight'],10)

    def test_bundle_is_self_contained_for_maps_and_detects_stale_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folders=[]
            for key,rid in [('ground','stairs'),('upper','landing')]:
                folder=root/key;folder.mkdir();folders.append(folder)
                p=plan();p['foundry']['key']=key;p['foundry']['regions'][0]['id']=rid
                if key=='upper':p['foundry']['regions'][0]['behaviors']=[]
                (folder/'scene-plan.json').write_text(json.dumps(p),encoding='utf-8')
                Image.new('RGB',(864,720),'green').save(folder/'map-vtt.webp',lossless=True)
                meta=dict(width=864,height=720,vtt_image='map-vtt.webp',plan_sha256=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest())
                (folder/'render.json').write_text(json.dumps(meta),encoding='utf-8')
            result=export_bundle(folders,root/'export','test-inn')
            self.assertEqual(result['scenes'],2)
            bundle=json.loads((root/'export/wowmap/test-inn/bundle.json').read_text(encoding='utf-8'))
            self.assertEqual(len(bundle['scenes']),2)
            for s in bundle['scenes']:self.assertTrue((root/'export'/s['background']['src']).is_file())
            with self.assertRaisesRegex(ValueError,'empty'):export_bundle(folders,root/'export','test-inn')
            p['name']='Changed';(folders[-1]/'scene-plan.json').write_text(json.dumps(p),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'changed after rendering'):export_bundle(folders,root/'stale','test-inn')
            self.assertFalse((root/'stale').exists())

    def test_vtt_background_excludes_closed_door_leaf(self):
        import io
        from zipfile import ZipFile
        from wowmap.render import render
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);packs=root/'packages';packs.mkdir()
            with ZipFile(packs/'textures.zip','w') as archive:
                for name,color in [('grass','green'),('wood','red'),('wall','gray')]:
                    blob=io.BytesIO();Image.new('RGB',(8,8),color).save(blob,format='PNG')
                    archive.writestr(name+'.png',blob.getvalue())
            p=plan();p.pop('foundry');p['surface_variation']=0
            p['walls'][0]['openings']=[dict(id='door',type='door',at=2,width=1,state='closed',asset='wood.png')]
            render(p,root/'assets',root/'render',packages=packs)
            with Image.open(root/'render/map.png') as im:self.assertGreater(im.getpixel((216,144))[0],150)
            with Image.open(root/'render/map-vtt.webp') as im:self.assertEqual(im.getpixel((216,144)),(0,128,0))

    @unittest.skipUnless(shutil.which('node'),'Node.js not installed')
    def test_import_macro_preflight_and_id_preservation(self):
        subprocess.run(['node',str(Path(__file__).with_name('test_foundry_import.cjs'))],check=True)


if __name__=='__main__':unittest.main()
