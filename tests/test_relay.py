import asyncio, json, tempfile, unittest
from server import Relay

class QueueProtocol(asyncio.DatagramProtocol):
    def __init__(self): self.queue = asyncio.Queue()
    def connection_made(self,t): self.transport=t
    def datagram_received(self,data,peer): self.queue.put_nowait((data,peer))

class RelayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop=asyncio.get_running_loop();self.tmp=tempfile.TemporaryDirectory()
        self.up,self.up_p=await self.loop.create_datagram_endpoint(QueueProtocol,local_addr=('127.0.0.1',0))
        cfg=dict(allow_firmware_forwarding=True,bind='127.0.0.1',allowed_clients=['127.0.0.1'],forward_upstream=True,
                 routes=[dict(name='test',listen_port=0,upstream_ip='127.0.0.1',upstream_port=self.up.get_extra_info('sockname')[1])])
        self.r=Relay(cfg,self.tmp.name);await self.r.start()
        self.client,self.client_p=await self.loop.create_datagram_endpoint(QueueProtocol,local_addr=('127.0.0.1',0))
        self.dest=self.r.transports[0].get_extra_info('sockname')
    async def asyncTearDown(self):
        self.client.close();self.up.close();await self.r.close();self.tmp.cleanup()
    async def exchange(self,data):
        self.client.sendto(data,self.dest)
        seen,peer=await asyncio.wait_for(self.up_p.queue.get(),1)
        self.assertEqual(data,seen)
        reply=b'\x00reply\xff'+data
        self.up.sendto(reply,peer)
        actual,_=await asyncio.wait_for(self.client_p.queue.get(),1)
        self.assertEqual(reply,actual)
        return peer
    async def test_binary_roundtrip_and_session_reuse(self):
        first=await self.exchange(bytes(range(256)))
        second=await self.exchange(b'next')
        self.assertEqual(first,second)
        self.assertEqual(self.r.counts['device_replies'],2)
    async def test_disable_blocks_both_directions_and_persists(self):
        peer=await self.exchange(b'initial')
        self.r.set_forwarding(False)
        self.up.sendto(b'late-reply',peer)
        self.client.sendto(b'must-not-forward',self.dest)
        with self.assertRaises(asyncio.TimeoutError): await asyncio.wait_for(self.up_p.queue.get(),.1)
        with self.assertRaises(asyncio.TimeoutError): await asyncio.wait_for(self.client_p.queue.get(),.1)
        restored=Relay(self.r.config,self.tmp.name)
        self.assertFalse(restored.forward)
        self.r.set_forwarding(True)
        await self.exchange(b'restored')
    async def test_client_allowlist(self):
        self.r.config['allowed_clients']=[]
        self.client.sendto(b'wrong-client',self.dest)
        with self.assertRaises(asyncio.TimeoutError): await asyncio.wait_for(self.up_p.queue.get(),.1)
        self.assertEqual(self.r.counts['rejected_clients'],1)
    async def test_boolean_validation(self):
        for value in ('false',0,1,None):
            with self.assertRaises(ValueError):self.r.set_forwarding(value)
        self.assertTrue(self.r.forward)

if __name__=='__main__':unittest.main()
