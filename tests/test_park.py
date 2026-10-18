import json

import pytest

from stamina import agent
from stamina.stamina import bill_park_day, park_item_kind
from stamina.tools import Session, ToolError


def item(id, name, lat, lon, category=None):
    return dict(id=id, name=name, category=category, latitude=str(lat), longitude=str(lon), description='')


PARK = item('p', '上海迪士尼度假区', 31.1414, 121.6670, '主题乐园')
ITEMS = [item('a', '七个小矮人矿山车', 31.1440, 121.6580), item('b', '华特迪士尼大剧院', 31.1409, 121.6610, '剧院剧场'),
         item('c', '梦幻世界', 31.1447, 121.6600, '公园乐园'), item('d', '小熊维尼历险记', 31.1445, 121.6590)]
FAR = item('z', '上海野生动物园', 31.0560, 121.7230, '动物园')
HOTEL = dict(id='h', name='园外民宿', latitude='31.1300', longitude='121.6700', price='¥120')
ONSITE = dict(id='o', name='乐园自营酒店', latitude='31.1420', longitude='121.6640', price='¥3800')


def result(items):
    return dict(status=0, data=dict(itemList=items))


@pytest.fixture
def park_search():
    calls = []
    def search_poi(city, keyword=None, category=None):
        calls.append(keyword)
        if keyword == '上海迪士尼':
            return result([PARK, ITEMS[2]])
        hits = [i for i in ITEMS + [FAR] if i['name'] == keyword]
        return result(hits) if hits else dict(status=-1, error='no json')
    def search_hotel(city, **kwargs):
        calls.append(kwargs)
        if kwargs.get('key_words'):
            return result([dict(ONSITE, shId='o')])
        return result([dict(HOTEL, shId='h')])
    search_poi.calls = calls
    return search_poi, search_hotel


def test_item_kinds():
    assert [park_item_kind(i) for i in ITEMS] == ['ride', 'show', 'area', 'ride']


def test_park_day_walks_inside_and_flags_height(profile):
    day = bill_park_day(profile['dates'][0], PARK, ITEMS, profile, HOTEL)
    inside = day['bill'][1:-1]  # 首尾是酒店往返
    assert all(r['mode'] != '打车' for r in inside)
    assert any(r['mode'] == '园内步行' for r in inside)
    show = next(r for r in day['bill'] if r['name'] == '华特迪士尼大剧院')
    assert show['seated'] and show['mode'] == '坐着看演出'
    coaster = next(r for r in day['bill'] if r['name'] == '七个小矮人矿山车')
    assert '身高限制' in coaster['risk']
    kinds = [r['kind'] for r in day['bill']]
    rest = kinds.index('rest')
    assert 0 < rest and 'visit' in kinds[rest:]  # 午休后面还有项目
    assert day['park'] == '上海迪士尼度假区'
    profile['travelers'] = [dict(age=35, mobility='normal')]
    day = bill_park_day(profile['dates'][0], PARK, ITEMS, profile, HOTEL)
    assert '身高限制' not in next(r for r in day['bill'] if r['name'] == '七个小矮人矿山车')['risk']


def test_search_park_items_keeps_only_in_park(profile, park_search):
    search_poi, search_hotel = park_search
    s = Session(profile, search_poi, search_hotel)
    out = s.search_park_items('上海迪士尼', [i['name'] for i in ITEMS] + ['上海野生动物园', '不存在的项目'])
    names = [i['name'] for i in out['items']]
    assert out['park']['name'] == '上海迪士尼度假区'
    assert set(names) == {i['name'] for i in ITEMS}  # 野生动物园在 2.5 km 外，查无此项的跳过
    assert all(s.park_of[i['id']] == 'p' for i in ITEMS)


def test_mixed_park_and_city_day_rejected(profile, park_search):
    search_poi, search_hotel = park_search
    s = Session(profile, search_poi, search_hotel)
    s.search_park_items('上海迪士尼', ['七个小矮人矿山车'])
    s.register(FAR)
    with pytest.raises(ToolError, match='混排'):
        s.compute(days=[['a', 'z'], []])


def test_agent_plans_park_days(profile, park_search):
    search_poi, search_hotel = park_search
    profile['daily_step_cap'] = 12000
    def call(name, i, **args):
        return dict(id=f'c{i}', name=name, arguments=json.dumps(args, ensure_ascii=False))
    days = [['c', 'b', 'a'], ['d']]
    turns = iter([[call('search_park_items', 1, park_name='上海迪士尼', item_names=[i['name'] for i in ITEMS])],
                  [call('search_hotel', 2, poi_name='上海迪士尼度假区'),
                   call('search_hotel', 3, key_words='上海迪士尼乐园酒店')],
                  [call('finalize', 3, days=days, hotel_id='h')]])
    plan = agent.agent_plan('迪士尼', profile, lambda m: dict(content='', tool_calls=next(turns)), search_poi, search_hotel)
    assert plan['mode'] == 'agent'
    assert all(d['park'] == '上海迪士尼度假区' for d in plan['stamina'])
    assert any(r['mode'] == '坐着看演出' for r in plan['stamina'][0]['bill'])
    # 普通版乐园日：按返回顺序排园内项目，不午休
    assert plan['ordinary'][0]['park'] == '上海迪士尼度假区'
    assert not any(r['kind'] == 'rest' for r in plan['ordinary'][0]['bill'])
    assert len(plan['ordinary'][0]['pois']) == len(ITEMS)
    # 同一行程换酒店重算：已选民宿和自营酒店都在，步数来自各自的真实账单
    compare = {h['name']: h for h in plan['hotel_compare']}
    assert compare['园外民宿']['chosen'] and not compare['乐园自营酒店']['chosen']
    assert compare['乐园自营酒店']['price'] == '¥3800'
    near = agent.bill_park_day(profile['dates'][0], PARK, plan['stamina'][0]['pois'], profile, ONSITE)
    assert compare['乐园自营酒店']['days'][0]['total_steps'] == near['total_steps']
    assert compare['乐园自营酒店']['distance_m'] < compare['园外民宿']['distance_m']
    assert {'key_words': '上海迪士尼乐园酒店'}.items() <= next(c for c in search_poi.calls if isinstance(c, dict) and 'key_words' in c).items()
    assert any('直通卡' in w for w in plan['warnings'])
