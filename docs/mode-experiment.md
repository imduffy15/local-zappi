# Labeled mode experiments, 29 September 2026

This page preserves the original ciphertext-correlation experiment. The later [session decoding](sessions.md) and [live control verification](device-mode.md) establish the current implementation; the original uncertainty below describes what this experiment alone proved.

The owner selected Stopped → Fast → Stopped, then Eco → Eco+ → Stopped, confirming each state in conversation. Confirmations are later than the exact app taps. Both dedicated recordings are stopped; the relay and normal bounded journal remain active with upstream forwarding enabled.

Seven 80-byte upstream messages in the combined test window share the observed control-message header family. Their candidate mode values, in order, are `1, 4, 4, 2, 4, 3, 4`. The extra Stop-like messages were not explicitly labeled user actions. An existing charging guard may have issued them; origin is not proven and the guard was not changed.

| Reported mode / interpretation | Observed byte at UDP payload offset `0x42` |
|---|---:|
| Fast | 1 |
| Eco | 2 |
| Eco+ | 3 |
| Stopped / repeated Stop-like message | 4 |

The Eco message preceded its dedicated recording by about six seconds, but was preserved in the continuous relay journal. A frozen continuous window is included with the private evidence. No Eco packet was fabricated or reconstructed from an expected value.

Across these seven provisionally labeled samples, `0x42` is the only byte that is constant within each assigned mode and different across all four modes. The repeated Stop-like samples help rule out the changing packet counter/time fields. Other differing locations included bytes 8–11, 16, 24–27 and 40; this experiment did not establish all their semantics.

**This is a strong within-session wire correlation, not a universal plaintext decoder.** The field lies inside the region passed to the firmware's decryption routine. Its numeric resemblance to mode codes does not establish that encryption can be ignored, that the same wire byte works with another key/session/device, or that a byte-patched packet passes validation. Extra Stop labels are inferred from the repeated pattern and user-reported final state; they are not independent proof of an automation firing.

## Implemented

`tools/learn_mode_fields.py` accepts private labeled samples and finds discriminating byte offsets, requiring at least one repeated mode. Tests verify that changing counters are not mistaken for mode fields. It neither decrypts nor transmits. Raw packets and labels stay in the private research archive.

## Subsequent implementation

Session recovery and firmware analysis established the decrypted envelope, selector-2 command layout and device-mode readback. The authenticated API now accepts requests for all four modes. The server constructs encrypted commands and confirms matching device telemetry. Local Fast and Stop were verified live; all four modes pass firmware emulation. See [device-mode verification](device-mode.md) for the header correction and evidence limits.

The capture tools remain offline and never replay packets. No local charging command was generated during this original labeled experiment. The later live verification is a separate result.
