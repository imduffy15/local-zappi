#!/usr/bin/env python3
"""Classify observed request/reply correlations without decrypting or replaying.
Unmatched upstream packets are candidates for unsolicited messages, not proven
commands. Capture start gaps, retries and old replies can also be unmatched.
"""
import argparse,collections,datetime,json,pathlib

def summarize(rows):
    counts=collections.Counter();lengths=collections.defaultdict(collections.Counter)
    pending=collections.defaultdict(collections.deque);unmatched=[];matched=0;delays=[];start=None;end=None
    for index,r in enumerate(rows,1):
        direction=r.get('direction');data=bytes.fromhex(r['hex']);stamp=r['time']
        if start is None:start=stamp
        end=stamp;counts[direction]+=1;lengths[direction][len(data)]+=1
        if direction not in ('device','upstream') or len(data)<8:continue
        key=(r.get('route'),data[4:8])
        if direction=='device':pending[key].append(stamp)
        elif pending[key]:
            sent=pending[key].popleft();matched+=1;delays.append((stamp-sent)*1000)
        else:
            unmatched.append(dict(record=index,time_utc=datetime.datetime.fromtimestamp(stamp,datetime.timezone.utc).isoformat(),
                                  bytes=len(data),correlation_hex=data[4:8].hex(),route=r.get('route')))
    return dict(records=sum(counts.values()),counts=dict(counts),lengths={k:dict(v) for k,v in lengths.items()},
                matched_upstream=matched,unmatched_upstream=unmatched,
                unmatched_device=sum(len(q) for q in pending.values()),
                matched_reply_delay_ms={'min':round(min(delays),3),'max':round(max(delays),3)} if delays else {},
                first_timestamp=start,last_timestamp=end,
                caveat='Correlation uses raw bytes 4..7 and route; unmatched does not by itself prove an app command.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('journal',type=pathlib.Path);a=p.parse_args()
    with a.journal.open() as f:result=summarize(json.loads(line) for line in f if line.strip())
    print(json.dumps(result,indent=2))
