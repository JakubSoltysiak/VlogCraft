from pathlib import Path
import tempfile
import time
import unittest

from preview_cache import PreviewCache
import server


class PreviewCacheTests(unittest.TestCase):
    def test_ready_cache_reuses_state_and_invalidates_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=PreviewCache(Path(folder)/'preview')
            state=server.default_state();state['output'].update(width=320,height=180,fps=24)
            clip=server.default_title();clip['end']=.5;state['tracks'][0]['clips']=[clip]
            try:
                job=cache.prepare(state,0,640)
                limit=time.monotonic()+15
                while cache.status(job['id'])['status'] in ('queued','rendering') and time.monotonic()<limit:
                    time.sleep(.02)
                self.assertEqual(cache.status(job['id'])['status'],'ready',cache.status(job['id']))
                self.assertTrue(cache.path(job['id']).is_file())
                self.assertEqual(cache.prepare(state,1,640)['id'],job['id'])
                clip['text']='Changed'
                newer=cache.prepare(state,0,640)
                self.assertNotEqual(newer['id'],job['id'])
                cache.cancel()
                self.assertEqual(cache.status(newer['id'])['status'],'cancelled')
                self.assertFalse((Path(folder)/'preview'/(newer['id']+'.mp4')).exists())
            finally:cache.close()
