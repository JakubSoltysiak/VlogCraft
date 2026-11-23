"""Bind sanitized local performance evidence to the exact relevant source tree."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=sorted({str(p.relative_to(ROOT)).replace('\\','/') for p in ROOT.glob('*.py')} |
 {str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'web').iterdir() if p.suffix in ('.js','.html','.css')} |
 {str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'native').iterdir() if p.suffix in ('.cpp','.h')} |
 {'packaging/requirements.txt','packaging/build_windows.py','web/branding/manifest.json'})

PROTOCOL_FILES=(
 'benchmarks/consistency.py','benchmarks/native_playback.py','benchmarks/windows_session.py',
 'benchmarks/window_geometry.py','benchmarks/window_visibility.py','benchmarks/runtime_trace.py',
 'benchmarks/performance_suite.py','benchmarks/performance_gate.py',
 'benchmarks/conditions.py','benchmarks/resource_history.py','benchmarks/generate_media.py',
 'benchmarks/session_memory.py','benchmarks/observer_memory.py','benchmarks/memory_metrics.py',
 'benchmarks/export_preservation.py','benchmarks/engine_profile.py','benchmarks/multicore_export.py',
 'benchmarks/camera_playback.py','benchmarks/camera_recovery.py','benchmarks/checkpoint_profile.py',
 'benchmarks/owned_process.py','benchmarks/run_qa.py','benchmarks/qa_progress.py','tests/qa_guard/sitecustomize.py',
 'benchmarks/detached_editing.py','benchmarks/graphics_diagnostics.py','benchmarks/observation_window.py',
 'benchmarks/root_cause_probe.py','benchmarks/flight_recorder.js',
 'benchmarks/allocation_summary.py','benchmarks/stabilization_evidence.py',
 'benchmarks/color_qualification.py','tests/test_hdr_color.py',
 'benchmarks/color_native_preview.py','tests/windows_color.py',
 'benchmarks/color_uhd.py',
 'benchmarks/mixed_still_export.py','tests/test_export_workflow.py','tests/windows_export_workflow.py',
 'benchmarks/hdr10plus_source_index.py','tests/test_hdr10plus_index.py',
 'tests/windows_timeline_editing.py',
 'benchmarks/compare_hdr10plus_bits.py','tests/test_hdr10plus_export.py','tests/windows_hdr10plus.py',
 'tests/windows_motion.py','tests/motion_presets.test.js',
 'tests/windows_library.py','tests/windows_icons.py',
 'benchmarks/studio355_live_flight.py',
 'tests/test_hdr10plus_authoring.py','tests/test_hdr10plus_master.py',
 'tests/windows_hdr10plus_master.py','tests/windows_hdr_profiles.py',
 'benchmarks/hdr10plus_camera_analysis.py',
 'tests/test_hdr_editing.py',
 'tests/test_timeline_transitions.py','tests/windows_hdr_editing.py',
 'tests/test_export_scratch.py','benchmarks/studio357_hdr_sequence.py',
 'benchmarks/profile_hdr_render.py','benchmarks/profile_preview_proxy.py',
 'tests/test_hdr_render_reuse.py',
 'tests/performance.py','tests/gpu_metrics.py',
 'benchmarks/phase2b_live.py','benchmarks/phase2b_conversion.py','benchmarks/phase2b_project_export.py',
 'benchmarks/phase2c_author.py','benchmarks/profile_phase2c_author.py','benchmarks/compare_phase2c_author.py',
 'benchmarks/check_phase2c_stats.py','benchmarks/phase2c_diagnostics.py','benchmarks/qualify_phase2c_project.py',
 'benchmarks/phase2d_project_export.py','tests/test_native_project_render.py','tests/windows_native_project_export.py',
 'benchmarks/check_phase2d_preview.py','benchmarks/check_phase2d_source_clock.py',
 'benchmarks/resume_phase2d_reference.py',
 'benchmarks/phase3b_scrub.py','benchmarks/native_seek.py','benchmarks/program_seek.py',
 'benchmarks/phase3a_encoder_probe.py','benchmarks/phase3a_first_project.py',
 'tests/test_phase3a_export.py','tests/windows_phase3a_export.py',
 'tests/verify_bundle.py','tools/setup_architecture_lab.py',
 'benchmarks/render_phase2.py','benchmarks/render_phase2_stream.py','benchmarks/render_phase2_export.py',
 'experiments/render_phase2/composite.h','experiments/render_phase2/d3d_composite.h',
 'experiments/render_phase2/hardware_inputs.h','experiments/render_phase2/hdr_statistics.cpp',
 'experiments/render_phase2/main.cpp','experiments/render_phase2/normalize_surface.h',
 'experiments/render_phase2/pq_shader.h','tests/test_phase2b_export.py')

def fingerprint(files=None):
 h=hashlib.sha256()
 for name in sorted(FILES if files is None else files):
  data=(ROOT/name).read_bytes().replace(b'\r\n',b'\n');h.update(name.encode()+b'\0'+data+b'\0')
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('record',type=Path);p.add_argument('--stamp',action='store_true');a=p.parse_args()
 data=json.loads(a.record.read_text('utf8'))
 if a.stamp:
  data['source_fingerprint']=fingerprint();data['fingerprint_method']='SHA256 sorted relevant relative path + NUL + LF-normalized source + NUL'
  data['benchmark_protocol_fingerprint']=fingerprint(PROTOCOL_FILES)
  data['benchmark_protocol_fingerprint_method']='SHA256 sorted benchmark driver/observer relative path + NUL + LF-normalized source + NUL'
  a.record.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
 else:
  assert data.get('source_fingerprint')==fingerprint(),'Performance evidence does not match the relevant source tree; run the impacted performance profile and update the record'
  assert data.get('benchmark_protocol_fingerprint')==fingerprint(PROTOCOL_FILES),'Performance evidence does not match the benchmark protocol; qualify the changed driver/observer and update the record'
  print(json.dumps({'performance_record_matches_source':True,'performance_record_matches_protocol':True,'qualification':data.get('qualification','partial')}))
if __name__=='__main__':main()
