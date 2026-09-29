#!/usr/bin/env python3
"""Local administrative client; token never appears in command arguments."""
import argparse,json,pathlib,urllib.request
p=argparse.ArgumentParser();p.add_argument('action',choices=['status','on','off']);a=p.parse_args()
url='http://127.0.0.1:18087/'
if a.action=='status':req=urllib.request.Request(url+'status')
else:
 token=pathlib.Path('/data/local-zappi/admin-token').read_text().strip()
 req=urllib.request.Request(url+'config',data=json.dumps({'forward_upstream':a.action=='on'}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
with urllib.request.urlopen(req,timeout=5) as r:print(json.dumps(json.load(r),indent=2))
