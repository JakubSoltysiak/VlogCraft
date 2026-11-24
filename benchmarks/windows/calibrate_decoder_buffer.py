"""Verify the workstation's D3D11 Stop payload against a private, isolated API caller."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess


def compare(stdout, events):
    observed = [line.split() for line in stdout.splitlines() if line.strip()]
    if len(observed) != 2 or any(len(row) != 7 for row in observed):
        raise ValueError("Expected two successful acquisitions")
    pid, tid = observed[0][:2]
    sequence = []
    for row in csv.reader(io.StringIO(events), skipinitialspace=True):
        if len(row) < 10 or not row[1].strip().isdigit() or row[3].strip() != tid:
            continue
        process = re.search(r"\(\s*(\d+)\s*\)$", row[2].strip())
        if not process or process[1] != pid:
            continue
        if row[0].startswith("Microsoft-Windows-Direct3D11/ID3D11VideoContext_GetDecoderBuffer/win:"):
            fields = dict(item.strip().split(" : ", 1) for item in row[9:] if " : " in item)
            sequence.append((row[0].rsplit(":", 1)[1], fields))
    if [op for op, _ in sequence] != ["Start", "Stop"] * 2:
        raise ValueError("Missing or ambiguous same-process/thread event pairs")
    result = []
    for i, recorded in enumerate(observed):
        _, start = sequence[2*i]
        _, stop = sequence[2*i+1]
        if recorded[:2] != [pid, tid] or int(start["pDecoder"], 0) != int(recorded[2], 16):
            raise ValueError("Decoder or thread identity mismatch")
        if int(start["Type"], 0) or int(stop["m_Ret"], 0):
            raise ValueError("Unexpected buffer type or HRESULT")
        pointer, size = int(stop["ppBuffer"], 0), int(stop["pBufferSize"], 0)
        result.append({
            "ppBuffer_matches_output_slot": pointer == int(recorded[5], 16),
            "ppBuffer_matches_returned_value": pointer == int(recorded[6], 16),
            "pBufferSize_matches_output_slot": size == int(recorded[3], 16),
            "pBufferSize_matches_returned_value": size == int(recorded[4]),
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    trace = args.output.resolve() / "buffer-probe.private.etl"
    session = f"VlogCraftDecoderCalibration-{os.getpid()}"
    subprocess.run(["logman", "start", session, "-p", "Microsoft-Windows-Direct3D11",
                    "0xffffffffffffffff", "5", "-o", str(trace), "-f", "bincirc", "-max", "32", "-ets"], check=True)
    try:
        values = subprocess.check_output([str(args.executable.resolve())], text=True, timeout=15)
    finally:
        subprocess.run(["logman", "stop", session, "-ets"], check=True)
    stats = subprocess.check_output(["xperf", "-i", trace, "-a", "tracestats"], text=True, errors="replace")
    for kind in ("Events", "Buffers"):
        if not re.search(rf"Total # Lost {kind}\s*:\s*0\b", stats):
            raise ValueError("Trace loss is nonzero or unknown")
    events = subprocess.check_output(["xperf", "-i", trace, "-a", "dumper", "-add_fieldnames"],
                                     text=True, errors="replace")
    print(json.dumps(compare(values, events), indent=2))


if __name__ == "__main__":
    main()
