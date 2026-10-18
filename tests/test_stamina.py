import math

import pytest

from stamina.stamina import distance_m, walking_steps, stride_m, poi_steps, stair_risk, transfer, bill_day


def test_distance_and_stride(profile, raw_pois):
    a,b = raw_pois[0]['data']['itemList'][:2]
    lat1,lat2 = map(math.radians,[float(a['latitude']),float(b['latitude'])])
    dlon = math.radians(float(b['longitude'])-float(a['longitude']))
    expected = 6371000*math.acos(math.sin(lat1)*math.sin(lat2)+math.cos(lat1)*math.cos(lat2)*math.cos(dlon))*1.3
    assert distance_m(a,b) == pytest.approx(expected,abs=0.01)
    assert distance_m(a,a) == 0
    assert stride_m(profile['travelers']) == 0.45
    assert walking_steps(450,profile['travelers']) == 1000


def test_taxi_threshold(profile, raw_pois):
    a,b = raw_pois[0]['data']['itemList'][:2]
    assert distance_m(a,b)>800
    assert transfer(a,b,profile['travelers'])['mode']=='打车'
    assert transfer(a,b,profile['travelers'])['steps']==200
    assert transfer(a,a,profile['travelers'])['mode']=='步行'


def test_category_and_stairs(raw_pois):
    poi = raw_pois[0]['data']['itemList'][0]
    assert poi_steps(poi)==3000
    assert stair_risk(poi)=='可能有台阶（未核实）'
    boat = next(p for p in raw_pois[1]['data']['itemList'] if '游船' in p['name'])
    assert poi_steps(boat)==300


def test_threshold_boundaries(monkeypatch, profile, raw_pois):
    a,b=raw_pois[0]['data']['itemList'][:2]
    monkeypatch.setattr('stamina.stamina.distance_m',lambda a,b:800)
    assert transfer(a,b,profile['travelers'])['mode']=='步行'
    monkeypatch.setattr('stamina.stamina.distance_m',lambda a,b:800.01)
    assert transfer(a,b,profile['travelers'])['mode']=='打车'
    monkeypatch.setattr('stamina.stamina.distance_m',lambda a,b:2000)
    assert transfer(a,b,profile['travelers'],2000,True)['mode']=='打车'


def test_noon_hotel_or_local(profile, raw_pois, raw_hotels):
    hotels = raw_hotels['data']['itemList']
    pois = [p for result in raw_pois for p in result['data']['itemList']]
    poi,close = min(((p,h) for p in pois for h in hotels),key=lambda pair:distance_m(*pair))
    assert distance_m(poi,close)<=5000
    day = bill_day(profile['dates'][0],[poi],profile,close)
    assert any(r['name']=='午间回酒店休息' for r in day['bill'])
    far_poi = max(raw_pois[0]['data']['itemList'],key=lambda x:distance_m(x,close))
    assert distance_m(far_poi,close)>5000
    day = bill_day(profile['dates'][0],[far_poi],profile,close)
    assert any('就近休息' in r['name'] for r in day['bill'])
    profile['need_noon_rest']=False
    assert not any(r['kind']=='rest' for r in bill_day(profile['dates'][0],[poi],profile,close)['bill'])
