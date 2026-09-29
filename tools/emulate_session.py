"""Offline session-handler execution. Network, EEPROM and AES hardware stubbed.

Executes the actual key-selection and key-install instructions. Synthetic keys
only. Requires unicorn and cryptography; never opens a network socket.
"""
from pathlib import Path
import sys, struct, json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import *
from protocol import crypt, hello_reply, KeyRecord, SessionNegotiator

STATE, KEYS, CONFIG, PRODUCT = 0x20010488, 0x20030000, 0x2000e400, 0x2002f000
PACKET, PAYLOAD, STOP = 0x20040000, 0x20041000, 0x9f000
SERIAL = 12345678


class Device:
    def __init__(self, image):
        self.u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.u.mem_map(0x30000, 0x70000); self.u.mem_write(0x30000, image)
        self.u.mem_map(0x20000000, 0x80000)
        self.put(STATE, KEYS); self.put(CONFIG+16, SERIAL)
        self.u.mem_write(CONFIG+0x28b, b'\x01\0\0\0\0\0\0\0\x08')
        self.u.mem_write(STATE+0x4c, struct.pack('<H', 0x100))
        self.u.mem_write(PRODUCT+0xb4, struct.pack('<H', 3562))
        self.u.mem_write(PRODUCT+0xa, struct.pack('<H', 5794))
        self.calls = []; self.sent = []; self.aes_key = None
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def put(self, address, value): self.u.mem_write(address, struct.pack('<I', value))
    def state(self): return (int.from_bytes(self.u.mem_read(STATE+0x4c, 2), 'little') >> 8) & 15
    def hook(self, u, a, size, _):
        if a == STOP: u.emu_stop(); return
        regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
        r = [u.reg_read(x) for x in regs]
        result = 0
        if a in (0x38d3c, 0x38fc8): u.mem_write(r[0], bytes(u.mem_read(r[1], r[2])))
        elif a == 0x3699c: u.mem_write(r[0], bytes(r[1]))
        elif a == 0x38fa0: result = int(bytes(u.mem_read(r[0], r[2])) != bytes(u.mem_read(r[1], r[2])))
        elif a == 0x4df9e: self.aes_key = bytes(u.mem_read(r[1], 32))
        elif a == 0x4e010:
            u.mem_write(r[2], crypt(bytes(u.mem_read(r[1], r[3])), self.aes_key)); result = 1
        elif a == 0x39000:
            self.sent.append(bytes(u.mem_read(r[1], r[2])))
        elif a in (0x39078, 0x3f154, 0x4df78, 0x4df8e, 0x4dfea, 0x4de84, 0x4deaa): pass
        elif a == 0x465f8: result = 1234
        else: return
        self.calls.append(hex(a)); u.reg_write(UC_ARM_REG_R0, result)
        u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))

    def receive(self, packet):
        self.u.mem_write(PAYLOAD, packet + bytes(1500-len(packet)))
        self.put(PACKET+16, PAYLOAD)
        self.u.mem_write(PACKET+20, struct.pack('<Hh', len(packet), 0))
        self.u.reg_write(UC_ARM_REG_SP, 0x2007f000)
        self.u.reg_write(UC_ARM_REG_R1, PACKET)
        self.u.reg_write(UC_ARM_REG_LR, STOP|1)
        self.u.emu_start(0x41951, STOP, count=100000)
        if self.u.reg_read(UC_ARM_REG_PC) != STOP:
            raise RuntimeError('handler did not finish')

    def hello(self):
        self.u.reg_write(UC_ARM_REG_SP, 0x2007f000)
        self.u.reg_write(UC_ARM_REG_R0, STATE)
        control = int.from_bytes(self.u.mem_read(STATE+0x34, 4), 'little') or 3
        self.u.reg_write(UC_ARM_REG_R1, control)
        self.u.reg_write(UC_ARM_REG_LR, STOP|1)
        count = len(self.sent)
        self.u.emu_start(0x4156d, STOP, count=100000)
        assert len(self.sent) == count + 1
        return self.sent[-1]


def run(image):
    d = Device(image)
    server = SessionNegotiator(SERIAL, 3562, 5794, image[:32], bytes(range(32)))
    # Plain hello selects firmware bootstrap slot zero, bypassing stored day keys.
    d.receive(server.reply(d.hello(), 30000000))
    assert d.state() == 2, d.state()
    bootstrap = image[:32]
    assert bytes(d.u.mem_read(KEYS+32, 32)) == bootstrap
    session = KeyRecord(bytes(range(32)))
    d.receive(server.reply(d.hello(), 30000000))
    assert d.state() == 5, d.state()
    assert bytes(d.u.mem_read(KEYS+32, 32)) == session.key
    d.receive(hello_reply(SERIAL, 0xcb040100, 30000000, key=session.key))
    assert d.state() == 5, 'wrong control header must not establish session'
    d.receive(server.reply(d.hello(), 30000000))
    assert d.state() == 6, d.state()
    assert server.established
    return dict(result='pass', states=[1, 2, 5, 6], generated_device_hellos=len(d.sent),
                scope=__doc__, physical_device_commands_sent=0)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path)
    args = parser.parse_args()
    import hashlib
    image = args.firmware.read_bytes()
    if hashlib.sha256(image).hexdigest() != '605ae6979f8fb3ea74bfd935682f4d632dac5b8f9714318c480382f047104a2d':
        parser.error('emulation addresses require the verified product 3562 firmware 5.794')
    print(json.dumps(run(image), indent=2))
