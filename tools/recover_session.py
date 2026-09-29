#!/usr/bin/env python3
"""Recover an owner's session from a captured key exchange, entirely offline.

Input is a JSON list of {src, hex} UDP payloads in capture order. Recovery uses
the unchanged stored-key references in consecutive plaintext/encrypted device
hellos. A candidate is accepted only after it decrypts a later server hello
with both the correct marker and device identity. No keys are printed.
"""
import argparse
import json
import os
import pathlib
import struct
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from protocol import HELLO_DEVICE, HELLO_SERVER, KeyRecord, open_packet, validate_server_packet


def recover(rows):
    packets = [bytes.fromhex(row['hex']) for row in rows]
    plain = None
    for index, packet in enumerate(packets):
        if len(packet) != 192 or int.from_bytes(packet[:4], 'little') != HELLO_DEVICE:
            continue
        control = int.from_bytes(packet[8:12], 'little')
        if control >> 24 == 0 and not control & 8:
            plain = packet
            continue
        if plain is None or control >> 24 != 1 or packet[4:8] != plain[4:8]:
            continue
        # Only use bytes 32..95: fixed slot-reference entries. Other plaintext
        # fields can change and must not be assumed known.
        stream = bytes(a ^ b for a, b in zip(plain[32:96], packet[32:96]))
        for candidate_index in range(index+1, min(index+20, len(packets))):
            reply = packets[candidate_index]
            if len(reply) != 96 or int.from_bytes(reply[:4], 'little') != HELLO_SERVER:
                continue
            if reply[4:12] != packet[4:12]:
                continue
            try:
                record = KeyRecord.decode(bytes(a ^ b for a, b in zip(reply[32:], stream)))
            except ValueError:
                continue
            if record.slot != 0 or record.group != 2:
                continue
            for check in packets[candidate_index+1:]:
                if len(check) < 32 or check[:8] != reply[:8]:
                    continue
                check_control = int.from_bytes(check[8:12], 'little')
                if check_control >> 24 or not check_control & 8:
                    continue
                try:
                    validate_server_packet(open_packet(check, record.key))
                except ValueError:
                    continue
                return {'serial': int.from_bytes(reply[4:8], 'little'),
                        'session_key_hex': record.key.hex(),
                        'source_packet_index': candidate_index,
                        'verified_against_packet_index': packets.index(check)}
    raise ValueError('no independently validated recoverable session exchange found')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=pathlib.Path)
    parser.add_argument('output', type=pathlib.Path)
    args = parser.parse_args()
    result = recover(json.loads(args.input.read_text()))
    # Refuse to overwrite and create with restrictive permissions from the start.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print('Recovered session validated against a subsequent encrypted handshake; saved privately.')


if __name__ == '__main__':
    main()
