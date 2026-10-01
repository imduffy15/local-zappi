# Session protocol: firmware 5.794, product 3562

The live relay decrypts device traffic, sends local mode commands, and automatically recovers replacement keys from supported cloud reconnect exchanges. With forwarding disabled and private bootstrap provisioning, the runtime uses the server-chosen session negotiator and local keepalives. Cold handshakes pass firmware emulation; physical cold-reboot verification remains outstanding. See [runtime architecture](architecture.md) and [verified device control](device-mode.md).

For setup, choose [Path A: local-only](local-only-setup.md) (bootstrap provisioning; no cloud key recovery) or [Path B: cloud-forwarded](get-session-key.md) (captured session key; no bootstrap file). This page explains the protocol behind those two paths.

## Encryption and identity checks

The firmware uses AES-256-CTR for the recovered session. Encryption begins at UDP payload offset 16 and restarts with counter `f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff` for each packet. The IV bytes also occur in the firmware image at `0x96553`. The key record supports an XOR alternative, but the recovered record specifies AES. The implementation currently supports AES only.

The application receive path (`0x4b78c`) checks the outer and decrypted device serials before dispatching. The handshake receiver checks decrypted marker `0x4b5c6d7f`. These checks are not a cryptographic authentication tag. The receive paths examined do not verify a MAC or signature. Keep the service restricted to the intended device/network; do not expose its UDP listeners to the Internet.

## Three key classes

| Header control, high byte | Meaning | Firmware evidence |
| --- | --- | --- |
| `0`, bit 3 set | Current RAM session key; requires state 5 or 6 and group 2 | `0x40e58` |
| `1` | Stored key selected by reference and validity interval | `0x41098` |
| `>= 0x80` | Bootstrap key; product-specific prefix | `0x40f18` |

Product 3562 maps to bootstrap prefix `0x85` (`0x41e8c`). For the firmware-backed bootstrap path, bits 16..19 select a 256-byte flash page starting at `0x30000`; its first 32 bytes become the key. The low halfword must match the firmware version. A separate device-provisioned bootstrap path exists when bit 20 is set; our implementation does not use it.

## Fresh session exchange

1. Device sends a 192-byte hello, magic `0xa5a5f001`, including its serial, product/version and stored-key references.
2. Server sends a 32-byte plaintext reply, magic `0xa5a5f000`, control `0x407`, slot zero. This selects the firmware bootstrap path even if stored day keys exist. Firmware advances from state 1 to state 2.
3. Device sends a bootstrap-encrypted hello. For this product/version its control is `0x850016a2`. Server verifies decrypted marker `0x3a4b5c6d` at offset 148.
4. Server returns a 96-byte encrypted reply containing a 64-byte key record: magic `0xfe502f5e`, slot 0, enabled 1, group 2, algorithm 2, key length 32. The firmware installs that session key in RAM and advances to state 5.
5. Device sends its session-encrypted hello. Server replies with the same key, server marker and matching serial. Firmware advances to state 6.

The server time field in hello replies is Unix time in minutes. Session records use slot zero; stored time-limited keys occupy other slots. Our fresh-session exchange does not write replacement day keys to EEPROM.

`SessionNegotiator` implements this exchange without network I/O. Its caller must persist a newly generated key before sending the grant. `offline.py` connects it to runtime routing when forwarding is disabled and bootstrap provisioning is present. Forwarded mode still shares the vendor session; the server does not translate between two independent concurrent sessions.

## How automatic reconnect recovery works

The running `SessionRecovery` observer follows handshakes for the privately configured serial and the same upstream route. It retains at most 32 route exchanges and expires an exchange after 120 seconds. A candidate must decode as an AES session-key record in slot zero, group two, then decrypt a later server hello with the correct identity and marker. It sends no negotiation packets.

After validation, `Control` saves the key atomically with mode 0600, clears control readiness and waits for fresh application traffic. If saving fails, it keeps the old key and reports a storage error. Missing, corrupt or unsupported exchanges do not replace the key. Forwarding continues independently of decoding.

At startup, the server scans `traffic.jsonl.1` and `traffic.jsonl` for a recoverable exchange. Before replacing the saved key, it checks the candidate against the latest relevant application reply when one exists. It also restores the last matching command counter, without restoring session readiness. This recovered the owner’s reboot exchange during live verification.

Initial provisioning is still required. The capture-based setup supplies device identity and the current key through private `session-keys.json`. A separately provisioned `bootstrap.json` can instead supply identity and enable local session establishment. Creating that file while the process is running requires a server restart. Recovery is limited to the supported complete exchange, not every possible reconnect or key class.

## Original recovery evidence

The upgrade capture includes a plaintext hello followed by a stored-key-encrypted hello. Bytes 32..95 contain unchanged key references. XORing those regions yields enough CTR keystream to decrypt the session-key record in the next server grant. The stored key itself is not recovered. The resulting session key is validated against a later encrypted server hello using its marker and device serial.

The recovered key also validated all 1,101 application replies in the initial validation snapshot: 1,048 type-1 replies and 53 type-3 commands (17 mode-command structures and 36 configuration writes). Later traffic continued to decrypt. All 1,071 device packets in a subsequent snapshot decrypted with the expected `0xe3` format byte at offset 31. These counts refer to different snapshots.

This replaces earlier speculative partial-XOR decoding. In particular, captured 80-byte commands have meaningful length **70**, not 80: the remainder is padding. Decrypted payload offset `0x42` is the mode byte only for selector-2 commands; selector 5 uses those bytes as configuration offset/region/length.

## Reproduce locally

Install `requirements.txt`. For the firmware emulator also install `unicorn`. Run `python tools/emulate_session.py /private/path/to/firmware.bin`. The tool checks the exact firmware hash before executing its hard-coded addresses.

The emulator runs the firmware's actual handshake builder, receiver, key selection and key installer. AES hardware, memory-copy, logging, network-send and EEPROM calls are substituted. Its packets never reach a physical device. It proves the control flow and formats for the initialized emulator state, not every live reconnection or concurrent-app scenario.

## Recover a key from a private capture

For a first **cloud-forwarded** installation, follow [Path B: recover a cloud session key](get-session-key.md). That guide includes packet capture and conversion commands, file placement and failure diagnosis. Local-only installations should use [Path A](local-only-setup.md) and skip capture recovery.

The offline tool accepts a JSON list of captured UDP payloads, with a `hex` field in capture order. It requires a suitable complete exchange and later handshake confirmation. It creates the output with mode 0600, refuses to overwrite an existing file and never prints the recovered key.

```sh
python tools/recover_session.py \
  /private/path/captured_packets.json \
  /private/path/session-keys.json
```

The live journal is JSON Lines with additional Ethernet records; it is not this tool’s JSON-list input format. The runtime journal scanner handles its own journal format automatically. Keep captures, recovered keys and firmware in private storage.
