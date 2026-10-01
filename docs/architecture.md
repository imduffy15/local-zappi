# Local control and optional cloud forwarding

With `forward_upstream: false` and private bootstrap provisioning, `offline.py` answers supported charger handshakes, persists the negotiated key before granting it, and replies to validated device polls with local keepalives. `Control.ready()` uses fresh validated charger traffic in this mode; it does not require a cloud reply. Startup without bootstrap provisioning cannot provide offline control.

With forwarding enabled, the relay shares the charger/cloud session and recovers supported replacement keys. It does not establish two simultaneous independent sessions or translate between different cloud and charger keys. Cloud automations can supersede local requests in forwarded mode.

## Provisioning

Choose [Path A: local-only](local-only-setup.md) or [Path B: cloud-forwarded](get-session-key.md). They have different initial key requirements.

For Path A, no recovered `session_key_hex` is required. The server generates a session key during local negotiation when none is saved, persists it in `session-keys.json`, and grants it to the charger. An existing saved key can be reused.

Use product 3562, firmware 5.794 only within the verified scope. Place `bootstrap.json` in the private data directory, permissions 0600, containing `serial`, `product` (3562), `version` (5794), and `bootstrap_key_hex`. The bootstrap material must come from the exact owned firmware; do not substitute arbitrary keys or publish this file. `session-keys.json` stores the current session key. The bootstrap exchange installs a session key in RAM; it does not flash firmware.

For Path B, supply a recovered `session-keys.json` and enable ordinary forwarding. No bootstrap file is required. This mode shares the cloud-negotiated session. Firmware forwarding defaults to disabled in both paths.

## Requests and state

Mode commands queue until the next validated device poll. A successful send becomes `sent_unconfirmed`; only matching fresh device telemetry confirms it. Each stage has a 30-second timeout. The UI always displays observed mode, not the requested value.

Boost and configuration operations are serialized against local mode commands. Native command acknowledgements come from the charger telemetry header. Schedule writes first require a fresh 128-byte configuration, preserve unrelated bytes, and read the complete block back after writing. Boost readback verifies saved parameters; it is not a measurement of charging activity.

Grid and charger power use explicit CT mappings and expire after 30 seconds. MQTT publishes current observations and Home Assistant discovery. There is no charge-history or household-consumption database.

## Firmware boundary

Normal forwarding cannot enable firmware updates. `allow_firmware_forwarding` is a separate startup boolean, false by default. Firmware routes and recognized firmware envelopes are ignored unless enabled; unsupported server commands are also dropped. Opt-in forwards bytes unchanged to the configured vendor endpoints. No local firmware is served. See the README for the two forwarding options and restart requirement.

## Persistence and verification

The private directory holds bootstrap/session keys, forwarding state, command counters and bounded packet journals. Current reports and settings refresh after restart. There is no HTTP authentication; restrict the service to the intended network.

Live tests confirmed all four modes with cloud forwarding disabled and recovery after a 90-second server outage. The full cold-start handshake passes the actual firmware emulator and loopback tests; a physical charger reboot into a new offline session has not been verified. Tests do not establish compatibility with other products or firmware versions.
