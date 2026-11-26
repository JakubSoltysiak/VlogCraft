import struct
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageCms, PngImagePlugin

import color_management
import hdr_layers
import hdr_render
import native_plan
import native_project_plan
import preview_dependencies
import project_store
import server
import timing
from test_hdr_color import project
from test_hdr10plus_export import command


SRGB_PRIMARIES = ((.64, .33), (.30, .60), (.15, .06))
P3_PRIMARIES = ((.68, .32), (.265, .69), (.15, .06))
REC2020_PRIMARIES = ((.708, .292), (.170, .797), (.131, .046))


def native_xyz(primaries):
    unscaled = np.column_stack([(x/y, 1, (1-x-y)/y) for x, y in primaries])
    x, y = .3127, .329
    return unscaled * np.linalg.solve(unscaled, (x/y, 1, (1-x-y)/y))


def icc_offsets(profile):
    return {name: offset for name, offset, _ in
            (struct.unpack_from(">4sII", profile, 132 + 12*index)
             for index in range(struct.unpack_from(">I", profile, 128)[0]))}


def matrix_profile(primaries):
    source = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    profile = bytearray(source)
    offsets = icc_offsets(profile)
    # Keep the original sRGB description to demonstrate that a label cannot
    # select the matrix. Rebuild the colorants using the embedded adaptation.
    adaptation = np.array(struct.unpack_from(">9i", profile, offsets[b"chad"]+8)).reshape(3, 3)/65536
    xyz = adaptation @ native_xyz(primaries)
    for column, tag in enumerate((b"rXYZ", b"gXYZ", b"bXYZ")):
        struct.pack_into(">3i", profile, offsets[tag]+8, *np.rint(xyz[:, column]*65536).astype(int))
    struct.pack_into(">6I", profile, offsets[b"chrm"]+12,
                     *(round(value*65536) for xy in primaries for value in xy))
    return bytes(profile)


def raw_picture(state, folder):
    args = hdr_render.command(state, 0, 2/24, folder/"still.mp4", folder)
    raw = command(*args[:args.index("-c:v")], "-c:v", "rawvideo", "-threads:v", "1", "-f", "rawvideo", "-")
    frames = np.frombuffer(raw, dtype="<u2").reshape(2, -1)
    np.testing.assert_array_equal(frames[0], frames[1])
    width, height = state["output"]["width"], state["output"]["height"]
    samples = width*height
    y = (frames[0][:samples].mean()-64)/876
    cb = (frames[0][samples:samples+samples//4].mean()-512)/896
    cr = (frames[0][samples+samples//4:].mean()-512)/896
    red, blue = y+1.4746*cr, y+1.8814*cb
    green = (y-.2627*red-.0593*blue)/.6780
    return color_management.pq_to_nits((red, green, blue))


class StillICCTests(unittest.TestCase):
    def test_colorants_white_and_transfer_determine_embedded_profile(self):
        srgb, p3 = matrix_profile(SRGB_PRIMARIES), matrix_profile(P3_PRIMARIES)
        self.assertEqual(hdr_layers.photograph_icc(srgb), hdr_layers.SRGB)
        self.assertEqual(hdr_layers.photograph_icc(p3), hdr_layers.DISPLAY_P3)

        other_primaries = ((.64, .33), (.21, .71), (.15, .06))
        with self.assertRaisesRegex(ValueError, "colorants"):
            hdr_layers.photograph_icc(matrix_profile(other_primaries))

        wrong_transfer = bytearray(p3)
        offsets = icc_offsets(wrong_transfer)
        struct.pack_into(">i", wrong_transfer, offsets[b"rTRC"]+12, round(2.6*65536))
        with self.assertRaisesRegex(ValueError, "transfer"):
            hdr_layers.photograph_icc(bytes(wrong_transfer))
        wrong_white = bytearray(p3)
        struct.pack_into(">i", wrong_white, offsets[b"chad"]+8, 65536)
        with self.assertRaisesRegex(ValueError, "adaptation"):
            hdr_layers.photograph_icc(bytes(wrong_white))

        alternate_lut = bytearray(p3)
        tag = next(index for index in range(struct.unpack_from(">I", p3, 128)[0])
                   if p3[132+12*index:136+12*index] == b"cprt")
        struct.pack_into(">4s", alternate_lut, 132+12*tag, b"A2B0")
        with self.assertRaisesRegex(ValueError, "LUT"):
            hdr_layers.photograph_icc(bytes(alternate_lut))

        encoded = np.linspace(0., 1., 1024)
        transfer = np.where(encoded <= .04045, encoded/12.92, ((encoded+.055)/1.055)**2.4)
        table = b"curv"+bytes(4)+struct.pack(">I", len(encoded))+np.rint(transfer*65535).astype(">u2").tobytes()
        self.assertTrue(hdr_layers.is_srgb_curve(table))

    def test_exif_geometry_and_untagged_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = Image.new("RGB", (48, 56))
            exif = Image.Exif()
            exif[274] = 6
            rotated = root/"rotated.jpg"
            image.save(rotated, exif=exif, icc_profile=matrix_profile(P3_PRIMARIES))
            self.assertEqual(hdr_layers.photo_contract(rotated), (56, 48, "transpose=clock", hdr_layers.DISPLAY_P3))
            untagged = root/"untagged.png"
            image.save(untagged)
            self.assertEqual(hdr_layers.photo_contract(untagged), (48, 56, "", hdr_layers.SRGB))

            custom_gamma = root/"gamma.png"
            info = PngImagePlugin.PngInfo()
            info.add(b"gAMA", struct.pack(">I", 38000))
            image.save(custom_gamma, pnginfo=info)
            with self.assertRaisesRegex(ValueError, "non-sRGB gamma"):
                hdr_layers.photo_contract(custom_gamma)

            custom_primaries = root/"chromaticities.png"
            info = PngImagePlugin.PngInfo()
            info.add(b"cHRM", struct.pack(">8I", 31270, 32900, 68000, 32000, 26500, 69000, 15000, 6000))
            image.save(custom_primaries, pnginfo=info)
            with self.assertRaisesRegex(ValueError, "non-sRGB chromaticities"):
                hdr_layers.photo_contract(custom_primaries)

    def test_managed_p3_alpha_gain_and_saved_srgb_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = root/"rgba.png"
            pixel = (226, 105, 65, 127)
            Image.new("RGBA", (128, 72), pixel).save(png, icc_profile=matrix_profile(P3_PRIMARIES))
            photo = {"id": "picture", "kind": "image", "name": png.name, "path": str(png), "duration": 0}
            state = project([photo])
            state["output"]["color"]["sdrWhiteNits"] = 203
            clip = state["tracks"][0]["clips"][0]
            clip.update(end=2/24, opacity=.65)
            with self.assertRaisesRegex(native_project_plan.Ineligible, "Display P3.*managed"):
                native_project_plan.compile_project(state, root)
            with self.assertRaisesRegex(native_plan.Unsupported, "still pictures.*reference compositor"):
                native_plan.compile_plan(state)
            key, _ = preview_dependencies.project(state, 0, 2, 128)
            actual_p3 = raw_picture(state, root)

            saved = root/"compat.vlogcraft"
            clip["inputColor"] = {"profile": "srgb", "range": "full"}
            project_store.save(saved, timing.encode(state), server.validate_document)
            restored, recovered = project_store.load(saved, server.validate_document)
            self.assertFalse(recovered)
            self.assertEqual(restored["tracks"][0]["clips"][0]["inputColor"], clip["inputColor"])
            self.assertNotEqual(preview_dependencies.project(restored, 0, 2, 128)[0], key)
            self.assertEqual(native_project_plan.compile_project(restored, root).sources[0].interpretation, hdr_layers.SRGB)
            actual_srgb = raw_picture(restored, root)

            rgb = ((np.array(pixel[:3])/255+.055)/1.055)**2.4
            rgb *= 203 * (.65*pixel[3]/255)
            for actual, primaries in ((actual_p3, P3_PRIMARIES), (actual_srgb, SRGB_PRIMARIES)):
                expected = np.linalg.solve(native_xyz(REC2020_PRIMARIES), native_xyz(primaries) @ rgb)
                np.testing.assert_allclose(actual, expected, atol=.8, rtol=0)
            self.assertGreater(actual_p3[0]-actual_srgb[0], 4)
