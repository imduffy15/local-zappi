#!/usr/bin/env python3
"""Local administrative client; token never appears in command arguments."""
import argparse,json,pathlib,urllib.request
p=argparse.ArgumentParser();p.add_argument('action',choices=['status','on','off','mode'])
p.add_argument('mode',nargs='?',choices=['fast','eco','eco_plus','stop']);a=p.parse_args()
if a.action=='mode' and a.mode is None:p.error('mode requires fast, eco, eco_plus or stop')
url='http://127.0.0.1:18087/'
if a.action=='status':req=urllib.request.Request(url+'status')
else:
 token=pathlib.Path('/data/local-zappi/admin-token').read_text().strip()
 endpoint='mode' if a.action=='mode' else 'config'
 body={'mode':a.mode} if a.action=='mode' else {'forward_upstream':a.action=='on'}
 req=urllib.request.Request(url+endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
with urllib.request.urlopen(req,timeout=5) as r:print(json.dumps(json.load(r),indent=2))
