import json
import os
import pathlib
import struct
import tempfile
import time
import unittest
from control import Control
from protocol import crypt, open_packet


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = bytes(range(32))
        p = pathlib.Path(self.temp.name)/'session-keys.json'
        p.write_text(json.dumps({'serial':12345678, 'session_key_hex': self.key.hex()}))
        p.chmod(0o600)
        self.c = Control(self.temp.name)

    def test_explicit_mode_only_and_stale_session_rejection(self):
        with self.assertRaises(RuntimeError): self.c.mode_packet('fast')
        self.c.peer=(None,('127.0.0.1',1234)); self.c.peer_at=self.c.verified_at=time.time()
        self.c.target=(0x81,0x50)
        for mode,value in [('fast',1),('eco',2),('eco_plus',3),('stop',4)]:
            p=open_packet(self.c.mode_packet(mode),self.key)
            self.assertEqual(struct.unpack_from('<HH',p,28),(70,3))
            self.assertEqual(p[32:40].hex(),'26816b6b01500200')
            self.assertEqual(p[42:66],bytes(24))
            self.assertEqual(p[66:70],bytes((value,1,0,0)))
        self.c.verified_at-=31
        with self.assertRaises(RuntimeError):self.c.mode_packet('stop')
        with self.assertRaises(ValueError):self.c.mode_packet('reset')

    def test_corrupt_upstream_invalidates_session(self):
        p=bytearray(64)
        struct.pack_into('<4I',p,0,0xab1234d2,0x104cb,0,12345678)
        struct.pack_into('<IIIHH',p,16,21,12345678,1700000000,60,1)
        p[16:]=crypt(bytes(p[16:]),self.key)
        self.c.upstream(bytes(p));self.assertGreater(self.c.verified_at,0)
        p[20]^=1;self.c.upstream(bytes(p));self.assertEqual(self.c.verified_at,0)
        self.assertEqual(self.c.counts['upstream_decode_rejected'],1)
        self.assertNotIn(self.key.hex(),json.dumps(self.c.status()))

    def test_private_file_permissions(self):
        (pathlib.Path(self.temp.name)/'session-keys.json').chmod(0o644)
        with self.assertRaises(ValueError):Control(self.temp.name)
