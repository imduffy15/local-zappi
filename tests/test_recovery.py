import json
import pathlib
import struct
import tempfile
import unittest
from unittest.mock import patch
from control import Control
from protocol import HELLO_DEVICE, crypt, hello_reply, KeyRecord
from recovery import SessionRecovery

SERIAL = 123456
OLD = bytes(range(32))
NEW = bytes(reversed(range(32)))


def exchange(key=NEW, serial=SERIAL):
    plain = bytearray(192)
    struct.pack_into('<4I', plain, 0, HELLO_DEVICE, serial, 0x10523, 3562 | 5794 << 16)
    plain[32:96] = bytes(range(64))
    encrypted = bytearray(plain)
    struct.pack_into('<I', encrypted, 8, 0x14006ce)
    encrypted[16:] = crypt(bytes(encrypted[16:]), OLD)
    return [bytes(plain), bytes(encrypted),
            hello_reply(serial, 0x14006ce, 30000000, records=[KeyRecord(key)], key=OLD),
            hello_reply(serial, 0x104cb, 30000000, key=key)]


class RecoveryTests(unittest.TestCase):
    def feed(self, recovery, packets, routes=None, times=None):
        return [recovery.observe('device' if i < 2 else 'upstream', p,
                                 routes[i] if routes else 'a', times[i] if times else i)
                for i, p in enumerate(packets)]

    def test_requires_independent_confirmation(self):
        self.assertEqual(self.feed(SessionRecovery(SERIAL), exchange()), [None, None, None, NEW])
        packets = exchange(); packets[-1] = hello_reply(SERIAL, 0x104cb, 30000000, key=OLD)
        self.assertEqual(self.feed(SessionRecovery(SERIAL), packets), [None]*4)

    def test_rejects_wrong_identity_route_expired_and_corrupt(self):
        self.assertEqual(self.feed(SessionRecovery(SERIAL+1), exchange()), [None]*4)
        self.assertEqual(self.feed(SessionRecovery(SERIAL), exchange(), ['a','a','b','a']), [None]*4)
        self.assertEqual(self.feed(SessionRecovery(SERIAL), exchange(), times=[0,1,2,121]), [None]*4)
        packets=exchange(); bad=bytearray(packets[2]);bad[32]^=1;packets[2]=bytes(bad)
        self.assertEqual(self.feed(SessionRecovery(SERIAL), packets), [None]*4)

    def test_changed_references_do_not_install_key(self):
        packets=exchange();bad=bytearray(packets[1]);bad[80]^=1;packets[1]=bytes(bad)
        self.assertEqual(self.feed(SessionRecovery(SERIAL), packets), [None]*4)

    def test_wrong_direction_and_incomplete_exchange(self):
        r=SessionRecovery(SERIAL)
        for i,p in enumerate(exchange()):
            self.assertIsNone(r.observe('upstream' if i<2 else 'device',p,'a',i))
        r=SessionRecovery(SERIAL)
        for i,p in enumerate(exchange()[1:]):
            self.assertIsNone(r.observe('device' if i==0 else 'upstream',p,'a',i))

    def make_control(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=pathlib.Path(temp.name)/'session-keys.json'
        path.write_text(json.dumps({'serial': SERIAL, 'session_key_hex': OLD.hex()}));path.chmod(0o600)
        return Control(temp.name), path

    def test_live_install_is_private_and_not_ready_until_fresh_data(self):
        c,path=self.make_control()
        for i,p in enumerate(exchange()):
            c.observe_handshake('device' if i<2 else 'upstream', p, 'a')
            if i<3:self.assertEqual(c.key,OLD)
        self.assertEqual(c.key,NEW)
        self.assertEqual(json.loads(path.read_text())['session_key_hex'],NEW.hex())
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertFalse(c.ready())
        self.assertNotIn(NEW.hex(),json.dumps(c.status()))
        self.assertEqual(Control(path.parent).key,NEW)

    def test_save_failure_keeps_old_key_and_disables_control(self):
        c,path=self.make_control()
        with patch('control.os.replace',side_effect=OSError('disk failure')):
            for i,p in enumerate(exchange()):
                c.observe_handshake('device' if i<2 else 'upstream',p,'a')
        self.assertEqual(c.key,OLD)
        self.assertEqual(c.session_state,'recovery_save_failed')
        self.assertFalse(c.ready())
        self.assertEqual(list(path.parent.glob('.session-*')),[])

    def test_startup_replays_rotated_journal_with_latest_verified_key(self):
        c,path=self.make_control()
        rows=[{'direction':'device' if i<2 else 'upstream','hex':p.hex(),'time':i,'route':'a'}
              for i,p in enumerate(exchange())]
        (path.parent/'traffic.jsonl.1').write_text('\n'.join(json.dumps(r) for r in rows[:2])+'\n')
        (path.parent/'traffic.jsonl').write_text('\n'.join(json.dumps(r) for r in rows[2:])+'\n{truncated')
        c=Control(path.parent)
        self.assertEqual(c.key,NEW)
        self.assertFalse(c.ready())
        self.assertEqual(c.counts['session_keys_recovered'],1)

    def test_stale_journal_does_not_replace_key_used_by_latest_reply(self):
        c,path=self.make_control()
        rows=[{'direction':'device' if i<2 else 'upstream','hex':p.hex(),'time':i,'route':'a'}
              for i,p in enumerate(exchange())]
        reply=bytearray(64)
        struct.pack_into('<4I',reply,0,0xab1234d2,0,0,SERIAL)
        struct.pack_into('<IIIHH',reply,16,21,SERIAL,1700000000,60,1)
        reply[16:]=crypt(bytes(reply[16:]),OLD)
        rows.append({'direction':'upstream','hex':reply.hex(),'time':5,'route':'a'})
        (path.parent/'traffic.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        c=Control(path.parent)
        self.assertEqual(c.key,OLD)
        self.assertEqual(c.counts['journal_recovery_rejected'],1)
