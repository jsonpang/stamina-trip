"""LLM extracts intent only; validated defaults are deterministic."""
import datetime as dt
import json

from .llm import client_and_model


def default_cap(travelers):
    return min(6000 if t['mobility'] == 'limited' or t['age'] >= 65
               else 7000 if t['age'] <= 8 else 12000 for t in travelers)


def validate_profile(value):
    if not isinstance(value, dict):
        raise ValueError('画像必须是 JSON object')
    city = value.get('city')
    if not isinstance(city, str) or not city.strip():
        raise ValueError('缺少城市')
    dates = value.get('dates')
    if not isinstance(dates, list) or not 1 <= len(dates) <= 14:
        raise ValueError('日期需为 1–14 天的列表')
    for day in dates:
        if not isinstance(day, str) or dt.date.fromisoformat(day).isoformat() != day:
            raise ValueError('日期必须为 YYYY-MM-DD')
    if dates != sorted(set(dates)):
        raise ValueError('日期必须递增且不能重复')
    travelers = value.get('travelers')
    if not isinstance(travelers, list) or not travelers:
        raise ValueError('缺少同行人')
    for person in travelers:
        if not isinstance(person, dict) or type(person.get('age')) is not int or not 0 <= person['age'] <= 120:
            raise ValueError('年龄必须为 0–120 的整数')
        if person.get('mobility') not in ('normal', 'limited'):
            raise ValueError('mobility 必须为 normal/limited')
    cap = value.get('daily_step_cap')
    cap = default_cap(travelers) if cap is None else cap
    if type(cap) is not int or not 0 < cap <= 100000:
        raise ValueError('步数上限必须为正整数且不超过 100000')
    rest = value.get('need_noon_rest')
    if type(rest) is not bool:
        raise ValueError('need_noon_rest 必须为布尔值')
    budget = value.get('budget_per_night')
    if budget is not None and (type(budget) not in (int, float) or not 0 < budget < float('inf')):
        raise ValueError('预算必须为正数或 null')
    return dict(city=city.strip(), dates=dates, travelers=travelers,
                daily_step_cap=cap, need_noon_rest=rest, budget_per_night=budget)


def parse_profile(query, complete=None, today=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ValueError('请输入 1–4000 字的旅行需求')
    today = today or dt.date.today()
    prompt = f'''今天是 {today.isoformat()}。只提取旅行画像，输出一个 JSON object，不要解释。
字段 city, dates(YYYY-MM-DD列表), travelers(每人 age 整数及 mobility normal/limited),
daily_step_cap(未指定填null), need_noon_rest(boolean), budget_per_night(未指定填null)。
没有年份时取今天之后最近的相应日期，日期范围展开到每天。爸妈为两人，膝盖不好标 limited。
只解析用户表达，不选择景点酒店，不计算行程。缺少年龄时成人按35、孩子按6并在字段中使用此默认。
缺少城市或日期不能猜，返回null让校验失败。'''
    messages = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': query}]
    if complete is None:
        client, model = client_and_model()
        def complete(msgs):
            return client.chat.completions.create(model=model, messages=msgs,
                response_format={'type': 'json_object'}, temperature=0).choices[0].message.content
    for attempt in range(2):
        try:
            return validate_profile(json.loads(complete(messages)))
        except (ValueError, TypeError, KeyError, OverflowError):
            messages.append({'role': 'user', 'content': '上次输出未通过 JSON/字段校验。请按全部字段要求重新输出合法 JSON。'})
        except Exception:
            # Never expose upstream exceptions: providers can echo headers or request bodies.
            if attempt == 1:
                raise RuntimeError('画像服务调用失败；请检查模型配置与代理服务') from None
    raise ValueError('画像解析两次失败，请明确城市、日期、同行人和步数要求')
