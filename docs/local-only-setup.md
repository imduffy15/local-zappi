# Path A: set up local-only control

Choose this path to run your charger through Local Zappi without forwarding to myenergi. You can use the local dashboard, MQTT and Home Assistant. The official app and cloud automations won't communicate with the charger through this path.

**You do not need to capture traffic or recover `session_key_hex` first.** Supply the matching bootstrap key instead. The server generates a session key during the local handshake and saves it automatically, or reuses an existing saved session key.

If you want to retain the official app, choose [Path B: cloud-forwarded setup](get-session-key.md). You do not need to complete both paths.

## 1. Check prerequisites

The verified scope is product 3562, firmware 5.794. Before changing charger routing, prepare these items:

- Your charger serial number and matching firmware identity
- Bootstrap material for that exact supported firmware, as described below
- The [shared Python environment and private configuration directory](../README.md#set-up-the-server)
- A router that can redirect charger traffic to the server and block direct WAN access

Local controls have passed live tests with cloud forwarding disabled. Complete cold-session negotiation passes firmware emulation and loopback tests; a physical cold reboot into a newly negotiated offline session remains unverified. Do not assume compatibility with other products or versions.

## 2. Create `bootstrap.json`

The bootstrap file identifies your charger and supplies the key used to establish a local session. Store it inside your private data directory, with permissions 0600. It contains these fields:

| Field | Value |
| --- | --- |
| `serial` | Your charger's numeric serial number |
| `product` | `3562` for the supported product |
| `version` | `5794` for firmware 5.794 |
| `bootstrap_key_hex` | The matching 32-byte bootstrap key, encoded as 64 hexadecimal characters |

The bootstrap key is not your myenergi API key, account password or a captured session key. Generating a random value for this field will not work.

### Obtain bootstrap material from the supported image

For the supported firmware bootstrap path, the charger uses the first 32 bytes of the selected firmware flash page. The implemented handshake selects page zero at flash address `0x30000`. This is separate from installing or upgrading firmware.

If you already have a private copy of the exact recovered firmware image used by this project, the command below creates `bootstrap.json`. It verifies the whole image's SHA-256 hash before extracting any material. The input must be the reconstructed section beginning at flash address `0x30000`, not an arbitrary vendor download, encrypted update package or full flash dump.

Replace the example firmware path and serial number. Run this from your checkout using its Python environment; `zappi_data` is the private directory created in the shared setup instructions:

```sh
python - /private/path/to/firmware.bin 12345678 "$zappi_data" <<'PY'
import hashlib
import json
import os
import pathlib
import sys

image = pathlib.Path(sys.argv[1]).read_bytes()
expected = '605ae6979f8fb3ea74bfd935682f4d632dac5b8f9714318c480382f047104a2d'
if hashlib.sha256(image).hexdigest() != expected:
    raise SystemExit('Unsupported image: no bootstrap file written.')
serial = int(sys.argv[2])
if not 0 < serial <= 0xffffffff:
    raise SystemExit('Invalid charger serial.')
config = dict(serial=serial, product=3562, version=5794,
              bootstrap_key_hex=image[:32].hex())
path = pathlib.Path(sys.argv[3]) / 'bootstrap.json'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    json.dump(config, output, indent=2)
    output.write('\n')
print('Created private bootstrap.json; no key printed.')
PY
```

The command refuses to overwrite an existing file and never sends anything to the charger. **Do not download or flash a different firmware version to satisfy this guide.**

If you don't already have matching bootstrap material or this exact privately recovered image, local-only provisioning is not yet a turnkey process. The project does not distribute firmware or bootstrap keys and has no general image-acquisition or unpacking wizard. A checksum mismatch means this recipe cannot use your input; don't remove the check or extract the first 32 bytes of an unrelated file. Path B is a separate option if you can capture its supported cloud handshake.

## 3. Disable both forwarding options

Set these fields in your complete `config.json`, alongside your routes, bind address and client allowlist:

```json
{
  "forward_upstream": false,
  "allow_firmware_forwarding": false
}
```

This fragment is not a complete configuration. The supplied `config.example.json` starts with both options disabled. Set the remaining fields for your network, and configure MQTT and Home Assistant discovery if wanted.

For a fresh installation, do not create `session-keys.json` manually. If you already have one for this same charger, keep it; the server can reuse the key. The server's runtime user needs write access to the private directory to persist a newly generated key before granting it to the charger.

For an existing installation, a saved `forwarding.json` overrides `forward_upstream` in the startup config. After provisioning bootstrap and restarting the server, disable ordinary forwarding through the local API:

```sh
curl --fail-with-body http://127.0.0.1:18087/config \
  -H 'Content-Type: application/json' \
  --data '{"forward_upstream":false}'
```

Run this on the server host, adjusting the port if needed. `allow_firmware_forwarding` is a separate startup setting; changing it requires a restart. Leave it false throughout setup.

## 4. Start the server and redirect the charger

Start the service with your private data directory, as shown in the [shared setup instructions](../README.md#set-up-the-server). For containers, mount that directory at `/data`. Keep bootstrap and session files private when copying them between hosts.

Apply the [charger routing rules](../README.md#route-traffic-and-open-the-dashboard): redirect its UDP port 87 traffic to the local listeners, preserve the return path, and block direct charger WAN access over IPv4 and IPv6. Keep local DNS and DHCP available. Disabling relay forwarding alone does not block other internet paths.

Let the charger reconnect to the redirected service. If needed, use the charger's documented restart procedure while it is idle. No firmware update or factory reset is required. A charger still sending packets under an unknown previous session cannot become ready until it performs a supported local handshake.

During that handshake, the server:

1. Uses your bootstrap material to validate the supported bootstrap exchange.
2. Generates a random session key if none is saved, then writes `session-keys.json` before sending the key grant.
3. Grants the session key to the charger and uses it for subsequent encrypted traffic.
4. Sends local keepalives and waits for validated device telemetry before enabling controls.

`session_key_hex` therefore still exists in local-only mode, but you do not obtain or type it yourself. Preserve both key files across server restarts.

## 5. Verify local-only operation

Inspect `GET /status` through the server's HTTP endpoint. Look for these values:

| Status field | Expected result |
| --- | --- |
| `forward_upstream` | `false` |
| `allow_firmware_forwarding` | `false` |
| `offline_control_supported` | `true`: bootstrap configuration is present, not proof of a completed handshake |
| `protocol.local_mode_control_ready` | `true` after validated device traffic |
| `protocol.device_mode` | A fresh device report with the actual charging mode |

The dashboard should show Connected and a fresh mode report. A successful `/health` request, a generated key file or `offline_control_supported: true` alone does not prove the charger accepted a session.

If readiness stays false, check the bootstrap product/version, file ownership, charger serial, redirected packets and return routing. A physical cold start into a new local session remains an explicit verification gap. Don't replace keys with random values or enable firmware forwarding to troubleshoot it.

## Switching to cloud-forwarded operation

[Path B](get-session-key.md) explains capturing and provisioning a cloud-negotiated session. A locally generated key does not authenticate you to myenergi. Do not assume that enabling forwarding creates a second independent cloud session: the current forwarded mode shares the charger/cloud session and requires a supported exchange. The service does not translate between two independent concurrent sessions.
