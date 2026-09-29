# local-zappi

Control a myenergi Zappi over your local network, read its reported charging mode, and keep the official app connected through a UDP relay. The dashboard supports Fast, Eco, Eco+ and Stop requests, confirms them from device telemetry, and publishes observations to MQTT.

Commands travel directly from this server to the charger. With private bootstrap provisioning, the server handles the charger session locally when cloud forwarding is disabled. The dashboard shows live grid and charger power, charging mode, manual/smart boost controls and four editable scheduled timers. Home Assistant can record the MQTT readings; this service does not maintain consumption or charge history.

## What works today

| Capability | Current behavior |
| --- | --- |
| Local mode control | Fast, Eco, Eco+ and Stop; HTTP API and dashboard without login |
| Device mode readback | Ethernet or decrypted UDP telemetry drives the displayed mode, including physical-device changes |
| Command confirmation | Requests wait for a charger poll, then matching telemetry; each stage times out after 30 seconds |
| Reconnect recovery | Automatically recovers keys from supported complete cloud handshakes, including captured exchanges found at startup |
| Official app coexistence | Optional forwarding of supported control traffic; existing cloud automations can still change the mode |
| MQTT | Telemetry, state, mode commands, outcomes and Home Assistant discovery |
| ECO+ allowance | Read from native charger configuration; no minimum-green setter |
| Boost and schedules | Manual/smart boost, cancellation, and four native timer slots; acknowledgement and configuration readback |
| Independent offline operation | Local handshake, keepalives and controls with private bootstrap provisioning |
| Live power | Signed watts from explicitly mapped Harvi/Zappi CT channels |
| Firmware updates | Ignored by default; explicit vendor passthrough option only |

Live verification on 29 September 2026 confirmed local Fast in approximately 1.5 seconds and local Stop in approximately 2.5 seconds. Both transitions appeared in device telemetry forwarded upstream. All four mode packets pass the firmware emulator. Subsequent live MQTT and browser tests confirmed all four modes with requests dispatched on charger polls. These observations are not latency guarantees or compatibility claims for other firmware.

See [live dashboard, MQTT and forwarding tests](docs/live-e2e-2026-09-29.md) for the subsequent end-to-end checks.

See [device state and confirmation](docs/device-mode.md) for the evidence and [runtime architecture](docs/architecture.md) for session behavior and verification limits.

## Set up the server

The verified protocol scope is product 3562, firmware 5.794. You need Python 3.13 or later, a private persistent data directory, a router capable of redirecting the charger's UDP traffic, and a privately recovered session key for initial provisioning. Passive Ethernet capture also needs Linux, access to the charger VLAN, and `NET_RAW` or equivalent privileges.

Install the dependencies in a virtual environment from the repository directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Create private configuration:

```sh
umask 077
zappi_data="$HOME/.local/share/local-zappi"
mkdir -p "$zappi_data"
chmod 700 "$zappi_data"
cp config.example.json "$zappi_data/config.json"
```

Edit `config.json` for your bind address, permitted router IP, upstream routes and device MAC. Set `telemetry_interface` to the charger-facing interface, or leave it `null` to disable Ethernet capture. Configure a private MQTT broker if needed; see [MQTT reporting](docs/mqtt.md).

Provision `session-keys.json` with your device's `serial` and `session_key_hex`, mode 0600. The [session recovery tool](docs/sessions.md#recover-a-key-from-a-private-capture) can create it from a suitable owned capture. For independent sessions, also provision private `bootstrap.json` (0600) with `serial`, `product`, `version` and `bootstrap_key_hex` for the exact supported firmware; see [session provisioning](docs/architecture.md). Keys and firmware are never distributed with this project.

Start the server using the private directory:

```sh
LOCAL_ZAPPI_DATA="$zappi_data" \
LOCAL_ZAPPI_CONFIG="$zappi_data/config.json" \
python server.py
```

For containers, mount that directory at `/data` in `ghcr.io/imduffy15/local-zappi`. Pin an image digest or commit tag. The [Dockerfile](Dockerfile) sets the runtime and dependencies; site-specific router, TLS and Kubernetes definitions belong in your private infrastructure repository.

## Route traffic and open the dashboard

Redirect only the intended charger's UDP port 87 traffic to the corresponding local listeners. Use a separate listener for each upstream destination so the relay preserves routing. Where needed, source NAT through the router ensures replies follow reverse NAT. Restrict `allowed_clients` to that router or the intended charger source.

Route other charger UDP87 destinations to the local director listener as a fallback. For complete offline isolation, also block direct charger WAN access over IPv4 and IPv6 before any flow-offload rule. Preserve local DNS/DHCP. The relay forwarding switch alone is not a firewall. The redirected path depends on the server being available.

The HTTP listener defaults to `127.0.0.1:18087`. For remote access, configure `admin_bind` and a private HTTPS reverse proxy. The dashboard and HTTP API have no authentication. Anyone who can reach the service can view status and change modes or forwarding. The dashboard contains live power, reported mode, mode controls and boost/timer settings; diagnostics remain available through `/status`.

Disabling `forward_upstream` closes upstream sessions and enables the local session service when bootstrap provisioning is present. Without provisioning, offline commands return HTTP 409. The saved forwarding setting survives restarts and overrides the initial configuration value. Route and listener changes require a restart.

### Firmware policy

`allow_firmware_forwarding` defaults to `false`, independently of normal app forwarding. Firmware-route requests, known firmware transfer envelopes, firmware advertisements and unsupported server commands are dropped without replies. The server does not construct, host, alter or install firmware images.

Only when you explicitly set `"allow_firmware_forwarding": true` in the startup configuration and restart the server may firmware traffic pass unchanged to and from the configured myenergi servers. Dedicated firmware routes can then forward even with ordinary forwarding disabled; enable ordinary forwarding too for vendor negotiation and update announcements on director routes. Restore the option to `false` and restart after an intentional upgrade. There is no dashboard or HTTP API switch for this option. No live firmware upgrade was performed during verification.

### Live power

Map each reading explicitly in `power_channels`, for example `{"grid":{"serial":12345678,"channel":1},"charger":{"serial":87654321,"channel":1}}`. Select the actual grid CT and internal charger-load CT for your installation. Values are signed watts and expire after 30 seconds; negative grid values mean export. No household consumption estimate or history database is maintained.

## Use the API

The API distinguishes a requested mode from a device report:

| Endpoint | Behavior |
| --- | --- |
| `GET /` | Dashboard |
| `GET /dashboard.js` | Dashboard script |
| `GET /health` | Process liveness, not proof of charger connectivity |
| `GET /status` | Forwarding, session diagnostics, telemetry, latest device mode and latest local request |
| `POST /mode` | Body `{"mode":"fast"}`, `eco`, `eco_plus` or `stop`; returns 202 when queued |
| `POST /settings/read` | Body `{}`; queues native configuration read |
| `POST /boost` | `{"kind":"manual","kwh":5}`, `{"kind":"smart","kwh":5,"time":"07:00"}` or `{"kind":"cancel"}` |
| `POST /schedules` | Four `schedules` rows with `start`, `duration_minutes` and `days` (Monday=0…Sunday=6); requires a recent configuration read |
| `POST /config` | Body `{"forward_upstream":true}` or `false`; persists the forwarding setting |

Invalid mode/configuration bodies return HTTP 400. Mode requests return HTTP 409 when the session is not ready or a settings operation is pending. HTTP 202 means `queued`, not that charging started. Commands transmit on the next valid charger poll, then become `sent_unconfirmed`.

Read `protocol.device_mode` for the device's mode, source and receipt timestamp. The dashboard shows Unavailable when the report is at least 30 seconds old. Read `protocol.last_local_command.status` for `queued`, `sent_unconfirmed`, `confirmed` or `not_confirmed`. Confirmation means fresh telemetry matched the request within 30 seconds; another actor could also have caused the change. The server does not automatically retry mode requests.

The host helper `ctl.py` supports `status`, `on`, `off`, and `mode fast|eco|eco_plus|stop`. It currently assumes the local API is on port 18087; use the API directly for other installations. Startup and deployment do not issue charging-mode commands.

## Diagnose connection or state problems

Validation happens automatically. Check `/status` for session status, last verified reply and traffic counters; there is no validation button. A successful HTTP health check alone does not establish a device connection.

Supported reconnect recovery needs a complete plaintext/stored-key/session-grant exchange and a later encrypted server hello. Missing or unsupported exchanges leave commands unavailable while forwarding continues. Recovery also scans the bounded private journals at startup. See [session recovery](docs/sessions.md) for its limits.

If a request times out, compare the actual device report with the requested mode. A sent command, observed cloud command or transport counter is not confirmation. Check for subsequent cloud commands from schedules or automations. An official-app display may also lag: compare the charger display, fresh local telemetry and a refreshed cloud view before sending another command.

The dashboard actively reads native settings once connected. Schedule writes preserve unrelated configuration, wait for native acknowledgements and read back the saved block. Boost requests wait for acceptance and refresh saved parameters; this does not prove the vehicle is drawing power. Selecting a boost tab only changes the displayed editor: existing timers remain active. A timer with no selected days is inactive. Minimum-green writes remain unavailable.

## Development and verification

Run the software tests and build the container:

```sh
python -m unittest discover -s tests -v
docker build -t local-zappi .
```

The software tests cover forwarding, operation without an access token, recovery, command construction, device-mode confirmation and timeout, telemetry framing, and MQTT. The [firmware emulator](docs/sessions.md#reproduce-locally) separately executes session and mode handlers using a privately supplied firmware image. Neither software tests nor emulation send physical charger commands.

GitHub Actions tests changes and publishes `latest` and full-commit `sha-...` tags on `main`. Version tags also publish images; pull requests build without publishing. Publishing an image does not update an existing digest-pinned deployment.

## Protocol documentation

The current implementation and historical research are documented separately:

- [Documentation and implementation review, 29 September 2026](docs/review-2026-09-29.md)
- [Runtime architecture and offline scope](docs/architecture.md)
- [Session encryption and reconnect recovery](docs/sessions.md)
- [Device state, confirmation and live control verification](docs/device-mode.md)
- [MQTT topics, events and Home Assistant discovery](docs/mqtt.md)
- [Initial app experiment](docs/app-experiment.md), historical findings superseded by session decoding
- [Labeled mode experiment](docs/mode-experiment.md), historical evidence followed by implemented control

Keep device keys, firmware and personal captures outside this public repository. Journals rotate at approximately 10 MiB with one previous file; preserve private evidence before a longer experiment. Avoid rollouts during labeled captures. The offline analysis tools never transmit packets; the control API constructs fresh commands rather than replaying captures.

This is independent protocol research, not an official myenergi product. The examined firmware identity checks are not cryptographic authentication tags; keep the service restricted to the intended private network.
