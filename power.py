"""Live power from explicitly configured CT channels; no local history."""
import struct
import time


class Power:
    def __init__(self, channels=None):
        self.channels=channels or {}
        self.values={}

    def observe(self, raw, source):
        if len(raw)<10:return
        kind=int.from_bytes(raw[2:4],'little')
        if kind==0x3730 and len(raw)>=14:
            serial=int.from_bytes(raw[10:14],'little');offset=14
        elif kind==0x3510 and len(raw)>=24 and (raw[4]>>3)&7==2:
            serial=int.from_bytes(raw[6:10],'little');offset=24
        else:return
        while offset<len(raw):
            size=raw[offset]&15
            if size<1 or offset+size>len(raw):break
            record=raw[offset:offset+size]
            if size==8 and record[0]>>4==0:
                channel=record[1]>>4
                for name,config in self.channels.items():
                    if config['serial']==serial and config['channel']==channel:
                        self.values[name]={'watts':struct.unpack_from('<h',record,4)[0],
                                           'received_at':time.time(),'source':source}
            offset+=size

    def status(self):
        now=time.time()
        return {name:(value if (value:=self.values.get(name)) and now-value['received_at']<30 else None)
                for name in self.channels}
