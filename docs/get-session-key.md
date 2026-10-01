# Path B: recover a cloud session key

**This is the optional cloud-forwarded path.** If you want local-only control, use [Path A: local-only setup](local-only-setup.md) instead. Local-only users do not need to capture or recover a cloud session key.

Use this guide to create `session-keys.json` for your own charger from a captured cloud handshake. You don't need to know its existing encryption key. Recovery depends on capturing a particular exchange; a reboot alone does not guarantee that exchange.

The verified scope is Zappi product 3562, firmware 5.794. Other products, firmware versions and handshake types are unverified. **Do not start a firmware upgrade to obtain a key.**

## Before you start

Prepare these items:

- Your charger's LAN IP address and serial number, from its display or your router's device list
- SSH access to a router with `tcpdump`, or a packet-capture interface that can see both directions of charger traffic
- A computer with Python 3.13 or later, this repository and its [Python dependencies installed](../README.md#set-up-the-server)
- `tshark`, Wireshark's command-line tool, on that computer

Capture on the charger-facing side of the router, before network address translation (NAT). Capturing on an ordinary laptop's network interface usually won't reveal another device's unicast traffic. Use the router, a mirrored switch port or an existing packet capture.

For initial provisioning, leave the charger communicating directly with myenergi. Do this before installing Local Zappi traffic redirects or WAN blocking. An unprovisioned relay is not the recommended capture path: its default firmware policy also drops encrypted server traffic it cannot validate.

Keep captures and keys outside the repository. Run the following commands from your checkout, with its Python virtual environment activated. Create a private workspace:

```sh
umask 077
zappi_data="$HOME/.local/share/local-zappi"
mkdir -p "$zappi_data"
chmod 700 "$zappi_data"
```

## 1. Capture a reconnect

In the command below, replace `your_router`, `your_lan_interface` and the example charger IP `192.0.2.10`. Use the LAN bridge or VLAN interface carrying the charger, not the router's WAN interface. The capture streams over SSH into a file on your computer:

```sh
ssh root@your_router \
  'tcpdump -i your_lan_interface -U -s 0 -w - \
  "host 192.0.2.10 and udp port 87"' \
  > "$zappi_data/handshake.pcap"
```

Leave this running in its terminal. While the charger is idle, use its documented restart procedure, or wait for a natural reconnect. Do not factory-reset the charger or initiate an update. Wait until cloud communication resumes, allow another minute of traffic, then press Ctrl+C in the capture terminal.

A successful recovery needs these packets, in order:

1. A plaintext device hello
2. A stored-key-encrypted device hello with unchanged key references
3. The server's encrypted session-key grant
4. A later server hello encrypted with that new session key

A reconnect may reuse its existing session or choose another handshake type. If that happens, this method cannot recover a key from that capture. The [session protocol reference](sessions.md#original-recovery-evidence) explains the supported exchange.

## 2. Convert the capture into recovery input

Extract UDP payloads in capture order. Replace the example IP with the same charger IP used above:

```sh
tshark -r "$zappi_data/handshake.pcap" \
  -Y 'ip.addr == 192.0.2.10 && udp.port == 87' \
  -T fields -e udp.payload \
  > "$zappi_data/payloads.txt"
```

These options read a capture, apply a display filter and export a field. See the [TShark reference](https://www.wireshark.org/docs/man-pages/tshark.html) for platform-specific usage.

Convert those payloads into the JSON array expected by the recovery tool. This preserves packet order and accepts hex with or without colon separators:

```sh
python - "$zappi_data" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
rows = []
for line in (root / 'payloads.txt').read_text().splitlines():
    value = line.strip().replace(':', '')
    if value:
        rows.append({'hex': bytes.fromhex(value).hex()})
if not rows:
    raise SystemExit('No UDP payloads: check the capture interface and IP.')
(root / 'captured_packets.json').write_text(json.dumps(rows))
print(f'Prepared {len(rows)} packets; no keys printed.')
PY
```

Do not merge captures from different chargers, reorder packets or use a long capture spanning several reconnects. The recovery tool returns the first verified exchange it finds; a later reconnect may already have replaced that key.

## 3. Recover and verify the key

Run the recovery tool against the converted capture:

```sh
python tools/recover_session.py \
  "$zappi_data/captured_packets.json" \
  "$zappi_data/session-keys.json"
```

Success prints:

```text
Recovered session validated against a subsequent encrypted handshake; saved privately.
```

The tool extracts the candidate key, then checks a later encrypted handshake using that key, its marker and the device serial. It refuses to create the file if validation fails. It creates the output with permissions 0600 and refuses to overwrite an existing file.

The file contains `serial`, `session_key_hex` and capture packet indexes used for verification. `session_key_hex` is the 32-byte session key encoded as 64 hexadecimal characters. You don't need to copy it into `config.json` or enter it in the web UI.

Check the recovered serial against your physical charger without displaying its key:

```sh
python - "$zappi_data/session-keys.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
saved = json.loads(path.read_text())
assert len(bytes.fromhex(saved['session_key_hex'])) == 32
assert path.stat().st_mode & 0o077 == 0
print('Recovered charger serial:', saved['serial'])
print('Key length and private permissions verified.')
PY
```

## 4. Start Local Zappi with this file

Keep `session-keys.json` in the directory passed as `LOCAL_ZAPPI_DATA`. For the container, mount that directory at `/data`. The runtime user must be able to read and update it; preserve private permissions when copying it to another host.

Follow the [server setup and routing instructions](../README.md#set-up-the-server), including `config.json`. Initially use `forward_upstream: true` and `allow_firmware_forwarding: false`. Restart an existing server after provisioning the file.

Once redirected traffic reaches the server, inspect `GET /status`. `protocol.local_mode_control_ready: true` indicates a validated control connection. The dashboard should show Connected and a fresh mode report. Loading a key alone does not establish readiness, and a successful `/health` response does not validate the key.

Keep firmware forwarding disabled throughout provisioning. If a different, already-provisioned installation has a saved `forwarding.json`, that file overrides the startup `forward_upstream` value. Use the documented `POST /config` endpoint to change ordinary forwarding when needed.

## If recovery fails

Use the error and capture contents to identify the next step:

| Result | What to check |
| --- | --- |
| No UDP payloads | Verify the charger's IP, capture interface and that both directions cross that interface. |
| `no independently validated recoverable session exchange found` | The required four-part exchange is missing, unsupported or inconsistent. Capture another natural reconnect from before its first hello. No key has been written. |
| `FileExistsError` | The tool refuses to overwrite a key. Use a different private output filename, verify its serial, then stop the service before deliberately replacing its file. |
| Permission error on startup | Set the key file to 0600 and its directory to 0700. Ensure the server's runtime user owns or can access them. |
| Key loaded but controls unavailable | Check redirects, bidirectional traffic, ordinary forwarding and whether a newer reconnect replaced the captured session. Do not substitute a random key. |

A failed capture does not prove that your charger is unsupported. It also does not mean another reboot will necessarily produce a recoverable exchange. No universal key-extraction procedure is established for every firmware version.

## What this enables, and what offline setup still needs

Path B does not require `bootstrap.json`. The recovered session key enables decoding and local commands while sharing the supported cloud session. The running observer can recover replacement keys from subsequent complete supported exchanges. A session key can change; it is not a permanent device credential.

To switch to Path A later, provision `bootstrap.json` using the [local-only guide](local-only-setup.md), then disable ordinary forwarding. You can keep your existing `session-keys.json`; the local service can reuse it. Starting with Path A never requires completing this capture guide. Neither guide distributes firmware or bootstrap keys, and there is no general firmware-download wizard.

| Value | Purpose | Obtained by this guide? |
| --- | --- | --- |
| `session_key_hex` | Encrypt and decrypt the current device session | Yes, when the required exchange is captured |
| `bootstrap_key_hex` | Establish a local session using the supported firmware bootstrap path | No |
| myenergi account password or API key | Authenticate to official cloud services | No; neither is needed for capture recovery |
