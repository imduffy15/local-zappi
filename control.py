"""Validated-session observation and explicit local charging-mode commands.

Does not interpret a sent command as confirmation that charging mode changed.
"""
import hashlib
import collections
import json
import pathlib
import os
import tempfile
import struct
import secrets
import time
from protocol import DATA_DEVICE, DATA_SERVER, HELLO_DEVICE, crypt, open_packet, validate_server_packet
from recovery import SessionRecovery

MODES = {'fast': 1, 'eco': 2, 'eco_plus': 3, 'stop': 4}


class Control:
    def __init__(self, state_dir):
        self.key_path = pathlib.Path(state_dir) / 'session-keys.json'
        self.serial = None
        self.key = None
        self.counts = collections.Counter()
        self.last_valid = None
        self.last_cloud_command = None
        self.last_mode_command = None
        self.last_local_command = None
        self.device_mode = None
        self.target = None
        self.sequence = 0
        self.command_counter = None
        self.counter_at = 0
        self.peer = None
        self.offline = False
        self.peer_at = 0
        self.verified_at = 0
        self.config_stage = {}
        self.observed_config = None
        self.records = {}
        self.session_state = "no_key"
        self.recovered_at = None
        self.emit = lambda kind, data: None
        self.telemetry = lambda source, record: None
        if self.key_path.exists():
            if self.key_path.stat().st_mode & 0o077:
                raise ValueError('session-keys.json must not be accessible to other users')
            saved = json.loads(self.key_path.read_text())
            self.serial = saved['serial']
            self.key = bytes.fromhex(saved['session_key_hex'])
            if type(self.serial) is not int or len(self.key) != 32:
                raise ValueError('invalid private session configuration')
            self.session_state = 'awaiting_traffic'
        self.recovery = SessionRecovery(self.serial)
        self.restore_session()
        self.restore_counter()

    def restore_session(self):
        # The handshake may have happened while an older server was running.
        # Replay only the bounded private journals, without restoring readiness.
        recovered = None
        latest_reply = None
        command_candidates = collections.deque(maxlen=256)
        for name in ('traffic.jsonl.1', 'traffic.jsonl'):
            path = self.key_path.parent / name
            if not path.exists():
                continue
            with path.open() as journal:
                for line in journal:
                    try:
                        row = json.loads(line)
                        if row.get('direction') not in ('device', 'upstream', 'local-command'):
                            continue
                        packet = bytes.fromhex(row['hex'])
                        if (row['direction'] == 'upstream' and len(packet) >= 32
                                and int.from_bytes(packet[:4], 'little') == DATA_SERVER
                                and int.from_bytes(packet[12:16], 'little') == self.serial):
                            latest_reply = packet
                        if row['direction'] in ('upstream', 'local-command') and len(packet) == 80:
                            command_candidates.append((row['time'], packet))
                        candidate = self.recovery.observe(row['direction'], packet,
                                                          row.get('route', ''), row['time'])
                        if candidate is not None:
                            recovered = candidate
                    except (ValueError, KeyError, TypeError):
                        continue
        if recovered is not None and recovered != self.key:
            try:
                # Do not overwrite a newer provisioned key with an old exchange.
                if latest_reply is not None:
                    validate_server_packet(open_packet(latest_reply, recovered))
                self.install_key(recovered)
            except ValueError:
                self.counts['journal_recovery_rejected'] += 1
            except OSError:
                self.counts['session_key_save_errors'] += 1
                self.session_state = 'recovery_save_failed'
        if self.key is not None:
            for timestamp, packet in reversed(command_candidates):
                try:
                    plain = validate_server_packet(open_packet(packet, self.key))
                    if (int.from_bytes(plain[:4], 'little') != DATA_SERVER
                            or int.from_bytes(plain[12:16], 'little') != self.serial
                            or struct.unpack_from('<HH', plain, 28) != (70, 3)):
                        continue
                    self.counter_at = timestamp
                    self.command_counter = int.from_bytes(plain[16:20], 'little')
                    self.sequence = int.from_bytes(plain[40:42], 'little') & 7
                    break
                except ValueError:
                    continue
        self.recovery.exchanges.clear()

    def restore_counter(self):
        path = self.key_path.parent / 'command-counter.json'
        if self.key is None or not path.exists(): return
        try:
            saved = json.loads(path.read_text())
            if (saved['session'] == hashlib.sha256(self.key).hexdigest()
                    and saved['updated_at'] >= self.counter_at
                    and type(saved['counter']) is int and 0 <= saved['counter'] <= 0xffffffff):
                self.command_counter = saved['counter']
                self.counter_at = saved['updated_at']
                self.sequence = self.command_counter & 7
        except (ValueError, KeyError, TypeError):
            self.counts['counter_restore_errors'] += 1

    def save_counter(self):
        fd, name = tempfile.mkstemp(prefix='.counter-', dir=self.key_path.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump({'session': hashlib.sha256(self.key).hexdigest(),
                           'counter': self.command_counter, 'updated_at': self.counter_at}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.key_path.parent / 'command-counter.json')
        finally:
            if os.path.exists(name): os.unlink(name)

    def install_key(self, key):
        # Persist privately and atomically before making the key active.
        fd, name = tempfile.mkstemp(prefix='.session-', dir=self.key_path.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump({'serial': self.serial, 'session_key_hex': key.hex()}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.key_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        self.key = key
        self.command_counter = None
        self.counter_at = 0
        self.sequence = 0
        self.peer = self.target = None
        self.peer_at = self.verified_at = 0
        self.config_stage = {}
        self.recovered_at = time.time()
        self.session_state = 'awaiting_traffic'
        self.counts['session_keys_recovered'] += 1
        self.emit('session_key_recovered', {'recovered_at': self.recovered_at})

    def observe_handshake(self, direction, packet, route):
        if (direction == 'device' and len(packet) == 192
                and int.from_bytes(packet[:4], 'little') == HELLO_DEVICE
                and int.from_bytes(packet[4:8], 'little') == self.serial):
            self.peer = None
            self.verified_at = 0
            self.session_state = 'recovering'
        candidate = self.recovery.observe(direction, packet, route, time.time())
        if candidate is not None:
            try:
                self.install_key(candidate)
            except OSError:
                self.counts['session_key_save_errors'] += 1
                self.session_state = 'recovery_save_failed'

    def device(self, packet, downstream, addr):
        self.observe_handshake('device', packet, downstream.route['name'])
        if self.key is None or len(packet) < 38 or len(packet) % 16:
            return
        if int.from_bytes(packet[:4], 'little') != DATA_DEVICE or int.from_bytes(packet[8:12], 'little') != self.serial:
            return
        plain = open_packet(packet, self.key)
        # Format sentinel plus bounded first telemetry record. Server replies
        # provide the stronger independent serial/envelope key validation.
        if plain[31] != 0xe3 or not 6 <= plain[32] + 1 <= len(plain)-32:
            self.session_state = 'key_mismatch'
            self.counts['device_decode_rejected'] += 1
            self.peer = None
            return
        self.peer = (downstream, addr)
        self.peer_at = time.time()
        self.counts['device_decrypted'] += 1
        if self.offline:
            self.session_state = 'verified_local'
        offset = 32
        while offset < len(plain) and plain[offset]:
            # UDP encodes record length minus one; Ethernet uses full length.
            size = plain[offset] + 1
            if size < 6 or offset+size > len(plain):
                self.counts['record_decode_rejected'] += 1
                break
            raw = plain[offset:offset+size]
            kind = f'0x{int.from_bytes(raw[2:4], "little"):04x}'
            if kind in ('0x7979', '0x3510') and len(raw) >= 10 and int.from_bytes(raw[6:10], 'little') == self.serial:
                self.target = (raw[1], raw[4] & 0x7f)
            self.observe_device_record(raw, 'udp')
            record_id = kind+':'+str(raw[4])
            if record_id in self.records or len(self.records) < 128:
                self.records[record_id] = {'type': kind, 'device_byte': raw[4],
                    'flags': raw[5], 'length': size, 'raw': raw.hex(), 'received_at': self.peer_at}
                self.telemetry('udp', self.records[record_id])
            offset += size
        self.dispatch_pending()
        return True

    def observe_device_record(self, raw, source):
        # Firmware 5.794 builder 0x3c5b0: 3510 byte 23 low two bits,
        # with stopped (internal mode >=4) encoded as zero.
        if (len(raw) < 24 or raw[2:4] != b'\x10\x35'
                or (raw[4] >> 3) & 7 != 2
                or int.from_bytes(raw[6:10], 'little') != self.serial):
            return
        now = time.time()
        mode = {0: 'stop', 1: 'fast', 2: 'eco', 3: 'eco_plus'}[raw[23] & 3]
        changed = self.device_mode is None or self.device_mode['mode'] != mode
        self.device_mode = {'mode': mode, 'received_at': now, 'source': source}
        if changed:
            self.emit('device_mode_observed', dict(self.device_mode))
        command = self.last_local_command
        if (command and command['status'] == 'sent_unconfirmed'
                and now > command['sent_at'] and mode == command['mode']
                and now - command['sent_at'] <= 30):
            command.update(status='confirmed', confirmed_at=now)
            self.emit('local_command_confirmed', dict(command))
        self.expire_command(now)

    def expire_command(self, now):
        command = self.last_local_command
        if (command and command['status'] in ('queued', 'sent_unconfirmed')
                and now-command.get('sent_at', command.get('requested_at', now)) > 30):
            command.update(status='not_confirmed', completed_at=now)
            self.emit('local_command_not_confirmed', dict(command))

    def upstream(self, packet, route=""):
        self.observe_handshake('upstream', packet, route)
        if self.key is None or len(packet) < 32 or len(packet) % 16:
            return
        magic = int.from_bytes(packet[:4], 'little')
        if magic != DATA_SERVER:
            return
        if int.from_bytes(packet[12:16], 'little') != self.serial:
            return
        try:
            plain = validate_server_packet(open_packet(packet, self.key))
        except ValueError:
            self.session_state = 'key_mismatch'
            self.counts['upstream_decode_rejected'] += 1
            self.verified_at = 0
            return
        now = time.time()
        self.verified_at = self.last_valid = now
        self.session_state = 'verified'
        self.counts['upstream_decrypted'] += 1
        length, subtype = struct.unpack_from('<HH', plain, 28)
        if subtype != 3 or length < 70:
            return
        selector, sequence = struct.unpack_from('<HH', plain, 38)
        self.sequence = sequence & 7
        self.command_counter = int.from_bytes(plain[16:20], 'little')
        self.counter_at = now
        try: self.save_counter()
        except OSError: self.counts['counter_save_errors'] += 1
        observed = {'received_at': now, 'selector': selector, 'sequence': sequence,
                    'target': plain[37]}
        if selector == 2:
            flags = plain[67]
            observed['flags'] = flags
            if flags & 1:
                observed['mode'] = next((name for name, value in MODES.items() if value == plain[66]), 'unknown')
                self.last_mode_command = dict(observed)
        elif selector == 5:
            offset, region, size = struct.unpack_from('<HBB', plain, 66)
            observed.update(offset=offset, region=region, size=size)
            # Observation only. Never use partial configuration as write data.
            if region == 1 and size <= 24 and offset + size <= 128:
                if offset == 0:
                    self.config_stage = {}
                self.config_stage[offset] = plain[42:42+size]
                if offset+size == 128:
                    merged = bytearray()
                    for start, data in sorted(self.config_stage.items()):
                        if start != len(merged): break
                        merged.extend(data)
                    if len(merged) == 128 and merged[:4] == bytes.fromhex('1057a5f8'):
                        self.observed_config = {'received_at': now, 'minimum_green_percent': merged[53]}
        self.last_cloud_command = observed
        self.emit('cloud_command_observed', dict(observed, status='observed_unconfirmed'))

    def ready(self):
        now = time.time()
        return (self.key is not None and self.peer is not None and self.target is not None
                and self.target[1] > 1 and now-self.peer_at < 30
                and (self.offline or now-self.verified_at < 30))

    def mode_packet(self, mode):
        if mode not in MODES:
            raise ValueError('mode must be fast, eco, eco_plus or stop')
        if not self.ready():
            raise RuntimeError('no recently verified live session; command not sent')
        self.command_counter = ((self.command_counter or self.sequence)+1) & 0xffffffff
        self.sequence = self.command_counter & 7
        self.counter_at = time.time()
        try: self.save_counter()
        except OSError as exc:
            raise RuntimeError('could not save command counter; command not sent') from exc
        packet = bytearray(80)
        struct.pack_into('<4I', packet, 0, DATA_SERVER, 0x001504cb, secrets.randbelow(0xffffffff)+1, self.serial)
        struct.pack_into('<IIIHH', packet, 16, self.command_counter, self.serial, int(time.time()), 70, 3)
        network, target = self.target
        packet[32:38] = bytes((38, network, 0x6b, 0x6b, 1, target))
        struct.pack_into('<HH', packet, 38, 2, self.sequence)
        packet[66:68] = bytes((MODES[mode], 1))
        packet[16:] = crypt(bytes(packet[16:]), self.key)
        return bytes(packet)

    def send_mode(self, mode):
        if mode not in MODES: raise ValueError('mode must be fast, eco, eco_plus or stop')
        if not self.ready(): raise RuntimeError('no recently verified live session; command not queued')
        self.expire_command(time.time())
        if self.last_local_command and self.last_local_command['status'] in ('queued', 'sent_unconfirmed'):
            raise RuntimeError('a mode request is already pending')
        self.last_local_command = {'mode': mode, 'requested_at': time.time(), 'status': 'queued'}
        self.emit('local_command_queued', dict(self.last_local_command))
        return self.last_local_command

    def cancel_pending(self):
        if self.last_local_command and self.last_local_command['status'] == 'queued':
            self.last_local_command.update(status='not_confirmed', completed_at=time.time())
            self.emit('local_command_not_confirmed', dict(self.last_local_command))

    def dispatch_pending(self):
        self.expire_command(time.time())
        command = self.last_local_command
        if not command or command['status'] != 'queued' or not self.ready(): return
        try:
            packet = self.mode_packet(command['mode'])
        except (RuntimeError, ValueError) as exc:
            self.cancel_pending()
            self.emit('local_command_rejected', {'mode': command['mode'], 'error': str(exc)})
            return
        downstream, addr = self.peer
        downstream.transport.sendto(packet, addr)
        downstream.relay.record('local-command', packet, route=downstream.route['name'], peer=addr)
        command.update(sequence=self.sequence, sent_at=time.time(), status='sent_unconfirmed')
        self.counts['local_commands_sent'] += 1
        self.emit('local_command_sent', dict(self.last_local_command))
        return self.last_local_command

    def status(self):
        self.expire_command(time.time())
        return {'key_loaded': self.key is not None, 'local_mode_control_ready': self.ready(),
                'session_state': self.session_state, 'session_recovered_at': self.recovered_at,
                'last_valid_upstream_at': self.last_valid, 'counters': dict(self.counts),
                'last_cloud_command': self.last_cloud_command,
                'last_mode_command': self.last_mode_command,
                'last_local_command': self.last_local_command,
                'device_mode': self.device_mode,
                'observed_cloud_config': self.observed_config,
                'udp_records': self.records}
