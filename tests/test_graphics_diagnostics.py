import unittest
from benchmarks.graphics_diagnostics import graphics_diagnostics

class GraphicsDiagnosticsTests(unittest.TestCase):
    def test_only_public_technical_fields_are_retained_and_observer_detaches(self):
        class CDP:
            detached=False
            def send(self,name):
                if name=='Browser.getVersion':return {'product':'Chrome/test','protocolVersion':'test','userAgent':'exclude','commandLine':'exclude'}
                return {'commandLine':'exclude','gpu':{'devices':[{'deviceString':'GPU','deviceId':'exclude','driverVersion':'test'}],
                        'auxAttributes':{'glRenderer':'D3D11 (0x0000150E)','privatePath':'exclude'},'featureStatus':{'gpu_compositing':'enabled'}}}
            def detach(self):self.detached=True
        cdp=CDP()
        class Browser:
            def new_browser_cdp_session(self):return cdp
        result=graphics_diagnostics(Browser())
        self.assertTrue(cdp.detached);self.assertNotIn('exclude',str(result))
        self.assertEqual(result['graphics'],{'glRenderer':'D3D11'})

    def test_unavailable_optional_diagnostic_keeps_only_failure_category(self):
        class CDP:
            detached=False
            def send(self,name):raise RuntimeError('identifying details must not be retained')
            def detach(self):self.detached=True
        cdp=CDP()
        class Browser:
            def new_browser_cdp_session(self):return cdp
        self.assertEqual(graphics_diagnostics(Browser()),{'runtime_unavailable':'RuntimeError','graphics_unavailable':'RuntimeError'})
        self.assertTrue(cdp.detached)
