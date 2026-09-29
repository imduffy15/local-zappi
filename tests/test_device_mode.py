import struct
from unittest.mock import patch
import unittest
import test_control


class DeviceModeTests(unittest.TestCase):
    setUp = test_control.ControlTests.setUp
    def record(self, mode, serial=12345678, device=0x50):
        b=bytearray(24)
        struct.pack_into('<BBHBBI',b,0,23,0x81,0x3510,device,255,serial)
        b[23]=0xa0|mode
        return bytes(b)

    def test_reported_modes_from_both_sources_and_identity_filter(self):
        for mode,name in enumerate(('stop','fast','eco','eco_plus')):
            for source in ('udp','ethernet'):
                self.c.observe_device_record(self.record(mode),source)
                self.assertEqual(self.c.device_mode['mode'],name)
                self.assertEqual(self.c.device_mode['source'],source)
        old=dict(self.c.device_mode)
        for b in (self.record(1,serial=7654321), self.record(1,device=0x58),self.record(1)[:23]):
            self.c.observe_device_record(b,'udp')
            self.assertEqual(self.c.device_mode,old)

    def test_request_does_not_change_mode_and_matching_readback_confirms(self):
        events=[];self.c.emit=lambda *event:events.append(event)
        with patch('control.time.time',return_value=100):
            self.c.observe_device_record(self.record(0),'udp')
        self.c.last_local_command={'mode':'fast','sent_at':101,'status':'sent_unconfirmed'}
        with patch('control.time.time',return_value=102):
            self.c.observe_device_record(self.record(0),'ethernet')
            self.assertEqual(self.c.device_mode['mode'],'stop')
            self.assertEqual(self.c.last_local_command['status'],'sent_unconfirmed')
        with patch('control.time.time',return_value=103):
            self.c.observe_device_record(self.record(1),'ethernet')
            self.assertEqual(self.c.last_local_command['status'],'confirmed')
            self.assertEqual(self.c.last_local_command['confirmed_at'],103)
        self.assertEqual(sum(e[0]=='local_command_confirmed' for e in events),1)

    def test_timeout_never_claims_success_and_late_mode_is_still_displayed(self):
        self.c.last_local_command={'mode':'fast','sent_at':100,'status':'sent_unconfirmed'}
        with patch('control.time.time',return_value=131):
            self.c.observe_device_record(self.record(0),'udp')
            self.assertEqual(self.c.status()['last_local_command']['status'],'not_confirmed')
        with patch('control.time.time',return_value=132):
            self.c.observe_device_record(self.record(1),'udp')
            self.assertEqual(self.c.device_mode['mode'],'fast')
            self.assertEqual(self.c.last_local_command['status'],'not_confirmed')

    def test_no_telemetry_also_times_out(self):
        self.c.last_local_command={'mode':'fast','sent_at':100,'status':'sent_unconfirmed'}
        with patch('control.time.time',return_value=131):
            self.assertEqual(self.c.status()['last_local_command']['status'],'not_confirmed')
