import json
import tempfile
import types
import unittest
from mqtt_events import Publisher


class Client:
    def __init__(self): self.messages = []
    def subscribe(self, topic, qos): self.subscription = (topic, qos)
    def publish(self, topic, payload, **options):
        self.messages.append((topic, payload, options))
        return types.SimpleNamespace(rc=0)


class MQTTTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p = Publisher({'enabled': True, 'home_assistant_discovery': True}, 1234, self.tmp.name)
        self.p.client = Client()

    def test_no_backlog_when_broker_down_and_no_event_retention(self):
        self.assertFalse(self.p.event('local_command_sent', {'mode': 'stop', 'status': 'sent_unconfirmed'}))
        self.assertFalse(self.p.client.messages)
        self.p.connected = True
        self.assertTrue(self.p.event('local_command_sent', {'mode': 'stop', 'status': 'sent_unconfirmed'}))
        topic, payload, opts = self.p.client.messages[-1]
        self.assertEqual(topic, 'local-zappi/1234/events')
        self.assertEqual(opts, {'qos': 1, 'retain': False})
        data = json.loads(payload)
        self.assertEqual(data['data']['status'], 'sent_unconfirmed')
        self.assertEqual(len(data['event_id']), 32)

    def test_connect_discovery_and_availability(self):
        self.p.on_connect(self.p.client, None, None, types.SimpleNamespace(is_failure=False), None)
        self.assertTrue(self.p.connected)
        topic, payload, opts = self.p.client.messages[0]
        self.assertEqual((topic, payload), ('local-zappi/1234/availability', 'online'))
        self.assertTrue(opts['retain'])
        discovery = [json.loads(payload) for topic, payload, opts in self.p.client.messages if topic.startswith('homeassistant/')]
        self.assertEqual(len(discovery), 3)
        self.assertEqual(self.p.client.subscription, ('local-zappi/1234/mode/set', 1))
        control = discovery[-1]
        self.assertFalse(control['optimistic'])
        self.assertFalse(control['retain'])
        self.assertEqual(control['command_topic'], 'local-zappi/1234/mode/set')
        self.p.on_disconnect(None, None, None, None, None)
        self.assertFalse(self.p.connected)

    def test_telemetry_routes_without_false_units(self):
        self.p.connected = True
        self.p.telemetry('ethernet', {'type': '0x3730', 'harvi_serial': 5678, 'ct_records': [{'value_a_s16': 9}]})
        topic, payload, opts = self.p.client.messages[-1]
        self.assertEqual(topic, 'local-zappi/1234/telemetry/ethernet/0x3730/5678')
        self.assertNotIn('watts', payload)
        self.assertEqual(opts, {'qos': 0, 'retain': False})

    def test_publish_failures_do_not_escape(self):
        self.p.connected = True
        self.assertFalse(self.p.publish('state', object()))
        self.assertEqual(self.p.counts['publish_errors'], 1)

    def test_commands_reject_retained_and_invalid_payloads(self):
        received = []
        self.p.command = received.append
        self.p.connected = True
        def message(payload, retain=False):
            self.p.on_message(None, None, types.SimpleNamespace(
                topic=self.p.prefix+'/mode/set', payload=payload, retain=retain))
        message(b'fast', True)
        message(b'garbage')
        message(b'\xff')
        self.assertEqual(received, [])
        message(b'fast')
        self.assertEqual(received, ['fast'])
        self.assertEqual(self.p.counts['retained_commands_ignored'], 1)

    def test_control_unavailable_without_forwarding_or_fresh_state(self):
        import time
        self.p.connected = True
        state = {'forward_upstream': True, 'protocol': {'local_mode_control_ready': True,
                 'device_mode': {'mode': 'stop', 'received_at': time.time()}}}
        for forward, timestamp, expected in [(True, time.time(), 'online'),
                (False, time.time(), 'offline'), (True, 0, 'offline')]:
            state['forward_upstream'] = forward
            state['protocol']['device_mode']['received_at'] = timestamp
            self.p.publish('state', state)
            self.assertEqual(self.p.client.messages[-2][1], expected)
