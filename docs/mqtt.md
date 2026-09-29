# MQTT reporting

Enable `mqtt.enabled` and configure `mqtt.host` in the server configuration.
The default topic prefix is `local-zappi/<serial>`. MQTT reporting is outbound
only: publishing a message to this namespace cannot execute charger commands.

| Topic suffix | Contents | QoS | Retained |
| --- | --- | --- | --- |
| `events` | JSON events with an ID, timestamp, serial, event name and data | 1 | No |
| `state` | Full dashboard snapshot, including latest telemetry, every 5 seconds | 0 | No |
| `telemetry/ethernet/<type>/<node>` | Each observed Ethernet telemetry record | 0 | No |
| `telemetry/udp/<type>/<node>` | Each decoded UDP telemetry record | 0 | No |
| `availability` | `online` / `offline`; offline Last Will and graceful shutdown | 1 | Yes |

Events include `bridge_connected`, `local_command_sent`, `cloud_command_observed`
and `forwarding_changed`. Command events carry `sent_unconfirmed` or
`observed_unconfirmed`; neither means that the charger applied the command.
Configuration-chunk observations include region, offset and size. The `state`
snapshot includes the last completely observed minimum-green setting, if any.
Raw CT values retain their original labels; physical units are not yet verified.

Example event (illustrative serial and ID):

```json
{"schema_version":1,"event_id":"unique-id","time":1790666000,"serial":12345678,"event":"local_command_sent","data":{"mode":"stop","sequence":1,"sent_at":1790666000,"status":"sent_unconfirmed"}}
```

QoS 1 can deliver duplicates; consumers should deduplicate by `event_id`.
This is a live stream, not a durable audit queue. Messages produced while
disconnected are dropped and counted. The MQTT client's pending queue is bounded
at 256 messages, reconnects use backoff, and MQTT networking runs separately from
the charger relay. The next state snapshot supplies current observations after
reconnection. Events are never retained or replayed from the traffic journal.
Do not use a command-observed event as an automation trigger that sends the same
command back, which would create a feedback loop.

## Home Assistant

With `mqtt.home_assistant_discovery: true`, the server publishes retained
discovery configuration for two read-only diagnostic binary sensors on a
**Local Zappi** device: **App forwarding** and **Local control ready**. Both use
availability and expire after 30 seconds without state updates. Discovery needs
Home Assistant's MQTT integration connected to the same broker. No Home Assistant
restart or charger firmware change is required.

For automation triggers, subscribe to `local-zappi/<serial>/events` and filter
the JSON `event` and `data` fields. For the entire stream:

```sh
mosquitto_sub -h mqtt.example.lan -t 'local-zappi/12345678/#' -v
```

The dashboard shows MQTT connection state and publish/drop counters. Access keys,
session keys and broker credentials are never included in MQTT messages.

## Authentication and TLS

By default the client uses port 1883 and the broker's existing authentication
policy. For authenticated brokers, create a private `mqtt-credentials.json` in
the data directory, mode 0600, containing `username` and `password`. Do not put
credentials in the public configuration. Set `mqtt.tls: true` and the appropriate
port (usually 8883) to enable certificate-verified TLS.

Implementation references: [Paho client documentation](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)
and [Home Assistant MQTT binary sensors](https://www.home-assistant.io/integrations/binary_sensor.mqtt/).
