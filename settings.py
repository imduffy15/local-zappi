"""Native boost and timer configuration, read before write and verified afterward."""
import struct
import time
from protocol import crypt, open_packet


def packet(control, selector, data=b'', tail=b''):
    plain=bytearray(open_packet(control.mode_packet('stop'),control.key))
    struct.pack_into('<H',plain,38,selector)
    plain[42:70]=bytes(28)
    plain[42:42+len(data)]=data
    plain[66:66+len(tail)]=tail
    plain[16:]=crypt(bytes(plain[16:]),control.key)
    return bytes(plain)


def decode_config(data):
    if len(data)!=128 or data[:4]!=bytes.fromhex('1057a5f8'):
        raise ValueError('unsupported charger configuration')
    schedules=[]
    for slot in range(4):
        duration,hour,minute,days=struct.unpack_from('<HBBB',data,4+slot*6)
        schedules.append({'slot':slot,'start':f'{hour:02}:{minute:02}',
                          'duration_minutes':duration,'days':[i for i in range(7) if days & 1<<i]})
    return {'schedules':schedules,'manual_kwh':data[56],'smart_kwh':data[51],
            'smart_time':f'{data[49]:02}:{data[50]:02}', 'minimum_green_percent':data[53]}


class Settings:
    def __init__(self, control):
        self.control=control
        self.config=None
        self.config_at=0
        self.queue=[]
        self.awaiting=None
        self.chunks={}
        self.expected=None
        self.result=None
        self.last_read_attempt=0

    def busy(self):return bool(self.queue or self.awaiting)

    def read(self):
        self.chunks={}
        self.queue.extend((4,b'',struct.pack('<HBB',o,1,min(40,128-o))) for o in range(0,128,40))
        self.last_read_attempt=time.time()

    def start(self, kind):
        if not self.control.ready():raise RuntimeError('charger is not connected')
        if self.busy():raise RuntimeError('charger settings request already pending')
        command=self.control.last_local_command or {}
        if command.get('status') in ('queued','sent_unconfirmed'):raise RuntimeError('mode change is pending')
        self.result={'kind':kind,'status':'pending','requested_at':time.time()}

    def refresh(self):
        self.start('read');self.read();return self.result

    def boost(self, body):
        kind=body.get('kind')
        if kind not in ('manual','smart','cancel'):raise ValueError('expected manual, smart or cancel')
        tail=bytearray(4);data=bytearray(24)
        if kind=='cancel':tail[1]=2
        else:
            kwh=body.get('kwh')
            if type(kwh) is not int or not 1<=kwh<=99:raise ValueError('boost energy must be 1–99 kWh')
            struct.pack_into('<H',data,16,kwh)
            tail[1]=12
            if kind=='smart':
                hour,minute=parse_time(body.get('time'))
                tail[1]|=16;tail[2:]=bytes((hour,minute))
        self.start('boost_'+kind)
        self.queue.append((2,bytes(data),bytes(tail)))
        self.read()
        return self.result

    def schedules(self, body):
        if self.config is None or time.time()-self.config_at>120:
            raise RuntimeError('refresh charger settings before saving schedules')
        rows=body.get('schedules')
        if not isinstance(rows,list) or len(rows)!=4:raise ValueError('expected four timer slots')
        data=bytearray(self.config)
        for slot,row in enumerate(rows):
            if not isinstance(row,dict):raise ValueError('invalid timer')
            hour,minute=parse_time(row.get('start'))
            duration=row.get('duration_minutes');days=row.get('days')
            if type(duration) is not int or not 0<=duration<=24*60:raise ValueError('duration must be 0–1440 minutes')
            if not isinstance(days,list) or any(type(d) is not int or not 0<=d<=6 for d in days):raise ValueError('invalid timer days')
            struct.pack_into('<HBBB',data,4+slot*6,duration,hour,minute,sum(1<<d for d in set(days)))
        self.start('schedules')
        self.expected=bytes(data)
        self.queue.extend((5,bytes(data[o:o+24]),struct.pack('<HBB',o,1,len(data[o:o+24]))) for o in range(0,128,24))
        self.read()
        return self.result

    def observe(self, raw, source):
        if (len(raw)>=24 and raw[2:4]==b'\x10\x35'
                and int.from_bytes(raw[6:10],'little')==self.control.serial):
            ack=raw[13]
            if (ack&0x80 and self.awaiting and self.awaiting.get('sequence')==ack&7):
                if not ack&8:self.fail('charger rejected the settings command')
                elif self.awaiting.get('kind')=='write':self.awaiting=None
        if len(raw)<14 or raw[2:4]!=b'||' or int.from_bytes(raw[6:10],'little')!=self.control.serial:return
        offset,region,size=struct.unpack_from('<HBB',raw,10)
        if region!=1 or not 0<size<=40 or offset+size>128 or len(raw)<14+size:return
        if not self.awaiting or self.awaiting.get('offset')!=offset:return
        self.chunks[offset]=bytes(raw[14:14+size]);self.awaiting=None
        if len(self.chunks)==4:
            data=b''.join(self.chunks[o] for o in (0,40,80,120))
            try:decode_config(data)
            except ValueError as exc:self.fail(str(exc));return
            self.config=data;self.config_at=time.time()
            if self.expected is not None and data!=self.expected:
                self.fail('charger settings readback did not match');return
            self.expected=None
            if self.result:
                # Configuration readback confirms saved values; boost activation
                # is exposed separately in telemetry, never inferred from send.
                self.result.update(status='read_back',completed_at=time.time())

    def fail(self, error):
        self.queue=[];self.awaiting=None;self.expected=None
        if self.result:self.result.update(status='failed',error=error,completed_at=time.time())

    def poll(self):
        if self.awaiting:
            if time.time()-self.awaiting['sent_at']>30:self.fail('charger configuration read timed out')
            return
        if not self.queue or not self.control.ready():return
        command=self.control.last_local_command or {}
        if command.get('status') in ('queued','sent_unconfirmed'):return
        selector,data,tail=self.queue.pop(0)
        try:wire=packet(self.control,selector,data,tail)
        except (RuntimeError,ValueError) as exc:self.fail(str(exc));return
        downstream,addr=self.control.peer
        downstream.transport.sendto(wire,addr)
        downstream.relay.record('local-settings',wire,route=downstream.route['name'],peer=addr)
        self.awaiting={'kind':'read' if selector==4 else 'write','sequence':self.control.sequence,'sent_at':time.time()}
        if selector==4:self.awaiting['offset']=int.from_bytes(tail[:2],'little')

    def status(self):
        if self.awaiting and time.time()-self.awaiting['sent_at']>30:self.fail('charger configuration read timed out')
        return {'configuration':decode_config(self.config) if self.config else None,
                'received_at':self.config_at or None,'request':self.result,'busy':self.busy()}


def parse_time(value):
    try:
        if not isinstance(value,str) or len(value)!=5 or value[2]!=':':raise ValueError()
        hour,minute=map(int,value.split(':'))
        if not 0<=hour<=23 or not 0<=minute<=59:raise ValueError()
        return hour,minute
    except (ValueError,TypeError):raise ValueError('time must be HH:MM') from None
