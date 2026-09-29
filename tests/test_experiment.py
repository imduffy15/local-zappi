import unittest
from tools.summarize_experiment import summarize

def packet(direction,key,route='one',t=1):
    return dict(direction=direction,route=route,time=t,hex=(b'abcd'+key+b'payload').hex())

class ExperimentTest(unittest.TestCase):
    def test_repeated_correlation_and_unsolicited_are_distinguished(self):
        rows=[packet('device',b'key1',t=1),packet('device',b'key1',t=2),
              packet('upstream',b'key1',t=3),packet('upstream',b'key1',t=4),
              packet('upstream',b'key2',t=5)]
        d=summarize(rows)
        self.assertEqual(d['matched_upstream'],2)
        self.assertEqual(d['unmatched_device'],0)
        self.assertEqual([r['record'] for r in d['unmatched_upstream']],[5])
    def test_other_route_does_not_match(self):
        d=summarize([packet('device',b'key1'),packet('upstream',b'key1',route='two')])
        self.assertEqual(d['matched_upstream'],0)
        self.assertEqual(d['unmatched_device'],1)
        self.assertEqual(len(d['unmatched_upstream']),1)
