"""Local Zappi relay, session observation and explicit local mode control."""
import asyncio, collections, http.server, json, os, pathlib, signal, socket, threading, time
from control import Control
from mqtt_events import Publisher

class Relay:
    def __init__(self, config, state_dir):
        self.config = config
        self.state_dir = pathlib.Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.flag_path = self.state_dir / 'forwarding.json'
        self.forward = config.get('forward_upstream', True)
        if self.flag_path.exists():
            self.forward = json.loads(self.flag_path.read_text())['forward_upstream']
        if type(self.forward) is not bool:
            raise ValueError('forward_upstream must be a boolean')
        self.started = time.time()
        self.counts = collections.Counter()
        self.sessions = {}
        self.latest = {}
        self.transports = []
        self.telemetry_socket = None
        self.capture = self.state_dir / 'traffic.jsonl'
        self.control = Control(self.state_dir)
        self.mqtt = Publisher(config.get('mqtt'), self.control.serial, self.state_dir)
        self.control.emit = self.mqtt.event
        self.control.telemetry = self.mqtt.telemetry

    def record(self, direction, data, **fields):
        # Bounded journal: at most roughly 2 x 10 MiB.
        if self.capture.exists() and self.capture.stat().st_size > 10 * 1024 * 1024:
            os.replace(self.capture, self.capture.with_suffix('.jsonl.1'))
        with self.capture.open('a') as f:
            f.write(json.dumps(dict(time=time.time(), direction=direction, hex=data.hex(), **fields))+'\n')

    def set_forwarding(self, value):
        if type(value) is not bool:
            raise ValueError('forward_upstream must be a JSON boolean')
        temp = self.flag_path.with_suffix('.tmp')
        with temp.open('w') as f:
            json.dump({'forward_upstream': value}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, self.flag_path)
        self.forward = value
        if not value:
            self.control.cancel_pending()
            for s in self.sessions.values():
                if s.transport: s.transport.close()
            self.sessions.clear()
        self.mqtt.event('forwarding_changed', {'forward_upstream': value})
        return self.status()

    def send_mode(self, mode):
        if not self.forward:
            raise RuntimeError('local control currently requires upstream forwarding')
        return self.control.send_mode(mode)

    def mqtt_command(self, mode):
        # Paho callbacks run on its network thread; all control stays on the relay loop.
        self.loop.call_soon_threadsafe(self.handle_mqtt_command, mode)

    def handle_mqtt_command(self, mode):
        try:
            self.send_mode(mode)
        except (ValueError, RuntimeError) as exc:
            self.mqtt.event('local_command_rejected', {'mode': mode, 'error': str(exc)})

    def status(self):
        return dict(forward_upstream=self.forward, offline_control_supported=False,
                    uptime_seconds=int(time.time()-self.started), counters=dict(self.counts),
                    sessions=len(self.sessions), last_telemetry=self.latest,
                    routes=self.config['routes'], protocol=self.control.status(), mqtt=self.mqtt.status())

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.mqtt.command = self.mqtt_command
        self.mqtt.start()
        self.mqtt_task = asyncio.create_task(self.publish_mqtt_state())
        for route in self.config['routes']:
            t, _ = await self.loop.create_datagram_endpoint(
                lambda r=route: Downstream(self, r),
                local_addr=(self.config['bind'], route['listen_port']))
            self.transports.append(t)
        if self.config.get('telemetry_interface'):
            from telemetry import records
            s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x88b5))
            s.bind((self.config['telemetry_interface'], 0)); s.setblocking(False)
            self.telemetry_socket = s
            self.loop.add_reader(s.fileno(), self.read_telemetry, records)
        self.expirer = asyncio.create_task(self.expire())

    async def publish_mqtt_state(self):
        while True:
            if self.mqtt.enabled:
                self.mqtt.publish('state', dict(schema_version=1, published_at=time.time(), **self.status()))
            await asyncio.sleep(5)

    def read_telemetry(self, records):
        try:
            data = self.telemetry_socket.recv(65535)
            if data[6:12].hex(':') != self.config['device_mac']: return
            for rec in records(data):
                if rec['type'] not in ('0x3510','0x3730'): rec.pop('origin_serial', None)
                rec['received_at'] = time.time()
                key = rec['type'] + ':' + str(rec.get('harvi_serial', rec.get('origin_serial', '')))
                self.control.observe_device_record(bytes.fromhex(rec['raw']), 'ethernet')
                self.latest[key] = rec
                self.counts['telemetry_records'] += 1
                self.mqtt.telemetry('ethernet', rec)
            self.record('ethernet', data)
        except (ValueError, OSError):
            self.counts['telemetry_errors'] += 1

    async def expire(self):
        while True:
            await asyncio.sleep(30)
            for key, s in list(self.sessions.items()):
                if time.monotonic()-s.last_seen > 300:
                    if s.transport: s.transport.close()
                    self.sessions.pop(key, None)

    async def close(self):
        self.expirer.cancel()
        self.mqtt_task.cancel()
        await asyncio.to_thread(self.mqtt.close)
        for t in self.transports: t.close()
        for s in self.sessions.values():
            if s.transport: s.transport.close()
        if self.telemetry_socket:
            self.loop.remove_reader(self.telemetry_socket.fileno())
            self.telemetry_socket.close()

class Downstream(asyncio.DatagramProtocol):
    def __init__(self, relay, route): self.relay, self.route = relay, route
    def connection_made(self, transport): self.transport = transport
    def datagram_received(self, data, addr):
        r = self.relay
        if addr[0] not in r.config['allowed_clients']:
            r.counts['rejected_clients'] += 1; return
        r.counts['device_packets'] += 1
        r.record('device', data, route=self.route['name'], peer=addr)
        r.control.device(data, self, addr)
        if not r.forward:
            r.counts['blocked_device_packets'] += 1; return
        key = (self.route['name'], addr)
        s = r.sessions.get(key)
        if s is None:
            if len(r.sessions) >= 32:
                r.counts['session_limit_drops'] += 1; return
            s = Upstream(r, self, addr, key)
            r.sessions[key] = s
            asyncio.create_task(s.connect())
        s.last_seen = time.monotonic()
        if s.transport: s.send(data)
        elif len(s.pending) < 32: s.pending.append(data)
        else: r.counts['pending_drops'] += 1
    def error_received(self, exc): self.relay.counts['downstream_errors'] += 1

class Upstream(asyncio.DatagramProtocol):
    def __init__(self, relay, downstream, peer, key):
        self.relay, self.downstream, self.peer, self.key = relay, downstream, peer, key
        self.transport = None; self.pending = []; self.last_seen = time.monotonic()
    async def connect(self):
        r = self.relay
        try:
            route = self.downstream.route
            transport, _ = await r.loop.create_datagram_endpoint(
                lambda: self, remote_addr=(route['upstream_ip'], route.get('upstream_port',87)))
            if not r.forward or r.sessions.get(self.key) is not self:
                transport.close(); return
            self.transport = transport
            for data in self.pending: self.send(data)
            self.pending.clear()
        except OSError:
            r.counts['connect_errors'] += 1
            if r.sessions.get(self.key) is self: r.sessions.pop(self.key, None)
    def send(self, data):
        if self.relay.forward and self.relay.sessions.get(self.key) is self:
            self.transport.sendto(data)
            self.relay.counts['upstream_sent'] += 1
    def datagram_received(self, data, addr):
        r = self.relay
        if not r.forward or r.sessions.get(self.key) is not self: return
        self.last_seen = time.monotonic()
        r.counts['upstream_received'] += 1
        r.record('upstream', data, route=self.downstream.route['name'], peer=addr)
        r.control.upstream(data, self.downstream.route['name'])
        self.downstream.transport.sendto(data, self.peer)
        r.counts['device_replies'] += 1
    def error_received(self, exc): self.relay.counts['upstream_errors'] += 1

def make_handler(relay):
    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self):
            super().setup(); self.connection.settimeout(5)
        def log_message(self, *args): pass
        def reply(self, code, value):
            b = json.dumps(value).encode(); self.send_response(code)
            self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            if self.path in ('/', '/dashboard.js'):
                name = 'index.html' if self.path == '/' else 'dashboard.js'
                b = (pathlib.Path(__file__).parent/'web'/name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8' if name.endswith('.html') else 'text/javascript; charset=utf-8')
                self.send_header('Content-Length', str(len(b)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
                self.end_headers(); self.wfile.write(b)
                return
            if self.path == '/health': self.reply(200, {'ok':True}); return
            if self.path != '/status': self.reply(404, {'error':'not found'}); return
            async def status(): return relay.status()
            value = asyncio.run_coroutine_threadsafe(status(), relay.loop).result(5)
            self.reply(200, value)
        def do_POST(self):
            if self.path not in ('/config', '/mode'): self.reply(404, {'error':'not found'}); return
            try:
                n = int(self.headers.get('Content-Length','0'))
                if not 0 < n <= 1024: raise ValueError('invalid body length')
                body = json.loads(self.rfile.read(n))
                if self.path == '/mode':
                    if not isinstance(body, dict) or set(body) != {'mode'} or not isinstance(body['mode'], str):
                        raise ValueError('expected mode only')
                    async def command():
                        return relay.send_mode(body['mode'])
                    value = asyncio.run_coroutine_threadsafe(command(), relay.loop).result(5)
                    self.reply(202, value)
                    return
                if not isinstance(body,dict) or set(body) != {'forward_upstream'}: raise ValueError('expected forward_upstream only')
                if type(body['forward_upstream']) is not bool: raise ValueError('boolean required')
                async def update(): return relay.set_forwarding(body['forward_upstream'])
                value = asyncio.run_coroutine_threadsafe(update(), relay.loop).result(5)
                self.reply(200,value)
            except (ValueError, KeyError) as exc: self.reply(400, {'error':str(exc)})
            except RuntimeError as exc: self.reply(409, {'error':str(exc)})
    return Handler

async def main():
    config = json.loads(pathlib.Path(os.environ.get('LOCAL_ZAPPI_CONFIG','/data/config.json')).read_text())
    relay = Relay(config, os.environ.get('LOCAL_ZAPPI_DATA','/data'))
    await relay.start()
    httpd = http.server.ThreadingHTTPServer((config.get('admin_bind','127.0.0.1'),config.get('admin_port',18087)),make_handler(relay))
    threading.Thread(target=httpd.serve_forever,daemon=True).start()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        relay.loop.add_signal_handler(sig, stop.set)
    try: await stop.wait()
    finally:
        await asyncio.to_thread(httpd.shutdown)
        httpd.server_close()
        await relay.close()

if __name__ == '__main__': asyncio.run(main())
