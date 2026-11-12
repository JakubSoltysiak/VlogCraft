"""Runs without paid services, GUI libraries, or an internet connection."""
import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import render_engine as engine

class StudioTests(unittest.TestCase):
    def setUp(self):
        self._tmp=tempfile.TemporaryDirectory();self.root=Path(self._tmp.name)
        self.orig=(server.MEDIA,server.THUMBS,server.WORK,server.PROJECT,server.STATE)
        server.WORK=self.root;server.MEDIA=self.root/'media';server.THUMBS=self.root/'thumbs'
        server.PROJECT=self.root/'project.json';server.STATE=server.default_state()
        server.MEDIA.mkdir();server.THUMBS.mkdir()
    def tearDown(self):
        server.MEDIA,server.THUMBS,server.WORK,server.PROJECT,server.STATE=self.orig
        self._tmp.cleanup()
    def media(self):
        fn=self.root/'my_video.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i','testsrc2=s=320x180:r=24:d=1.2',
                        '-f','lavfi','-i','sine=frequency=450:sample_rate=48000:duration=1.2',
                        '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',
                        '-shortest',str(fn)],check=True,capture_output=True)
        return fn
    def start(self):
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        return self.http.server_address[1]
    def req(self,port,method,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=80)
        if isinstance(body,dict):body=json.dumps(body).encode();headers={'Content-Type':'application/json',**(headers or {})}
        c.request(method,path,body=body,headers=headers or {})
        r=c.getresponse();raw=r.read();c.close()
        return r.status,json.loads(raw.decode())
    def test_multitrack_video_audio_and_text_export(self):
        source=self.media();a=server.add_asset(source,auto_add=False)
        state=server.default_state();state['assets']=[a]
        state['output']={'width':320,'height':180,'fps':24,'crf':27,'preset':'ultrafast'}
        main=next(t for t in state['tracks'] if t['name'].startswith('V1'))
        overlay=next(t for t in state['tracks'] if t['name'].startswith('V2'))
        a2=next(t for t in state['tracks'] if t['name'].startswith('A2'))
        c=server.default_clip(a);c['end']=1.;main['clips']=[c]
        title=server.default_title(.12);title['end']=.4;title['text']='KENYA';overlay['clips']=[title]
        audio=server.default_clip(a,.0,'audio');audio['end']=1.;audio['volume']=.2;a2['clips']=[audio]
        out=self.root/'edited.mp4'
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            engine.render(state,out,tmp)
        info=server.probe(out)
        self.assertEqual(info['width'],320);self.assertTrue(info['hasAudio'])
        self.assertGreater(out.stat().st_size,10000)
    def test_clip_types_tracks_validate_and_preserve_existing_assets(self):
        source=self.media();a=server.add_asset(source,auto_add=False)
        state=server.default_state();server.STATE['assets']=[a];state['assets']=[a]
        t=next(t for t in state['tracks'] if t['name'].startswith('V1'))
        t['clips'].append(server.default_clip(a))
        checked=server.validate_state(state)
        self.assertEqual(checked['tracks'][1]['clips'][0]['assetId'],a['id'])
        for c in checked['tracks'][1]['clips']:self.assertLessEqual(c['end'],a['duration']+.12)
    def test_chunked_import_to_timeline_and_export_via_http(self):
        media=self.media();port=self.start()
        try:
            raw=media.read_bytes()
            status,started=self.req(port,'POST','/api/upload/start',{'name':media.name,'size':len(raw)})
            self.assertEqual(status,200)
            id=started['id'];offset=0
            while offset<len(raw):
                data=raw[offset:offset+8192]
                status,r=self.req(port,'PUT',f'/api/upload/chunk?id={id}&offset={offset}',data)
                self.assertEqual(status,200);offset=r['offset']
            status,done=self.req(port,'POST','/api/upload/finish',{'id':id})
            self.assertEqual(status,200);asset=done['asset']
            self.assertTrue(Path(asset['path']).is_file())
            status,state=self.req(port,'GET','/api/state')
            self.assertEqual(status,200);self.assertEqual(len(state['assets']),1)
            t=next(t for t in state['tracks'] if t['name'].startswith('V1'))
            c=server.default_clip(asset);c['end']=.4;t['clips']=[c]
            state['output']={'width':1280,'height':720,'fps':24,'crf':27,'preset':'ultrafast'}
            status,checked=self.req(port,'POST','/api/state',state)
            self.assertEqual(status,200)
            self.assertEqual(checked['tracks'][1]['clips'][0]['id'],c['id'])
            # HTTP 206 media streaming, without loading the whole file.
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
            conn.request('GET',f'/media/{asset["id"]}',headers={'Range':'bytes=0-7'})
            response=conn.getresponse();sample=response.read();conn.close()
            self.assertEqual(response.status,206);self.assertEqual(len(sample),8)
            target=self.root/'finished.mp4'
            status,r=self.req(port,'POST','/api/export',{'path':str(target)})
            self.assertEqual(status,200)
            import time
            for _ in range(80):
                status,jobs=self.req(port,'GET','/api/jobs')
                if jobs['export']['status'] in ('done','error','cancelled'):break
                time.sleep(.15)
            self.assertEqual(jobs['export']['status'],'done',jobs['export'])
            self.assertTrue(target.exists())
            self.assertEqual(server.probe(target)['width'],1280)
        finally:self.http.shutdown();self.http.server_close()

    def test_large_file_http_range_beyond_four_gib(self):
        video=self.root/'huge_fake.mp4';size=4*1024**3+615000000
        with video.open('wb') as file:
            file.truncate(size)
            file.seek(size-4);file.write(b'END!')
        aid='a'*32
        server.STATE['assets'].append({'id':aid,'name':video.name,'path':str(video),'kind':'video',
                                        'size':size,'duration':5,'hasAudio':False,'width':1920,'height':1080})
        port=self.start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=15)
            conn.request('GET',f'/media/{aid}',headers={'Range':f'bytes={size-4}-{size-1}'})
            response=conn.getresponse();body=response.read();conn.close()
            self.assertEqual(response.status,206)
            self.assertEqual(body,b'END!')
            self.assertEqual(response.getheader('Content-Range'),f'bytes {size-4}-{size-1}/{size}')
        finally:self.http.shutdown();self.http.server_close()

    def test_64bit_upload_offsets_and_http_ranges(self):
        port=self.start()
        try:
            big_size=4*1024**3+600000000
            status,r=self.req(port,'POST','/api/upload/start',{'name':'VeryLongKenyaClip.mp4','size':big_size})
            self.assertEqual(status,200);id=r['id']
            # Simulates a mostly transferred 4.5+ GB file using a sparse file,
            # without consuming 4.5GB of CI disk. It is NOT a full 4.5GB transfer test.
            with server.UPLOAD_LOCK:
                u=server.UPLOADS[id];u['offset']=big_size-64
                with Path(u['tmp']).open('r+b') as f:f.truncate(big_size-64)
            c=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
            c.request('PUT',f'/api/upload/chunk?id={id}&offset={big_size-64}',body=b'X'*64)
            resp=c.getresponse();payload=json.loads(resp.read());c.close()
            self.assertEqual(resp.status,200);self.assertEqual(payload['offset'],big_size)
            self.assertEqual(Path(u['tmp']).stat().st_size,big_size)
            status,r=self.req(port,'POST','/api/upload/cancel',{'id':id})
            self.assertTrue(r['cancelled']);self.assertFalse(Path(u['tmp']).exists())
        finally:self.http.shutdown();self.http.server_close()

if __name__=='__main__':unittest.main(verbosity=2)
