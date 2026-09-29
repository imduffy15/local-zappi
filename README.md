# local-zappi

Experimental local server for observing and relaying a myenergi Zappi's proprietary UDP traffic, with a persistent boolean `forward_upstream` option and passive Ethernet telemetry decoding.

**This is not yet a complete offline replacement for myenergi's control server.** The live service decrypts a privately provisioned session and provides explicit local FAST/ECO/ECO+/STOP commands while retaining cloud forwarding. Fresh-session negotiation is implemented and firmware-emulator tested, but is not yet connected to the relay. Disabling forwarding currently blocks cloud communication and local mode controls.

## Features

- Per-upstream UDP listeners preserve each original destination and byte content.
- Per-client connected upstream sockets accept replies only from the configured upstream endpoint.
- Persistent forwarding switch closes existing upstream sessions when disabled.
- Optional receive-only EtherType `0x88b5` telemetry parsing: device announcements and candidate Harvi CT records. Numeric units remain unverified.
- Loopback HTTP API, bounded local raw traffic journal, session expiry and source allowlist.
- Web dashboard with explicit mode controls, session status, raw CT readings and every observed Ethernet/decrypted UDP record.
- Local mode packets tested through the firmware receiver in offline emulation; live requests remain pending until matching charger telemetry is received, with a 30-second confirmation timeout.
- No factory commands, generic EEPROM writes, or automatic charging-mode changes.

## Run

Copy `config.example.json` to a private data directory as `config.json`, adjust the bind address, permitted router IP and route mappings, and create `admin-token` containing at least 32 random characters. The same directory stores `forwarding.json` and bounded `traffic.jsonl`/`traffic.jsonl.1`; preserve it across restarts. Protect it from other users. Raw traffic and telemetry may contain private identifiers.

Run `python server.py` with `LOCAL_ZAPPI_DATA` and `LOCAL_ZAPPI_CONFIG`, or mount the directory at `/data` in `ghcr.io/imduffy15/local-zappi:latest`. Passive Ethernet reception requires host networking, the correct interface, and Linux `NET_RAW`; disable it with `telemetry_interface: null` when unavailable. The HTTP API defaults to 127.0.0.1:18087. Set `admin_bind` to expose it through a private HTTPS ingress. Remote status access and all writes require the access key; loopback status is readable locally. Do not expose it through an unauthenticated reverse proxy; status includes private telemetry.

A router must redirect only the target charger's UDP87 traffic to each corresponding listener. Preserve the original destination with distinct listener ports. Source NAT to the permitted router address keeps replies on the reverse NAT path when the server is multihomed. Unknown UDP87 destinations must not bypass the switch: block them and add validated route mappings as needed. This does not block unrelated transports or IPv6; it is not a whole-device internet kill switch. Site-specific router/Kubernetes definitions belong in the operator's private infrastructure configuration.

The initial forwarding setting defaults to true. Persisted `forwarding.json` overrides the initial configuration after restart. Configuration/routes are read at startup; only the forwarding boolean changes at runtime.

## API

- `GET /`: dashboard; enter the server access key to unlock remote data and controls.
- `GET /health`: process HTTP liveness.
- `GET /status`: forwarding state, counters, routes and latest telemetry; no credentials.
- `POST /mode`: `{"mode":"stop"}`, `fast`, `eco`, or `eco_plus`; bearer authentication required. Returns 202 with `sent_unconfirmed`, or 409 if no recently verified session exists.
- `POST /config`: `{"forward_upstream": false}` or `true`, with `Authorization: Bearer <admin-token>`.

On the server host, `python ctl.py status` prints status. `sudo python ctl.py off` / `on` reads the token from `/data/local-zappi/admin-token` without putting it in shell arguments. `off` intentionally interrupts cloud/app connectivity and any cloud-based charging automations; existing device behavior is not a substitute for implemented local controls. Use `sudo python ctl.py mode stop` (or another mode) for an explicit local command. The dashboard stores its access key only for the browser tab. Retrieve the key on the server with `sudo cat /data/local-zappi/admin-token`. Never place it in a public repository.

## Build and verification

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
docker build -t local-zappi .
```

GitHub Actions tests each change and publishes `latest` and full-commit `sha-...` tags to GHCR on main; version tags are also published. Pull requests build without publishing. Pin a digest or commit tag for deployment.

Tests cover byte-exact bidirectional forwarding, session reuse, source filtering, persistent disable/re-enable and rejection of non-boolean settings. Upstream replies are evidence of relay connectivity, not proof of end-to-end app behavior or fully decoded control semantics.

## Next protocol work

See [session findings](docs/sessions.md). Remaining work: connect fresh-session negotiation, implement independent application replies and session coordination with the vendor, validate boost/schedule/configuration controls. The dashboard intentionally disables unsupported write controls. Charging mode is read from device telemetry; local or cloud command requests never set the displayed mode. Raw telemetry fields are available, but unverified CT values are not labelled with physical units. Keep raw vendor firmware and personal packet captures outside this public repository. This project is independent research, not an official myenergi product.

## Labeled app experiments

Keep upstream forwarding enabled and avoid server rollouts while recording. Preserve the journal in a private experiment directory before its bounded rotation discards older data. Record UTC timestamps and human labels for each app action; separate actions by about ten seconds to distinguish them from periodic telemetry. A record of an app tap alone is not proof the charger accepted it.

`python tools/analyze_journal.py PRIVATE_JOURNAL.jsonl` emits an offline UDP timeline, observed request/reply correlation bytes, response delays and byte-change ranges against the previous packet of the same direction/route/length. Those ranges include checksums, counters and possibly ciphertext; they are not decoded commands. Keep generated timelines and app labels private alongside the raw capture. Do not replay captured packets. Local mode commands are freshly constructed from validated fields.

## MQTT reporting

Optional outbound MQTT reporting streams telemetry, observed cloud commands,
local commands sent, forwarding changes and periodic status. Read-only Home
Assistant discovery is supported. See [topics and setup](docs/mqtt.md).

## Private session provisioning

The live service loads `/data/session-keys.json` if present, requiring mode 0600. Supply `serial` and `session_key_hex` privately. The recovery tool can produce these from an owned capture. Keys are never returned by the API. On reconnect, the relay passively follows a complete plaintext/stored-key/session-grant handshake and independently verifies the candidate key against a later server hello. It then atomically saves the key with mode 0600 and waits for fresh application traffic before enabling controls. Startup also scans the two bounded private journals to recover a handshake captured before a server restart. Missing, unsupported or invalid exchanges leave controls disabled; forwarding continues unchanged. Recovery does not initiate a handshake or send any charger command. Do not assume session recovery from one capture is permanent provisioning.
