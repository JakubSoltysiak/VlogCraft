"""Compare native and NumPy metadata on complete, adversarially ordered pictures."""
import argparse
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hdr10plus_authoring import payload
from phase2c_author import NativeStatistics


def validate(library):
    analyzer = NativeStatistics(library)
    rng = np.random.default_rng(209440)
    random = rng.integers(0,65536,(3,313,257),dtype=np.uint16)
    moving = np.full((3,101,113),19000,dtype=np.uint16)
    moving[0,15,:] = 65535
    moving[2,99,4] = 65534
    binary = np.where(random>32767,65535,0).astype(np.uint16)
    frames = [random,binary,moving,moving[:,:,::-1],np.zeros((3,1,1),np.uint16),
              np.broadcast_to(np.array([0,32768,65535],dtype=np.uint16)[:,None,None],(3,19,13))]
    expected = [payload(frame) for frame in frames]
    for workers in (1,3):
        if list(analyzer.records(iter(frames),workers))!=expected:
            raise AssertionError("Native analysis changed serialized values or picture order")
    return len(frames)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library",type=Path)
    args = parser.parse_args()
    print(f"Exact serial and three-worker metadata on {validate(args.library)} controls")
