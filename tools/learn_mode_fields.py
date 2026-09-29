#!/usr/bin/env python3
"""Offline correlation of labeled wire samples; not a decryptor or command builder.
Input: JSON list of {mode: label, hex: complete UDP payload}. Requires repeated
observations of at least one mode to reject incidental counters. Output stays a
capture-specific hypothesis; encryption/key changes can invalidate wire offsets.
"""
import argparse,json,pathlib

def candidates(samples):
    groups={}
    for sample in samples:
        groups.setdefault(sample['mode'],[]).append(bytes.fromhex(sample['hex']))
    if len(groups)<2 or not any(len(v)>1 for v in groups.values()):
        raise ValueError('Need at least two modes and a repeated observation of one mode')
    lengths={len(b) for values in groups.values() for b in values}
    if len(lengths)!=1:raise ValueError('Compare samples of the same length and message family')
    result=[]
    for offset in range(next(iter(lengths))):
        values={mode:{b[offset] for b in packets} for mode,packets in groups.items()}
        if all(len(v)==1 for v in values.values()):
            mapped={mode:next(iter(v)) for mode,v in values.items()}
            if len(set(mapped.values()))==len(groups):
                result.append({'offset':offset,'offset_hex':hex(offset),'wire_values':mapped})
    return {'samples':len(samples),'modes':list(groups),'candidate_fields':result,
            'confidence':'Within supplied labeled samples only; not proof of plaintext or cross-session compatibility.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('samples',type=pathlib.Path);a=p.parse_args()
    print(json.dumps(candidates(json.loads(a.samples.read_text())),indent=2))
