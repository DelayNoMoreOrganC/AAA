"""Disk budget and stub transport protocols, not model/case accuracy evidence."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from recognition_journal import RecognitionJournal, RecognitionJournalError
from model_request_budget import TaskRequestBudget


class Transport:
    def __init__(self,fail=False): self.calls=0;self.metrics={};self.fail=fail
    def complete(self,messages):
        self.calls+=1
        if self.fail: raise TimeoutError('private transport detail')
        return {'ok':True}


def client(root, *, limit=2, scope='classification', retry=None, transport=None):
    budget=TaskRequestBudget(root/'model-budget',scope={'task_id':1,'org_id':'org'},
        limit=limit,journal_directory=root/'recognition-journal')
    transport=transport or Transport()
    wrapped=RecognitionJournal(root/'recognition-journal').wrap(transport,
        scope={'phase':scope},retry_token=retry,request_budget=budget)
    return wrapped,transport


def test_total_limit_spans_classification_fields_writing_and_cache_replay(tmp_path):
    first,transport=client(tmp_path);first.complete([{'content':'one'}]);assert transport.calls==1
    restored,replay=client(tmp_path);restored.complete([{'content':'one'}]);assert replay.calls==0
    second,transport=client(tmp_path,scope='fields');second.complete([{'content':'two'}])
    assert transport.calls==1 and second.metrics['task_request_budget']['reserved_requests']==2
    third,transport=client(tmp_path,scope='writing')
    with pytest.raises(RecognitionJournalError,match='额度已用尽') as e: third.complete([{'content':'three'}])
    assert e.value.code=='REQUEST_BUDGET_EXHAUSTED' and transport.calls==0
    assert not list((tmp_path/'recognition-journal'/third.scope_sha256).glob('r-*.json'))


def test_timeout_consumes_slot_and_retry_token_does_not_replenish(tmp_path):
    first,transport=client(tmp_path,limit=1,transport=Transport(fail=True))
    with pytest.raises(RecognitionJournalError) as e:first.complete([{'content':'one'}])
    assert e.value.code=='REQUEST_UNCERTAIN' and transport.calls==1
    retried,transport=client(tmp_path,limit=1,retry='a'*32)
    with pytest.raises(RecognitionJournalError) as e:retried.complete([{'content':'one'}])
    assert e.value.code=='REQUEST_BUDGET_EXHAUSTED' and transport.calls==0


@pytest.mark.parametrize('change',['delete','corrupt','limit','scope'])
def test_missing_or_changed_frozen_counter_fails_closed(tmp_path,change):
    first,_=client(tmp_path);first.complete([{'content':'one'}])
    path=tmp_path/'model-budget'/'budget.json'
    if change=='delete':path.unlink()
    if change=='corrupt':path.write_text('{}',encoding='utf-8')
    second,transport=client(tmp_path,scope='fields',limit=3 if change=='limit' else 2)
    if change=='scope':second._request_budget.identity['scope_sha256']='f'*64
    with pytest.raises(RecognitionJournalError) as e:second.complete([{'content':'two'}])
    assert e.value.code=='RECORD_INVALID' and transport.calls==0


def test_no_configured_ceiling_counts_without_inventing_a_user_limit(tmp_path):
    first,_=client(tmp_path,limit=None)
    for n in range(3):first.complete([{'content':str(n)}])
    assert first.metrics['task_request_budget']['reserved_requests']==3
    assert first.metrics['task_request_budget']['max_requests'] is None
    saved=json.loads((tmp_path/'model-budget'/'budget.json').read_text())
    assert set(saved['payload'])=={'version','scope_sha256','max_requests','reserved_requests'}


def test_parallel_scopes_cannot_spend_the_same_last_slot(tmp_path):
    # OS lock contention may reject one dispatcher before the budget check.
    def call(scope):
        wrapper,transport=client(tmp_path,limit=1,scope=scope)
        try:wrapper.complete([{'content':scope}])
        except RecognitionJournalError as e:assert e.code in ('LOCKED','REQUEST_BUDGET_EXHAUSTED')
        return transport.calls
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(call,['classification','fields']))==1


def test_budget_storage_failure_stops_before_transport(tmp_path,monkeypatch):
    import model_request_budget as module
    def failed(*args):raise RecognitionJournalError('WRITE_FAILED')
    monkeypatch.setattr(module,'_atomic_write',failed)
    wrapper,transport=client(tmp_path)
    with pytest.raises(RecognitionJournalError) as error:wrapper.complete([{'content':'one'}])
    assert error.value.code=='WRITE_FAILED' and transport.calls==0


def test_zero_limit_prevents_first_dispatch(tmp_path):
    wrapper,transport=client(tmp_path,limit=0)
    with pytest.raises(RecognitionJournalError) as error:wrapper.complete([{'content':'one'}])
    assert error.value.code=='REQUEST_BUDGET_EXHAUSTED' and transport.calls==0


def test_twenty_dispatch_ceiling_includes_failure_and_survives_restart(tmp_path):
    total=0
    # Each new wrapper simulates a recreated provider/journal after a restart.
    for number in range(19):
        wrapper,transport=client(tmp_path,limit=20,scope=['classification','fields','writing'][number%3])
        wrapper.complete([{'content':str(number)}]);total+=transport.calls
    first,transport=client(tmp_path,limit=20,transport=Transport(fail=True))
    message=[{'content':'classification failed transport'}]
    with pytest.raises(RecognitionJournalError):first.complete(message)
    total+=transport.calls
    assert total==20
    replay,transport=client(tmp_path,limit=20,scope='writing')
    replay.complete([{'content':'17'}])
    assert transport.calls==0  # Completed work is still readable at the cap.
    retry,transport=client(tmp_path,limit=20,retry='b'*32)
    with pytest.raises(RecognitionJournalError) as error:retry.complete(message)
    assert error.value.code=='REQUEST_BUDGET_EXHAUSTED' and transport.calls==0
    assert retry.metrics['task_request_budget']['reserved_requests']==20


def test_preserved_slots_are_atomic_and_remain_available_for_writing(tmp_path):
    wrapper,transport=client(tmp_path,limit=4)
    for n in range(2):wrapper.complete_preserving([{'content':str(n)}],preserve_requests=2)
    with pytest.raises(RecognitionJournalError) as error:
        wrapper.complete_preserving([{'content':'third extraction'}],preserve_requests=2)
    assert error.value.code=='REQUEST_BUDGET_RESERVED' and transport.calls==2
    assert wrapper.metrics['task_request_budget']['reserved_requests']==2
    # Cached first/second responses still replay with only the reserved slots left.
    replay,replayed=client(tmp_path,limit=4)
    for n in range(2):replay.complete_preserving([{'content':str(n)}],preserve_requests=2)
    assert replayed.calls==0
    writer,model=client(tmp_path,limit=4,scope='writing')
    writer.complete([{'content':'write'}]);writer.complete([{'content':'review'}])
    assert model.calls==2 and writer.metrics['task_request_budget']['reserved_requests']==4
    with pytest.raises(RecognitionJournalError) as error:writer.complete([{'content':'extra'}])
    assert error.value.code=='REQUEST_BUDGET_EXHAUSTED' and model.calls==2


@pytest.mark.parametrize('limit',[None,2])
def test_reserve_does_not_invent_a_cap_or_change_tiny_explicit_budget(tmp_path,limit):
    wrapper,transport=client(tmp_path,limit=limit)
    wrapper.complete_preserving([{'content':'extract'}],preserve_requests=2)
    assert transport.calls==1


def test_preserved_slots_remain_protected_between_competing_scopes(tmp_path):
    def call(scope):
        wrapper,transport=client(tmp_path,limit=4,scope=scope)
        for n in range(3):
            try:wrapper.complete_preserving([{'content':str(n)}],preserve_requests=2)
            except RecognitionJournalError as error:
                assert error.code in ('LOCKED','REQUEST_BUDGET_RESERVED')
                break
        return transport.calls
    with ThreadPoolExecutor(max_workers=2) as pool:assert sum(pool.map(call,['a','b']))==2
    writer,_=client(tmp_path,limit=4,scope='writing')
    writer.complete([{'content':'write'}]);writer.complete([{'content':'review'}])
    assert writer.metrics['task_request_budget']['reserved_requests']==4


@pytest.mark.parametrize('limit',[True,-1,1.5,'2',100001])
def test_invalid_limits_rejected(tmp_path,limit):
    with pytest.raises(RecognitionJournalError):client(tmp_path,limit=limit)
