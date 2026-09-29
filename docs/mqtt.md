# MQTT reporting

Enable `mqtt.enabled` and configure `mqtt.host` in the server configuration. The default topic prefix is `local-zappi/<serial>`. Publish an unretained UTF-8 `stop`, `fast`, `eco` or `eco_plus` to `local-zappi/<serial>/mode/set` to request a mode change. Commands share HTTP readiness checks and device confirmation. Retained commands are ignored; invalid or unavailable requests emit `local_command_rejected`.

| Topic suffix | Contents | QoS | Retained |
| --- | --- | --- | --- |
| `mode/set` | Incoming mode request | 1 | Never |
| `control/availability` | Whether fresh state and mode control are available | 1 | No |
| `events` | JSON events with an ID, timestamp, serial, event name and data | 1 | No |
| `state` | Full dashboard snapshot, including latest telemetry, every 5 seconds | 0 | No |
| `telemetry/ethernet/<type>/<node>` | Each observed Ethernet telemetry record | 0 | No |
| `telemetry/udp/<type>/<node>` | Each decoded UDP telemetry record | 0 | No |
| `availability` | `online` / `offline`; offline Last Will and graceful shutdown | 1 | Yes |

Events distinguish requests, device reports and request outcomes:

| Event | Meaning |
| --- | --- |
| `bridge_connected` | MQTT connection established; includes the process boot ID |
| `forwarding_changed` | Relay forwarding setting changed |
| `session_key_recovered` | A supported handshake produced a validated replacement key during runtime |
| `cloud_command_observed` | Decoded cloud request, with `observed_unconfirmed` status |
| `local_command_rejected` | Invalid MQTT request or control unavailable |
| `local_command_queued` | Accepted request waiting for the next valid charger poll |
| `local_command_sent` | Local request transmitted, with `sent_unconfirmed` status |
| `device_mode_observed` | First device-mode report or a change in reported mode |
| `local_command_confirmed` | Fresh device telemetry matched the local request within 30 seconds |
| `local_command_not_confirmed` | No matching report arrived within the 30-second confirmation window |

A sent or observed command does not prove that the charger applied it. A confirmation proves that matching state was subsequently reported, not which actor caused the change. Mode events indicate a charging policy, not actual power consumption. State snapshots include the latest `protocol.device_mode`, its receipt time and source, and `protocol.last_local_command` with its current status.

Check report timestamps before treating snapshot values as current. The dashboard treats mode reports at least 30 seconds old as stale; MQTT consumers must apply their own freshness check. `device_mode_observed` fires on changes, not every repeated report. Startup key recovery happens before MQTT connects and is available in state/counters rather than a replayed event.

Configuration-chunk observations include region, offset and size. The state snapshot includes the last complete observed minimum-green setting, if available; the relay does not request it. Raw CT values retain their original labels because physical units remain unverified.

Example event (illustrative serial and ID):

```json
{"schema_version":1,"event_id":"unique-id","time":1790666000,"serial":12345678,"event":"local_command_sent","data":{"mode":"stop","sequence":1,"sent_at":1790666000,"status":"sent_unconfirmed"}}
```

QoS 1 can deliver duplicates; consumers should deduplicate by `event_id`. This is a live stream, not a durable audit queue. Messages produced while disconnected are dropped and counted. The MQTT client's pending queue is bounded at 256 messages, reconnects use backoff, and MQTT networking runs separately from the charger relay. The next state snapshot supplies current observations after reconnection. Events are never retained or replayed from the traffic journal. Do not use a command-observed event as an automation trigger that sends the same command back, which would create a feedback loop.

## Home Assistant

With `mqtt.home_assistant_discovery: true`, the server publishes retained discovery configuration for a **Charging mode** select, grid and charger power sensors, and two diagnostic binary sensors on a **Local Zappi** device: **App forwarding** and **Local control ready**. The select uses reported device state, never optimistic updates, and becomes unavailable when control readiness or fresh device state is missing. The diagnostics expire after 30 seconds without state updates. Discovery needs Home Assistant's MQTT integration connected to the same broker. No Home Assistant restart or charger firmware change is required.

For automation triggers, subscribe to `local-zappi/<serial>/events` and filter the JSON `event` and `data` fields. For the entire stream:

```sh
mosquitto_sub -h mqtt.example.lan -t 'local-zappi/12345678/#' -v
```

The `/status` API shows MQTT connection state and publish/drop counters. Session keys and broker credentials are never included in MQTT messages.

## Authentication and TLS

By default the client uses port 1883 and the broker's existing authentication policy. For authenticated brokers, create a private `mqtt-credentials.json` in the data directory, mode 0600, containing `username` and `password`. Do not put credentials in the public configuration. Set `mqtt.tls: true` and the appropriate port (usually 8883) to enable certificate-verified TLS.

Implementation references: [Paho client documentation](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) and [Home Assistant MQTT select](https://www.home-assistant.io/integrations/select.mqtt/) and [Home Assistant MQTT binary sensors](https://www.home-assistant.io/integrations/binary_sensor.mqtt/).
