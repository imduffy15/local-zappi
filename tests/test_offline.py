import asyncio
import json
import pathlib
import struct
import time
from test_relay import RelayTest
from protocol import crypt, open_packet, validate_server_packet, KeyRecord
from offline import Offline


class OfflineTest(RelayTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.key=bytes(range(32));self.bootstrap=bytes(reversed(range(32)))
        self.r.control.serial=12345678
        self.r.control.install_key(self.key)
        path=pathlib.Path(self.tmp.name)/'bootstrap.json'
        path.write_text(json.dumps({'serial':12345678,'product':3562,'version':5794,
                                    'bootstrap_key_hex':self.bootstrap.hex()}));path.chmod(0o600)
        self.r.offline=Offline(self.r.control,self.tmp.name)
        self.r.set_forwarding(False)

    async def packet(self, data):
        self.client.sendto(data,self.dest)
        reply,_=await asyncio.wait_for(self.client_p.queue.get(),1)
        self.assertEqual(self.r.counts['upstream_sent'],0)
        return reply

    def poll(self, mode=0):
        p=bytearray(64)
        struct.pack_into('<III',p,0,0xfacecacf,0x104cb,12345678)
        p[31]=0xe3
        struct.pack_into('<BBHBBI',p,32,23,0x81,0x3510,0x50,255,12345678)
        p[55]=mode
        p[16:]=crypt(bytes(p[16:]),self.key)
        return bytes(p)

    async def test_offline_handshake_without_cloud_and_control_after_restart(self):
        p=bytearray(192)
        struct.pack_into('<4I',p,0,0xa5a5f001,12345678,3,3562|5794<<16)
        struct.pack_into('<I',p,148,0x3a4b5c6d)
        reply=await self.packet(p)
        self.assertEqual(int.from_bytes(reply[8:12],'little'),0x407)
        struct.pack_into('<I',p,8,0x850016a2)
        reply=await self.packet(p[:16]+crypt(p[16:],self.bootstrap))
        self.assertEqual(KeyRecord.decode(open_packet(reply,self.bootstrap)[32:]).key,self.key)
        struct.pack_into('<I',p,8,0x105ab)
        validate_server_packet(open_packet(await self.packet(p[:16]+crypt(p[16:],self.key)),self.key))
        self.assertTrue(self.r.offline.negotiator.established)
        reply=validate_server_packet(open_packet(await self.packet(self.poll()),self.key))
        self.assertEqual(struct.unpack_from('<HH',reply,28),(33,2))
        self.assertTrue(self.r.control.ready())
        self.assertEqual(self.r.control.verified_at,0)
        self.r.send_mode('fast')
        command=open_packet(await self.packet(self.poll()),self.key)
        self.assertEqual(command[66],1)
        await self.client_p.queue.get() # keepalive follows command
        await self.packet(self.poll(1))
        self.assertEqual(self.r.control.last_local_command['status'],'confirmed')
        from server import Relay
        restored=Relay(self.r.config,self.tmp.name)
        self.assertFalse(restored.forward)
        self.assertTrue(restored.offline.supported)
        self.assertFalse(restored.control.ready())
        self.assertEqual(restored.control.key,self.key)

    async def test_invalid_packet_does_not_refresh_offline_readiness(self):
        await self.packet(self.poll())
        p=bytearray(self.poll());p[31]^=1
        self.client.sendto(p,self.dest)
        with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(self.client_p.queue.get(),.1)
        self.assertFalse(self.r.control.ready())

    # Base relay tests exercise forwarding explicitly.
    async def test_binary_roundtrip_and_session_reuse(self):
        self.r.set_forwarding(True)
        await super().test_binary_roundtrip_and_session_reuse()
    async def test_disable_blocks_both_directions_and_persists(self):
        self.r.set_forwarding(True)
        await super().test_disable_blocks_both_directions_and_persists()
    async def test_boolean_validation(self):
        self.r.set_forwarding(True)
        await super().test_boolean_validation()
