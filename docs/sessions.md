# Session protocol: firmware 5.794, product 3562

The session key has been recovered and independently validated against captured
traffic. A fresh session using a server-chosen key also completes against the
actual ARM firmware in offline emulation. These are separate results: neither
claims that the deployed relay already provides offline charging control.

## Encryption and identity checks

The firmware uses AES-256-CTR for the recovered session. Encryption begins at
UDP payload offset 16 and restarts with counter `f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff`
for each packet. The IV bytes also occur in the firmware image at `0x96553`.
The key record supports an XOR alternative, but the recovered record specifies
AES. The implementation currently supports AES only.

The application receive path (`0x4b78c`) checks the outer and decrypted device
serials before dispatching. The handshake receiver checks decrypted marker
`0x4b5c6d7f`. These checks are not a cryptographic authentication tag. The receive
paths examined do not verify a MAC or signature. Keep the service restricted to
the intended device/network; do not expose its UDP listeners to the Internet.

## Three key classes

| Header control, high byte | Meaning | Firmware evidence |
| --- | --- | --- |
| `0`, bit 3 set | Current RAM session key; requires state 5 or 6 and group 2 | `0x40e58` |
| `1` | Stored key selected by reference and validity interval | `0x41098` |
| `>= 0x80` | Bootstrap key; product-specific prefix | `0x40f18` |

Product 3562 maps to bootstrap prefix `0x85` (`0x41e8c`). For the firmware-backed
bootstrap path, bits 16..19 select a 256-byte flash page starting at `0x30000`;
its first 32 bytes become the key. The low halfword must match the firmware
version. A separate device-provisioned bootstrap path exists when bit 20 is set;
our implementation does not use it.

## Fresh session exchange

1. Device sends a 192-byte hello, magic `0xa5a5f001`, including its serial,
   product/version and stored-key references.
2. Server sends a 32-byte plaintext reply, magic `0xa5a5f000`, control `0x407`,
   slot zero. This selects the firmware bootstrap path even if stored day keys
   exist. Firmware advances from state 1 to state 2.
3. Device sends a bootstrap-encrypted hello. For this product/version its control
   is `0x850016a2`. Server verifies decrypted marker `0x3a4b5c6d` at offset 148.
4. Server returns a 96-byte encrypted reply containing a 64-byte key record:
   magic `0xfe502f5e`, slot 0, enabled 1, group 2, algorithm 2, key length 32.
   The firmware installs that session key in RAM and advances to state 5.
5. Device sends its session-encrypted hello. Server replies with the same key,
   server marker and matching serial. Firmware advances to state 6.

The server time field in hello replies is Unix time in minutes. Session records
use slot zero; stored time-limited keys occupy other slots. Our fresh-session
exchange does not write replacement day keys to EEPROM.

`SessionNegotiator` implements this exchange without network I/O. Its caller
must persist a newly generated key before sending the grant. Live routing,
upstream/local session coordination, retry policy and application replies remain
integration work; the deployed relay still forwards vendor bytes unchanged.

## Recovery from the existing capture

The upgrade capture includes a plaintext hello followed by a stored-key-encrypted
hello. Bytes 32..95 contain unchanged key references. XORing those regions yields
enough CTR keystream to decrypt the session-key record in the next server grant.
The stored key itself is not recovered. The resulting session key is validated
against a later encrypted server hello using its marker and device serial.

The recovered key also validated all 1,101 application replies in the initial
validation snapshot: 1,048 type-1 replies and 53 type-3 commands (17 mode-command
structures and 36 configuration writes). Later traffic continued to decrypt.
All 1,071 device packets in a subsequent snapshot decrypted with the expected
`0xe3` format byte at offset 31. These counts refer to different snapshots.

This replaces earlier speculative partial-XOR decoding. In particular, captured
80-byte commands have meaningful length **70**, not 80: the remainder is padding.
Wire offset `0x42` is the mode byte only for selector-2 commands; selector 5 uses
those bytes as configuration offset/region/length.

## Reproduce locally

Install `requirements.txt`. For the firmware emulator also install `unicorn`.
Run `python tools/emulate_session.py /private/path/to/firmware.bin`. The tool
checks the exact firmware hash before executing its hard-coded addresses.

The emulator runs the firmware's actual handshake builder, receiver, key
selection and key installer. AES hardware, memory-copy, logging, network-send
and EEPROM calls are substituted. Its packets never reach a physical device.
It proves the control flow and formats for the initialized emulator state,
not every live reconnection or concurrent-app scenario.

`tools/recover_session.py input.json output-private.json` accepts captured UDP
payloads as a JSON list with `hex` fields in capture order. It requires a later
handshake to validate recovery and creates the output with mode 0600. It never
prints keys. Keep captures, recovered keys and firmware in private storage.
