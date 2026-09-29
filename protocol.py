"""Zappi 5.794 session primitives, recovered from an owner-supplied firmware.

Keys and firmware are deliberately not bundled. AES-CTR restarts its fixed
counter for every datagram, as the firmware does; this is not a recommendation
for designing a new protocol. This module performs no network I/O.
"""
import dataclasses
import struct
import secrets
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

IV = bytes(range(0xf0, 0x100))
KEY_MAGIC = 0xfe502f5e
HELLO_DEVICE = 0xa5a5f001
HELLO_SERVER = 0xa5a5f000
DATA_DEVICE = 0xfacecacf
DATA_SERVER = 0xab1234d2
SERVER_MARKER = 0x4b5c6d7f


def crypt(data, key):
    if len(key) != 32 or len(data) % 16:
        raise ValueError('AES-256 key and whole blocks required')
    return Cipher(algorithms.AES(key), modes.CTR(IV)).encryptor().update(data)


@dataclasses.dataclass(frozen=True)
class KeyRecord:
    key: bytes = dataclasses.field(repr=False)
    slot: int = 0
    group: int = 2
    algorithm: int = 2
    reference: int = 0
    valid_from: int = 0
    valid_to: int = 0

    def encode(self):
        if len(self.key) != 32 or not 0 <= self.slot < 32:
            raise ValueError('invalid key record')
        b = bytearray(64)
        struct.pack_into('<IHBBBBBBIIIIHH', b, 0, KEY_MAGIC, 64,
                         self.slot, 0x40, 1, self.group, self.algorithm, 1,
                         self.reference, self.valid_from, self.valid_to, 0, 32, 0)
        b[32:] = self.key
        return bytes(b)

    @classmethod
    def decode(cls, data):
        if len(data) < 64:
            raise ValueError('truncated key record')
        magic, length = struct.unpack_from('<IH', data)
        keylen = struct.unpack_from('<H', data, 28)[0]
        if magic != KEY_MAGIC or length != 64 or keylen != 32 or data[8] != 1:
            raise ValueError('unsupported key record')
        if data[10] != 2:
            raise ValueError('only AES-256 records supported')
        ref, start, end = struct.unpack_from('<III', data, 12)
        return cls(bytes(data[32:64]), data[6] & 31, data[9], data[10], ref, start, end)


def hello_reply(serial, control, minute, counter=0, slot=0, records=(), key=None):
    """Build the 32-byte reply header plus optional encrypted key records."""
    records = tuple(records)
    if not 0 <= slot < 32 or len(records) > 31:
        raise ValueError('invalid slot or record count')
    b = bytearray(32)
    struct.pack_into('<8I', b, 0, HELLO_SERVER, serial, control, minute,
                     counter, SERVER_MARKER, serial, slot | (len(records) << 8))
    b.extend(b''.join(record.encode() for record in records))
    if key is not None:
        b[16:] = crypt(bytes(b[16:]), key)
    return bytes(b)


def open_packet(packet, key):
    if len(packet) < 32 or len(packet) % 16:
        raise ValueError('invalid encrypted datagram length')
    return packet[:16] + crypt(packet[16:], key)


def validate_server_packet(plaintext):
    if len(plaintext) < 32:
        raise ValueError('truncated reply')
    magic = struct.unpack_from('<I', plaintext)[0]
    if magic == HELLO_SERVER:
        if plaintext[4:8] != plaintext[24:28] or struct.unpack_from('<I', plaintext, 20)[0] != SERVER_MARKER:
            raise ValueError('invalid handshake identity/marker')
    elif magic == DATA_SERVER:
        if plaintext[12:16] != plaintext[20:24]:
            raise ValueError('invalid application identity')
        length, subtype = struct.unpack_from('<HH', plaintext, 28)
        if not 32 <= length <= len(plaintext) or subtype not in (1, 2, 3, 4):
            raise ValueError('invalid application envelope')
    else:
        raise ValueError('unsupported reply magic')
    return plaintext


class SessionNegotiator:
    """Pure server-side handshake state machine for one configured charger.

    Bootstrap material is supplied privately from the matching firmware dump.
    Callers must persist session_key before transmitting a key grant. This class
    does not send packets or change a charger's mode/settings.
    """
    def __init__(self, serial, product, version, bootstrap_key, session_key=None):
        if product != 3562:
            raise ValueError('only product 3562 has been verified')
        if len(bootstrap_key) != 32 or (session_key is not None and len(session_key) != 32):
            raise ValueError('invalid key size')
        self.serial, self.product, self.version = serial, product, version
        self.bootstrap_key = bootstrap_key
        self.session_key = session_key
        self.established = False

    def reply(self, packet, minute):
        if len(packet) != 192:
            raise ValueError('expected a device hello')
        magic, serial, control, product_version = struct.unpack_from('<4I', packet)
        if magic != HELLO_DEVICE or serial != self.serial:
            raise ValueError('unexpected device identity')
        if product_version != self.product | self.version << 16:
            raise ValueError('unexpected firmware identity')
        if control >> 24 == 0 and not control & 8:
            self.established = False
            # Force the known firmware bootstrap path; do not replace EEPROM keys.
            return hello_reply(serial, 0x407, minute)
        if control == 0x85000000 | self.version:
            plain = open_packet(packet, self.bootstrap_key)
            key = self.bootstrap_key
            installing = True
        elif control >> 24 == 0 and control & 8 and self.session_key is not None:
            plain = open_packet(packet, self.session_key)
            key = self.session_key
            installing = False
        else:
            raise ValueError('unsupported key reference; bootstrap needed')
        if struct.unpack_from('<I', plain, 148)[0] != 0x3a4b5c6d:
            raise ValueError('invalid decrypted device hello marker')
        counter = struct.unpack_from('<I', plain, 16)[0]
        if installing:
            if self.session_key is None:
                self.session_key = secrets.token_bytes(32)
            return hello_reply(serial, control, minute, counter=counter,
                               records=[KeyRecord(self.session_key)], key=key)
        self.established = True
        return hello_reply(serial, (control & ~0xe0) | 0xc0, minute,
                           counter=counter, key=key)
