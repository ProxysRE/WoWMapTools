import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from class_package_builder import build_package
from class_builder import ClassBuilderError
from foundry_module_builder import prepare_documents,ModuleBuilderError


def package():
 return {'schema_version':3,'identifier':'race-test','rules':'2014','races':[{'name':'Тестовая раса','identifier':'race-test','advancement':[{'type':'item_choice','choices':{'0':{'count':1}},'pool':['feature:asi-pair'],'allow_drops':False},{'type':'item_grant','level':3,'items':['spell:sample'],'spell':{'ability':['wis'],'method':'innate','uses':{'max':'1','per':'lr','requireSlot':False}}}]}], 'features':[{'key':'feature:asi-pair','name':'Сила +2; Ловкость +1','automation':{'mode':'passive'},'mechanics':{'passive':True},'advancement':[{'type':'asi','level':0,'points':0,'fixed':{'str':2,'dex':1}}]}], 'spells':[{'_id':'1234567890abcdef','name':'Тестовое заклинание','type':'spell','system':{'identifier':'sample','level':1,'activities':{}},'effects':[]}]}

class RacialContent(unittest.TestCase):
 def test_nested_asi_and_spell_refs(self):
  result=build_package(package());f=result['documents']['features'][0]
  a=next(iter(f['system']['advancement'].values()))
  self.assertEqual(a['level'],0);self.assertEqual(a['configuration']['fixed']['str'],2);self.assertEqual(a['configuration']['fixed']['dex'],1)
  prepared=prepare_documents(result,module_id='combined')
  self.assertEqual(set(prepared),{'races','features','spells'})
  grant=next(a for a in prepared['races'][0]['system']['advancement'].values() if a['type']=='ItemGrant')
  self.assertEqual(grant['configuration']['items'][0]['uuid'],'Compendium.combined.spells.Item.1234567890abcdef')
  self.assertEqual(grant['configuration']['spell']['method'],'innate')
  self.assertEqual(grant['configuration']['spell']['uses']['per'],'lr')
 def test_bad_nested_advancement_rejected(self):
  p=package();p['features'][0]['advancement']=[{'type':'hit_points'}]
  with self.assertRaises(ClassBuilderError):build_package(p)
 def test_orphan_and_invalid_spell_rejected(self):
  p=package();p['spells'][0]['_id']='bad'
  with self.assertRaises(ClassBuilderError):build_package(p)
  p=package();p['races'][0]['advancement'].pop()
  with self.assertRaises(ClassBuilderError):build_package(p)
 def test_spell_pack_name_reserved(self):
  with self.assertRaises(ModuleBuilderError):prepare_documents(build_package(package()),feature_pack='spells')

class CombinedClasses(unittest.TestCase):
 def test_two_classes_with_distinct_subclasses(self):
  from character_test_support import _control_package
  from class_builder import _stable_id
  one=build_package(_control_package());two=copy.deepcopy(one)
  two['documents']['class']['_id']=_stable_id('second-class')
  two['documents']['class']['system']['identifier']='second-class'
  sub=two['documents']['subclasses'][0];sub['_id']=_stable_id('second-subclass');sub['system']['identifier']='second-path';sub['system']['classIdentifier']='second-class'
  doc=one['documents'];doc['classes']=[doc.pop('class'),two['documents']['class']];doc['subclasses'].append(sub);doc.pop('subclass',None)
  self.assertEqual(len(prepare_documents(one)['classes']),4)


class NativeAbilityAllocation(unittest.TestCase):
 def test_free_points_and_locked_abilities_are_native(self):
  p=package();p['features'][0]['advancement']=[{'type':'asi','level':0,'points':1,'cap':1,'locked':['str','dex','con','wis'],'fixed':{'dex':2}}]
  f=build_package(p)['documents']['features'][0]
  a=next(iter(f['system']['advancement'].values()))
  self.assertEqual(a['configuration']['points'],1)
  self.assertEqual(a['configuration']['cap'],1)
  self.assertEqual(a['configuration']['locked'],['str','dex','con','wis'])
  self.assertEqual(a['configuration']['fixed']['dex'],2)

class CompositeEffects(unittest.TestCase):
 def test_followup_effect_and_numeric_utility_range_survive(self):
  from class_package_builder import _feature_item
  f,_=_feature_item({'key':'feature:test-composite','name':'Атака, затем спасбросок','mechanics':{'activities':[
   {'type':'utility','duration':{'value':1,'units':'hour','concentration':True},'targeting':{'range':{'value':30,'units':'ft'},'affects':{'type':'creature','count':'1'}}},
   {'type':'save','save':{'ability':'con','dc_formula':'8 + @prof'},'consume_uses':False,'effects':[{'name':'Ошеломлён','status':'stunned','duration':{'rounds':1}}]}]}},'test')
  a=list(f['system']['activities'].values())
  self.assertEqual(a[0]['range']['value'],'30')
  self.assertTrue(a[0]['range']['override'])
  self.assertTrue(a[0]['duration']['override'])
  self.assertTrue(a[0]['duration']['concentration'])
  self.assertEqual(a[0]['effects'],[])
  self.assertEqual(f['effects'][0]['statuses'],['stunned'])
  self.assertEqual(a[1]['effects'][0]['_id'],f['effects'][0]['_id'])
  self.assertEqual(f['effects'][0]['duration']['rounds'],1)
 def test_skipped_step_does_not_rebind_effect(self):
  from class_package_builder import _feature_item
  f,_=_feature_item({'key':'feature:test-invalid','name':'Некорректный шаг','mechanics':{'activities':[
   {'type':'unknown','effects':[{'name':'Не должен перейти','status':'stunned'}]},
   {'type':'utility'}]}},'test')
  self.assertEqual(next(iter(f['system']['activities'].values()))['effects'],[])

class NativeRaceExport(unittest.TestCase):
 def test_exported_fixed_bonus_is_preserved_with_missing_id_and_inherited_units(self):
  from race_builder import build_race
  asi={'type':'AbilityScoreImprovement','_id':'pvdcvlznzEsSf1QT','configuration':{'points':0,'fixed':{k:1 for k in ['str','dex','con','int','wis','cha']},'cap':2,'locked':[],'recommendation':None},'value':{'type':'asi'},'level':0,'title':'','flags':{},'hint':''}
  size={'type':'Size','_id':'1FDkYW2yHFJsTuBw','configuration':{'sizes':['med']},'level':0}
  original={'name':'Человек','type':'race','system':{'identifier':'chelovek','advancement':{asi['_id']:asi,size['_id']:size},'movement':{'walk':'30','units':None},'senses':{'units':None,'ranges':{'darkvision':None}},'type':{'value':'humanoid'}}}
  before=copy.deepcopy(original);d,report=build_race(original)
  self.assertEqual(original,before)
  self.assertEqual(report.input_format,'foundry')
  self.assertEqual(d['system']['advancement'][asi['_id']],asi)
  self.assertEqual(d['system']['movement']['walk'],30)
  self.assertEqual(d['system']['movement']['units'],'ft')
  self.assertEqual(d['system']['senses']['units'],'ft')
  self.assertEqual(len(d['_id']),16)

class ClassIdentity(unittest.TestCase):
 def test_distinct_classes_in_one_module_have_distinct_ids_and_explicit_id_survives(self):
  from character_test_support import _control_package
  one=_control_package();two=copy.deepcopy(one)
  two['class']['identifier']='another-class'
  two['subclass']['class_identifier']='another-class'
  first=build_package(one)['documents']['class']
  second=build_package(two)['documents']['class']
  self.assertNotEqual(first['_id'],second['_id'])
  two['class']['_id']='legacyID12345678'
  self.assertEqual(build_package(two)['documents']['class']['_id'],'legacyID12345678')

if __name__=='__main__':unittest.main()
