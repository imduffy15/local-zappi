# local-zappi

Experimental local server for observing and relaying a myenergi Zappi's proprietary UDP traffic, with a persistent boolean `forward_upstream` option and passive Ethernet telemetry decoding.

**This is not yet an offline replacement for myenergi's control server.** It preserves opaque cloud packets; encryption/session handling and local charging commands are not implemented. Setting forwarding to false blocks relayed cloud communication. It does not enable local FAST/ECO/STOP controls, and the vendor app will lose fresh charger updates/control.

## Features

- Per-upstream UDP listeners preserve each original destination and byte content.
- Per-client connected upstream sockets accept replies only from the configured upstream endpoint.
- Persistent forwarding switch closes existing upstream sessions when disabled.
- Optional receive-only EtherType `0x88b5` telemetry parsing: device announcements and candidate Harvi CT records. Numeric units remain unverified.
- Loopback HTTP API, bounded local raw traffic journal, session expiry and source allowlist.
- No cloud credentials, packet injection, charging commands, or factory commands.

## Run

Copy `config.example.json` to a private data directory as `config.json`, adjust the bind address, permitted router IP and route mappings, and create `admin-token` containing at least 32 random characters. The same directory stores `forwarding.json` and bounded `traffic.jsonl`/`traffic.jsonl.1`; preserve it across restarts. Protect it from other users. Raw traffic and telemetry may contain private identifiers.

Run `python server.py` with `LOCAL_ZAPPI_DATA` and `LOCAL_ZAPPI_CONFIG`, or mount the directory at `/data` in `ghcr.io/imduffy15/local-zappi:latest`. Passive Ethernet reception requires host networking, the correct interface, and Linux `NET_RAW`; disable it with `telemetry_interface: null` when unavailable. The HTTP API binds only to 127.0.0.1:18087. Do not expose it through an unauthenticated reverse proxy; status includes private telemetry.

A router must redirect only the target charger's UDP87 traffic to each corresponding listener. Preserve the original destination with distinct listener ports. Source NAT to the permitted router address keeps replies on the reverse NAT path when the server is multihomed. Unknown UDP87 destinations must not bypass the switch: block them and add validated route mappings as needed. This does not block unrelated transports or IPv6; it is not a whole-device internet kill switch. Site-specific router/Kubernetes definitions belong in the operator's private infrastructure configuration.

The initial forwarding setting defaults to true. Persisted `forwarding.json` overrides the initial configuration after restart. Configuration/routes are read at startup; only the forwarding boolean changes at runtime.

## API

- `GET /health`: process HTTP liveness.
- `GET /status`: forwarding state, counters, routes and latest telemetry; no credentials.
- `POST /config`: `{"forward_upstream": false}` or `true`, with `Authorization: Bearer <admin-token>`.

On the server host, `python ctl.py status` prints status. `sudo python ctl.py off` / `on` reads the token from `/data/local-zappi/admin-token` without putting it in shell arguments. `off` intentionally interrupts cloud/app connectivity and any cloud-based charging automations; existing device behavior is not a substitute for implemented local controls. No automated live off/on test is required; loopback tests cover the switch.

## Build and verification

```sh
python3 -m unittest discover -s tests -v
docker build -t local-zappi .
```

GitHub Actions tests each change and publishes `latest` and full-commit `sha-...` tags to GHCR on main; version tags are also published. Pull requests build without publishing. Pin a digest or commit tag for deployment.

Tests cover byte-exact bidirectional forwarding, session reuse, source filtering, persistent disable/re-enable and rejection of non-boolean settings. Upstream replies are evidence of relay connectivity, not proof of end-to-end app behavior or fully decoded control semantics.

## Next protocol work

Identify session/key negotiation and validate message framing against owned-device evidence; implement authentication/decryption and a simulated server before generating charging commands. Keep raw vendor firmware and personal packet captures outside this public repository. This project is independent research, not an official myenergi product.
