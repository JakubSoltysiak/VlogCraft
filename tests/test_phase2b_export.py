from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from benchmarks.phase2b_live import select_pictures
from benchmarks.phase2b_project_export import export_project
import project_store
import render_engine
import server
import timing
from hdr10plus_index import SIDE_DATA
from test_hdr_color import probe, project, source
from test_hdr10plus_export import command, decoded


class Phase2BExportTests(unittest.TestCase):
    def test_rational_vfr_selection_preserves_source_in_and_frame_order(self):
        ticks = (90,93,98,104,106,119)
        self.assertEqual(select_pictures(ticks,Fraction(1,120),Fraction(1,40),Fraction(30),4),
                         (1,1,2,3))
        with self.assertRaises(ValueError):
            select_pictures((90,93,93,120),Fraction(1,120),Fraction(0),Fraction(30),4)
        with self.assertRaises(ValueError):
            select_pictures(ticks,Fraction(1,120),Fraction(1,40),Fraction(30),30)

    def test_saved_project_parallel_export_and_reference_fallback_match(self):
        with tempfile.TemporaryDirectory() as path:
            folder = Path(path)
            sdr = source(folder,"sdr",sdr=True)
            pq = source(folder,"pq",nits=800)
            png = folder/"moving.png"
            Image.new("RGBA",(48,56),(24,70,214,164)).save(png)
            photo = dict(id="photo",kind="image",path=str(png),name=png.name,**server.probe(png))
            state = project([photo,sdr,pq])
            state["output"]["fps"] = "30000/1001"
            end = float(Fraction(6*1001,30000))
            for track in state["tracks"]:
                track["clips"][0]["end"] = end
            clip = state["tracks"][0]["clips"][0]
            clip.update(mask="ellipse",maskRadius=.5,feather=.2,rotation=7,keys={
                "x":[{"time":0,"value":-.18,"mode":"linear"},{"time":end,"value":.12,"mode":"linear"}],
            })
            wav = folder/"tone.wav"
            command("ffmpeg","-v","error","-f","lavfi","-i","sine=f=521:r=48000:d=0.3",str(wav))
            audio = dict(id="audio",kind="audio",path=str(wav),name=wav.name,**server.probe(wav))
            state["assets"].append(audio)
            sound = server.default_clip(audio)
            sound["end"] = end
            state["tracks"].append(dict(id="sound",type="audio",name="Sound",volume=1,clips=[sound]))
            saved = folder/"test.vlogcraft.json"
            document = timing.encode(state)
            project_store.save(saved,document,server.validate_document)
            restored,backup = project_store.load(saved,server.validate_document)
            self.assertFalse(backup)
            original = saved.read_bytes()
            preview = folder/"preview-before.mp4"
            preview_work = folder/"preview-before"
            preview_work.mkdir()
            render_engine.render_range(restored,0,end,preview,preview_work,"preview")
            outputs = [folder/name for name in ("reference.mp4","parallel.mp4","fallback.mp4")]
            report = export_project(restored,outputs[0],progress=lambda _:None)
            self.assertEqual(report["frames"],6)
            events = []
            report = export_project(restored,outputs[1],backend="parallel",workers=2,progress=events.append)
            self.assertGreater(report["parallel_segments"],0,(report,events))
            self.assertEqual(report["fallback_segments"],0)
            with patch("benchmarks.phase2b_project_export.run_segment",side_effect=OSError("converter failed")):
                report = export_project(restored,outputs[2],backend="parallel",workers=2,progress=lambda _:None)
            self.assertGreater(report["fallback_segments"],0)
            self.assertEqual(saved.read_bytes(),original)
            self.assertEqual(decoded(outputs[0]),decoded(outputs[1]))
            self.assertEqual(decoded(outputs[0]),decoded(outputs[2]))
            def broken_records(_):
                raise ValueError("injected HDR analysis failure")
            author_fallback = folder/"author-fallback.mp4"
            report = export_project(restored,author_fallback,authoring={"picture_records":broken_records},
                                    progress=lambda _:None)
            self.assertTrue(report["author_fallback"])
            self.assertEqual(decoded(outputs[0]),decoded(author_fallback))
            info = probe(outputs[1])
            frames = [frame for frame in info["frames"] if frame["media_type"]=="video"]
            self.assertEqual([int(frame["pts"]) for frame in frames],[4004*index for index in range(6)])
            self.assertTrue(all(sum(tag["side_data_type"]==SIDE_DATA for tag in frame["side_data_list"])==1
                                for frame in frames))
            after = folder/"preview-after.mp4"
            after_work = folder/"preview-after"
            after_work.mkdir()
            render_engine.render_range(restored,0,end,after,after_work,"preview")
            self.assertEqual(decoded(preview),decoded(after))
            with self.assertRaises(FileExistsError):
                export_project(restored,outputs[0],backend="parallel",progress=lambda _:None)
            restored["assets"][0]["path"] = str(folder/"missing.png")
            failed = folder/"failed.mp4"
            with self.assertRaises(FileNotFoundError):
                export_project(restored,failed,backend="parallel",progress=lambda _:None)
            self.assertFalse(failed.exists())
