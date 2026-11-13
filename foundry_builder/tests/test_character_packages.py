import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from class_builder import ClassBuilderError, build_class
from class_package_builder import build_package, write_zip
from foundry_module_builder import ModuleBuilderError, prepare_documents, create_module
from race_builder import build_race
from subclass_builder import build_subclass
from character_test_support import _control_package


def fixture():
    p = _control_package()
    p['schema_version'] = 3
    p['rules'] = '2014'
    p['subclasses'] = [p.pop('subclass')]
    p['subclasses'].append(dict(p['subclasses'][0], name='Второй путь', identifier='other-path'))
    p['races'] = [{
        'name': 'Проверочная раса', 'identifier': 'audit-race', 'sizes': ['sm', 'med'],
        'movement': {'walk': 25, 'swim': 30}, 'senses': {'ranges': {'darkvision': 60}},
        'advancement': [
            {'type': 'asi', 'level': 0, 'points': 0, 'fixed': {'con': 2, 'int': 1}},
            {'type': 'trait', 'level': 0, 'grants': ['languages:standard:common']},
            {'type': 'item_choice', 'choices': {'0': {'count': 1}}, 'pool': ['feature:audit-action']},
        ],
    }]
    for index, sub in enumerate(p['subclasses']):
        key = f'feature:path-{index}'
        p['features'].append(dict(p['features'][0], key=key, name=f'Способность пути {index}'))
        sub['advancement'] = [{'type': 'item_grant', 'level': 3, 'items': [key]},
                              {'type': 'item_grant', 'level': 20, 'items': [key]}]
    return p


class Packages(unittest.TestCase):
    def _class_library_spell(self, owner=None, original=True):
        r = build_package(fixture())
        docs = r['documents']
        parent = docs.get('class') or next(d for d in docs['classes'] if d['type'] == 'class')
        conversion = {'class': owner or parent['system']['identifier']}
        if original:
            conversion['original_spell'] = 'optional-library-spell'
        spell = {'_id': 'abcde12345678901', 'name': 'Каталожное заклинание', 'type': 'spell',
                 'system': {'identifier': 'optional-library-spell', 'description': {'value': '<p>Игровой текст.</p>'}},
                 'flags': {'warcraft-conversion': conversion}}
        docs.setdefault('spells', []).append(spell)
        return r

    def test_class_spell_library_does_not_require_html_catalogue(self):
        r = self._class_library_spell()
        packs = prepare_documents(r, module_id='target')
        spell = next(d for d in packs['spells'] if d['_id'] == 'abcde12345678901')
        self.assertEqual(spell['system']['description']['value'], '<p>Игровой текст.</p>')
        self.assertNotIn('advancement', spell['system'])

    def test_class_spell_library_rejects_unknown_owner(self):
        with self.assertRaises(ModuleBuilderError):
            prepare_documents(self._class_library_spell(owner='missing-class'))

    def test_class_spell_library_requires_original_spell_identity(self):
        with self.assertRaises(ModuleBuilderError):
            prepare_documents(self._class_library_spell(original=False))

    def test_class_metadata_does_not_hide_orphan_features(self):
        r = self._class_library_spell()
        spell = r['documents']['spells'].pop()
        spell['type'] = 'feat'
        r['documents']['features'].append(spell)
        with self.assertRaises(ModuleBuilderError):
            prepare_documents(r)

    def test_multiple_subclasses_and_race(self):
        r = build_package(fixture())
        self.assertEqual(len(r['documents']['subclasses']), 2)
        self.assertNotIn('subclass', r['documents'])
        packs = prepare_documents(r, module_id='target')
        self.assertEqual({k:len(v) for k,v in packs.items()}, {'classes':3,'races':1,'features':3})
        self.assertIn('Compendium.target.features.Item.', json.dumps(packs))
        self.assertNotIn('Compendium.audit-package.', json.dumps(packs))
        self.assertEqual(packs['races'][0]['system']['source']['rules'], '2014')
        self.assertEqual(packs['features'][0]['system']['source']['rules'], '2014')

    def test_legacy_singleton_and_no_input_mutation(self):
        p = _control_package(); before=copy.deepcopy(p)
        r = build_package(p)
        self.assertEqual(p, before)
        self.assertEqual(r, build_package(p))
        self.assertEqual(r['documents']['subclass'], r['documents']['subclasses'][0])
        legacy = copy.deepcopy(r); del legacy['documents']['subclasses']; del legacy['documents']['races']
        self.assertEqual(prepare_documents(r), prepare_documents(legacy))

    def test_wrong_parent_compact_and_native(self):
        for native in [False, True]:
            p=fixture()
            if native:
                item=build_package(p)['documents']['subclasses'][0]; item['system']['classIdentifier']='wrong'; p['subclasses'][0]=item
            else:
                p['subclasses'][0]['class_identifier']='wrong'
            with self.assertRaisesRegex(ClassBuilderError, 'class_identifier'):
                build_package(p)

    def test_duplicates(self):
        p=fixture(); p['subclasses'].append(copy.deepcopy(p['subclasses'][0]))
        with self.assertRaises(ClassBuilderError): build_package(p)
        p=fixture(); p['races'].append(copy.deepcopy(p['races'][0]))
        with self.assertRaises(ClassBuilderError): build_package(p)

    def test_missing_feature_and_unreferenced_feature(self):
        p=fixture(); p['features']=[]
        with self.assertRaisesRegex(ClassBuilderError,'ссылки'): build_package(p)
        p=fixture(); p['features'].append(dict(p['features'][0],key='feature:orphan',name='Orphan'))
        with self.assertRaisesRegex(ClassBuilderError,'не связаны'): build_package(p)

    def test_empty_automation_mode(self):
        p=fixture(); p['features'][0]['automation']={}
        with self.assertRaisesRegex(ClassBuilderError,'automation.mode'): build_package(p)
        for mode in ['partial','manual']:
            p['features'][0]['automation']={'mode':mode}
            with self.assertRaisesRegex(ClassBuilderError,'automation.manual'): build_package(p)

    def test_no_subclass_selection(self):
        p=fixture(); p['class']['advancement']=[a for a in p['class']['advancement'] if a['type']!='subclass']
        with self.assertRaisesRegex(ClassBuilderError,'Subclass advancement'): build_package(p)

    def test_no_subclasses_allowed(self):
        p=fixture(); p['subclasses']=[];p['features']=p['features'][:1]
        self.assertEqual(len(prepare_documents(build_package(p))['classes']),1)

    def test_race_only(self):
        p=fixture(); del p['class']; p['subclasses']=[];p['features']=p['features'][:1]
        self.assertEqual(set(prepare_documents(build_package(p))),{'races','features'})
        p['features']=[]; p['races'][0]['advancement']=[{'type':'trait','grants':['dr:fire']}]
        self.assertEqual(set(prepare_documents(build_package(p))),{'races'})

    def test_race_roundtrip_and_zero_level(self):
        item,report=build_race(fixture()['races'][0])
        self.assertFalse(report.warnings)
        self.assertEqual(build_race(item)[0],item)
        self.assertEqual(item['system']['senses']['ranges']['darkvision'],60)
        for a in item['system']['advancement'].values():
            if a['type'] in {'Trait','AbilityScoreImprovement'}: self.assertEqual(a['level'],0)

    def test_invalid_race_data(self):
        for field,value in [('sizes',[]),('sizes',['dragon']),('movement',{'walk':-1}),('movement',{'units':'yards'}),('senses',{'ranges':{'xray':10}})]:
            p=fixture()['races'][0];p[field]=value
            with self.assertRaises(ClassBuilderError): build_race(p)
        p=fixture()['races'][0];p['advancement']=[{'type':'hit_points'}]
        with self.assertRaises(ClassBuilderError): build_race(p)

    def test_size_and_hp_not_allowed_in_wrong_types(self):
        p=fixture()['class'];p['advancement'].append({'type':'Size'})
        with self.assertRaises(ClassBuilderError): build_class(p)
        p=fixture()['subclasses'][0];p['advancement']=[{'type':'Size'}]
        with self.assertRaises(ClassBuilderError): build_subclass(p)
        p=build_package(fixture())['documents']['subclasses'][0];p['system']['advancement']={'1234567890abcdef':{'_id':'1234567890abcdef','type':'HitPoints'}}
        with self.assertRaises(ClassBuilderError): build_subclass(p)

    def test_external_uuids_and_inline_links_not_corrupted(self):
        p=fixture();p['class']['advancement'].append({'type':'item_grant','level':2,'items':['Compendium.dnd5e.spells.Item.1234567890abcdef']})
        r=build_package(p);u=r['reference_map']['feature:audit-action']
        r['documents']['class']['system']['description']['value']=f'@UUID[{u}] and @UUID[Compendium.dnd5e.spells.Item.1234567890abcdef]'
        packs=prepare_documents(r,module_id='target')
        text=json.dumps(packs)
        self.assertIn('Compendium.dnd5e.spells.Item.1234567890abcdef',text)
        self.assertIn('@UUID[Compendium.target.features.Item.',text)

    def test_dangling_local_uuid_rejected(self):
        r=build_package(fixture());r['documents']['class']['system']['description']['value']='@UUID[Compendium.audit-package.features.Item.0000000000000000]'
        with self.assertRaises(ModuleBuilderError): prepare_documents(r)

    def test_files_and_zip(self):
        p=fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for i,s in enumerate(p.pop('subclasses')): (root/f's{i}.json').write_text(json.dumps(s))
            p['subclass_files']=['s0.json','s1.json']
            (root/'r.json').write_text(json.dumps(p.pop('races')[0]));p['race_files']=['r.json']
            r=build_package(p,root);write_zip(r,root/'result.zip')
            with zipfile.ZipFile(root/'result.zip') as z:
                self.assertEqual(len([f for f in z.namelist() if f.startswith('classes/')]),3)
                self.assertIn('package.json',z.namelist())

    def test_feature_must_not_be_silently_retyped(self):
        r=build_package(fixture());r['documents']['features'][0]['type']='spell'
        with self.assertRaises(ModuleBuilderError): prepare_documents(r)

    def test_manifest_only_lists_built_packs(self):
        # A recording CLI stub exercises source export and manifest selection, not actual LevelDB compilation.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cli=root/'record.mjs'
            cli.write_text("import fs from 'node:fs'; export async function compilePack(s,d){fs.mkdirSync(d,{recursive:true});fs.writeFileSync(d+'/count',String(fs.readdirSync(s).length));}")
            p=fixture();del p['class'];p['subclasses']=[];p['features']=p['features'][:1]
            dest=create_module(build_package(p),root,cli_module=cli,module_id='test-module')
            manifest=json.loads((dest/'module.json').read_text())
            self.assertEqual({p['name'] for p in manifest['packs']},{'races','features'})
            self.assertTrue((dest/'scripts/resource-pools.mjs').exists())


    def test_failed_compile_preserves_existing_module(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); target=root/'existing';target.mkdir();(target/'keep').write_text('old')
            cli=root/'fail.mjs';cli.write_text("export async function compilePack(){throw Error('test failure');}")
            with self.assertRaises(ModuleBuilderError):
                create_module(build_package(fixture()),root,cli_module=cli,module_id='existing')
            self.assertEqual((target/'keep').read_text(),'old')
            self.assertFalse((target/'module.json').exists())

class ResourceAuthoring(unittest.TestCase):
    def test_subclass_keeps_its_preparation_formula(self):
        from subclass_builder import build_subclass
        source = {"name":"Feral", "identifier":"feral", "class_identifier":"test-druid", "spellcasting":{"progression":"half", "ability":"wis", "preparation":{"formula":"max(1, @classes.test-druid.levels + @abilities.wis.mod)"}}}
        item, _ = build_subclass(source)
        self.assertEqual(item["system"]["spellcasting"]["preparation"], source["spellcasting"]["preparation"])
        source["spellcasting"].pop("preparation")
        item, _ = build_subclass(source)
        self.assertEqual(item["system"]["spellcasting"]["preparation"], {"formula":""})

    def test_per_use_shared_pool_limit_exported(self):
        from class_package_builder import _feature_item
        raw = {"key":"feature:limit", "name":"Limit", "mechanics":{"activity_type":"utility", "activation":{"type":"action"}, "resource":{"type":"pool", "target":"runic", "value":"3", "max_cost":"max(1, @abilities.cha.mod)"}}}
        item, _ = _feature_item(raw, "test")
        activity = next(iter(item["system"]["activities"].values()))
        self.assertEqual(activity["flags"]["foundry-content-generator"]["resourcePool"]["maxCost"], "max(1, @abilities.cha.mod)")

    def test_timed_activations_are_not_replaced_by_actions(self):
        for unit, value in [("minute", 10), ("hour", 1), ("day", 1)]:
            with self.subTest(unit=unit):
                p=_control_package()
                p['features'][0]['mechanics']={'activity_type':'utility','activation':{'type':unit,'value':value}}
                f=build_package(p)['documents']['features'][0]
                a=next(iter(f['system']['activities'].values()))
                self.assertEqual(a['activation']['type'],unit)
                self.assertEqual(a['activation']['value'],value)

    def test_reserve_restores_pool_and_consumes_own_use(self):
        p=_control_package()
        p['features'][0]['resource_pool']={'key':'rage','max':'6','initial_empty':True,'recovery':[]}
        p['features'].append({'key':'feature:reserve','name':'Reserve','automation':{'mode':'partial','manual':['Choose timing']},'uses':{'max':'1','spent':0,'recovery':[{'period':'sr','type':'recoverAll'}]},'mechanics':{'activity_type':'utility','consume_uses':True,'resource':{'type':'pool','target':'rage','value':'3','operation':'restore'}}})
        p['class']['advancement'].append({'type':'item_grant','level':2,'items':['feature:reserve']})
        result=build_package(p)
        pool,reserve=result['documents']['features']
        self.assertTrue(pool['flags']['foundry-content-generator']['resourcePool']['initialEmpty'])
        activity=next(iter(reserve['system']['activities'].values()))
        self.assertEqual(activity['flags']['foundry-content-generator']['resourcePool']['operation'],'restore')
        self.assertEqual(activity['consumption']['targets'][0]['type'],'itemUses')

    def test_feature_prerequisites_icons_and_names_survive(self):
        p=_control_package();p['features'][0]['prerequisites']={'items':['class:audit-class'],'level':6,'repeatable':False}
        p['features'][0]['img']='modules/example/assets/original.webp'
        f=build_package(p)['documents']['features'][0]
        self.assertEqual(f['system']['prerequisites']['level'],6)
        a=next(iter(f['system']['activities'].values()))
        self.assertEqual(a['img'],f['img'])
        self.assertEqual(a['name'],'Проверить')

if __name__=='__main__': unittest.main()
