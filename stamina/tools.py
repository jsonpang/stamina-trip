"""Tools the planning agent may call.

Search tools return compact views of real flyai items; the full items stay in the
session so the final plan is rebuilt from flyai data, never from model text.
compute_stamina and finalize run the deterministic estimates in stamina.py.
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

from . import flyai
from .planner import items_from, usable_coordinates, price_value
from .stamina import (bill_day, bill_park_day, distance_m, park_item_kind, park_item_risk, poi_steps, stair_risk,
                      CATEGORY_STEPS, DAILY_TAXI_KM_BUDGET, DETOUR_FACTOR, PARK_ITEM_STEPS, PARK_RADIUS_M)

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
        "name": "search_park_items",
        "description": "主题乐园（如迪士尼）园内规划：给出乐园名和你知道的园内项目、园区、演出名称，逐个用飞猪实时数据核实，"
                       "只返回坐标在乐园范围内的项目。某天只排这些项目时，按园内步行计算步数。",
        "parameters": {"type": "object", "properties": {
            "park_name": {"type": "string"},
            "item_names": {"type": "array", "items": {"type": "string"}, "description": "8–15 个园内项目名"},
        }, "required": ["park_name", "item_names"]}}},
    {"type": "function", "function": {
        "name": "search_hotel",
        "description": "用飞猪实时数据搜索酒店，入住退房日期与每晚预算自动按画像填写。poi_name 找某景点附近，"
                       "key_words 按酒店名找（如「上海迪士尼乐园酒店」）；二选一。",
        "parameters": {"type": "object", "properties": {
            "poi_name": {"type": "string", "description": "以哪个景点为中心找酒店"},
            "key_words": {"type": "string", "description": "酒店名关键词"},
        }}}},
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
        self.park_of = {}  # in-park item id -> park POI id
        self.final = None

    def call(self, name, args):
        if name == 'search_poi':
            return self.search_poi(**args)
        if name == 'search_hotel':
            return self.search_hotel(**args)
        if name == 'search_park_items':
            return self.search_park_items(**args)
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

    def register(self, item):
        key = str(item.get('id') or item['name'])
        self.pois.setdefault(key, dict(item, id=key, source_order=len(self.pois)))
        return self.pois[key]

    def search_park_items(self, park_name, item_names):
        if not isinstance(item_names, list) or not item_names:
            raise ToolError('item_names 必须是非空的项目名列表')
        city = self.profile['city']
        first = self.search_poi_fn(city, keyword=park_name)
        self.raw_results.append(first)
        found_items = [i for i in found(first) if i.get('name') and usable_coordinates(i)]
        parks = [i for i in found_items if i.get('category') == '主题乐园'] or found_items
        if not parks:
            raise ToolError(f'飞猪没有找到乐园「{park_name}」')
        park = self.register(parks[0])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: self.search_poi_fn(city, keyword=str(n)), item_names[:15]))
        self.raw_results.extend(results)
        items, seen = [], {park['id']}
        for result in [first] + results:
            if result.get('status') != 0:
                continue
            for item in items_from(result):
                if not item.get('name') or not usable_coordinates(item):
                    continue
                # 直线距离（去掉绕行系数）判定是否在乐园范围内
                if distance_m(park, item) / DETOUR_FACTOR > PARK_RADIUS_M:
                    continue
                record = self.register(item)
                if record['id'] in seen:
                    continue
                seen.add(record['id'])
                self.park_of[record['id']] = park['id']
                items.append(record)
        return {'park': dict(id=park['id'], name=park['name']),
                'items': [park_item_view(i, self.profile['travelers']) for i in items]}

    def search_hotel(self, poi_name=None, key_words=None):
        if not poi_name and not key_words:
            raise ToolError('poi_name 和 key_words 至少给一个')
        dates = self.profile['dates']
        checkout = dates[-1] if len(dates) > 1 else (dt.date.fromisoformat(dates[0]) + dt.timedelta(days=1)).isoformat()
        search = dict(check_in_date=dates[0], check_out_date=checkout, max_price=self.profile['budget_per_night'])
        if key_words:
            search['key_words'] = key_words
        if poi_name:
            search.update(poi_name=poi_name, sort='distance_asc')
        result = self.search_hotel_fn(self.profile['city'], **search)
        self.raw_results.append(result)
        query = dict(poi_name=poi_name or key_words, check_in=dates[0], check_out=checkout)
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
        return {'items': [dict(id=h['id'], name=h['name'], price=h.get('price'), star=h.get('star'),
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
        days = []
        for date, route in zip(self.profile['dates'], routes):
            parks = {self.park_of.get(p['id']) for p in route}
            if route and parks != {None}:
                if len(parks) > 1:
                    raise ToolError(f'{date} 同一天不能混排园内项目和园外景点（或两个乐园）')
                days.append(bill_park_day(date, self.pois[parks.pop()], route, self.profile, hotel))
            else:
                days.append(bill_day(date, route, self.profile, hotel))
        return days

    def review(self, billed, routes):
        """Validation problems of one billed plan; shared by compute and finalize."""
        problems = []
        for route, day in zip(routes, billed):
            if any('夜游' in p['name'] for p in route[:-1]):
                problems.append(f"{day['date']} 夜游必须放在当天最后")
            if day['over_cap']:
                problems.append(f"{day['date']} 共 {day['total_steps']} 步，超过上限 {day['cap']}")
            if day['noon_rest_missing']:
                problems.append(f"{day['date']} 排不进午休：午休要在累计步数达上限 35% 或走完 2 个点之后、且后面还有景点，请调整顺序或增减景点")
            if day['taxi_over_budget']:
                problems.append(f"{day['date']} 打车 {day['taxi_km']} 公里，超过 {DAILY_TAXI_KM_BUDGET:g} 公里；"
                                "把这天离得远的景点换成彼此更近的（例如都在西湖边），或减少景点数")
        return problems

    def compute(self, days, hotel_id=None):
        routes, hotel = self.resolve(days, hotel_id)
        billed = self.bill(routes, hotel)
        # State the verdict in the result: left implicit, the model re-derives the same
        # conclusion over several turns and burns the turn budget before finalizing.
        problems = self.review(billed, routes)
        return {'days': [day_view(d) for d in billed], 'hotel_included': hotel is not None,
                'verdict': '校验通过，请用完全相同的 days 和 hotel_id 调用 finalize 提交。' if not problems
                           else '未通过校验：' + '；'.join(problems)}

    def finalize(self, days, hotel_id=None):
        routes, hotel = self.resolve(days, hotel_id)
        if not any(routes):
            raise ToolError('至少安排一个景点')
        problems = self.review(self.bill(routes, hotel), routes)
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


def park_item_view(item, travelers):
    kind = park_item_kind(item)
    return dict(id=item['id'], name=item['name'], kind=kind, seated=kind == 'show',
                est_steps_inside=PARK_ITEM_STEPS[kind], risk=park_item_risk(item, travelers) or None,
                latitude=item['latitude'], longitude=item['longitude'],
                description=(item.get('description') or '')[:60])


def day_view(day):
    return dict(date=day['date'], total_steps=day['total_steps'], cap=day['cap'], over_cap=day['over_cap'],
                taxi_km=day['taxi_km'], taxi_over_budget=day['taxi_over_budget'], long_rides=day['long_rides'],
                noon_rest_missing=day['noon_rest_missing'],
                bill=[f"{r['name']}｜{r['mode']}｜{r['steps']}步｜累计{r['cumulative_steps']}" for r in day['bill']])
