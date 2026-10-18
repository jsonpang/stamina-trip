import json

from stamina import cli
from stamina.guardrails import explain_plan


def test_cli_offline_end_to_end(monkeypatch,tmp_path,profile,raw_pois,raw_hotels):
    responses=iter(raw_pois)
    monkeypatch.setattr('stamina.flyai.search_poi',lambda *a,**k:next(responses))
    monkeypatch.setattr('stamina.flyai.search_hotel',lambda *a,**k:raw_hotels)
    monkeypatch.setattr(cli,'parse_profile',lambda q:profile)
    monkeypatch.setattr(cli,'explain_plan',lambda p:explain_plan(p,lambda m:'{"explanations":[]}'))
    monkeypatch.setattr(cli,'ROOT',tmp_path)
    monkeypatch.setattr('sys.argv',['stamina.cli','杭州'])
    assert cli.main()==0
    plan=json.loads((tmp_path/'out'/'plan.json').read_text(encoding='utf-8'))
    assert all(day['total_steps']<=6000 for day in plan['stamina'])
    assert '体力账单' in (tmp_path/'out'/'plan.md').read_text(encoding='utf-8')
