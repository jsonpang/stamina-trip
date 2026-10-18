"""Tool-calling planning loop.

The model decides what to search and which stops to try; every step count comes
from compute_stamina, and the finalized route is billed again here before it
reaches the plan. Any failure falls back to the deterministic planner.
"""
import datetime as dt
import json

from .planner import collect_and_plan, choose_hotel, ordinary_days, plan_warnings
from .stamina import is_boat
from .tools import SPECS, Session, ToolError

MAX_TURNS = 12

SYSTEM = '''你是体力预算规划师。按同行人走得动多少来排行程。
做法：先按用户偏好用 search_poi 搜景点（偏好如看动物、看展、坐船，各搜一次），再用 search_hotel 找第一天主要景点附近的酒店，
然后用 compute_stamina 试算，超上限或打车超 20 公里就换点或减点再算，满意后调用 finalize。
规则：每天的步数、是否超限只看 compute_stamina 返回值，不要自己估算；只能使用工具返回的 id；
行动受限的同行人尽量避开标了台阶风险的景点；每天 1–3 个景点，夜游放在当天最后；不要安排重复景点。
需要午休时：午休自动插在累计步数达上限 35% 或走完 2 个点之后，且后面还得有景点，所以一天 2–3 个点时把步数多的点放前面。
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
    for _ in range(max_turns):
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


def plan_from_session(session):
    profile = session.profile
    routes, hotel = session.final
    active = session.bill(routes, hotel)
    if hotel:
        # Report distance to the first non-empty day's centroid, as the deterministic planner does.
        hotel = choose_hotel([hotel], next(r for r in routes if r), profile['budget_per_night'])
    candidates = main_pois(sorted(session.pois.values(), key=lambda p: p['source_order']))
    plan = dict(profile=profile, ordinary=ordinary_days(profile, candidates, hotel), stamina=active, hotel=hotel,
                warnings=plan_warnings(hotel, active), removed_claims=[], explanation='', system_messages=[])
    if hotel:
        query = session.hotel_queries[hotel['id']]
        plan['hotel_search_poi'] = query['poi_name']
        plan['hotel_stay'] = dict(check_in=query['check_in'], check_out=query['check_out'])
    plan['system_messages'] = list(dict.fromkeys(str(r['systemMessage']) for r in session.raw_results
                                                 if r.get('systemMessage')))
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
