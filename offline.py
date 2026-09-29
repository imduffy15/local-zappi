"""Charger-facing session service used only while cloud forwarding is disabled."""
import json
import pathlib
import secrets
import struct
import time
from recovery import SessionRecovery
from protocol import SessionNegotiator, DATA_DEVICE, DATA_SERVER, HELLO_DEVICE, crypt


def keepalive(packet, serial, key):
    # Subtype 2 ignores an extension whose first byte is not 0x3e, but updates
    # receive liveness (firmware 0x4b2dc, 0x4b576). No configuration is written.
    reply = bytearray(48)
    struct.pack_into('<4I', reply, 0, DATA_SERVER,
                     int.from_bytes(packet[4:8], 'little'), secrets.randbelow(0xffffffff)+1, serial)
    struct.pack_into('<IIIHH', reply, 16, 21, serial, int(time.time()), 33, 2)
    reply[16:] = crypt(bytes(reply[16:]), key)
    return bytes(reply)


class Offline:
    def __init__(self, control, state_dir):
        self.control = control
        self.negotiator = None
        path = pathlib.Path(state_dir) / 'bootstrap.json'
        if path.exists():
            if path.stat().st_mode & 0o077: raise ValueError('bootstrap.json must be private (0600)')
            config = json.loads(path.read_text())
            serial = config['serial']
            if control.serial is not None and serial != control.serial:
                raise ValueError('bootstrap serial does not match provisioned device')
            control.serial = serial
            control.recovery = SessionRecovery(serial)
            self.negotiator = SessionNegotiator(serial, config['product'], config['version'],
                                               bytes.fromhex(config['bootstrap_key_hex']), control.key)

    @property
    def supported(self): return self.negotiator is not None

    def receive(self, packet, downstream, addr, valid=False):
        c = self.control
        if self.negotiator is None: return
        if int.from_bytes(packet[:4], 'little') == HELLO_DEVICE:
            try:
                self.negotiator.session_key = c.key
                reply = self.negotiator.reply(packet, int(time.time()//60))
                if self.negotiator.session_key != c.key:
                    c.install_key(self.negotiator.session_key)
            except (ValueError, OSError):
                c.counts['offline_handshake_rejected'] += 1
                return
            downstream.transport.sendto(reply, addr)
            downstream.relay.record('local-session', reply, route=downstream.route['name'], peer=addr)
            c.counts['offline_handshake_replies'] += 1
            return
        # Control.device has already validated identity, decryption and records.
        if (not valid or int.from_bytes(packet[:4], 'little') != DATA_DEVICE or c.peer != (downstream, addr)
                or time.time()-c.peer_at > .5 or c.session_state != 'verified_local'):
            return
        reply = keepalive(packet, c.serial, c.key)
        downstream.transport.sendto(reply, addr)
        downstream.relay.record('local-keepalive', reply, route=downstream.route['name'], peer=addr)
        c.counts['offline_keepalives'] += 1
