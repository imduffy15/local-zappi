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

    def test_udp_records_use_length_minus_one_and_preserve_all_records(self):
        class Downstream:
            route = {'name': 'test'}
        records=[]
        for kind in (0x3510, 0x7979, 0x7777):
            records.append(struct.pack('<BBHBBI',9,0x81,kind,0x50,1,12345678))
        plain=bytearray(64)
        struct.pack_into('<III',plain,0,0xfacecacf,0,12345678)
        plain[31]=0xe3
        plain[32:62]=b''.join(records)
        plain[16:]=crypt(bytes(plain[16:]),self.key)
        self.c.device(bytes(plain),Downstream(),('127.0.0.1',87))
        self.assertEqual(len(self.c.records),3)
        self.assertEqual(self.c.target,(0x81,0x50))
        self.assertEqual(self.c.counts['record_decode_rejected'],0)
        self.assertEqual(bytes.fromhex(self.c.records['0x7979:80']['raw']),records[1])

    def test_command_counter_and_sequence_follow_observed_command(self):
        self.c.peer=(None,('127.0.0.1',1234))
        self.c.peer_at=self.c.verified_at=time.time();self.c.target=(0x81,0x50)
        self.c.command_counter=7
        p=open_packet(self.c.mode_packet('fast'),self.key)
        self.assertEqual(int.from_bytes(p[16:20],'little'),8)
        self.assertEqual(int.from_bytes(p[40:42],'little'),0)
        self.assertNotEqual(p[8:12],bytes(4))
        row={'direction':'local-command','time':time.time(),'route':'test',
             'hex':(p[:16]+crypt(p[16:],self.key)).hex()}
        (pathlib.Path(self.temp.name)/'traffic.jsonl').write_text(json.dumps(row)+'\n')
        restored=Control(self.temp.name)
        self.assertEqual(restored.command_counter,8)
        self.assertEqual(restored.sequence,0)
        self.assertFalse(restored.ready())

    def test_counter_survives_journal_rotation_and_is_scoped_to_session(self):
        self.c.peer=(None,('127.0.0.1',1234))
        self.c.peer_at=self.c.verified_at=time.time();self.c.target=(0x81,0x50)
        self.c.command_counter=5
        self.c.mode_packet('fast')
        restored=Control(self.temp.name)
        self.assertEqual(restored.command_counter,6)
        self.assertFalse(restored.ready())
        restored.install_key(bytes(reversed(self.key)))
        other=Control(self.temp.name)
        self.assertIsNone(other.command_counter)

    def test_counter_save_failure_prevents_packet_creation(self):
        from unittest.mock import patch
        self.c.peer=(None,('127.0.0.1',1234))
        self.c.peer_at=self.c.verified_at=time.time();self.c.target=(0x81,0x50)
        with patch.object(self.c, 'save_counter', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(RuntimeError, 'command not sent'):
                self.c.mode_packet('fast')

    def test_queued_command_waits_for_device_poll_and_can_be_cancelled(self):
        import types
        sent=[]
        downstream=types.SimpleNamespace(route={'name':'test'},
            transport=types.SimpleNamespace(sendto=lambda *args:sent.append(args)),
            relay=types.SimpleNamespace(record=lambda *args,**kwargs:None))
        self.c.peer=(downstream,('127.0.0.1',1234))
        self.c.peer_at=self.c.verified_at=time.time();self.c.target=(0x81,0x50)
        request=self.c.send_mode('fast')
        self.assertEqual(request['status'],'queued')
        self.assertEqual(sent,[])
        with self.assertRaises(RuntimeError):self.c.send_mode('eco')
        self.c.cancel_pending();self.c.dispatch_pending()
        self.assertEqual(sent,[])
        request=self.c.send_mode('fast')
        plain=bytearray(64)
        struct.pack_into('<III',plain,0,0xfacecacf,0,12345678)
        plain[31]=0xe3
        struct.pack_into('<BBHBBI',plain,32,9,0x81,0x7979,0x50,1,12345678)
        plain[16:]=crypt(bytes(plain[16:]),self.key)
        self.c.device(bytes(plain),downstream,('127.0.0.1',1234))
        self.assertEqual(len(sent),1)
        self.assertEqual(request['status'],'sent_unconfirmed')
        self.c.device(bytes(plain),downstream,('127.0.0.1',1234))
        self.assertEqual(len(sent),1)

    def test_queued_command_expires_without_transmitting(self):
        self.c.last_local_command={'mode':'fast','status':'queued','requested_at':100}
        self.c.expire_command(131)
        self.assertEqual(self.c.last_local_command['status'],'not_confirmed')
