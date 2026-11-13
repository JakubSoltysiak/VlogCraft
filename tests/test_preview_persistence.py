from pathlib import Path
import tempfile,threading,time,unittest
from unittest import mock
from preview_cache import PreviewCache
import server

class PreviewPersistenceTests(unittest.TestCase):
    def state(self):
        state=server.default_state();state['output'].update(width=320,height=180,fps=24)
        first=server.default_title();first.update(text='Near',end=.5)
        far=server.default_title(16);far.update(text='Far',end=.5)
        state['tracks'][0]['clips']=[first,far]
        return state

    def ready(self,cache,key):
        limit=time.monotonic()+20
        while cache.status(key)['status'] in ('queued','rendering') and time.monotonic()<limit:time.sleep(.01)
        self.assertEqual(cache.status(key)['status'],'ready',cache.status(key))

    def test_unrelated_edit_restart_and_corrupted_file_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=PreviewCache(folder);state=self.state()
            try:
                one=cache.prepare(state,0,640);self.ready(cache,one['id'])
                path=cache.path(one['id']);original=path.read_bytes()
                state['tracks'][0]['clips'][1]['text']='Unrelated edit'
                same=cache.prepare(state,0,640)
                self.assertEqual(same['id'],one['id']);self.assertTrue(same['cacheHit'])
                self.assertEqual(path.read_bytes(),original)
                cache.close();cache=PreviewCache(folder)
                with mock.patch('render_engine.render_range',side_effect=AssertionError('Should restore from disk')):
                    restored=cache.prepare(state,0,640)
                    self.assertEqual(restored['status'],'ready');self.assertTrue(restored['cacheHit'])
                self.assertEqual(cache.metrics()['diskHits'],1)
                path.write_bytes(b'corrupted')
                repaired=cache.prepare(state,0,640);self.assertFalse(repaired['cacheHit'])
                self.ready(cache,repaired['id'])
                self.assertGreater(path.stat().st_size,1000)
            finally:cache.close()

    def test_single_budget_includes_previous_session_files_and_preserves_linked_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for n in range(4):(root/(f'{n:064x}'+'.mp4')).write_bytes(b'old derivative')
            protected=root/('f'*64+'.mp4');protected.write_bytes(b'original source')
            cache=PreviewCache(root,max_files=2);state=self.state()
            state['assets']=[{'id':'a'*32,'path':str(protected),'kind':'video'}]
            try:
                job=cache.prepare(state,0,640);self.ready(cache,job['id'])
                owned=[p for p in root.glob('*.mp4') if p!=protected]
                self.assertLessEqual(len(owned),2);self.assertEqual(protected.read_bytes(),b'original source')
                self.assertGreaterEqual(cache.metrics()['evicted'],3)
            finally:cache.close()

    def test_rapid_edits_keep_two_pending_snapshots_and_shutdown_joins_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            entered=threading.Event();release=threading.Event()
            def render(state,start,end,dest,work,*args):
                entered.set();release.wait(10);dest.write_bytes(b'completed test range')
            with mock.patch('render_engine.render_range',side_effect=render):
                cache=PreviewCache(folder,max_files=2);state=self.state()
                try:
                    first=cache.prepare(state,0,640);self.assertTrue(entered.wait(2))
                    for n in range(100):
                        state['tracks'][0]['clips'][0]['text']='Changed '+str(n)
                        cache.prepare(state,0,640)
                    with cache.guard:
                        self.assertLessEqual(sum('_snapshot' in j for j in cache.jobs.values()),2)
                        self.assertLessEqual(len(cache.jobs),6)
                    release.set()
                finally:release.set();cache.close()
                self.assertFalse(cache.worker.is_alive())
