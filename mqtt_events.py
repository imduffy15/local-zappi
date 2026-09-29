"""MQTT reporting, mode commands and Home Assistant discovery."""
import collections
import json
import pathlib
import time
import uuid


class Publisher:
    def __init__(self, config, serial, state_dir):
        self.config = config or {}
        self.serial = serial
        self.enabled = self.config.get('enabled', False)
        self.prefix = self.config.get('topic_prefix', f'local-zappi/{serial or "bridge"}').strip('/')
        if not self.prefix or any(c in self.prefix for c in '+#\0'):
            raise ValueError('invalid MQTT topic prefix')
        self.command = None
        self.client = None
        self.connected = False
        self.counts = collections.Counter()
        self.state_dir = pathlib.Path(state_dir)
        self.boot_id = uuid.uuid4().hex

    def start(self):
        if not self.enabled: return
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=self.config.get('client_id', f'local-zappi-{self.serial or "bridge"}'))
        client.max_queued_messages_set(256)
        client.max_inflight_messages_set(20)
        client.reconnect_delay_set(1, 30)
        client.will_set(self.prefix+'/availability', 'offline', qos=1, retain=True)
        credentials = self.state_dir/'mqtt-credentials.json'
        if credentials.exists():
            if credentials.stat().st_mode & 0o077:
                raise ValueError('mqtt-credentials.json must be private (0600)')
            auth = json.loads(credentials.read_text())
            client.username_pw_set(auth['username'], auth['password'])
        if self.config.get('tls', False): client.tls_set()
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        self.client = client
        client.connect_async(self.config['host'], self.config.get('port', 1883), keepalive=30)
        client.loop_start()

    def on_connect(self, client, userdata, flags, reason, properties):
        self.connected = not reason.is_failure
        if not self.connected: return
        self.counts['connections'] += 1
        client.subscribe(self.prefix+'/mode/set', qos=1)
        client.publish(self.prefix+'/availability', 'online', qos=1, retain=True)
        if self.config.get('home_assistant_discovery', False):
            for name, field in [('App forwarding', 'forward_upstream'),
                                ('Local control ready', 'protocol.local_mode_control_ready')]:
                ident = name.lower().replace(' ', '_')
                config = {'name': name, 'unique_id': f'local_zappi_{self.serial}_{ident}',
                    'state_topic': self.prefix+'/state', 'availability_topic': self.prefix+'/availability',
                    'value_template': "{{ 'ON' if value_json."+field+" else 'OFF' }}",
                    'expire_after': 30, 'entity_category': 'diagnostic',
                    'device': {'identifiers': [f'local_zappi_{self.serial}'], 'name': 'Local Zappi',
                               'manufacturer': 'local-zappi', 'model': 'Zappi local bridge'}}
                client.publish(f'homeassistant/binary_sensor/local_zappi_{self.serial}/{ident}/config',
                               json.dumps(config), qos=1, retain=True)
            config = {
                'name': 'Charging mode', 'unique_id': f'local_zappi_{self.serial}_charging_mode',
                'default_entity_id': f'select.local_zappi_{self.serial}_charging_mode',
                'command_topic': self.prefix+'/mode/set', 'state_topic': self.prefix+'/state',
                'value_template': "{{ value_json.protocol.device_mode.mode if value_json.protocol.device_mode else 'None' }}",
                'options': ['stop', 'fast', 'eco', 'eco_plus'], 'optimistic': False,
                'retain': False, 'qos': 1,
                'availability_mode': 'all',
                'availability': [
                    {'topic': self.prefix+'/availability'},
                    {'topic': self.prefix+'/control/availability'}],
                'device': {'identifiers': [f'local_zappi_{self.serial}'], 'name': 'Local Zappi',
                           'manufacturer': 'local-zappi', 'model': 'Zappi local bridge'}}
            client.publish(f'homeassistant/select/local_zappi_{self.serial}/charging_mode/config',
                           json.dumps(config), qos=1, retain=True)
        self.event('bridge_connected', {'boot_id': self.boot_id})

    def on_message(self, client, userdata, message):
        if message.topic != self.prefix+'/mode/set': return
        # Never replay a retained action when reconnecting.
        if message.retain:
            self.counts['retained_commands_ignored'] += 1
            return
        try:
            mode = message.payload.decode('utf-8')
            if mode not in ('stop', 'fast', 'eco', 'eco_plus'):
                raise ValueError('expected stop, fast, eco or eco_plus')
            if self.command is None: raise ValueError('command handler unavailable')
            self.command(mode)
            self.counts['commands_received'] += 1
        except (UnicodeError, ValueError) as exc:
            self.event('local_command_rejected', {'error': str(exc)})

    def on_disconnect(self, client, userdata, flags, reason, properties):
        self.connected = False

    def publish(self, topic, value, qos=0):
        if not self.enabled: return False
        if not self.connected:
            self.counts['dropped_disconnected'] += 1
            return False
        try:
            if topic == 'state' and isinstance(value, dict):
                protocol = value.get('protocol', {})
                observed = protocol.get('device_mode') or {}
                ready = (protocol.get('local_mode_control_ready')
                         and time.time() - observed.get('received_at', 0) < 30)
                self.client.publish(self.prefix+'/control/availability',
                                    'online' if ready else 'offline', qos=1, retain=False)
            result = self.client.publish(self.prefix+'/'+topic,
                json.dumps(value, separators=(',', ':')), qos=qos, retain=False)
            if result.rc != 0:
                self.counts['publish_errors'] += 1
                return False
            self.counts['published'] += 1
            return True
        except (ValueError, TypeError, OSError):
            self.counts['publish_errors'] += 1
            return False

    def event(self, kind, data):
        return self.publish('events', {'schema_version': 1, 'event_id': uuid.uuid4().hex,
            'time': time.time(), 'serial': self.serial, 'event': kind, 'data': data}, qos=1)

    def telemetry(self, source, record):
        node = record.get('harvi_serial', record.get('origin_serial', record.get('device_byte', 'unknown')))
        return self.publish(f'telemetry/{source}/{record["type"]}/{node}',
                            {'schema_version': 1, 'serial': self.serial, 'source': source, **record})

    def status(self):
        return {'enabled': self.enabled, 'connected': self.connected,
                'topic_prefix': self.prefix, 'counters': dict(self.counts)}

    def close(self):
        if self.client is None: return
        if self.connected:
            try:
                self.client.publish(self.prefix+'/availability', 'offline', qos=1, retain=True).wait_for_publish(timeout=2)
            except (RuntimeError, ValueError): pass
        self.client.disconnect()
        self.client.loop_stop()
        self.connected = False
