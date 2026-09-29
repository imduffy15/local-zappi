#!/usr/bin/env python3
"""Offline timeline and byte differences; no decryption or command inference.
Accepts local-zappi JSONL. Does not contact the charger or vendor services.
"""
import argparse,collections,datetime,json,pathlib,struct

def spans(indices):
    groups=[]
    for i in indices:
        if groups and groups[-1][1]+1==i: groups[-1][1]=i
        else: groups.append([i,i])
    return groups

def analyze(path):
    previous={};pending={};counts=collections.Counter()
    with path.open() as f:
        for line in f:
            try:r=json.loads(line)
            except json.JSONDecodeError:continue # writer may have a partial final line
            direction=r.get('direction')
            if direction not in ('device','upstream'):continue
            try:b=bytes.fromhex(r['hex'])
            except (ValueError,KeyError):continue
            counts[direction]+=1
            row=dict(time_utc=datetime.datetime.fromtimestamp(r['time'],datetime.timezone.utc).isoformat(),
                     direction=direction,route=r.get('route'),bytes=len(b))
            if len(b)>=16:
                row['magic_le']=f'0x{struct.unpack_from("<I",b)[0]:08x}'
                # These bytes match in observed request/reply pairs. Names are provisional.
                row['correlation_hex']=b[4:8].hex()
                key=(r.get('route'),b[4:8])
                if direction=='device':pending[key]=r['time']
                elif key in pending:row['reply_delay_ms']=round((r['time']-pending.pop(key))*1000,3)
            key=(direction,r.get('route'),len(b))
            if key in previous:
                old=previous[key]
                row['changed_byte_ranges_vs_previous_same_length']=spans(i for i,(a,c) in enumerate(zip(old,b)) if a!=c)
            previous[key]=b
            yield row

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('journal',type=pathlib.Path);a=p.parse_args()
    for row in analyze(a.journal):print(json.dumps(row))
