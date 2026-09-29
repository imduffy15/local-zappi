"""Passive, bounded recovery of session grants; never sends charger traffic."""
import struct
from protocol import HELLO_DEVICE, HELLO_SERVER, KeyRecord, open_packet, validate_server_packet


class SessionRecovery:
    def __init__(self, serial):
        self.serial = serial
        self.exchanges = {}

    def observe(self, direction, packet, route, now):
        # Scope recovery to one configured device and the same upstream route.
        self.exchanges = {r: s for r, s in self.exchanges.items()
                          if 0 <= now - s['started'] <= 120}
        if len(packet) < 32 or len(packet) % 16:
            return None
        magic, serial, control = struct.unpack_from('<III', packet)
        if serial != self.serial:
            return None
        if direction == 'device' and magic == HELLO_DEVICE and len(packet) == 192:
            if control >> 24 == 0 and not control & 8:
                if route not in self.exchanges and len(self.exchanges) >= 32:
                    return None
                self.exchanges[route] = {'started': now, 'plain': packet}
            elif control >> 24 == 1 and route in self.exchanges:
                state = self.exchanges[route]
                if packet[12:16] != state['plain'][12:16]:
                    return None
                state['control'] = control
                state['stream'] = bytes(a ^ b for a, b in zip(state['plain'][32:96], packet[32:96]))
                state.pop('candidate', None)
            return None
        if direction != 'upstream' or magic != HELLO_SERVER:
            return None
        state = self.exchanges.get(route, {})
        if len(packet) == 96 and control == state.get('control'):
            try:
                record = KeyRecord.decode(bytes(a ^ b for a, b in zip(packet[32:], state['stream'])))
            except ValueError:
                return None
            if record.slot == 0 and record.group == 2:
                state['candidate'] = record.key
        elif control >> 24 == 0 and control & 8 and 'candidate' in state:
            try:
                validate_server_packet(open_packet(packet, state['candidate']))
            except ValueError:
                return None
            key = state['candidate']
            del self.exchanges[route]
            return key
        return None
