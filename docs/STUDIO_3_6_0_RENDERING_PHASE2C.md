# VlogCraft Studio 3.6.0 Phase 2C

The verified Phase 2B starting commit is `899ad995fc6ffd013e1eac2c25339459887fedc6`. The prepared 600-frame UHD60 HDR10+ export finished in 157.253 s, with 112.27 s attributed to authoring. [Phase 2B evidence](STUDIO_3_6_0_RENDERING_PHASE2B.md).

## Authoring profile on AC

The profile uses 120 encoded UHD pictures from the generated Phase 2B control. A setup encode removes the earlier dynamic metadata and supplies one identical tagged Main10 intermediate to all authoring arms. Setup is excluded from the measurement.

| Operation | Wall |
|---|---:|
| HEVC decode to null | 0.704 s |
| HEVC decode and PQ RGB16 reconstruction to null | 1.070 s |
| Decode, reconstruct and drain the original Windows pipe | 19.789 s |
| Frozen statistics and payload serialization during authoring | 5.306 s |
| Prepare HEVC fragments | 0.091 s |
| Insert per-picture SEI | 0.095 s |
| Remux | 0.113 s |
| Verify all packets | 0.269 s |
| Complete frozen authoring | 27.107 s |

Null and pipe probes are independent arms. Decode and reconstruction overlap transport. Python statistics and serialization consumed 5.313 host CPU seconds. The timed author used 33.77 sampled process-tree CPU seconds and reached 1,140 MiB peak summed working set. It transferred about 5.54 GiB of raw reconstructed data across the pipe. The large difference between reconstruction-to-null and the drained pipe identifies transfer and buffering as the first target.

## Exact authoring optimization

The experimental path opens a 1 MiB anonymous Windows pipe. The native pass calculates the exact 65,536-bin MaxRGB histogram and three unsigned 16-bit channel maxima using SSE2. Four reusable histogram shards reduce contention in frequently populated bins. The existing PQ lookup, rank policy, rounding and serialization are shared. Up to three workers in the measured route consume complete decoded frames in order. Per-picture payload authority remains the final decoded and quantized Main10 encode.

| 120-frame matched authoring | Wall | Peak summed working set | Final master |
|---|---:|---:|---|
| Frozen | 27.107 s | 1,140 MiB | Reference |
| Large pipe, NumPy statistics | 9.771 s | 1,133 MiB | Byte-identical |
| Large pipe, native statistics, one worker | 4.590 s | 1,135 MiB | Byte-identical |
| Large pipe, native statistics, three workers | 3.820 s | 1,137 MiB | Byte-identical |

The first comparison invocation used the same name for the final output and the fragment transport and stopped in remux. The corrected invocation uses a distinct destination and retained the failed receipt. The standalone statistics check independently compares complete serialized metadata for six controls with random values, ties, end-range codes, moving highlights, strided input and an incomplete SIMD block.

The saved-project export tool exposes explicit fast authoring. Its qualified default still uses the original decoder and NumPy statistics. Failure of the experimental author closes its scratch job and retries the same encoded intermediate through the reference author. The verified final master uses the existing atomic publication path.

```powershell
python benchmarks/profile_phase2c_author.py generated-120.mp4 build/qa/profile120 --frames 120
python benchmarks/compare_phase2c_author.py build/qa/profile120 build/qa/author120 --library $statisticsDll --mode pipe --mode native1 --mode native3
```
