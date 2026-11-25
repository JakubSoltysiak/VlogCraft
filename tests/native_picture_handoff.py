"""Compare actual player draws through the default and independent-device paths."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def compare(worker, media, out):
    out.mkdir(parents=True, exist_ok=False)
    receipts = []
    for label, name in (("nv12","h264-4k60-0.mp4"), ("p010","hevc10-4k5994.mp4")):
        source = (media / name).resolve()
        info = subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries",
            "stream=color_transfer,color_space", "-of","json",str(source)])
        stream = json.loads(info)["streams"][0]
        color = "PQ" if stream.get("color_transfer") == "smpte2084" else "SDR"
        plan = out / (label + ".plan")
        # Six positions, including a discontinuity back to the first picture.
        plan.write_text(f"VLOGCRAFT_NATIVE 1\nRATE 60 1\nCANVAS 320 180\nEND 6\nCOLOR {color}\n"
            f"SOURCE a\t{source}\nCLIP outgoing a 0 3 2 1 60 1 1 0 0 1 0 1 0 0 0 0 5\n"
            "CLIP incoming a 3 6 0 1 60 1 1 0 0 1 0 1 0 0 0 0 3\n",encoding="utf8")
        outputs = []
        selections = []
        for enabled in (False,True):
            folder = out / f"{label}-{int(enabled)}"
            folder.mkdir()
            env = dict(os.environ, VLOGCRAFT_EXPERIMENTAL_PICTURE_HANDOFF=str(int(enabled)))
            selected = []
            # The worker captures the first and final draw. End a prefix at
            # each position to check the whole cut using the shipped interface.
            for count in range(1, 7):
                result = subprocess.run([worker,"--plan",plan,"--offscreen","--frames",str(count),"--capture",folder/"frame"],
                                        capture_output=True, timeout=30,env=env)
                (folder/f"worker-{count}.log").write_bytes(result.stdout + result.stderr)
                result.check_returncode()
                status = json.loads(result.stdout.splitlines()[-1])
                assert status["picture_handoff"] is enabled and status["handoff_fallbacks"] == 0
                assert status["handoff_draws"] == (count if enabled else 0)
                selected.append(status["selected"])
            selections.append(selected)
            outputs.append([(folder/f"frame-{n}.rgba16f").read_bytes() for n in range(6)])
        assert selections[0] == selections[1] and outputs[0] == outputs[1]
        assert all(len(frame) == 320*180*8 for frame in outputs[0]) and len(set(outputs[0])) > 1
        receipts.append({"format":label,"color":color,"matched_draws":6,"bytes_per_draw":320*180*8,
                         "last_pts":selections[0][-1][0]["pts"],"fallbacks":0})
    (out/"comparison.json").write_text(json.dumps(receipts,indent=2),encoding="utf8")
    return receipts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("worker","media","out"):
        parser.add_argument(arg,type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.worker.resolve(),args.media,args.out)))
