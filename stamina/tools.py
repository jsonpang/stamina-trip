"""Tools the agent may call.

Every tool returns a compact JSON-able dict built only from flyai data plus the
deterministic functions in stamina.py/planner.py. Step and distance numbers are
always computed by bill_day; the model may never supply them.
"""
import json

from .planner import choose_hotel, price_value, usable_coordinates
from .stamina import bill_day, is_boat, stair_risk, DAILY_TAXI_KM_BUDGET, LONG_RIDE_M

POI_LIMIT = 10
HOTEL_LIMIT = 8
MAX_PER_DAY = 3

POI_FIELDS = ("id", "name", "category", "address", "latitude", "longitude",
              "description", "freePoiStatus", "ticketInfo", "jumpUrl", "mainPic", "listRank")
HOTEL_FIELDS = ("id", "name", "price", "star", "interestsPoi", "address",
                "latitude", "longitude", "detailUrl", "mainPic")


class ToolError(Exception):
    """Bad arguments or an unusable request; the agent may retry."""


class InvalidFinalize(Exception):
    """finalize() cannot be honoured at all; the caller falls back."""


SPECS = [
    {"type": "function", "function": {
        "name": "search_poi",
        "description": "用飞猪实时数据搜索景点，返回 poi_id、坐标、分类、门票与简介。"
                       "按用户偏好自选 keyword 或 category（想看动物就搜「动物园」或 category=动物园）。",
        "parameters": {"type": "object", "properties": {
            "city_name": {"type": "string", "description": "城市名，默认用画像城市"},
            "keyword": {"type": "string", "description": "关键词，例如 动物园、夜游、博物馆"},
            "category": {"type": "string", "description": "分类，例如 动物园、城市观光、博物馆"},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "search_hotel",
        "description": "用飞猪实时数据搜索酒店。dest_name 必须是城市或区县；poi_name 用来找某个景点附近的酒店。",
        "parameters": {"type": "object", "properties": {
            "dest_name": {"type": "string"},
            "poi_name": {"type": "string", "description": "靠近的景点名，建议用第一天首个景点"},
            "check_in_date": {"type": "string", "description": "YYYY-MM-DD"},
            "check_out_date": {"type": "string", "description": "YYYY-MM-DD"},
            "max_price": {"type": "integer", "description": "每晚最高价（元）"},
        }, "required": ["dest_name"]}}},
    {"type": "function", "function": {
        "name": "compute_stamina",
        "description": "用确定性函数核算给定行程：返回每天步数、是否超过步数上限、当天打车总公里数与逐段账单摘要。"
                       "步数只以本工具的返回为准；不要自己估算步数。",
        "parameters": {"type": "object", "properties": {
            "dates": {"type": "array", "items": {"type": "string"}, "description": "YYYY-MM-DD 列表，默认用画像日期"},
            "days": {"type": "array", "description": "按日期排列，每天是 1-3 个 poi_id 的数组",
                     "items": {"type": "array", "items": {"type": "string"}}},
            "hotel_id": {"type": "string", "description": "search_hotel 返回的酒店 id"},
        }, "required": ["days"]}}},
    {"type": "function", "function": {
        "name": "finalize",
        "description": "提交最终行程。days 为按日期排列的 poi_id 数组（每天 1-3 个，不能跨天重复）。"
                       "提交后仍会用确定性函数重算一遍作为最终数据。",
        "parameters": {"type": "object", "properties": {
            "days": {"type": "array", "description": "按日期排列，每天是 1-3 个 poi_id 的数组",
                     "items": {"type": "array", "items": {"type": "string"}}},
            "hotel_id": {"type": "string", "description": "search_hotel 返回的酒店 id"},
        }, "required": ["days"]}}},
]


def poi_id(item):
    return str(item.get('id') or item.get('name') or '').strip()


def hotel_id(item):
    return str(item.get('id') or item.get('shId') or item.get('name') or '').strip()


def trim_poi(item):
    return {k: item.get(k) for k in POI_FIELDS if item.get(k) is not None}


def trim_hotel(item):
    return {k: item.get(k) for k in HOTEL_FIELDS if item.get(k) is not None}


def compact_bill(day):
    """Bill rows as compact text: the model reads them, but must not recompute them."""
    return [dict(seg=r['name'], mode=r['mode'], steps=r['steps'], cumulative=r['cumulative_steps'],
                 km=None if r['mode'] != '打车' else round(r['distance_m']/1000, 2),
                 long_ride=bool(r.get('long_ride')), rest=r['kind'] == 'rest') for r in day['bill']]


def day_report(day, profile):
    """Deterministic per-day verdict plus the reasons the agent should react to."""
    tips = []
    if not day['pois']:
        tips.append(f"{day['date']} 没有安排景点；请从 search_poi 结果中选点。")
    if day['over_cap']:
        tips.append(f"{day['date']} 超过步数上限 {day['cap']}（{day['total_steps']} 步，估算）；"
                    f"请减少景点或换成更近的点后重新核算。")
    if day['taxi_over_budget']:
        tips.append(f"{day['date']} 当天打车总里程 {day['taxi_km']} 公里，超过 {DAILY_TAXI_KM_BUDGET:g} 公里；"
                    f"体力版把长距离打车计成成本，请换成更近的点。")
    if day['long_rides']:
        tips.append(f"{day['date']} 有 {day['long_rides']} 段单程车程超过 {LONG_RIDE_M/1000:g} 公里"
                    f"（标注「车程较长」），行动受限同行人会较累。")
    if profile['need_noon_rest'] and not any(r['kind'] == 'rest' for r in day['bill']):
        tips.append(f"{day['date']} 未触发午休（当天累计步数未达上限的 35% 且不足 2 个点）。")
    return dict(date=day['date'], poi_names=[p['name'] for p in day['pois']],
                total_steps=day['total_steps'], cap=day['cap'], over_cap=day['over_cap'],
                taxi_km=day['taxi_km'], taxi_over_budget=day['taxi_over_budget'],
                long_rides=day['long_rides'], bill=compact_bill(day), tips=tips)


def _day_routes(session, days, strict):
    """Resolve [[poi_id, ...], ...] into routes; raise on anything unusable."""
    if not isinstance(days, list) or not days:
        raise ToolError('days 必须是按日期排列的 poi_id 数组')
    if len(days) > len(session.profile['dates']):
        raise ToolError(f"画像只有 {len(session.profile['dates'])} 天，days 最多同样长度")
    routes, seen = [], set()
    for index, ids in enumerate(days):
        if not isinstance(ids, list):
            raise ToolError(f'第 {index+1} 天必须是 poi_id 数组')
        if not ids:
            raise ToolError(f'第 {index+1} 天没有景点；请至少安排一个点')
        if len(ids) > MAX_PER_DAY:
            raise ToolError(f'第 {index+1} 天最多 {MAX_PER_DAY} 个景点')
        route = []
        for raw in ids:
            poi = session.find_poi(raw)
            if poi is None:
                raise ToolError(f'景点 {raw} 不在之前的 search_poi 结果中；请先用 search_poi 查询并引用其 poi_id')
            if poi['id'] in seen:
                raise ToolError(f"景点 {poi['name']} 被重复安排（同一景点不能跨天或同日重复）")
            seen.add(poi['id'])
            route.append(poi)
        routes.append(route)
    if strict and len(routes) != len(session.profile['dates']):
        raise ToolError(f"days 需要覆盖全部 {len(session.profile['dates'])} 天")
    return routes


def search_poi(args, session):
    city = args.get('city_name') or args.get('city') or session.profile['city']
    if not isinstance(city, str) or not city.strip():
        raise ToolError('city_name 必须是城市名')
    result = session.search_poi(city_name=city.strip(), keyword=args.get('keyword'),
                                category=args.get('category'))
    if result.get('status') != 0:
        raise ToolError(f"飞猪景点搜索失败：{result.get('message') or result.get('error') or '未返回数据'}")
    items = (result.get('data') or {}).get('itemList') or []
    kept = [poi for poi in (session.add_poi(item) for item in items[:POI_LIMIT]) if poi]
    if not kept:
        raise ToolError('这次搜索没有带有效坐标的景点；请换关键词或分类重试')
    return dict(items=kept, count=len(kept),
                summary=f"飞猪返回 {len(items)} 条，纳入 {len(kept)} 个可用景点（按返回顺序）；"
                        f"引用 poi_id 才能核算步数。")


def search_hotel(args, session):
    dest = args.get('dest_name') or session.profile['city']
    result = session.search_hotel(dest_name=dest, poi_name=args.get('poi_name'),
                                  check_in_date=args.get('check_in_date'),
                                  check_out_date=args.get('check_out_date'),
                                  max_price=args.get('max_price'), sort=args.get('sort'))
    if result.get('status') != 0:
        raise ToolError(f"飞猪酒店搜索失败：{result.get('message') or result.get('error') or '未返回数据'}")
    items = (result.get('data') or {}).get('itemList') or []
    kept = [hotel for hotel in (session.add_hotel(item) for item in items[:HOTEL_LIMIT]) if hotel]
    if not kept:
        raise ToolError('这次搜索没有带坐标和可读价格的酒店；请换 poi_name 或不带 max_price 重试')
    return dict(items=kept, count=len(kept),
                summary=f"飞猪返回 {len(items)} 条，纳入 {len(kept)} 个可用酒店；"
                        f"把 hotel_id 传给 compute_stamina 与 finalize。")


def compute_stamina(args, session):
    dates = args.get('dates') or session.profile['dates']
    if not isinstance(dates, list) or not dates:
        raise ToolError('dates 必须是 YYYY-MM-DD 列表')
    routes = _day_routes(session, args.get('days'), strict=False)
    hotel = session.find_hotel(args.get('hotel_id')) if args.get('hotel_id') else None
    if args.get('hotel_id') and hotel is None:
        raise ToolError(f"hotel_id {args['hotel_id']} 不在 search_hotel 结果中")
    days = []
    reports = []
    for date, route in zip(dates, routes):
        day = bill_day(date, route, session.profile, hotel)
        days.append(day)
        reports.append(day_report(day, session.profile))
    tips = [tip for report in reports for tip in report['tips']]
    for day in days:
        tips.extend(f"{day['date']} 提示：{p['name']}{stair_risk(p)}，建议少走台阶"
                    for p in day['pois'] if stair_risk(p))
    over = [d['date'] for d in reports if d['over_cap']]
    return dict(days=reports, within_cap=not over,
                over_cap_dates=over,
                taxi_over_budget_dates=[d['date'] for d in days if d['taxi_over_budget']],
                hotel=hotel['name'] if hotel else None,
                summary=('全部日期都在步数上限内。' if not over else f"{'、'.join(over)} 超过步数上限，需要换点。")
                        + '（步数为确定性函数估算，以本结果为准）',
                tips=tips)


def finalize(args, session):
    """Resolve and re-bill the submitted itinerary. Raises InvalidFinalize when unusable."""
    for key in ('total_steps', 'steps', 'estimated_steps'):
        if key in args:
            session.ignore_step_claim(f'finalize 参数 {key}={args[key]}（模型自报步数一律不采用）')
    try:
        routes = _day_routes(session, args.get('days'), strict=True)
    except ToolError as exc:
        raise InvalidFinalize(str(exc)) from None
    hotel_id = args.get('hotel_id')
    hotel = None
    if hotel_id in (None, ''):
        if session.hotels:
            raise InvalidFinalize('请从 search_hotel 结果中选择一个 hotel_id')
    else:
        hotel = session.find_hotel(hotel_id)
        if hotel is None:
            raise InvalidFinalize(f'hotel_id {hotel_id} 不在 search_hotel 结果中')
        if not usable_coordinates(hotel):
            raise InvalidFinalize(f"酒店 {hotel['name']} 没有有效坐标")
        if price_value(hotel) is None:
            raise InvalidFinalize(f"酒店 {hotel['name']} 没有可读价格")
        budget = session.profile['budget_per_night']
        if budget is not None and price_value(hotel) > budget:
            raise InvalidFinalize(f"酒店 {hotel['name']} 报价 {hotel['price']} 超过每晚预算 {budget}")
        # Same deterministic justification as the fallback pipeline.
        hotel = choose_hotel([hotel], routes[0], budget) or hotel
    days = [bill_day(date, route, session.profile, hotel) for date, route in zip(session.profile['dates'], routes)]
    over = [d['date'] for d in days if d['over_cap']]
    if over:
        raise ToolError('、'.join(f"{d['date']} {d['total_steps']}/{d['cap']} 步" for d in days if d['over_cap'])
                        + ' 超过步数上限；请减少景点或换成更近的点后重新 finalize。')
    return dict(ok=True, days=[day_report(d, session.profile) for d in days],
                hotel=hotel['name'] if hotel else None,
                hotel_id=hotel['id'] if hotel else None,
                summary='已定稿：'
                        + '；'.join(f"{d['date']} {d['total_steps']}/{d['cap']} 步（估算）" for d in days))


REGISTRY = {'search_poi': search_poi, 'search_hotel': search_hotel,
            'compute_stamina': compute_stamina, 'finalize': finalize}


def dispatch(name, args, session):
    handler = REGISTRY.get(name)
    if handler is None:
        return dict(error=f'未知工具 {name}；可用工具：{", ".join(sorted(REGISTRY))}')
    if not isinstance(args, dict):
        return dict(error=f'{name} 的参数必须是 JSON object')
    try:
        return handler(args, session)
    except InvalidFinalize:
        raise
    except ToolError as exc:
        return dict(error=str(exc))
    except Exception as exc:  # Upstream errors are never echoed verbatim.
        return dict(error=f'{name} 调用失败：{type(exc).__name__}')


def result_count(result):
    if isinstance(result.get('items'), list):
        return len(result['items'])
    if isinstance(result.get('days'), list):
        return len(result['days'])
    return 1 if result.get('ok') else 0


def result_summary(result):
    return result.get('summary') or result.get('error') or ''


def parse_arguments(raw):
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
