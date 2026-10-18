from stamina.planner import candidates, build_plan, collect_and_plan, choose_hotel, items_from, best_day
from stamina.render import markdown, json_text
from stamina.stamina import distance_m
import json
import pytest


def test_budget_and_bills(profile, raw_pois, raw_hotels):
    plan = build_plan(profile,candidates(raw_pois)[:24],items_from(raw_hotels))
    assert len(plan['stamina'])==2
    for day in plan['stamina']:
        assert day['pois']
        assert len(day['pois'])<=3
        assert day['total_steps']<=6000
        assert sum(r['steps'] for r in day['bill'])==day['total_steps']
        assert day['bill'][-1]['cumulative_steps']==day['total_steps']
        assert any(r['kind']=='rest' for r in day['bill'])
        assert all(r['mode']=='打车' for r in day['bill'] if r['kind']=='transfer' and r['distance_m']>800)
    assert all(d['total_steps']>6000 for d in plan['ordinary'])
    selected = [p['name'] for d in plan['stamina'] for p in d['pois']]
    assert len(set(selected))==len(selected)
    text=markdown(plan)
    assert 'color:red' in text and '估算' in text and '飞猪预订' in text
    assert json.loads(json_text(plan))['stamina']==plan['stamina']


def test_hotel_budget(profile, raw_pois, raw_hotels):
    pois=candidates(raw_pois)[:2]
    assert choose_hotel(items_from(raw_hotels),pois,1) is None
    hotel=choose_hotel(items_from(raw_hotels),pois,None)
    assert hotel['price'] and hotel['centroid_distance_m']>=0
    assert '估算' in hotel['reason']


def test_search_anchor_and_hints(profile,raw_pois,raw_hotels):
    calls=[]
    responses=iter(raw_pois)
    def hotels(*args,**kwargs):
        calls.append(kwargs)
        return raw_hotels
    plan=collect_and_plan(profile,lambda *a,**k:next(responses),hotels)
    assert calls[0]['poi_name']==plan['stamina'][0]['pois'][0]['name']
    assert calls[0]['check_out_date']==profile['dates'][-1]
    expected=list(dict.fromkeys(r['systemMessage'] for r in raw_pois+[raw_hotels] if r.get('systemMessage')))
    assert plan['system_messages']==expected
    plan['system_messages']=['测试平台提示']
    assert markdown(plan).rstrip().endswith('测试平台提示')


def test_tiny_budget_is_not_padded(profile,raw_pois,raw_hotels):
    profile['daily_step_cap']=1
    plan=build_plan(profile,candidates(raw_pois)[:5],items_from(raw_hotels))
    assert all(d['total_steps']==0 and not d['pois'] for d in plan['stamina'])
    assert plan['warnings']


def test_missing_coordinates_are_rejected(raw_pois):
    data=raw_pois[0]
    for item in data['data']['itemList']:
        item.pop('latitude',None)
    with pytest.raises(ValueError,match='坐标'):
        candidates([data])


def test_night_tour_after_daytime(profile, raw_pois, raw_hotels):
    plan=build_plan(profile,candidates(raw_pois)[:24],items_from(raw_hotels))
    for day in plan['stamina']:
        assert not any('夜游' in p['name'] for p in day['pois'][:-1])


def test_limited_demotes_stairs(profile,raw_pois):
    risky=dict(raw_pois[0]['data']['itemList'][0], source_order=0)
    safe=dict(raw_pois[2]['data']['itemList'][0], source_order=1)
    profile.update(daily_step_cap=3000, need_noon_rest=False)
    assert best_day(profile['dates'][0],[risky,safe],profile)['pois'][0]['name']==safe['name']
    profile['travelers']=[dict(age=35,mobility='normal')]
    assert best_day(profile['dates'][0],[risky,safe],profile)['pois'][0]['name']==risky['name']
