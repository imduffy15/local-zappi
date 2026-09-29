# Initial app-toggle experiment, 29 September 2026

This is a historical record from before session decoding and local control were implemented. The current [session decoder](sessions.md), [device confirmation loop](device-mode.md), and [README](../README.md) supersede its open questions.

The owner exercised available app controls while the local relay preserved cloud traffic. Exact labels/order were not supplied. Raw captures and device identifiers are retained privately, not in this repository.

The frozen log contains 1,963 records: 175 device-to-cloud UDP packets, 194 cloud-to-device UDP packets and 1,594 raw local Ethernet frames. It includes a preceding baseline.

Matching bytes 4–7 and route links 175 upstream packets to preceding device requests. The other **19 upstream packets** have no matching request in this log and occur during the app interaction interval. They all have 80-byte UDP payloads and share one correlation/header value. Ordinary matched replies are 64 or 80 bytes; length alone is not a command discriminator.

This is evidence of an unsolicited message path through the relay, consistent with app control delivery. This initial analysis did not decode the commands or prove that every app tap reached the charger. Changes can include transaction identifiers, time, checksums and encrypted data.

Static receiver analysis identifies a path that decrypts the payload beginning at offset 16, checks the outer device serial against local configuration and a decrypted copy, then passes decrypted length/type/payload fields to the application handler. Both XOR and AES machinery exist in the firmware; at the time of this experiment, the active algorithm, key and message integrity requirements had not been established for these control packets. Repeated ciphertext regions alone do not prove an algorithm or recover a key.

## Implemented from this experiment

`tools/summarize_experiment.py` separates observed request/reply matches from unsolicited candidates and retains candidate record numbers/timestamps. Its tests cover repeated correlation values and route separation. `tools/analyze_journal.py` provides the byte-difference timeline. Neither tool transmits anything.

## Follow-up results

The subsequent [labeled mode experiment](mode-experiment.md) supplied the requested mode sequence. Session recovery then established AES-256-CTR decoding and selector-2 mode semantics. The control API now constructs fresh commands, with local Fast and Stop verified against device telemetry. Boost, schedules and minimum-green writes remain separate unfinished work.

This experiment’s tools still perform offline analysis only. The live server now supports a provisioned local session when forwarding is disabled; see [runtime architecture](architecture.md).
