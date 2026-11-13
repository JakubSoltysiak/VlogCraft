"""Verify approved artwork, all ICO frames and frozen PE resources without visual guesses."""
import hashlib,io,json
from pathlib import Path
from PIL import Image,ImageChops
ROOT=Path(__file__).resolve().parents[1]
BRAND=ROOT/'web/branding'

def ico_payloads(path):
    import struct
    data=path.read_bytes();reserved,kind,count=struct.unpack_from('<HHH',data)
    assert (reserved,kind,count)==(0,1,7)
    result={}
    for i in range(count):
        w,h,colors,zero,planes,bits,size,offset=struct.unpack_from('<BBBBHHII',data,6+i*16)
        result[(w or 256,h or 256)]=data[offset:offset+size]
    return result

def verify_assets():
    original=ROOT/'assets/branding/vlogcraft-original.png'
    manifest=json.loads((BRAND/'manifest.json').read_text('utf8'))
    assert hashlib.sha256(original.read_bytes()).hexdigest()==manifest['source_sha256']
    payloads=ico_payloads(BRAND/'vlogcraft-approved.ico')
    assert sorted(n for n,h in payloads)==[16,24,32,48,64,128,256]
    for (n,h),data in payloads.items():
        actual=Image.open(io.BytesIO(data)).convert('RGBA')
        expected=Image.open(BRAND/f'vlogcraft-{n}.png').convert('RGBA')
        assert actual.size==(n,n) and actual.tobytes()==expected.tobytes()
        assert actual.getchannel('A').getextrema()[0]==0 and actual.getchannel('A').getextrema()[1]>128
    return True

def verify_executable(path):
    import pefile
    expected=list(ico_payloads(BRAND/'vlogcraft-approved.ico').values())
    with pefile.PE(str(path)) as pe:
        groups=[];icons=[]
        for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if kind.id not in (3,14):continue
            for entry in kind.directory.entries:
                for language in entry.directory.entries:
                    r=language.data.struct
                    (icons if kind.id==3 else groups).append(pe.get_data(r.OffsetToData,r.Size))
        assert len(groups)==1 and len(icons)==7,(len(groups),len(icons))
        assert sorted(hashlib.sha256(x).digest() for x in icons)==sorted(hashlib.sha256(x).digest() for x in expected)
    return True
if __name__=='__main__':
    import sys
    verify_assets()
    if len(sys.argv)>1:verify_executable(Path(sys.argv[1]))
    print(json.dumps({'approved_source_and_seven_icon_frames':True,'exe_resources':len(sys.argv)>1}))
