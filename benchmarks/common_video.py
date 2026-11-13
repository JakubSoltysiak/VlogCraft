"""Common static three-layer workload, separate from the full editor benchmark."""
from pathlib import Path
def graph(layers,width,height):
    filters=[]
    for n in range(layers):
        w=width if n==0 else width//2;h=height if n==0 else height//2
        f=f'[{n}:v]scale={w}:{h}:flags=bilinear,format=rgba'
        if n:f+=',colorchannelmixer=aa=.75'
        filters.append(f+'[v'+str(n)+']')
    last='v0'
    for n in range(1,layers):
        x=round(width*(.05 if n==1 else .45));y=height//4
        filters.append(f'[{last}][v{n}]overlay=x={x}:y={y}:format=rgb:shortest=1[o{n}]');last='o'+str(n)
    filters.append(f'[{last}]null[result]')
    return ';'.join(filters)

def command(paths,width,height,frames,target=None):
    cmd=['ffmpeg','-nostdin','-v','info','-nostats','-benchmark','-filter_complex_threads','1']
    for p in paths:cmd+=['-threads','1','-an','-i',str(p)]
    filters=graph(len(paths),width,height)
    if target is None:
        filters=filters.replace('null[result]',f'trim=end_frame={frames},showinfo=checksum=0[result]')
        output=['-c:v','wrapped_avframe','-f','null','-']
    else:output=['-c:v','rawvideo','-pix_fmt','rgba','-f','rawvideo',str(target)]
    return cmd+['-y','-filter_complex',filters,'-map','[result]','-an','-frames:v',str(frames),*output]
