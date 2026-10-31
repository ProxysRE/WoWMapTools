import unittest
from unittest.mock import patch
from wowmap.creature_appearances import creature_display_skin

class Table:
    def __init__(self,fields,row):self.fields=fields;self.records=1;self.row=row
    def cell(self,i,j,kind=None):return self.row[j]
class Assets:
    def read(self,path):return b'data'
    def has(self,path):return True
class CreatureAppearanceTests(unittest.TestCase):
    def test_three_skin_slots_keep_dbc_order(self):
        display=Table(16,{0:4162,1:37,3:0,6:'SuccubusNewSkin',7:'SuccubusSkinWing',8:'SuccubusHair'})
        model=Table(28,{0:37,2:'Creature\\Succubus\\Succubus.mdx'})
        with patch('wowmap.creature_appearances.DBC',side_effect=[display,model]),patch('wowmap.creature_appearances.model_info',return_value={'textures':[{'kind':11},{'kind':12},{'kind':13}]}):
            out=creature_display_skin(Assets(),4162)
        self.assertEqual(out['model'],'creature/succubus/succubus.m2')
        self.assertTrue(out['textures'][11].endswith('/succubusnewskin.blp'))
        self.assertTrue(out['textures'][12].endswith('/succubusskinwing.blp'))
        self.assertTrue(out['textures'][13].endswith('/succubushair.blp'))
    def test_character_display_requires_extra_assembly(self):
        with patch('wowmap.creature_appearances.DBC',side_effect=[Table(16,{0:6417,1:185,3:4214}),Table(28,{})]):
            with self.assertRaisesRegex(ValueError,'CreatureDisplayInfoExtra'):creature_display_skin(Assets(),6417)
if __name__=='__main__':unittest.main()
