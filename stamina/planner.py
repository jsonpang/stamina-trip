"""Search adapters and deterministic route/hotel selection."""
import datetime as dt
import itertools
import math
import re

from . import flyai
from .stamina import bill_day, distance_m, stair_risk, is_boat, DAILY_TAXI_KM_BUDGET


def usable_coordinates(item):
    try:
        lat, lon = float(item['latitude']), float(item['longitude'])
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
    except (KeyError, TypeError, ValueError):
        return False


def items_from(result):
    if result.get('status') != 0:
        raise RuntimeError('飞猪搜索失败，请重试；未使用虚构数据替代')
    return (result.get('data') or {}).get('itemList') or []


def candidates(results):
    pois, seen = [], set()
    for result in results:
        for item in items_from(result):
            key = str(item.get('id') or item.get('name'))
            if key not in seen and item.get('name') and usable_coordinates(item):
                seen.add(key)
                pois.append(dict(item, source_order=len(pois)))
    if not pois:
        raise ValueError('飞猪未返回带坐标的景点，无法计算行程')
    # Returned order is the within-search popularity order; listRank boards are not comparable.
    # Keep city-center day trips bounded without inventing a city center coordinate.
    return [p for p in pois if distance_m(pois[0], p) <= 25000]


def price_value(hotel):
    raw = str(hotel.get('price', '')).replace(',', '')
    if '*' in raw or '起' in raw and not re.search(r'\d', raw):
        return None
    match = re.fullmatch(r'\s*[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|起|元起)?\s*', raw)
    return float(match[1]) if match else None


def choose_hotel(hotels, route, budget):
    if not route:
        return None
    center = {'latitude': sum(float(p['latitude']) for p in route)/len(route),
              'longitude': sum(float(p['longitude']) for p in route)/len(route)}
    valid = [h for h in hotels if h.get('name') and usable_coordinates(h) and
             price_value(h) is not None and (budget is None or price_value(h) <= budget)]
    if not valid:
        return None
    selected = min(valid, key=lambda h: (distance_m(center, h), price_value(h), h['name']))
    meters = round(distance_m(center, selected))
    return dict(selected, centroid_distance_m=meters,
                reason=f"距第一天景点重心约{meters}米（估算）；飞猪报价{selected['price']}，" +
                       ('符合每晚预算。' if budget is not None else '未设置每晚预算。'))


def best_day(date, available, profile, hotel=None, anchor=None, max_taxi_km=None):
    limited = any(t['mobility'] == 'limited' for t in profile['travelers'])
    # 体力版把长距离打车计成成本：默认当天打车总里程不超过 20 公里。
    max_taxi_km = DAILY_TAXI_KM_BUDGET if max_taxi_km is None else max_taxi_km
    best, best_key = None, None
    fallback, fallback_key = None, None
    for count in range(1, min(3, len(available))+1):
        for route in itertools.permutations(available, count):
            # A returned night-tour POI belongs at the end, after daytime rest.
            if any('夜游' in p['name'] for p in route[:-1]):
                continue
            if anchor and route[0].get('id', route[0]['name']) != anchor.get('id', anchor['name']):
                continue
            if sum(is_boat(p) for p in route) > 1:
                continue
            day = bill_day(date, route, profile, hotel)
            if day['over_cap']:
                continue
            key = (day['noon_rest_missing'], -count, sum(bool(stair_risk(p)) + (not p.get('category')) for p in route) if limited else 0,
                   sum(p['source_order'] for p in route), day['total_steps'],
                   tuple(p['source_order'] for p in route))
            # Day-total taxi distance is a cost for the stamina version: keep the
            # cheapest-by-taxi route as fallback, but prefer routes within budget.
            in_budget = day['taxi_km'] <= max_taxi_km
            candidate_key = (0 if in_budget else 1,) + key
            if in_budget and (best_key is None or key < best_key):
                best, best_key = day, key
            if fallback_key is None or candidate_key < fallback_key:
                fallback, fallback_key = day, candidate_key
    return best or fallback or bill_day(date, [], profile, hotel)


def stamina_days(profile, pois, hotel=None, anchor=None, max_taxi_km=None):
    remaining, days = list(pois), []
    for i, date in enumerate(profile['dates']):
        day = best_day(date, remaining, profile, hotel, anchor if i == 0 else None, max_taxi_km)
        days.append(day)
        used = {p.get('id', p['name']) for p in day['pois']}
        remaining = [p for p in remaining if p.get('id', p['name']) not in used]
    return days


def build_plan(profile, pois, hotels, anchor=None):
    preliminary = stamina_days(profile, pois, anchor=anchor)
    hotel = choose_hotel(hotels, preliminary[0]['pois'], profile['budget_per_night'])
    # Recompute with all hotel and noon-rest transfers inside the cap.
    active = stamina_days(profile, pois, hotel, anchor)
    if hotel:
        # Keep the hotel fixed, but report distance to the final route's actual centroid.
        hotel = choose_hotel([hotel], active[0]['pois'], profile['budget_per_night'])
    return dict(profile=profile, ordinary=ordinary_days(profile, pois, hotel), stamina=active, hotel=hotel,
                warnings=plan_warnings(hotel, active), removed_claims=[], explanation='', system_messages=[])


def ordinary_days(profile, pois, hotel=None):
    """普通版：按飞猪返回顺序每天取 3–4 个热门点，不考虑体力。"""
    normal = []
    count = 4 if len(pois) >= 4 * len(profile['dates']) else 3
    for i, date in enumerate(profile['dates']):
        normal.append(bill_day(date, pois[i*count:(i+1)*count], profile, hotel, ordinary=True))
    return normal


def plan_warnings(hotel, active):
    warnings = ['全部距离、步数和台阶风险均为估算，非导航路线；开放时间、班次、余票及休息场所需另行确认。',
                '景点分类步数不包含排队、用餐及临时绕行；实际体力需预留余量。',
                '普通版按飞猪各次返回顺序合并取点；不同 listRank 榜单不能跨榜比较。',
                '酒店按初选第一天景点重心距离排序并用预算过滤；加入酒店接驳后重新校验体力，所示距离对应最终景点重心。',
                '酒店默认首日入住、末日退房（单日行程按一晚）；午间回酒店需另行确认当日入住与退房时间。']
    if not hotel:
        warnings.append('未找到同时具备有效坐标、可读价格且符合预算的酒店；酒店往返未计入，午休按就近休息估算。')
    if any(not d['pois'] for d in active):
        warnings.append('部分日期没有可在预算内完成的候选景点，保留空闲，不强行凑点。')
    if any(d.get('taxi_over_budget') for d in active):
        warnings.append('部分日期打车总里程超过 20 公里（估算），车程偏长。')
    return warnings


def collect_and_plan(profile, search_poi=None, search_hotel=None):
    search_poi = search_poi or flyai.search_poi
    search_hotel = search_hotel or flyai.search_hotel
    results = [search_poi(profile['city'])]
    for kwargs in ({'category': '城市观光'}, {'category': '博物馆'}, {'keyword': '游船'}):
        results.append(search_poi(profile['city'], **kwargs))
    pois = candidates(results)
    # Bounded candidate set: retain source order and avoid factorial growth on wider APIs.
    pois = pois[:24]
    first = stamina_days(profile, pois)[0]['pois']
    if not first:
        plan = build_plan(profile, pois, [])
    else:
        checkout = profile['dates'][-1] if len(profile['dates']) > 1 else (dt.date.fromisoformat(profile['dates'][0])+dt.timedelta(days=1)).isoformat()
        hotel_result = search_hotel(profile['city'], poi_name=first[0]['name'],
            check_in_date=profile['dates'][0], check_out_date=checkout,
            max_price=profile['budget_per_night'], sort='distance_asc')
        results.append(hotel_result)
        plan = build_plan(profile, pois, items_from(hotel_result), anchor=first[0])
        plan['hotel_search_poi'] = first[0]['name']
        plan['hotel_stay'] = dict(check_in=profile['dates'][0], check_out=checkout)
    plan['system_messages'] = list(dict.fromkeys(str(r['systemMessage']) for r in results if r.get('systemMessage')))
    plan['data_retrieved_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    return plan
