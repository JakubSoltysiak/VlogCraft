from fractions import Fraction
from collections import defaultdict
import tempfile
from pathlib import Path
import unittest
from xml.etree import ElementTree

import numpy as np

import color_management
from hdr10plus_index import SIDE_DATA
import hdr10plus_master
import render_engine
import server
from test_hdr10plus_authoring import linear_units
from test_hdr10plus_export import command, decoded
from test_hdr_color import probe, project, source


def verify_master(test, static, master, fps, count, width=128, height=72):
    test.assertEqual(decoded(static), decoded(master))
    info = probe(master)
    video, audio = info['streams']
    test.assertEqual(
        tuple(video[key] for key in ('profile','codec_tag_string','pix_fmt','color_transfer',
                                    'color_primaries','color_space','color_range')),
        ('Main 10','hvc1','yuv420p10le','smpte2084','bt2020','bt2020nc','tv'))
    test.assertLessEqual(abs(Fraction(audio['duration_ts']) * Fraction(audio['time_base']) -
                             count/fps), Fraction(1,48000))
    frames = [frame for frame in info['frames'] if frame['media_type'] == 'video']
    test.assertEqual(len(frames), count)
    xml = ElementTree.fromstring(command('ffprobe','-v','error','-select_streams','v:0',
                                         '-show_frames','-of','xml',str(master)))
    side_data = xml.findall('./frames/frame')
    test.assertEqual(len(side_data), count)
    master_display = next(data for data in frames[0]['side_data_list']
                          if data['side_data_type'] == 'Mastering display metadata')
    test.assertEqual(Fraction(master_display['max_luminance']), 1000)
    test.assertEqual(Fraction(master_display['min_luminance']), Fraction('0.005'))
    # Independent delivery oracle decodes YCbCr directly. These fixtures
    # deliberately have neutral chroma, so no RGB reconstruction filter is needed.
    raw = command('ffmpeg','-v','error','-i',str(master),'-map','0:v','-pix_fmt',
                  'yuv420p10le','-fps_mode','passthrough','-f','rawvideo','-')
    size = width*height
    samples = np.frombuffer(raw, dtype='<u2').reshape(count,size*3//2)
    test.assertTrue(np.all(samples[:,size:] == 512))
    levels = []
    for index,(frame,picture) in enumerate(zip(frames,samples)):
        test.assertEqual(Fraction(int(frame['pts']))*Fraction(video['time_base']), index/fps)
        test.assertEqual(Fraction(int(frame['duration']))*Fraction(video['time_base']), 1/fps)
        [tag] = [x for x in frame['side_data_list'] if x['side_data_type'] == SIDE_DATA]
        test.assertEqual((tag['application version'], tag['num_windows']), (1,1))
        test.assertEqual(Fraction(tag['targeted_system_display_maximum_luminance']), 0)
        lut = {int(code):linear_units(round(max(0,min(1,(int(code)-64)/876))*65535))
               for code in np.unique(picture[:size])}
        linear = sorted(lut[int(code)] for code in picture[:size])
        expected = round(sum(linear)*100000/size)
        actual = round(Fraction(tag['average_maxrgb'])*100000)
        test.assertLessEqual(abs(actual-expected), 2, (index, actual, expected))
        repeated = defaultdict(list)
        [dynamic] = side_data[index].findall(f"./side_data_list/side_data[@type='{SIDE_DATA}']")
        for item in dynamic.findall('side_datum'):
            repeated[item.attrib['key']].append(item.attrib['value'])
        test.assertEqual(len(repeated['maxscl']), 3)
        for component in repeated['maxscl']:
            test.assertLessEqual(abs(round(Fraction(component)*100000)-round(linear[-1]*100000)), 2)
        pairs = dict(zip(map(int,repeated['distribution_maxrgb_percentage']),
                         repeated['distribution_maxrgb_percentile']))
        test.assertEqual(list(pairs), [1,5,10,25,50,75,90,95,99])
        for percentile,value in pairs.items():
            rank = (size*(9998 if percentile == 99 else 100*percentile)+9999)//10000
            expect = 0 if percentile == 5 else 255 if percentile == 10 else round(linear[rank-1]*100000)
            test.assertLessEqual(abs(round(Fraction(value)*100000)-expect), 2)
        levels.append(actual)
    return levels


class HDR10PlusMasterTests(unittest.TestCase):
    def test_actual_edited_rational_main10_mixed_layers_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pq = source(root,'ramp',ramp=True)
            sdr = source(root,'white',sdr=True)
            timeline = project([sdr,pq])
            timeline['output']['fps'] = '30000/1001'
            overlay = timeline['tracks'][0]['clips'][0]
            overlay.update(start=.05,end=.45,speed=2,hdrExposure=1,fadeIn=.05,fadeOut=.05)
            base = timeline['tracks'][1]['clips'][0]
            base.update(start=.20,end=.4,hdrExposure=-1)
            timeline['tracks'][1]['clips'].append({**base,'id':'earlier-source-later','position':.2,
                                                   'start':0,'end':.30,'hdrExposure':0})
            audio = root/'tone.wav'
            command('ffmpeg','-v','error','-f','lavfi','-i','sine=f=400:r=48000:d=0.4',str(audio))
            sound = dict(id='tone',kind='audio',name='tone',path=str(audio),**server.probe(audio))
            timeline['assets'].append(sound)
            clip = server.default_clip(sound, position=.05)
            timeline['tracks'].append({'id':'sine','type':'audio','clips':[clip]})
            static, output = root/'static.mp4', root/'master.mp4'
            render_engine.render(timeline,static,root/'render')
            work=root/'author'
            work.mkdir()
            count=15
            fps=Fraction(30000,1001)
            actual = hdr10plus_master.author(static,output,work,fps,count,render_engine._run,
                                            lambda *_:None,lambda:False)
            self.assertEqual(actual, count)
            levels = verify_master(self,static,output,fps,count)
            self.assertGreater(max(levels)-min(levels),1000)

    def test_vfr_source_pts_trim_speed_and_hold_to_cfr(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root/'source.yuv'
            values = [round(64+876*float(color_management.nits_to_pq(n))) for n in (100,500,1000)]
            raw.write_bytes(b''.join(
                np.full((72,128),level,dtype='<u2').tobytes()+
                np.full((2,72,128),512,dtype='<u2').tobytes() for level in values))
            path = root/'source.mkv'
            command('ffmpeg','-v','error','-f','rawvideo','-pixel_format','yuv444p10le',
                    '-video_size','128x72','-framerate','10','-i',str(raw),
                    '-vf',r'setpts=if(eq(N\,0)\,0\,if(eq(N\,1)\,2\,5)),setsar=1,'
                          'setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc',
                    '-fps_mode','vfr','-c:v','libx265','-preset','ultrafast',
                    '-x265-params','lossless=1:pools=1:frame-threads=1',str(path))
            asset = dict(id='varying',kind='video',name='VFR',path=str(path),**server.probe(path))
            state = project([asset])
            state['output']['fps'] = 30
            state['tracks'][0]['clips'][0].update(start=.1,end=.6,speed=2)
            static, output = root/'static.mp4', root/'master.mp4'
            render_engine.render(state,static,root/'render')
            self.assertEqual(hdr10plus_master.author(static,output,root,30,8,render_engine._run,
                                                     lambda *_:None,lambda:False),8)
            levels=verify_master(self,static,output,Fraction(30),8)
            np.testing.assert_allclose(np.array(levels)/10,[100]*2+[500]*4+[1000]*2,atol=12)

    def test_cancelled_analysis_does_not_create_a_master(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            static = root/'static.mp4'
            render_engine.render(project([source(root,'constant')]), static, root/'render')
            output = root/'master.mp4'
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                hdr10plus_master.author(static,output,root,24,12,render_engine._run,
                                        lambda *_:None,lambda:True)
            self.assertFalse(output.exists())
