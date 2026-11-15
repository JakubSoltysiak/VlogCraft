import unittest
from benchmarks.allocation_summary import allocation_summary

class AllocationSummaryTests(unittest.TestCase):
    def test_aggregates_sampled_bytes_without_publishing_paths_or_urls(self):
        def node(url,fn,size):return {'callFrame':{'url':url,'functionName':fn},'selfSize':size,'children':[]}
        root=node('http://127.0.0.1:123/app.js','animate',10)
        root['children']=[node('http://127.0.0.1:123/app.js','animate',20),node('private://hidden/name.js','path/identifying',50)]
        out=allocation_summary({'head':root})
        self.assertEqual(out,[{'script':'other','function':'anonymous','sampled_bytes':50},{'script':'app.js','function':'animate','sampled_bytes':30}])
    def test_limits_public_stack_groups(self):
        root={'callFrame':{'url':'','functionName':''},'selfSize':0,'children':[{'callFrame':{'url':'','functionName':'fn'+str(n)},'selfSize':n} for n in range(80)]}
        self.assertEqual(len(allocation_summary({'head':root})),30)
