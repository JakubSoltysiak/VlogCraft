from copy import deepcopy
from fractions import Fraction
import array,os,subprocess,tempfile,unittest
from pathlib import Path
import server,native_plan,native_playback,timing
from unittest import mock

class NativeTransport(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def state(self):
  a={'id':'a'*32,'path':str(self.root/'source.mp4'),'kind':'video','duration':1,'width':1280,'height':720,
     'hasAudio':False,'audioChannels':2,'timeBase':'1/90000','colorTransfer':'bt709','colorPrimaries':'bt709'}
  s=server.default_state();s['assets']=[a];s['output']['fps']='60000/1001';c=server.default_clip(a);c['end']=.8
  s['tracks'][1]['clips']=[c];return s
 def test_rational_source_ticks_keys_and_nested_projection(self):
  s=self.state();c=s['tracks'][1]['clips'][0];c['start']=.1001;c['keys']={'x':[{'time':.1,'value':-.2,'mode':'linear'},{'time':.5,'value':.2,'mode':'ease-in'}]}
  nested=server.default_title(1);nested.update(kind='sequence',children=s['tracks'],assetId=None)
  outer=deepcopy(s);outer['tracks']=[{**s['tracks'][0],'clips':[nested]}]
  result=native_plan.compile_plan(outer)
  self.assertIn('RATE 60000 1001',result['text']);self.assertIn('9009 1 90000',result['text']);self.assertIn('KEY ',result['text'])
  self.assertFalse(result['hdr'])
 def test_no_silent_effect_or_color_or_layout_loss(self):
  for change in ({'mask':'ellipse'},{'grade':'warm'},{'lutId':'look'},{'keys':{'contrast':[{'time':0,'value':1,'mode':'linear'}]}}):
   s=self.state();s['tracks'][1]['clips'][0].update(change)
   with self.assertRaises(native_plan.Unsupported):native_plan.compile_plan(s)
  s=self.state();s['assets'][0]['colorTransfer']='arib-std-b67'
  with self.assertRaises(native_plan.Unsupported):native_plan.compile_plan(s)
  s=self.state();s['assets'][0].update(hasAudio=True,audioChannels=6)
  with self.assertRaises(native_plan.Unsupported):native_plan.compile_plan(s)
 def test_layer_and_shared_source_limits_are_explicit(self):
  s=self.state();c=s['tracks'][1]['clips'][0];other=deepcopy(c);other['id']='b'*32;s['tracks'][0]['clips']=[other]
  with self.assertRaises(native_plan.Unsupported):native_plan.compile_plan(s)
 def test_hdr_precision_contract_does_not_claim_dynamic_mastering(self):
  s=self.state();s['assets'][0].update(hdr=True,colorTransfer='smpte2084',colorPrimaries='bt2020')
  result=native_plan.compile_plan(s)
  self.assertTrue(result['hdr']);self.assertIn('COLOR PQ',result['text']);self.assertIn('not applied',result['colorPolicy'])
 def test_legacy_layout_is_refreshed_before_native_admission(self):
  s=self.state();s['assets'][0].update(hasAudio=True);s['assets'][0].pop('audioChannels')
  c=native_playback.Controller(None,self.root,self.root)
  with mock.patch.object(server,'probe',return_value={'rotation':0,'colorTransfer':'bt709','audioChannels':6}):
   with self.assertRaises(native_plan.Unsupported):c.start(s,{'width':960})
  c.close()
 def audio_state(self):
  source=self.root/'tone.wav'
  subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=f=440:r=48000:d=1','-c:a','pcm_s16le',str(source)],check=True,capture_output=True)
  s=self.state();s['assets'][0].update(path=str(source),hasAudio=True,kind='audio',audioChannels=1)
  # A silent detached video determines sequence duration; only the delayed audio is audible.
  s['tracks'][1]['clips'][0]['audioDetached']=True
  a=server.default_clip(s['assets'][0],float(Fraction(6,1)/timing.rate(s['output']['fps'])),'audio');a.update(end=.5,volume=.5)
  s['tracks'][2]['clips']=[a];return s
 def test_pcm_sample_budget_delay_and_seek(self):
  s=self.audio_state();c=native_playback.Controller(None,self.root,self.root);c.snapshot=s;c.generation=1
  try:
   samples,end,chunks=c.audio(1,0);data=b''.join(chunks)
   self.assertEqual(len(data),samples*4);self.assertEqual(samples,timing.sample_at(end,timing.rate(s['output']['fps'])))
   pcm=array.array('h');pcm.frombytes(data)
   self.assertTrue(all(v==0 for v in pcm[:6000]));self.assertGreater(max(abs(x) for x in pcm[16000:20000]),100)
   samples,end,chunks=c.audio(1,12);seek=b''.join(chunks)
   self.assertEqual(len(seek),samples*4);self.assertGreater(max(abs(x) for x in array.array('h',seek)[:4000]),100)
  finally:c.close()
 def test_original_audio_start_offset_is_preserved(self):
  source=self.root/'offset.mkv'
  subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=160x90:r=24:d=1',
   '-f','lavfi','-i','sine=f=440:r=48000:d=0.5','-af','asetpts=PTS+0.125/TB','-c:v','ffv1','-c:a','pcm_s16le',str(source)],capture_output=True,check=True)
  a=dict(id='a'*32,kind='video',path=str(source),**server.probe(source));s=server.default_state();s['assets']=[a];s['output'].update(width=160,height=90,fps=24,preset='ultrafast')
  s['tracks'][1]['clips']=[server.default_clip(a)]
  target=self.root/'offset.mov';import render_engine
  work=self.root/'offset-export';work.mkdir();render_engine.render_range(s,0,1,target,work)
  raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(target),'-vn','-ac','2','-ar','48000','-f','s16le','-'])
  pcm=array.array('h',raw)
  self.assertLess(max(abs(v) for v in pcm[:10000]),8)
  self.assertGreater(max(abs(v) for v in pcm[12500:18000]),500)
 def test_obsolete_seek_cannot_move_a_new_generation(self):
  c=native_playback.Controller(None,self.root,self.root);c.snapshot=self.state();c.generation=3
  try:
   self.assertEqual(c.seek(12,2),{'stale':True,'generation':3})
   self.assertEqual(c.generation,3)
   self.assertEqual(c.seek(12,3),{'generation':4})
  finally:c.close()
 def test_obsolete_pcm_cancels_and_reaps(self):
  s=self.audio_state();c=native_playback.Controller(None,self.root,self.root);c.snapshot=s;c.generation=1
  samples,end,chunks=c.audio(1,0);next(chunks);old=list(c.audio_processes)
  c.seek(4)
  with self.assertRaises(ValueError):next(chunks)
  c.close();self.assertTrue(all(p.poll() is not None for p in old));self.assertFalse(c.audio_processes)
