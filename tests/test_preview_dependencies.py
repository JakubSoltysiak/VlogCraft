from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from preview_dependencies import project
import server

class PreviewDependenciesTests(unittest.TestCase):
    def scene(self,root):
        source=root/'original.mp4';source.write_bytes(b'original')
        a={'id':'a'*32,'kind':'video','name':source.name,'path':str(source),'size':8,'duration':24,
           'width':1280,'height':720,'hasAudio':True,'fps':24}
        state=server.default_state();state['assets']=[a];state['output'].update(width=1280,height=720,fps=24)
        c=server.default_clip(a);state['tracks'][1]['clips']=[c]
        title=server.default_title(16);title.update(text='Far caption',end=2)
        state['tracks'][0]['clips']=[title]
        return state,a,c,title

    def test_unrelated_caption_name_assets_and_export_encoder_do_not_invalidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);s,a,c,title=self.scene(root)
            key,snapshot=project(s,0,192,960)
            title['text']='Changed far caption';s['name']='Renamed';s['output']['encoder']='h264_amf'
            s['assets'].append(dict(a,id='b'*32,path=str(root/'missing-unrelated.mp4')))
            self.assertEqual(project(s,0,192,960)[0],key)
            self.assertEqual(len(snapshot['assets']),1)
            self.assertFalse(snapshot['tracks'][0]['clips'])
            self.assertNotEqual(project(s,384,576,960)[0],project({**s,'tracks':[dict(t,clips=[] if i==0 else t['clips']) for i,t in enumerate(s['tracks'])]},384,576,960)[0])

    def test_related_effect_source_proxy_solo_rate_and_nested_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);s,a,c,_=self.scene(root)
            key,_=project(s,0,192,960)
            for change in ('effect','solo','rate','source','proxy','nested'):
                key,_=project(s,0,192,960)
                newer=deepcopy(s)
                proxies=None
                if change=='effect':newer['tracks'][1]['clips'][0]['opacity']=.5
                if change=='solo':newer['tracks'][2]['solo']=True
                if change=='rate':newer['output']['fps']='24000/1001'
                if change=='source':Path(a['path']).write_bytes(b'new original')
                if change=='proxy':
                    proxy=root/'proxy.mp4';proxy.write_bytes(b'proxy');proxies={a['id']:str(proxy)}
                if change=='nested':
                    child=deepcopy(newer['tracks'][1])
                    newer['tracks'][1]['clips']=[dict(id='n'*32,kind='sequence',start=0,end=24,position=0,speed=1,children=[child])]
                self.assertNotEqual(project(newer,0,192,960,proxies)[0],key,change)
            proxy=root/'proxy.mp4';proxy.write_bytes(b'proxy')
            stamp=proxy.stat().st_mtime_ns+2_000_000_000
            os.utime(a['path'],ns=(stamp,stamp))
            _,snapshot=project(s,0,192,960,{a['id']:str(proxy)})
            self.assertEqual(snapshot['assets'][0]['path'],a['path'],'Stale proxy falls back to the original')
            Path(a['path']).unlink()
            _,snapshot=project(s,0,192,960,{a['id']:str(proxy)})
            self.assertEqual(snapshot['assets'][0]['path'],str(proxy),'Existing proxy editing survives offline originals')
