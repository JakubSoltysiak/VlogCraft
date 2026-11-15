import json,tempfile,threading,unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import desktop_recovery as r
import project_store


class Backend:
    def __init__(self,root):
        self.PROJECT=root/'project.vlogcraft';self.LOCK=threading.RLock();self.STATE={'name':'published','tracks':[],'output':{}}
        self.NATIVE_PLAYBACK=SimpleNamespace(clock_position=1234567);self.save_state(self.STATE)
    def validate_state(self,state):
        if state.get('name')=='invalid':raise ValueError('invalid draft')
        return deepcopy(state)
    def save_state(self,state):
        self.STATE=deepcopy(state);project_store.atomic_write(self.PROJECT,json.dumps(state).encode())


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.backend=Backend(self.root)
    def tearDown(self):self.tmp.cleanup()
    def checkpoint(self,model,name='draft',revision=2,sequence=1):
        return model.checkpoint({'epoch':model.epoch,'sequence':sequence,'revision':revision,
           'document':{'name':name,'tracks':[],'output':{},'apiKey':'must not be retained'},
           'ui':{'playhead':.5,'engine':'native','undo':[{'tracks':[]}],'apiKey':'must not be retained'}})
    def test_acknowledgement_follows_atomic_publication(self):
        path=self.root/'journal.json';acks=[]
        journal=r.Journal(path,lambda epoch,seq:acks.append(json.loads(path.read_text())['sequence']))
        journal.submit({'epoch':0,'sequence':4});journal.flush();self.assertEqual(acks,[4])
        before=path.read_bytes()
        with patch.object(r.project_store,'atomic_write',side_effect=OSError('injected')):
            journal.submit({'epoch':0,'sequence':5})
            with self.assertRaises(OSError):journal.flush()
        self.assertEqual(path.read_bytes(),before);self.assertEqual(acks,[4])
    def test_coalescing_preserves_last_checkpoint_and_releases_worker(self):
        journal=r.Journal(self.root/'journal.json')
        for n in range(100):journal.submit({'epoch':0,'sequence':n})
        journal.flush();self.assertEqual(json.loads(journal.path.read_text())['sequence'],99)
        self.assertIsNone(journal.pending);self.assertIsNone(journal.thread)
    def test_close_storage_failure_still_detaches_and_allows_host_cleanup(self):
        host=r.WindowsRecovery.__new__(r.WindowsRecovery)
        host.model=SimpleNamespace(closing=False);host.timer=SimpleNamespace(cancel=lambda:None)
        events=[];detached=[]
        host.journal_flush=lambda:(_ for _ in ()).throw(OSError('injected disk failure'))
        host.event=lambda event:events.append(event);host.detach=lambda:detached.append(True)
        with self.assertLogs(level='ERROR'):host.close()
        self.assertTrue(host.model.closing);self.assertEqual(detached,[True])
        self.assertEqual(events,['checkpoint_close_failed','host_close'])
    def test_diagnostic_storage_failure_does_not_interrupt_recovery(self):
        host=r.WindowsRecovery.__new__(r.WindowsRecovery)
        host.cache=self.root/'unavailable';host.started=__import__('time').perf_counter();host.log_guard=threading.Lock()
        with self.assertLogs(level='ERROR'):host.event('process_failed',exit_code=1)
    def test_queued_ui_callback_is_ignored_after_close(self):
        host=r.WindowsRecovery.__new__(r.WindowsRecovery);host.model=SimpleNamespace(closing=False)
        queued=[];called=[]
        form=SimpleNamespace(IsDisposed=False,Disposing=False,IsHandleCreated=True,BeginInvoke=lambda fn:queued.append(fn))
        host.window=SimpleNamespace(native=form)
        with patch.dict('sys.modules',{'System':SimpleNamespace(Action=lambda fn:fn)}):
            host.dispatch(lambda:called.append(True));host.model.closing=True
            queued.pop()();host.dispatch(lambda:called.append(True))
        self.assertEqual(called,[]);self.assertEqual(queued,[])
    def test_encoded_history_is_durable_without_expanding_old_history_on_each_checkpoint(self):
        model=r.Recovery(self.backend,self.root);self.checkpoint(model);model.journal.flush()
        history={'encoding':'json','data':json.dumps({'undo':[{'tracks':[]}],'redo':[]})}
        model.checkpoint({'epoch':model.epoch,'sequence':2,'ui':{'history':dict(history,apiKey='must not be retained')}});model.journal.flush()
        self.assertEqual(model.journal.latest['ui']['history'],history);self.assertNotIn('undo',model.journal.latest['ui'])
        old=model.begin();model.preserve(old);self.assertEqual(model.restore['history'],history)
    def test_invalid_encoded_history_does_not_replace_the_previous_checkpoint(self):
        model=r.Recovery(self.backend,self.root);self.checkpoint(model);model.journal.flush();before=model.journal.path.read_bytes()
        with self.assertRaises(ValueError):model.checkpoint({'epoch':model.epoch,'sequence':2,'ui':{'history':{'encoding':'unknown','data':'x'}}})
        self.assertEqual(model.sequence,1);self.assertEqual(model.journal.path.read_bytes(),before)
    def test_corrupt_history_is_quarantined_without_losing_the_valid_project_draft(self):
        model=r.Recovery(self.backend,self.root);self.checkpoint(model);model.journal.flush()
        model.checkpoint({'epoch':model.epoch,'sequence':2,'ui':{'history':{'encoding':'gzip-base64','data':'invalid!'}}});model.journal.flush()
        before=model.journal.path.read_bytes();old=model.begin();model.preserve(old)
        self.assertEqual(self.backend.STATE['name'],'draft');self.assertNotIn('history',model.restore)
        self.assertEqual(next(self.root.glob('recovery-history-invalid-*')).read_bytes(),before)
        self.assertIsNotNone(model.journal.warning)
    def test_durable_draft_undo_position_and_epoch_survive_renderer_loss(self):
        model=r.Recovery(self.backend,self.root);self.checkpoint(model);model.journal.flush()
        old=model.begin();self.assertEqual(old,0)
        with self.assertRaises(ValueError):model.check_epoch(old)
        model.preserve(old)
        self.assertEqual(self.backend.STATE['name'],'draft');self.assertEqual(model.restore['undo'],[{'tracks':[]}])
        self.assertEqual(model.restore['playhead'],1.234567)
        self.assertNotIn('apiKey',model.journal.path.read_text())
        self.assertFalse(self.checkpoint_at_epoch(model,old))
        model.ready(model.epoch);self.assertEqual(model.phase,'ready')
    def checkpoint_at_epoch(self,model,epoch):return model.checkpoint({'epoch':epoch,'sequence':999,'ui':{}})
    def test_late_completed_save_is_never_replaced_with_an_older_draft(self):
        model=r.Recovery(self.backend,self.root);self.checkpoint(model);model.journal.flush();old=model.begin()
        self.backend.save_state({'name':'newer published','tracks':[],'output':{}});model.note_saved(old,3)
        model.preserve(old);self.assertEqual(self.backend.STATE['name'],'newer published')
    def test_restart_recovers_draft_only_when_bound_to_same_published_revision(self):
        model=r.Recovery(self.backend,self.root);self.checkpoint(model);model.journal.flush()
        restarted=r.Recovery(self.backend,self.root);self.assertEqual(self.backend.STATE['name'],'draft')
        self.backend.save_state({'name':'external revision','tracks':[],'output':{}})
        r.Recovery(self.backend,self.root);self.assertEqual(self.backend.STATE['name'],'external revision')
    def test_unreadable_or_invalid_checkpoint_is_retained_without_damaging_project(self):
        path=self.root/'recovery-checkpoint.json';path.write_bytes(b'broken{')
        model=r.Recovery(self.backend,self.root);self.assertIsNotNone(model.journal.warning)
        self.assertEqual(list(self.root.glob('*unreadable*'))[0].read_bytes(),b'broken{')
        self.checkpoint(model,'invalid');model.journal.flush();before=self.backend.PROJECT.read_bytes()
        restarted=r.Recovery(self.backend,self.root);self.assertIsNotNone(restarted.journal.warning)
        self.assertEqual(self.backend.PROJECT.read_bytes(),before);self.assertTrue(list(self.root.glob('*rejected*')))
