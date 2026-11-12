import cv2
import numpy as np
import unittest

import motion


class RotationTests(unittest.TestCase):
    def test_rotation_path_and_correction_follow_known_camera_roll(self):
        width,height=240,160
        rng=np.random.default_rng(49)
        original=cv2.GaussianBlur(rng.integers(0,256,(height,width),dtype=np.uint8),(3,3),0)
        angles=np.array([0,2,-2,3,-1,2,0],dtype=float)
        def frames():
            for a in angles:
                m=cv2.getRotationMatrix2D(((width-1)/2,(height-1)/2),-a,1)
                yield cv2.warpAffine(original,m,(width,height),borderMode=cv2.BORDER_REFLECT)
        path=motion.translations(frames(),None,rotation=True)
        np.testing.assert_allclose(path[:,2],angles,atol=.30)
        np.testing.assert_allclose(path[:,:2],0,atol=.005)
        residual=angles+motion.smooth_correction(path,1,2)[:,2]
        self.assertLess(np.std(np.diff(residual)),np.std(np.diff(angles))*.4)
