"""Tools the planning agent may call.

Search tools return compact views of real flyai items; the full items stay in the
session so the final plan is rebuilt from flyai data, never from model text.
compute_stamina and finalize run the deterministic estimates in stamina.py.
"""
import datetime as dt

from . import flyai
from .planner import items_from, usable_coordinates, price_value
from .stamina import bill_day, poi_steps, stair_risk, CATEGORY_STEPS, DAILY_TAXI_KM_BUDGET

DAYS_SCHEMA = {"type": "array", "description": "每天一个景点 id 列表，按游览顺序；天数必须等于行程天数",
               "items": {"type": "array", "items": {"type": "string"}}}

SPECS = [
    {"type": "function", "function": {
        "name": "search_poi",
        "description": "用飞猪实时数据搜索目的地城市的景点。按同行人兴趣选关键词或分类，例如想看动物就搜「动物园」。",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string"},
            "category": {"type": "string", "enum": list(CATEGORY_STEPS)},
        }}}},
    {"type": "function", "function": {
        "name": "search_hotel",
        "description": "用飞猪实时数据搜索某个景点附近的酒店，入住退房日期与每晚预算自动按画像填写。",
        "parameters": {"type": "object", "properties": {
            "poi_name": {"type": "string", "description": "以哪个景点为中心找酒店"},
        }, "required": ["poi_name"]}}},
    {"type": "function", "function": {
        "name": "compute_stamina",
        "description": "按体力预算确定性计算每天步数、是否超上限、打车里程和逐段账单。步数只能以此为准。",
        "parameters": {"type": "object", "properties": {
            "days": DAYS_SCHEMA,
            "hotel_id": {"type": "string", "description": "search_hotel 返回的酒店 id，可省略"},
        }, "required": ["days"]}}},
    {"type": "function", "function": {
        "name": "finalize",
        "description": "提交最终行程。会重新计算校验：每天不超步数上限、打车不超 20 公里、夜游放在当天最后。",
        "parameters": {"type": "object", "properties": {
            "days": DAYS_SCHEMA,
            "hotel_id": {"type": "string"},
        }, "required": ["days"]}}},
]


class ToolError(ValueError):
    """A tool call the model can correct; the message goes back to the model."""


class Session:
    def __init__(self, profile, search_poi=None, search_hotel=None):
        self.profile = profile
        self.search_poi_fn = search_poi or flyai.search_poi
        self.search_hotel_fn = search_hotel or flyai.search_hotel
        self.pois, self.hotels = {}, {}  # id -> full flyai item
        self.raw_results = []
        self.hotel_queries = {}  # hotel id -> the search that returned it
        self.final = None

    def call(self, name, args):
        if name == 'search_poi':
            return self.search_poi(**args)
        if name == 'search_hotel':
            return self.search_hotel(**args)
        if name == 'compute_stamina':
            return self.compute(**args)
        if name == 'finalize':
            return self.finalize(**args)
        raise ToolError(f'没有这个工具：{name}')

    def search_poi(self, keyword=None, category=None):
        if category and category not in CATEGORY_STEPS:
            # flyai rejects free-text categories such as「看动物」; search them as a keyword instead.
            keyword, category = keyword or category, None
        result = self.search_poi_fn(self.profile['city'], keyword=keyword or None, category=category or None)
        self.raw_results.append(result)
        items = []
        for item in found(result):
            if not item.get('name') or not usable_coordinates(item):
                continue
            key = str(item.get('id') or item['name'])
            self.pois.setdefault(key, dict(item, id=key, source_order=len(self.pois)))
            items.append(self.pois[key])
        return {'items': [poi_view(p) for p in items[:10]]}

    def search_hotel(self, poi_name):
        dates = self.profile['dates']
        checkout = dates[-1] if len(dates) > 1 else (dt.date.fromisoformat(dates[0]) + dt.timedelta(days=1)).isoformat()
        result = self.search_hotel_fn(self.profile['city'], poi_name=poi_name, check_in_date=dates[0],
                                      check_out_date=checkout, max_price=self.profile['budget_per_night'],
                                      sort='distance_asc')
        self.raw_results.append(result)
        query = dict(poi_name=poi_name, check_in=dates[0], check_out=checkout)
        items = []
        budget = self.profile['budget_per_night']
        for item in found(result):
            if not item.get('name') or not usable_coordinates(item) or price_value(item) is None:
                continue
            if budget is not None and price_value(item) > budget:
                continue
            key = str(item.get('shId') or item.get('id') or item['name'])
            self.hotels[key] = dict(item, id=key)
            self.hotel_queries[key] = query
            items.append(self.hotels[key])
        return {'items': [dict(id=h['id'], name=h['name'], price=h.get('price'),
                               latitude=h['latitude'], longitude=h['longitude']) for h in items[:8]]}

    def resolve(self, days, hotel_id=None):
        if not isinstance(days, list) or len(days) != len(self.profile['dates']):
            raise ToolError(f"days 必须是 {len(self.profile['dates'])} 个列表（每天一个）")
        seen, routes = set(), []
        for ids in days:
            if not isinstance(ids, list):
                raise ToolError('days 的每一项必须是景点 id 列表')
            route = []
            for poi_id in ids:
                poi_id = str(poi_id)
                if poi_id not in self.pois:
                    raise ToolError(f'未知景点 id {poi_id}：只能用 search_poi 返回的 id')
                if poi_id in seen:
                    raise ToolError(f'景点 {poi_id} 重复安排')
                seen.add(poi_id)
                route.append(self.pois[poi_id])
            routes.append(route)
        hotel = None
        if hotel_id:
            if str(hotel_id) not in self.hotels:
                raise ToolError(f'未知酒店 id {hotel_id}：只能用 search_hotel 返回的 id')
            hotel = self.hotels[str(hotel_id)]
        return routes, hotel

    def bill(self, routes, hotel):
        return [bill_day(date, route, self.profile, hotel) for date, route in zip(self.profile['dates'], routes)]

    def compute(self, days, hotel_id=None):
        routes, hotel = self.resolve(days, hotel_id)
        return {'days': [day_view(d) for d in self.bill(routes, hotel)],
                'hotel_included': hotel is not None}

    def finalize(self, days, hotel_id=None):
        routes, hotel = self.resolve(days, hotel_id)
        if not any(routes):
            raise ToolError('至少安排一个景点')
        problems = []
        for route, day in zip(routes, self.bill(routes, hotel)):
            if any('夜游' in p['name'] for p in route[:-1]):
                problems.append(f"{day['date']} 夜游必须放在当天最后")
            if day['over_cap']:
                problems.append(f"{day['date']} 共 {day['total_steps']} 步，超过上限 {day['cap']}")
            if day['noon_rest_missing']:
                problems.append(f"{day['date']} 排不进午休：午休要在累计步数达上限 35% 或走完 2 个点之后、且后面还有景点，请调整顺序或增减景点")
            if day['taxi_over_budget']:
                problems.append(f"{day['date']} 打车 {day['taxi_km']} 公里，超过 {DAILY_TAXI_KM_BUDGET:g} 公里")
        if problems:
            raise ToolError('未通过校验：' + '；'.join(problems))
        self.final = (routes, hotel)
        return {'ok': True}


def found(result):
    """Items of one flyai result; a failed search is reported to the model, not fatal."""
    try:
        return items_from(result)
    except RuntimeError:
        raise ToolError('飞猪搜索失败，可换个关键词重试') from None


def poi_view(poi):
    ticket = poi.get('ticketInfo') or {}
    return dict(id=poi['id'], name=poi['name'], category=poi.get('category'),
                latitude=poi['latitude'], longitude=poi['longitude'],
                ticket=ticket.get('price') or ('免费' if poi.get('freePoiStatus') == 'FREE' else None),
                est_steps_inside=poi_steps(poi), stair_risk=stair_risk(poi) or None,
                description=(poi.get('description') or '')[:60])


def day_view(day):
    return dict(date=day['date'], total_steps=day['total_steps'], cap=day['cap'], over_cap=day['over_cap'],
                taxi_km=day['taxi_km'], taxi_over_budget=day['taxi_over_budget'], long_rides=day['long_rides'],
                noon_rest_missing=day['noon_rest_missing'],
                bill=[f"{r['name']}｜{r['mode']}｜{r['steps']}步｜累计{r['cumulative_steps']}" for r in day['bill']])
