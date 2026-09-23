import io
import json
import struct
import uuid
from pathlib import Path
import pytest
from answer_cache_agent.graph import RuntimeDeps, Agent
from answer_cache_agent.embeddings import HashEmbedder
from answer_cache_agent.providers.fake import demo_provider
from answer_cache_agent.repository import Repository
from answer_cache_agent.ingest import ingest
from answer_cache_agent.harness import run_script
from questionnaire_host.service import Service, CONTRACT, SCOPE
from questionnaire_host.native import read_message, write_message, allowed_origin, MAX_FRAME
from questionnaire_host.private_store import protect

ROOT = Path(__file__).resolve().parents[2]
class MemoryStore:
    def __init__(self): self.data = {"credentials":{},"bindings":{}}
    def read(self): return self.data
    def write(self, value): self.data=value

def request(op, data=None, **kwargs):
    return {"id":str(uuid.uuid4()),"protocol":1,"fingerprint":CONTRACT["fingerprint"],"operation":op,"data":data or {},**kwargs}

def runtime(path, bindings=None):
    return RuntimeDeps(db_path=str(path),embedder=HashEmbedder(),bindings=bindings or {},adapters={"routine":demo_provider(),"advanced":demo_provider("fake-adv",diagnoser=True)})

@pytest.fixture
def service(tmp_path): return Service(tmp_path, runtime(tmp_path/'db.sqlite'),MemoryStore())

def event(session='s',type='prepare_form',revision=None,payload=None):
    return {"event_id":str(uuid.uuid4()),"session_id":session,"scope_id":SCOPE,"type":type,"expected_revision":revision,"payload":payload or {"questions":[{"id":"q","text":"What is your specialty?"}]}}

def call(s,e,authorized=False): return s.dispatch(request('event',{'event':e,'authorized':authorized}))

@pytest.mark.parametrize('fixture',['personal_application','org_questionnaire'])
def test_fixture_bridge_matches_engine(tmp_path,fixture):
    directory=ROOT/'fixtures'/fixture
    bindings=json.loads((directory/'bindings.json').read_text())
    app=Service(tmp_path/'host',runtime(tmp_path/'host.sqlite',bindings),MemoryStore())
    direct=Agent(runtime(tmp_path/'direct.sqlite',bindings))
    for repo in [app.repo(),Repository(direct.conn,SCOPE,direct.embedder,direct.store)]:
        ingest(repo,(directory/'knowledge.jsonl').read_text().splitlines())
    class Bridge:
        def handle_event(self,e):return call(app,e,e['type'] in ('generate_initial','regenerate_question'))
    steps=[json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
    baseline=run_script(direct,steps,SCOPE,'baseline',out=None)
    bridged=run_script(Bridge(),steps,SCOPE,'bridge',out=None)
    def summary(results):return [(r['status'],len(r['candidates']),{k:len(v) for k,v in r['cached'].items()},r['unresolved']) for r in results]
    assert summary(baseline)==summary(bridged)
    assert any(r['unresolved'] or r['status']=='partial' for r in bridged)

def test_native_frames_partial_reads_and_limits():
    stream=io.BytesIO();write_message(stream,{'text':'é🙂'});stream.seek(0)
    assert read_message(stream)=={'text':'é🙂'}
    assert read_message(stream) is None
    for data in [b'\x01',struct.pack('<I',MAX_FRAME+1),struct.pack('<I',0)]:
        with pytest.raises((ValueError,EOFError)):read_message(io.BytesIO(data))
    class Slow(io.BytesIO):
        def read(self,n=-1):return super().read(min(n,1))
    assert read_message(Slow(stream.getvalue()))=={'text':'é🙂'}

def test_reject_untrusted_origin():
    origin='chrome-extension://'+'a'*32+'/'
    assert allowed_origin(origin,[origin])
    assert not allowed_origin('https://evil.example/',[origin])
    assert not allowed_origin(origin+'extra',[origin])

def test_schema_and_auth(service):
    with pytest.raises(ValueError):service.dispatch(request('hello',fingerprint='stale'))
    with pytest.raises(ValueError):service.dispatch(request('hello',{'key':'hidden'}))
    e=event();r=call(service,e)
    with pytest.raises(ValueError):call(service,event(type='generate_initial',revision=r['revision'],payload={'target_question_ids':['q']}))
    invalid=event(payload={'questions':[],'key':'invalid'})
    with pytest.raises(ValueError):call(service,invalid)
    e['scope_id']='other'
    with pytest.raises(ValueError):call(service,e)

def test_no_paid_calls_and_replay(service):
    e=event();r=call(service,e)
    cached=event(type='get_candidate',revision=r['revision'],payload={'question_id':'q'})
    assert call(service,cached)['status']=='partial'
    assert call(service,e)==r
    service.dispatch(request('search',{'query':'specialty'}))
    assert service.engine().rt.adapters['routine'].calls==[]

def test_private_text_blocked_before_persistence(service):
    service.engine().rt.bindings={'secret':'Private sentence never leaves'}
    with pytest.raises(ValueError):call(service,event(payload={'questions':[{'id':'q','text':'Private sentence never leaves'}]}))
    assert service.repo().session('s') is None
    preview=service.dispatch(request('render',{'body':'{{secret}}','constraints':{'max_length':3}}))
    assert preview['problems']
    assert service.dispatch(request('render',{'body':'{{missing}}'}))['text'] is None

def test_no_provider_saved_answer_roundtrip(service):
    record={'kind':'template','id':'T_test','intent':'specialty','aliases':['What is your specialty?'],'body':'My synthetic specialty is testing.','disclosure':'local_only','approved_by':'user','approved_at':'2026-09-22'}
    service.dispatch(request('ingest',{'record':record}))
    result=service.dispatch(request('search',{'query':'What is your specialty?'}))
    assert result['matches'][0]['body']==record['body']
    assert result['complete'] is False and result['autofillEligible'] is False
    assert service.engine().rt.adapters['routine'].calls==[]
    with pytest.raises(ValueError):service.dispatch(request('ingest',{'record':record}))

def test_change_requires_new_session(service):
    r=call(service,event())
    service.dispatch(request('ingest',{'record':{'kind':'variable','id':'v','safe_description':'description'}}))
    with pytest.raises(ValueError):call(service,event(type='get_candidate',revision=r['revision'],payload={'question_id':'q'}))
    assert call(service,event(session='fresh'))['status']=='ready'

def test_epoch_reconnect_retains_sessions(tmp_path):
    store=MemoryStore();a=Service(tmp_path,runtime(tmp_path/'a.db'),store)
    e=event();result=call(a,e)
    b=Service(tmp_path,runtime(tmp_path/'a.db'),store)
    assert call(b,e)==result
    assert call(b,event(type='get_candidate',revision=result['revision'],payload={'question_id':'q'}))['status']=='partial'

def test_non_windows_no_plaintext_fallback():
    import os
    if os.name!='nt':
        with pytest.raises(RuntimeError):protect(b'secret')

def test_old_prepare_cannot_bypass_dependency_invalidation(service):
    original=event();call(service,original)
    service.dispatch(request('ingest',{'record':{'kind':'variable','id':'v','safe_description':'safe'}}))
    with pytest.raises(ValueError):call(service,original)

def test_budget_exhaustion_keeps_cache_available(service):
    service.dispatch(request('ingest',{'record':{'kind':'template','id':'T','intent':'specialty','aliases':['What is your specialty?'],'body':'I test software.','disclosure':'model_visible','approved_by':'user','approved_at':'2026-09-22'}}))
    r=call(service,event())
    denied=call(service,event(type='generate_initial',revision=r['revision'],payload={'target_question_ids':['q'],'limits':{'max_cost_usd':0}}),True)
    assert denied['status']=='budget_exhausted'
    assert service.engine().rt.adapters['routine'].calls==[]
    assert call(service,event(type='get_candidate',revision=r['revision'],payload={'question_id':'q'}))['status']=='partial'

def test_stale_revision_does_not_generate(service):
    call(service,event())
    result=call(service,event(type='generate_initial',revision='stale',payload={'target_question_ids':['q']}),True)
    assert result['status']=='stale_context'
    assert service.engine().rt.adapters['routine'].calls==[]
