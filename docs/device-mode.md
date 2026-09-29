# Device mode readback and command confirmation

The dashboard mode comes from the configured charger's `0x3510` telemetry,
received through Ethernet or decrypted UDP. A local command only creates a
pending request. Fresh matching telemetry within 30 seconds confirms that the
requested mode is now reported; otherwise the request becomes `not_confirmed`.
That observation does not prove which actor caused a change. A later mode
change still updates the dashboard but does not retroactively confirm a timed
out request. Reports older than 30 seconds are labelled stale and the main
value becomes Unknown. No automatic mode retry is performed.

For the verified Zappi record family (device-byte bits 3–5 equal 2), byte 23
bits 0–1 encode Stop=0, Fast=1, Eco=2, Eco+=3. This is distinct from the command
encoding, where Stop=4. The record must contain the configured device serial
and at least the complete 24-byte base payload. Upper bits are unrelated flags.

Firmware 5.794 record builder `0x3c390` constructs `0x3510`. At
`0x3c5b0`–`0x3c5c2`, it puts the mode into the low two bits of record byte 23,
encoding internal mode values >=4 as zero. This matches the owner's private
labeled Fast/Stop/Eco/Eco+/Stop captures. UDP's length byte excludes itself;
Ethernet's length byte includes itself. Neither raw capture nor firmware is
included here.

Device telemetry continues through the byte-preserving upstream relay. We do
not synthesize cloud telemetry or acknowledge mode changes on the device's
behalf. MQTT distinguishes `device_mode_observed`, `local_command_sent`,
`local_command_confirmed`, and `local_command_not_confirmed`.

## Outstanding live command investigation

The owner reported that local Fast requests did not change the charger. Router
capture proved the second request reached the charger-facing network with the
expected Ethernet destination, reverse-NAT source and valid UDP checksum.
Telemetry remained Stop. The packet passes the offline firmware-handler test,
but live acceptance is unresolved. A same-session official-app command was
requested as a comparison. Session validation and a UDP send alone must not be
presented as successful physical control.
