"""Regression coverage for still decoding, measured progress and safe publication."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import render_engine
import server


def ffmpeg(*args):
    return subprocess.run(['ffmpeg','-nostdin','-v','error','-y',*map(str,args)],
                          check=True,capture_output=True,timeout=90).stdout


def fixture(root, width=320, height=180, still_seconds=.2):
    plain = root/'ordinary.png'
    alpha = root/'alpha %03d.png'
    jpeg = root/'portrait.jpg'
    camera = root/'video.mp4'
    Image.new('RGB',(160,90),(20,100,180)).save(plain)
    exif = Image.Exif()
    exif[274] = 1
    Image.new('RGBA',(160,90),(240,30,20,128)).save(alpha,exif=exif)
    exif[274] = 6
    picture = Image.new('RGB',(90,160),(220,40,20))
    picture.paste((20,180,40),(0,0,90,80))
    picture.save(jpeg,exif=exif)
    ffmpeg('-f','lavfi','-i','testsrc2=s=320x180:r=60:d=0.2',
           '-f','lavfi','-i','sine=frequency=450:sample_rate=48000:duration=0.2',
           '-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',camera)
    paths = [plain,alpha,jpeg,camera]
    state = server.default_state()
    state['output'].update(width=width,height=height,fps=60,encoder='libx264',preset='ultrafast')
    for index,path in enumerate(paths):
        asset = {'id':str(index),'kind':server.classify(path),'name':path.name,'path':str(path),**server.probe(path)}
        state['assets'].append(asset)
    plain_asset,alpha_asset,jpeg_asset,video_asset = state['assets']
    lower = server.make_track('video',1)
    upper = server.make_track('video',2)
    for asset,position,length in ((plain_asset,0,still_seconds),(jpeg_asset,still_seconds,.2),
                                  (video_asset,still_seconds+.2,.2)):
        clip = server.default_clip(asset,position)
        clip['end'] = length
        lower['clips'].append(clip)
    clip = server.default_clip(alpha_asset,0)
    clip['end'] = still_seconds
    upper['clips'].append(clip)
    state['tracks'] = [upper,lower]
    return state, paths


def decode(path):
    result = subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams',
                                      '-of','json',str(path)],timeout=90)
    streams = json.loads(result)['streams']
    return (next(s for s in streams if s['codec_type']=='video'),
            next(s for s in streams if s['codec_type']=='audio'))


class ExportWorkflowTests(unittest.TestCase):
    def test_mixed_stills_metadata_alpha_orientation_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state, paths = fixture(root)
            hashes = [hashlib.sha256(p.read_bytes()).digest() for p in paths]
            target = root/'mixed.mp4'
            render_engine.render(state,target,root/'scratch',popen=lambda cmd,cwd: subprocess.run(
                cmd,cwd=cwd,check=True,capture_output=True,timeout=20))
            video,audio = decode(target)
            self.assertEqual((video['width'],video['height'],video['avg_frame_rate']),(320,180,'60/1'))
            self.assertEqual(int(video['nb_read_frames']),36)
            self.assertAlmostEqual(float(audio['duration']),.6,places=3)
            samples = ffmpeg('-i',target,'-ss','0.4','-t','0.2','-map','0:a','-f','s16le','pipe:1')
            self.assertTrue(any(samples))
            pixels = ffmpeg('-i',target,'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','pipe:1')
            self.assertTrue(all(abs(actual-expected)<14 for actual,expected in zip(pixels,(130,65,100))),list(pixels))
            left,right = [ffmpeg('-ss','0.2','-i',target,'-frames:v','1','-vf',f'crop=24:24:{x}:78,scale=1:1',
                                 '-pix_fmt','rgb24','-f','rawvideo','pipe:1') for x in (60,236)]
            self.assertGreater(left[0],left[1]+60,list(left))
            self.assertGreater(right[1],right[0]+60,list(right))
            self.assertEqual([hashlib.sha256(p.read_bytes()).digest() for p in paths],hashes)

    def test_destination_and_atomic_overwrite_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dest = root/'Łódź.mp4'
            part = root/'delivery.partial.mp4'
            source = root/'source.mp4'
            source.write_bytes(b'original')
            assets = [{'path':str(source)}]
            self.assertEqual(server.export_destination(str(dest.with_suffix('')),assets),dest)
            with self.assertRaisesRegex(ValueError,'original'):
                server.export_destination(str(source),assets)
            alias = root/'alias.mp4'
            os.link(source,alias)
            with self.assertRaisesRegex(ValueError,'original'):
                server.export_destination(str(alias),assets)
            for name in ('bad.mov','CON.mp4','*.mp4'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    server.export_destination(str(root/name),assets)
            dest.write_bytes(b'keep')
            part.write_bytes(b'new')
            with self.assertRaises(FileExistsError):
                server.publish_export(part,dest,assets,False)
            self.assertEqual(dest.read_bytes(),b'keep')
            server.publish_export(part,dest,assets,True)
            self.assertEqual(dest.read_bytes(),b'new')
            self.assertEqual(source.read_bytes(),b'original')

    def test_stage_progress_uses_frame_budget_and_retains_last_useful_activity(self):
        job = dict(stage='video',stageFraction=0,percent=25,duration=20,
                   _start=5,_end=10,_first=300,_frames=300,_activity=0)
        with patch.dict(server.JOBS,export=job):
            server.update_export_progress({b'frame':b'120',b'fps':b'39.2',b'out_time_us':b'1900000'})
            self.assertEqual((job['frames'],job['encodedSeconds'],job['fps']),(420,7,39.2))
            self.assertGreater(job['percent'],25)
            activity = job['_activity']
            server.update_export_progress({b'frame':b'120',b'fps':b'30'})
            self.assertEqual(job['_activity'],activity)
            job.update(stage='audio',stageFraction=0)
            server.update_export_progress({b'out_time_us':b'5000000'})
            self.assertEqual(job['frames'],420)
            self.assertEqual(job['stageFraction'],1)
