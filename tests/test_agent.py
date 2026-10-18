import json

import pytest

from stamina import agent
from stamina.render import markdown

GOOD_DAYS = [['2267'], ['14761420']]  # 孤山馆区 / 杭州博物馆
HOTEL = '58674065'


@pytest.fixture
def searches(raw_pois, raw_hotels):
    by_query = {None: raw_pois[0], '城市观光': raw_pois[1], '博物馆': raw_pois[2], '游船': raw_pois[3]}
    calls = []
    def search_poi(city, keyword=None, category=None):
        calls.append(('poi', city, keyword, category))
        return by_query.get(category or keyword, raw_pois[0])
    def search_hotel(city, **kwargs):
        calls.append(('hotel', city, kwargs))
        return raw_hotels
    return search_poi, search_hotel, calls


def call(name, i, **args):
    return dict(id=f'c{i}', name=name, arguments=json.dumps(args, ensure_ascii=False))


def scripted(*turns):
    """Fake model: each turn is a list of tool calls; records the messages it saw."""
    seen = []
    replies = iter(turns)
    def complete(messages):
        seen.append(list(messages))
        return dict(content='', tool_calls=next(replies))
    complete.seen = seen
    return complete


def happy_turns(final_args=None):
    return ([call('search_poi', 1, category='博物馆'), call('search_poi', 2, keyword='游船')],
            [call('search_hotel', 3, poi_name='西湖游船')],
            [call('compute_stamina', 4, days=GOOD_DAYS, hotel_id=HOTEL)],
            [call('finalize', 5, **(final_args or dict(days=GOOD_DAYS, hotel_id=HOTEL)))])


def test_agent_finalizes_with_recomputed_steps(profile, searches):
    search_poi, search_hotel, calls = searches
    complete = scripted(*happy_turns())
    plan = agent.agent_plan('孩子想看展', profile, complete, search_poi, search_hotel)
    assert plan['mode'] == 'agent'
    assert [p['id'] for p in plan['stamina'][0]['pois']] == GOOD_DAYS[0]
    assert plan['hotel']['name'] == '杭州他她它民宿(西湖太子湾店)'
    assert all(d['total_steps'] <= 6000 for d in plan['stamina'])
    assert [t['tool'] for t in plan['tool_trace']] == ['search_poi', 'search_poi', 'search_hotel',
                                                       'compute_stamina', 'finalize']
    assert plan['tool_trace'][-1]['ok'] is True
    # 酒店搜索的日期和预算来自画像，不由模型填写。
    hotel_call = [c for c in calls if c[0] == 'hotel'][0][2]
    assert hotel_call['check_in_date'] == '2026-11-07' and hotel_call['check_out_date'] == '2026-11-08'
    # compute_stamina 的真实账单回传给了模型。
    tool_msgs = [m for m in complete.seen[-1] if m['role'] == 'tool']
    assert '累计' in tool_msgs[-1]['content']
    assert '智能体决策过程' in markdown(plan)
    assert len(plan['ordinary']) == 2


def test_finalize_rejects_day_without_noon_rest(profile, searches):
    search_poi, search_hotel, _ = searches
    no_rest = [['203005', '2267'], ['14761420']]  # 游船只有约 500 步，孤山馆区是最后一站：排不进午休
    turns = happy_turns(dict(days=no_rest, hotel_id=HOTEL)) + ([call('finalize', 6, days=GOOD_DAYS, hotel_id=HOTEL)],)
    plan = agent.agent_plan('q', profile, scripted(*turns), search_poi, search_hotel)
    assert '午休' in plan['tool_trace'][-2]['error']
    assert plan['mode'] == 'agent'


def test_model_reported_steps_are_ignored(profile, searches):
    search_poi, search_hotel, _ = searches
    lying = dict(days=GOOD_DAYS, hotel_id=HOTEL, total_steps=100)  # extra arg: rejected, not trusted
    turns = happy_turns(lying) + ([call('finalize', 6, days=GOOD_DAYS, hotel_id=HOTEL)],)
    plan = agent.agent_plan('q', profile, scripted(*turns), search_poi, search_hotel)
    assert plan['mode'] == 'agent'
    assert 'error' in plan['tool_trace'][-2]
    assert all(d['total_steps'] != 100 and d['total_steps'] > 1000 for d in plan['stamina'])
    assert plan['stamina'][0]['total_steps'] == sum(r['steps'] for r in plan['stamina'][0]['bill'])


def test_over_cap_finalize_is_rejected_then_fixed(profile, searches):
    search_poi, search_hotel, _ = searches
    heavy = [['14761420', '184887029', '2398'], ['2267']]
    turns = happy_turns(dict(days=heavy, hotel_id=HOTEL)) + ([call('finalize', 6, days=GOOD_DAYS, hotel_id=HOTEL)],)
    plan = agent.agent_plan('q', profile, scripted(*turns), search_poi, search_hotel)
    assert '超过上限' in plan['tool_trace'][-2]['error']
    assert plan['mode'] == 'agent'


def test_unknown_id_is_rejected(profile, searches):
    search_poi, search_hotel, _ = searches
    turns = happy_turns(dict(days=[['made-up'], []])) + ([call('finalize', 6, days=GOOD_DAYS, hotel_id=HOTEL)],)
    plan = agent.agent_plan('q', profile, scripted(*turns), search_poi, search_hotel)
    assert '未知景点' in plan['tool_trace'][-2]['error']


def test_turn_limit_falls_back(profile, searches, monkeypatch):
    search_poi, search_hotel, _ = searches
    monkeypatch.setattr(agent, 'MAX_TURNS', 3)  # read at call time
    forever = [[call('search_poi', i, category='博物馆')] for i in range(20)]
    plan = agent.agent_plan('q', profile, scripted(*forever), search_poi, search_hotel)
    assert plan['mode'] == 'fallback'
    assert '轮内' in plan['fallback_reason']
    assert plan['tool_trace']  # partial trace is kept
    assert all(d['total_steps'] <= 6000 for d in plan['stamina'])
    assert '确定性规划兜底' in markdown(plan)


def test_model_error_falls_back_without_leaking(profile, searches):
    search_poi, search_hotel, _ = searches
    def broken(messages):
        raise ConnectionError('Authorization: Bearer secret')
    plan = agent.agent_plan('q', profile, broken, search_poi, search_hotel)
    assert plan['mode'] == 'fallback'
    assert 'secret' not in plan['fallback_reason']


def test_taxi_over_budget_finalize_rejected(profile, searches, raw_pois):
    search_poi, search_hotel, _ = searches
    # 良渚博物院在城北约 20 km 外：和西湖边的点同一天，打车往返超预算。
    far_day = [['2398', '2267'], ['14761420']]
    profile['daily_step_cap'] = 20000
    turns = happy_turns(dict(days=far_day, hotel_id=HOTEL)) + ([call('finalize', 6, days=GOOD_DAYS, hotel_id=HOTEL)],)
    plan = agent.agent_plan('q', profile, scripted(*turns), search_poi, search_hotel)
    assert '打车' in plan['tool_trace'][-2]['error']


def test_free_text_category_becomes_keyword(profile, searches):
    search_poi, search_hotel, calls = searches
    from stamina.tools import Session
    Session(profile, search_poi, search_hotel).search_poi(category='看动物')
    Session(profile, search_poi, search_hotel).search_poi(category='动物园', keyword='杭州')
    assert calls[0] == ('poi', '杭州', '看动物', None)
    assert calls[1] == ('poi', '杭州', '杭州', '动物园')


def test_ordinary_skips_sub_areas():
    pois = [dict(name='杭州动物园'), dict(name='杭州动物园-虎山'), dict(name='西湖游船'),
            dict(name='西湖游船涌金池码头'), dict(name='西湖外事游船'), dict(name='杭州博物馆')]
    assert [p['name'] for p in agent.main_pois(pois)] == ['杭州动物园', '西湖游船', '杭州博物馆']
