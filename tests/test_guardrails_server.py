import json

from fastapi.testclient import TestClient

from stamina.guardrails import filter_claims, explain_plan
from stamina.planner import build_plan, candidates, items_from
from stamina.server import app


def test_guard_removes_unsupported():
    clean,removed=filter_claims('景色优美。有电梯！提供无障碍和轮椅。可乘观光车。搭索道。','景色优美。','示例')
    assert clean=='景色优美。'
    assert len(removed)==4


def test_guard_preserves_source_term():
    clean,removed=filter_claims('有电梯。提供轮椅。','电梯','示例')
    assert clean=='有电梯。'
    assert len(removed)==1


def test_guard_removes_unverified_physical_claims():
    clean,removed=filter_claims('道路平坦。设有休息区域。估算步数在上限内。','景点简介','示例')
    assert clean=='估算步数在上限内。'
    assert len(removed)==2


def test_explanation_guard_records(profile,raw_pois,raw_hotels):
    plan=build_plan(profile,candidates(raw_pois)[:24],items_from(raw_hotels))
    poi=plan['stamina'][0]['pois'][0]
    result=json.dumps({'explanations':[{'poi':poi['name'],'text':'有电梯和无障碍。安排较少步行。'}]})
    explain_plan(plan,lambda m:result)
    assert plan['removed_claims']
    assert plan['explanation'][0]['text']=='安排较少步行。'


def test_api_success_and_validation(monkeypatch,profile,raw_pois,raw_hotels):
    import stamina.server as server
    expected=build_plan(profile,candidates(raw_pois)[:5],items_from(raw_hotels))
    monkeypatch.setattr(server,'create_plan',lambda q:expected)
    with TestClient(app) as client:
        response=client.post('/plan',json={'query':'杭州'})
        assert response.status_code==200 and response.json()==expected
        assert client.post('/plan',json={'query':''}).status_code==422


def test_api_upstream_failure(monkeypatch):
    import stamina.server as server
    def fail(q):
        raise RuntimeError('private provider error')
    monkeypatch.setattr(server,'create_plan',fail)
    with TestClient(app) as client:
        response=client.post('/plan',json={'query':'杭州'})
        assert response.status_code==503
        assert 'private' not in response.text
