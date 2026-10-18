"""Tool-calling planning loop.

The model decides what to search and which stops to try; every step count comes
from compute_stamina, and the finalized route is billed again here before it
reaches the plan. Any failure falls back to the deterministic planner.
"""
import datetime as dt
import json

from .planner import collect_and_plan, choose_hotel, ordinary_days, plan_warnings
from .planner import price_value
from .stamina import bill_park_day, distance_m, is_boat, DETOUR_FACTOR
from .tools import SPECS, Session, ToolError

MAX_TURNS = 12

SYSTEM = '''你是体力预算规划师。按同行人走得动多少来排行程。
做法：先按用户偏好用 search_poi 搜景点（偏好如看动物、看展、坐船，各搜一次），再用 search_hotel 找第一天主要景点附近的酒店，
然后用 compute_stamina 试算，超上限或打车超 20 公里就换点或减点再算，满意后调用 finalize。
规则：每天的步数、是否超限只看 compute_stamina 返回值，不要自己估算；只能使用工具返回的 id；
compute_stamina 的 verdict 写明是否通过：通过就用完全相同的参数立刻调用 finalize，不要再换点或重算；
行动受限的同行人尽量避开标了台阶风险的景点；每天 1–3 个景点，夜游放在当天最后；不要安排重复景点。
需要午休时：午休自动插在累计步数达上限 35% 或走完 2 个点之后，且后面还得有景点，所以一天 2–3 个点时把步数多的点放前面。
去主题乐园（如迪士尼）时：用 search_park_items 给出乐园名和你知道的园内项目、园区、演出名（8–15 个），只用它返回的项目；乐园那天只排园内项目（每天 4–8 个，按位置顺路排），项目之间按步行计算；演出是坐着看的，适合穿插在走路多的项目之间；标了身高限制风险的项目要提醒，不要替用户断定能不能玩；酒店搜两次：search_hotel(poi_name=乐园名) 找附近的，search_hotel(key_words=乐园名+酒店) 找乐园自营酒店，系统会自动对比两类酒店对步数的影响。
画像：{profile}
用户原话：{query}'''


class AgentFailed(RuntimeError):
    pass


def openai_complete():
    from .llm import client_and_model
    client, model = client_and_model()
    def complete(messages):
        message = client.chat.completions.create(model=model, messages=messages, tools=SPECS,
                                                 tool_choice='auto', temperature=0).choices[0].message
        return dict(content=message.content or '',
                    tool_calls=[dict(id=c.id, name=c.function.name, arguments=c.function.arguments)
                                for c in message.tool_calls or []])
    return complete


def run_agent(query, profile, complete=None, search_poi=None, search_hotel=None, max_turns=None, trace=None):
    """Returns the finalized session; appends each tool call to `trace`. Raises AgentFailed otherwise."""
    max_turns = max_turns or MAX_TURNS
    session = Session(profile, search_poi, search_hotel)
    trace = [] if trace is None else trace
    complete = complete or openai_complete()
    messages = [{'role': 'system', 'content': SYSTEM.format(profile=json.dumps(profile, ensure_ascii=False), query=query)},
                {'role': 'user', 'content': '开始规划。'}]
    for turn in range(max_turns):
        reply = complete(messages)
        calls = reply.get('tool_calls') or []
        if not calls:
            messages += [{'role': 'assistant', 'content': reply.get('content') or ''},
                         {'role': 'user', 'content': '请继续调用工具，最后必须调用 finalize。'}]
            continue
        messages.append({'role': 'assistant', 'content': reply.get('content') or '',
                         'tool_calls': [{'id': c['id'], 'type': 'function',
                                         'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]})
        for c in calls:
            entry = dict(tool=c['name'])
            try:
                args = json.loads(c['arguments'] or '{}')
                if not isinstance(args, dict):
                    raise ToolError('参数必须是 JSON object')
                entry['args'] = args
                result = session.call(c['name'], args)
                entry['n'] = len(result.get('items') or result.get('days') or [])
                if c['name'] == 'finalize':
                    entry['ok'] = True
            except (ToolError, TypeError, json.JSONDecodeError) as exc:
                result = {'error': str(exc)}
                entry['error'] = str(exc)
            trace.append(entry)
            messages.append({'role': 'tool', 'tool_call_id': c['id'],
                             'content': json.dumps(result, ensure_ascii=False)})
        if session.final:
            return session
        # Nudge before the budget runs out: models otherwise keep re-probing routes.
        if turn + 1 == max_turns - 2:
            messages.append({'role': 'user', 'content': f'还剩 {max_turns-turn-1} 轮。'
                                                        'compute_stamina 返回「校验通过」后请立刻用相同的参数调用 finalize，'
                                                        '不要继续试算；没有通过就减到每天 1–2 个点再提交。'})
    raise AgentFailed(f'{max_turns} 轮内没有通过校验的 finalize')


def main_pois(pois):
    """Drop sub-areas such as「杭州动物园-虎山」or「西湖游船涌金池码头」when the parent POI is also a
    candidate, and keep only the first boat ride, so the ordinary plan is not padded with variants."""
    names = {p['name'] for p in pois}
    kept, boat_seen = [], False
    for p in pois:
        if any(p['name'] != n and p['name'].startswith(n) for n in names):
            continue
        if is_boat(p):
            if boat_seen:
                continue
            boat_seen = True
        kept.append(p)
    return kept


ORDINARY_PARK_ITEMS = 8


def ordinary_plan(session, routes, candidates, hotel):
    """普通版：城市日按返回顺序每天 3–4 个点；乐园日按返回顺序每天排满 8 个园内项目、不午休。"""
    profile = session.profile
    city = ordinary_days(profile, [p for p in candidates if p['id'] not in session.park_of], hotel)
    days, used = [], set()
    for i, (date, route) in enumerate(zip(profile['dates'], routes)):
        park_id = next((session.park_of[p['id']] for p in route if p['id'] in session.park_of), None)
        if park_id is None:
            days.append(city[i])
            continue
        # 园内项目名常以乐园名开头（「上海迪士尼度假区-加勒比海盗…」），不经过子景点过滤。
        everything = sorted(session.pois.values(), key=lambda p: p['source_order'])
        items = [p for p in everything if session.park_of.get(p['id']) == park_id and p['id'] not in used]
        items = items[:ORDINARY_PARK_ITEMS]
        used.update(p['id'] for p in items)
        days.append(bill_park_day(date, session.pois[park_id], items, profile, hotel, ordinary=True))
    return days


HOTEL_COMPARE_MAX = 4


def compare_hotels(session, routes, chosen):
    """同一行程换不同酒店重算：已选酒店、离首日景点最近的两家、最便宜的一家。"""
    hotels = list(session.hotels.values())
    if not hotels or not any(routes):
        return []
    first = next(r for r in routes if r)
    center = {'latitude': sum(float(p['latitude']) for p in first) / len(first),
              'longitude': sum(float(p['longitude']) for p in first) / len(first)}
    by_distance = sorted(hotels, key=lambda h: distance_m(center, h))
    picks = ([session.hotels[chosen['id']]] if chosen else []) + by_distance[:2] + [min(hotels, key=price_value)]
    seen, rows = set(), []
    for hotel in picks:
        if hotel['id'] in seen or len(rows) >= HOTEL_COMPARE_MAX:
            continue
        seen.add(hotel['id'])
        days = session.bill(routes, hotel)
        rows.append(dict(id=hotel['id'], name=hotel['name'], price=hotel.get('price'), star=hotel.get('star'),
                         detailUrl=hotel.get('detailUrl'), chosen=bool(chosen) and hotel['id'] == chosen['id'],
                         distance_m=round(distance_m(center, hotel) / DETOUR_FACTOR),
                         days=[dict(date=d['date'], total_steps=d['total_steps'], over_cap=d['over_cap'],
                                    taxi_km=d['taxi_km']) for d in days]))
    return rows


def plan_from_session(session):
    profile = session.profile
    routes, hotel = session.final
    active = session.bill(routes, hotel)
    if hotel:
        # Report distance to the first non-empty day's centroid, as the deterministic planner does.
        hotel = choose_hotel([hotel], next(r for r in routes if r), profile['budget_per_night'])
    candidates = main_pois(sorted(session.pois.values(), key=lambda p: p['source_order']))
    plan = dict(profile=profile, ordinary=ordinary_plan(session, routes, candidates, hotel), stamina=active, hotel=hotel,
                warnings=plan_warnings(hotel, active), removed_claims=[], explanation='', system_messages=[])
    if hotel:
        query = session.hotel_queries[hotel['id']]
        plan['hotel_search_poi'] = query['poi_name']
        plan['hotel_stay'] = dict(check_in=query['check_in'], check_out=query['check_out'])
    plan['system_messages'] = list(dict.fromkeys(str(r['systemMessage']) for r in session.raw_results
                                                 if r.get('systemMessage')))
    plan['hotel_compare'] = compare_hotels(session, routes, hotel)
    if any(d.get('park') for d in active):
        plan['warnings'] += ['排队站立时间未计入步数；直通卡/尊享卡可缩短排队，价格与适用项目以乐园官方为准（未核实）。',
                             '园内午休按就近坐下估算；是否出园回酒店及再入园规则未核实。',
                             '园内项目坐标来自飞猪，项目之间按直线距离乘 1.3 估算步行，非园内实际路线。',
                             '酒店对比口径：酒店到乐园 800 米内按步行，超过按打车每段 200 步；未计接驳车、停车场到入口的步行，'
                             '所以近处酒店可能显示步数更多，实际以接驳方式为准。']
    plan['data_retrieved_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    return plan


def agent_plan(query, profile, complete=None, search_poi=None, search_hotel=None):
    trace = []
    try:
        session = run_agent(query, profile, complete, search_poi, search_hotel, trace=trace)
        plan = plan_from_session(session)
        plan.update(mode='agent', tool_trace=trace)
        return plan
    except Exception as exc:
        # Never echo upstream exception text: providers can include request details.
        reason = str(exc) if isinstance(exc, AgentFailed) else f'智能体调用失败（{type(exc).__name__}）'
    plan = collect_and_plan(profile, search_poi, search_hotel)
    plan.update(mode='fallback', fallback_reason=reason, tool_trace=trace)
    return plan
