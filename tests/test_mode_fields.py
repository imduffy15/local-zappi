import unittest
from tools.learn_mode_fields import candidates
class ModeFieldsTest(unittest.TestCase):
    def test_changing_counter_is_not_a_mode_field(self):
        samples=[{'mode':'Fast','hex':'010110'}, {'mode':'Stopped','hex':'020411'},
                 {'mode':'Eco','hex':'030212'}, {'mode':'Stopped','hex':'040413'}]
        result=candidates(samples)['candidate_fields']
        self.assertEqual(result,[{'offset':1,'offset_hex':'0x1','wire_values':{'Fast':1,'Stopped':4,'Eco':2}}])
    def test_requires_repeated_mode(self):
        with self.assertRaises(ValueError):candidates([{'mode':'Fast','hex':'01'},{'mode':'Stop','hex':'04'}])
