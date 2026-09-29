import json, os, pathlib, socket, subprocess, sys, tempfile, time, unittest, urllib.request, urllib.error

class ProcessTest(unittest.TestCase):
    def test_startup_api_auth_persistence_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            with socket.socket() as s:
                s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            cfg=dict(bind='127.0.0.1',allowed_clients=['127.0.0.1'],admin_port=port,
                     routes=[dict(name='test',listen_port=0,upstream_ip='127.0.0.1')])
            (root/'config.json').write_text(json.dumps(cfg));(root/'admin-token').write_text('x'*40)
            env=dict(os.environ,LOCAL_ZAPPI_DATA=directory,LOCAL_ZAPPI_CONFIG=str(root/'config.json'))
            p=subprocess.Popen([sys.executable,'server.py'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            url=f'http://127.0.0.1:{port}'
            try:
                for _ in range(100):
                    if p.poll() is not None:self.fail(p.stderr.read().decode())
                    try:
                        with urllib.request.urlopen(url+'/health',timeout=.2):break
                    except OSError:time.sleep(.05)
                else:self.fail('server did not start')
                def post(value,auth=None):
                    headers={'Content-Type':'application/json'}
                    if auth:headers['Authorization']='Bearer '+auth
                    req=urllib.request.Request(url+'/config',data=json.dumps({'forward_upstream':value}).encode(),headers=headers)
                    with urllib.request.urlopen(req,timeout=2) as r:return json.load(r)
                with self.assertRaises(urllib.error.HTTPError) as e:post(False)
                self.assertEqual(e.exception.code,401)
                with self.assertRaises(urllib.error.HTTPError) as e:post('false','x'*40)
                self.assertEqual(e.exception.code,400)
                self.assertFalse(post(False,'x'*40)['forward_upstream'])
                self.assertFalse(json.loads((root/'forwarding.json').read_text())['forward_upstream'])
                self.assertTrue(post(True,'x'*40)['forward_upstream'])
                p.terminate();p.wait(timeout=3);self.assertEqual(p.returncode,0)
            finally:
                if p.poll() is None:p.kill();p.wait()
                p.stdout.close();p.stderr.close()
