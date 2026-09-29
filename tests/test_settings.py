import struct
import time
import unittest
from settings import Settings,decode_config,packet
from power import Power
import test_control
from protocol import open_packet

class SettingsTest(unittest.TestCase):
    setUp=test_control.ControlTests.setUp
    def ready(self):
        self.c.peer=(None,None);self.c.peer_at=self.c.verified_at=time.time();self.c.target=(0x81,0x50)
    def test_boost_fields_and_invalid_requests(self):
        self.ready();s=Settings(self.c)
        s.boost({'kind':'smart','kwh':12,'time':'07:30'})
        selector,data,tail=s.queue[0]
        p=open_packet(packet(self.c,selector,data,tail),self.key)
        self.assertEqual(p[58:60],b'\x0c\0');self.assertEqual(p[66:70],bytes((0,28,7,30)))
        for body in ({'kind':'manual','kwh':100},{'kind':'smart','kwh':1,'time':'24:00'}):
            with self.assertRaises(ValueError):Settings(self.c).boost(body)
    def test_schedule_write_preserves_every_unrelated_byte(self):
        self.ready();s=Settings(self.c)
        data=bytearray(range(128));data[:4]=bytes.fromhex('1057a5f8')
        s.config=bytes(data);s.config_at=time.time()
        rows=[{'start':'01:30','duration_minutes':60,'days':[0,2]} for _ in range(4)]
        s.schedules({'schedules':rows})
        expected=s.expected
        self.assertEqual(expected[28:],data[28:])
        for slot in range(4):
            self.assertEqual(expected[9+6*slot],data[9+6*slot])
        self.assertEqual(decode_config(expected)['schedules'][0]['days'],[0,2])
        self.assertEqual(len([q for q in s.queue if q[0]==5]),6)
    def test_power_source_mapping_and_signed_watts(self):
        p=Power({'grid':{'serial':55,'channel':1}})
        r=bytearray(24);struct.pack_into('<H',r,2,0x3730);struct.pack_into('<I',r,10,55)
        r[14:22]=struct.pack('<BBBBhh',8,0x11,1,0,-400,500)
        p.observe(r,'ethernet');self.assertEqual(p.status()['grid']['watts'],-400)
        p.values['grid']['received_at']-=31;self.assertIsNone(p.status()['grid'])
