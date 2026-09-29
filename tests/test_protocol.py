import struct
import unittest
from protocol import KeyRecord, SessionNegotiator, crypt, hello_reply, open_packet, validate_server_packet
from tools.recover_session import recover


class SessionTests(unittest.TestCase):
    def test_fresh_negotiation_and_rejected_identity(self):
        bootstrap, session = bytes(range(32)), bytes(reversed(range(32)))
        server = SessionNegotiator(123456, 3562, 5794, bootstrap, session)
        hello = bytearray(192)
        struct.pack_into('<4I', hello, 0, 0xa5a5f001, 123456, 3, 3562 | 5794 << 16)
        struct.pack_into('<I', hello, 148, 0x3a4b5c6d)
        initial = server.reply(bytes(hello), 30000000)
        self.assertEqual(int.from_bytes(initial[8:12], 'little'), 0x407)
        struct.pack_into('<I', hello, 8, 0x850016a2)
        encrypted = bytes(hello[:16]) + crypt(bytes(hello[16:]), bootstrap)
        grant = validate_server_packet(open_packet(server.reply(encrypted, 30000000), bootstrap))
        self.assertEqual(KeyRecord.decode(grant[32:]).key, session)
        self.assertFalse(server.established)
        struct.pack_into('<I', hello, 8, 0x105ab)
        encrypted = bytes(hello[:16]) + crypt(bytes(hello[16:]), session)
        validate_server_packet(open_packet(server.reply(encrypted, 30000000), session))
        self.assertTrue(server.established)
        bad = bytearray(encrypted); bad[4] ^= 1
        with self.assertRaises(ValueError): server.reply(bytes(bad), 30000000)
        bad = bytearray(encrypted); bad[148] ^= 1
        with self.assertRaises(ValueError): server.reply(bytes(bad), 30000000)

    def test_record_layout_matches_firmware_installer(self):
        record = KeyRecord(bytes(range(32)))
        encoded = record.encode()
        self.assertEqual(encoded[:12].hex(), '5e2f50fe4000004001020201')
        self.assertEqual(encoded[28:32], b'\x20\0\0\0')
        self.assertEqual(KeyRecord.decode(encoded), record)
        self.assertNotIn(record.key.hex(), repr(record))

    def test_server_identity_marker_and_lengths(self):
        key = bytes(range(32))
        wire = hello_reply(123456, 0x104cb, 30000000, key=key)
        plain = open_packet(wire, key)
        self.assertEqual(validate_server_packet(plain), plain)
        bad = bytearray(plain); bad[24] ^= 1
        with self.assertRaises(ValueError): validate_server_packet(bad)
        with self.assertRaises(ValueError): open_packet(wire[:-1], key)
        with self.assertRaises(ValueError): crypt(bytes(16), bytes(16))

    def test_recover_from_stable_references_with_other_fields_changed(self):
        day, session = bytes(range(32)), bytes(reversed(range(32)))
        first = bytearray(192)
        first[:12] = bytes.fromhex('01f0a5a540e2010023050100')
        first[32:148] = bytes(range(116))
        second = bytearray(first)
        second[8:12] = bytes.fromhex('cd064001')
        second[16:32] = b'fields changed!!'
        second[16:] = crypt(bytes(second[16:]), day)
        grant = hello_reply(123456, 0x14006cd, 30000000,
                            records=[KeyRecord(session)], key=day)
        confirm = hello_reply(123456, 0x104cb, 30000000, key=session)
        rows = [{'hex': p.hex()} for p in [first, second, grant, confirm]]
        self.assertEqual(recover(rows)['session_key_hex'], session.hex())
        with self.assertRaises(ValueError): recover(rows[:-1])


if __name__ == '__main__': unittest.main()
