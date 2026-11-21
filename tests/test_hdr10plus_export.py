import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import hdr10plus_export
from hdr10plus_bitstream import conformance_issues, parse_payload
from hdr10plus_index import SIDE_DATA


def command(*args):
    return subprocess.run(args,check=True,capture_output=True,timeout=45).stdout


def generated_payload(luma, reserved=0):
    """Known ST 2094-40 version-1 test fields with a distinct value per picture."""
    fields = [(1,8),(1,2),(400,27),(0,1)]
    fields += [(luma,17)] * 4 + [(9,4)]
    for position in (1,5,10,25,50,75,90,95,99):
        quantized = reserved if position==5 else 255 if position==10 else luma
        fields.extend([(position,7),(quantized,17)])
    fields.extend([(0,10),(0,1),(0,1),(0,1)])
    bits = ''.join(f'{number:0{width}b}' for number,width in fields)
    bits = bits.ljust((len(bits)+7)//8*8,'0')
    return bytes.fromhex('b5003c000104')+int(bits,2).to_bytes(len(bits)//8,'big')


def fixture(root, reserved=0, fps='24', frames=12):
    raw = root/'bare.hevc'
    tagged = root/'tagged.hevc'
    source = root/'source.mp4'
    command('ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i',f'testsrc2=s=128x72:r={fps}',
            '-vf','setsar=1,setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc',
            '-frames:v',str(frames),'-c:v','libx265','-pix_fmt','yuv420p10le','-profile:v','main10',
            '-preset','ultrafast','-x265-params','pools=2:frame-threads=1:bframes=0:aud=1:hdr10=1:repeat-headers=1:max-cll=400,100',
            '-f','hevc',str(raw))
    units = re.split(rb'\x00\x00\x00?\x01',raw.read_bytes())[1:]
    sequence = []
    count = 0
    for nal in units:
        if (nal[0]>>1)&63<32:
            payload = generated_payload(1000+count*100,reserved)
            sei = bytes([4,len(payload)])+payload+b'\x80'
            sei = re.sub(rb'\x00\x00(?=[\x00-\x03])',b'\x00\x00\x03',sei)
            sequence.append(b'\x4e\x01'+sei)
            count += 1
        sequence.append(nal)
    assert count==frames
    tagged.write_bytes(b''.join(b'\x00\x00\x00\x01'+n for n in sequence))
    command('ffmpeg','-nostdin','-v','error','-y','-r',fps,'-i',str(tagged),'-f','lavfi','-i',
            'sine=frequency=440:sample_rate=48000:duration=0.5','-map','0:v','-map','1:a',
            '-c:v','copy','-tag:v','hvc1','-c:a','aac','-video_track_timescale','120000',str(source))
    return source


def state_for(source, fps=24, duration=.5):
    return {'output':{'width':128,'height':72,'fps':fps},
            'assets':[{'id':'source','path':str(source)}],
            'tracks':[{'type':'video','clips':[{'id':'clip','kind':'video','assetId':'source','end':duration}]}]}


def decoded(path):
    result = command('ffmpeg','-v','error','-i',str(path),'-map','0:v','-map','0:a',
                     '-pix_fmt','yuv420p10le','-f','framemd5','-')
    return [line for line in result.splitlines() if not line.startswith(b'#')]


class HDR10PlusPreservationTests(unittest.TestCase):
    def test_encoded_metadata_and_every_decoded_frame_and_audio_sample_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = fixture(root)
            output = root/'delivery.mp4'
            frames = hdr10plus_export.render(state_for(original),output,lambda args,_:command(*args),
                                             lambda *_:None,lambda:False)
            self.assertEqual(frames,12)
            self.assertEqual(decoded(original),decoded(output))
            info = json.loads(command('ffprobe','-v','error','-select_streams','v:0','-show_frames',
                                      '-show_streams','-of','json',str(output)))
            stream = info['streams'][0]
            self.assertEqual((stream['codec_name'],stream['profile'],stream['pix_fmt'],stream['color_transfer'],
                              stream['color_primaries'],stream['color_range'],stream['duration']),
                             ('hevc','Main 10','yuv420p10le','smpte2084','bt2020','tv','0.500000'))
            observed = [next(d for d in frame['side_data_list'] if d['side_data_type']==SIDE_DATA)
                        for frame in info['frames']]
            self.assertEqual(len(observed),12)
            self.assertEqual([d['average_maxrgb'] for d in observed],
                             [f'{1000+n*100}/100000' for n in range(12)])

    def test_reserved_nonzero_field_and_transform_are_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = fixture(root, reserved=42)
            output = root/'blocked.mp4'
            state = state_for(original)
            render = lambda: hdr10plus_export.render(state,output,lambda args,_:command(*args),
                                                      lambda *_:None,lambda:False)
            with self.assertRaisesRegex(ValueError,'reserved_5_percent'):
                render()
            self.assertFalse(output.exists())
            state['tracks'][0]['clips'][0]['scale'] = 1.1
            with self.assertRaisesRegex(ValueError,'effects'):
                render()
            self.assertFalse(output.exists())

    def test_bad_payload_tail_and_reserved_field_classification(self):
        good = generated_payload(10000)
        self.assertEqual(conformance_issues(parse_payload(good)),[])
        self.assertEqual(conformance_issues(parse_payload(generated_payload(10000,50))),['reserved_5_percent'])
        with self.assertRaises(ValueError):
            parse_payload(good+b'\x00')
