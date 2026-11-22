"""Verify the native packed PQ surface before lossy HEVC encoding."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

import numpy as np

from phase2b_conversion import raw_converter
from render_phase2 import ROOT, Scenario, call, clips_for, write_plan
from render_phase2_export import video_command


def color_tiles(width, height):
    """Pairs of saturated edges, optical black, near-black and HDR neutrals."""
    swatches=np.array([
        (0,0,0),(.0001,.0001,.0001),(.01,.01,.01),(1,1,1),(10,10,10),(100,100,100),
        (4,0,0),(0,4,0),(0,0,4),(.001,.5,1),(5,1,.2),(.6,.04,3),
    ],dtype='<f4')
    yy,xx=np.indices((height,width))
    first=swatches[(xx//7+3*(yy//5))%len(swatches)]
    second=swatches[(xx%3+4*(yy%3))%len(swatches)]
    opaque=np.ones((height,width,1),dtype='<f4')
    return np.stack((np.concatenate((first,opaque),axis=2),np.concatenate((second,opaque),axis=2)))


def run(executable, backend):
    from color_management import pq_to_nits
    from test_hdr_color import CONTRACT

    scenario=Scenario('pq-reference',68,34)
    width,height=scenario.width,scenario.height
    count=2
    with tempfile.TemporaryDirectory(prefix='phase2b-color-') as name:
        folder=Path(name)
        sources=folder/'rgba.bin'
        swatches=color_tiles(width,height)
        swatches.tofile(sources)
        plan=folder/'plan.bin'
        write_plan(plan,scenario,clips_for(scenario,count),count,precise_edges=True,
                   source_slots=((0,1),))
        command=[executable,backend,plan,sources]
        gbr=folder/'linear.gbr'
        gbr.write_bytes(call([*command,'@gbr-stream','0','2','0']).stdout)
        rgb_definition=video_command(gbr,folder/'unused.mov',scenario,count,CONTRACT)
        reference=call(raw_converter(rgb_definition)).stdout
        candidate=call([*command,'@pq-stream','0','2','0']).stdout
    if len(reference)!=len(candidate) or len(candidate)!=count*width*height*3:
        raise AssertionError('Wrong packed 4:2:0 picture length')
    expected=np.frombuffer(reference,'<u2').reshape(count,-1).astype(np.int32)
    actual=np.frombuffer(candidate,'<u2').reshape(count,-1).astype(np.int32)
    samples=width*height
    offsets=(0,samples,samples*5//4,samples*3//2)
    stats={}
    for plane,start,end in zip('YUV',offsets,offsets[1:]):
        selected=actual[:,start:end]
        delta=selected-expected[:,start:end]
        low,maximum=(64,940) if plane=='Y' else (64,960)
        stats[plane]=dict(max_error=int(abs(delta).max()),rmse=float(np.sqrt(np.mean(delta**2))),
                          minimum=int(selected.min()),maximum=int(selected.max()))
        if selected.min()<low or selected.max()>maximum:
            raise AssertionError(f'{plane} exceeds 10-bit limited range')
        if stats[plane]['max_error']>2:
            raise AssertionError(f'{plane} differs by more than two quantized codes: {stats}')
    if actual[0,0]!=64 or not 64<actual[0,7]<120 or actual[0,39]!=940:
        raise AssertionError('Unexpected optical black, shadow or mastering peak')
    original=swatches.reshape(count,samples,4)
    neutral=(original[...,0]==original[...,1])&(original[...,1]==original[...,2])
    exact=original[...,0][neutral]*100
    reference_nits=pq_to_nits((expected[:,:samples][neutral]-64)/876)
    candidate_nits=pq_to_nits((actual[:,:samples][neutral]-64)/876)
    delta=candidate_nits-reference_nits
    stats["decoded_neutral"]={
        "max_linear_error_in_100_nit_units":float(abs(delta).max()/100),
        "linear_rmse_in_100_nit_units":float(np.sqrt(np.mean(delta**2))/100),
        "max_absolute_shadow_error_nits":float(abs(delta[exact<=1]).max()),
        "max_relative_highlight_error":float(np.max(abs(delta[exact>=1000])/exact[exact>=1000])),
    }
    return stats


if __name__=='__main__':
    sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
    parser=argparse.ArgumentParser()
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--backend',choices=('warp32','gpu32'),default='warp32')
    args=parser.parse_args()
    print(json.dumps(run(args.executable.resolve(),args.backend),indent=2))
