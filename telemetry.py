#!/usr/bin/env python3
"""Read-only decoder of saved myenergi Ethernet frames (not RF packets).
Standard library only. Prints one JSON object per decoded message. All CT
numeric fields remain raw until units are verified against firmware/measurements.
"""
import argparse, collections, json, struct
from pathlib import Path

def packets(path):
    with path.open('rb') as f:
        h=f.read(24)
        if len(h)!=24: raise ValueError('Truncated pcap header')
        formats={b'\xd4\xc3\xb2\xa1':('<',1e6),b'\xa1\xb2\xc3\xd4':('>',1e6),b'\x4d\x3c\xb2\xa1':('<',1e9),b'\xa1\xb2\x3c\x4d':('>',1e9)}
        if h[:4] not in formats: raise ValueError('Classic pcap required')
        endian,scale=formats[h[:4]]
        if struct.unpack(endian+'I',h[20:24])[0]!=1: raise ValueError('Ethernet link type required')
        n=0
        while hdr:=f.read(16):
            if len(hdr)!=16: raise ValueError('Truncated packet header')
            sec,sub,cap,wire=struct.unpack(endian+'4I',hdr)
            if cap>16*1024*1024: raise ValueError('Invalid capture length')
            packet=f.read(cap)
            if len(packet)!=cap: raise ValueError('Truncated packet')
            n+=1
            yield n,sec+sub/scale,packet

def records(frame):
    if len(frame)<14:return
    ethertype=int.from_bytes(frame[12:14],'big');pos=14
    while ethertype in (0x8100,0x88a8):
        if len(frame)<pos+4:return
        ethertype=int.from_bytes(frame[pos+2:pos+4],'big');pos+=4
    if ethertype!=0x88b5:return
    data=frame[pos:]
    if len(data)<24 or data[:4]!=bytes.fromhex('cbdae9f8'):return
    off=24
    while off<len(data):
        n=data[off]
        if n==0:return  # Ethernet padding
        if n<6 or off+n>len(data):raise ValueError('Invalid myenergi record length')
        r=data[off:off+n]
        rec=dict(eth_src=frame[6:12].hex(':'),eth_dst=frame[:6].hex(':'),type=f'0x{int.from_bytes(r[2:4],"little"):04x}',length=n,network_byte=r[1],device_byte=r[4],flags=r[5],raw=r.hex())
        if len(r)>=10:rec['origin_serial']=int.from_bytes(r[6:10],'little')
        if rec['type']=='0x3730' and len(r)>=16:
            rec['harvi_serial']=int.from_bytes(r[10:14],'little')
            ct=[];p=14
            while p+8<=len(r)-2:
                q=r[p:p+8]
                if q[0]!=8:break
                ct.append(dict(channel=q[1]>>4,channel_flags=q[1]&15,type_code=q[2],status_byte=q[3],value_a_s16=struct.unpack_from('<h',q,4)[0],value_b_s16=struct.unpack_from('<h',q,6)[0],raw=q.hex()))
                p+=8
            rec['ct_records']=ct;rec['remaining_hex']=r[p:].hex()
        yield rec
        off+=n

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('pcap',type=Path,nargs='+');ap.add_argument('--summary',action='store_true');args=ap.parse_args()
    counts=collections.Counter();harvis=collections.defaultdict(list)
    for path in args.pcap:
        for number,timestamp,frame in packets(path):
            for r in records(frame):
                r.update(capture=str(path),frame=number,timestamp=timestamp)
                counts[r['type']]+=1
                if 'harvi_serial' in r:harvis[r['harvi_serial']].append(r)
                if not args.summary:print(json.dumps(r))
    if args.summary:
        summary=dict(record_types=counts,harvis={})
        for sn,rs in harvis.items():
            channel={}
            for r in rs:
                for c in r['ct_records']:
                    channel.setdefault(c['channel'],[]).append(c)
            summary['harvis'][sn]=dict(records=len(rs),channels={ch:dict(type_codes=sorted(set(c['type_code'] for c in cs)),a_range=[min(c['value_a_s16'] for c in cs),max(c['value_a_s16'] for c in cs)],b_range=[min(c['value_b_s16'] for c in cs),max(c['value_b_s16'] for c in cs)]) for ch,cs in channel.items()})
        print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
