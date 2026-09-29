# Device mode readback and command confirmation

The dashboard mode comes from the configured charger's `0x3510` telemetry, received through Ethernet or decrypted UDP. A local command only creates a pending request. Fresh matching telemetry within 30 seconds confirms that the requested mode is now reported; otherwise the request becomes `not_confirmed`. That observation does not prove which actor caused a change. A later mode change still updates the dashboard but does not retroactively confirm a timed out request. Reports older than 30 seconds are labelled stale and the main value becomes Unknown. No automatic mode retry is performed.

For the verified Zappi record family (device-byte bits 3–5 equal 2), byte 23 bits 0–1 encode Stop=0, Fast=1, Eco=2, Eco+=3. This is distinct from the command encoding, where Stop=4. The record must contain the configured device serial and at least the complete 24-byte base payload. Upper bits are unrelated flags.

Firmware 5.794 record builder `0x3c390` constructs `0x3510`. At `0x3c5b0`–`0x3c5c2`, it puts the mode into the low two bits of record byte 23, encoding internal mode values >=4 as zero. This matches the owner's private labeled Fast/Stop/Eco/Eco+/Stop captures. UDP's length byte excludes itself; Ethernet's length byte includes itself. Neither raw capture nor firmware is included here.

Device telemetry continues through the byte-preserving upstream relay. We do not synthesize cloud telemetry or acknowledge mode changes on the device's behalf. MQTT distinguishes `device_mode_observed`, `local_command_sent`, `local_command_confirmed`, and `local_command_not_confirmed`.

## Live control verification, 2026-09-29

The initial local Fast packets reached the charger-facing network with correct addressing and UDP checksums, but did not change its mode. A working official-app Fast command under the same session key had the same mode payload. The local sender differed in its outer header: it used a constant application counter of 21 with an unrelated three-bit sequence, and zero in the varying outer ID field.

The corrected sender uses a fresh nonzero outer ID and advances the application counter with its low three bits as the command sequence. It persists the counter independently of the journal, scoped to the session key, and can also restore it from validated same-key journal records. These header changes were tested together; the live experiment does not isolate which field caused the original rejection.

Local Fast was confirmed by fresh charger telemetry approximately 1.5 seconds after transmission, then local Stop was confirmed approximately 2.5 seconds after transmission. The device was left stopped. UDP telemetry contained both transitions, all observed device packets were forwarded upstream, and MQTT remained connected. No cloud command was used to perform that local test.

This remains a shared-session relay. Independent local/cloud sessions and their command coordination remain separate work; see [runtime architecture](architecture.md). Existing cloud automations can issue new commands after a locally confirmed change.


## Poll timing and restart follow-up

Further live testing found that a mode request sent between charger polls could remain unconfirmed. Fast sent immediately after a poll was confirmed. Requests now queue until the next valid device datagram, expire if no poll arrives within 30 seconds, and have a separate 30-second confirmation window after transmission. Disabling forwarding cancels a queued request. A second request while one is pending is rejected.

The bounded journal candidate scan could also forget a command after enough ordinary replies. Counters now persist atomically in `command-counter.json`, scoped to the session key. A storage failure blocks transmission. This fixes restart continuity but does not by itself explain all earlier failed commands.
