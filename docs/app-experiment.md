# Initial app-toggle experiment — 2026-09-29

The owner exercised available app controls while the local relay preserved cloud traffic. Exact labels/order were not supplied. Raw captures and device identifiers are retained privately, not in this repository.

The frozen log contains 1,963 records: 175 device-to-cloud UDP packets, 194 cloud-to-device UDP packets and 1,594 raw local Ethernet frames. It includes a preceding baseline.

Matching bytes 4–7 and route links 175 upstream packets to preceding device requests. The other **19 upstream packets** have no matching request in this log and occur during the app interaction interval. They all have 80-byte UDP payloads and share one correlation/header value. Ordinary matched replies are 64 or 80 bytes; length alone is not a command discriminator.

This is evidence of an unsolicited message path through the relay, consistent with app control delivery. It is not yet a decoded list of commands, proof that every app tap reached the charger, or a replay recipe. Changes can include transaction identifiers, time, checksums and encrypted data.

Static receiver analysis identifies a path that decrypts the payload beginning at offset 16, checks the outer device serial against local configuration and a decrypted copy, then passes decrypted length/type/payload fields to the application handler. Both XOR and AES machinery exist in the firmware; the active algorithm/key and message integrity requirements are not yet established for these observed control packets. Repeated ciphertext regions alone do not prove an algorithm or recover a key.

## Implemented from this experiment

`tools/summarize_experiment.py` separates observed request/reply matches from unsolicited candidates and retains candidate record numbers/timestamps. Its tests cover repeated correlation values and route separation. `tools/analyze_journal.py` provides the byte-difference timeline. Neither tool transmits anything.

## Next evidence needed

Map a small labeled sequence (for example Stop → Eco+ → Fast → Stop) to candidate packets and corresponding telemetry changes, then trace the firmware's decrypted application fields. Treat those controls as distinct from boost configuration, schedules and minimum-green settings. Build and validate an offline decoder before adding command generation. Current local-zappi still reports offline control unsupported and keeps forwarding enabled.
