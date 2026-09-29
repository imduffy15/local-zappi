import unittest
import struct
from protocol import crypt
from firmware_policy import permitted

class FirmwarePolicyTests(unittest.TestCase):
    def test_default_drop_update_envelopes_and_unknown_packets(self):
        for magic in (0xab1234dd,0xab1234ee,0xab1234ff,0xdeadbeef):
            packet=struct.pack('<I',magic)+bytes(60)
            for direction in ('device','upstream'):
                self.assertFalse(permitted(packet,direction,bytes(32)))
    def test_drop_firmware_advertisement_but_allow_mode_command(self):
        key=bytes(32);packet=bytearray(80)
        struct.pack_into('<4I',packet,0,0xab1234d2,0x104cb,1,123)
        struct.pack_into('<IIIHH',packet,16,1,123,1,70,3)
        struct.pack_into('<H',packet,38,2)
        wire=lambda:bytes(packet[:16])+crypt(bytes(packet[16:]),key)
        self.assertTrue(permitted(wire(),'upstream',key))
        struct.pack_into('<H',packet,38,6)
        self.assertFalse(permitted(wire(),'upstream',key))
        struct.pack_into('<H',packet,30,2)
        packet[32]=0x3e
        self.assertFalse(permitted(wire(),'upstream',key))

    def test_upgrade_opt_in_is_independent_from_normal_forwarding(self):
        import tempfile
        from server import Relay
        route={'name':'firmware-primary'}
        packet=struct.pack('<I',0xab1234ee)+bytes(60)
        with tempfile.TemporaryDirectory() as directory:
            relay=Relay({'routes':[],'forward_upstream':True},directory)
            self.assertFalse(relay.forwards(route))
            self.assertFalse(relay.allows_packet(packet,'device',route))
            relay.allow_firmware=True
            self.assertTrue(relay.forwards(route))
            self.assertTrue(relay.allows_packet(packet,'device',route))
            relay.forward=False
            self.assertTrue(relay.forwards(route))
            self.assertFalse(relay.forwards({'name':'director-primary'}))
