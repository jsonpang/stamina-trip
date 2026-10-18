"""Pure, deterministic estimates. No routing or accessibility verification."""
import math

# 景点内步数是分类估算，并非飞猪实测或完整游览所需步数。
CATEGORY_STEPS = {'历史古迹': 3000, '宗教场所': 3000, '山湖田园': 3500,
                  '博物馆': 2500, '城市观光': 2000, '主题乐园': 5000,
                  '动物园': 5000, '公园乐园': 4000, '水上乐园': 4000,
                  '森林丛林': 4500, '古镇古村': 3500, '园林花园': 3000}
DEFAULT_POI_STEPS = 2500
DETOUR_FACTOR = 1.3
TAXI_STEPS = 200  # 估算上下车与接驳步行；不代表出租车门到门。
# 名称含这些词的景点按坐船处理：游览主要在水上，步行远少于分类估算。
BOAT_WORDS = ('夜游', '游船', '游艇', '画舫', '观光船')
BOAT_STEPS = 300
# 体力版把长距离打车计成成本：同一天打车总里程超过该值要扣分/避免。
DAILY_TAXI_KM_BUDGET = 20.0
# 有 limited 同行人时，单段打车超过该值标注「车程较长」。
LONG_RIDE_M = 10000.0
# 午休插入门槛：当天累计步数达到上限的该比例，或已安排该数量的景点之后。
NOON_REST_MIN_FRACTION = 0.35
NOON_REST_MIN_POIS = 2


def distance_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (float(a['latitude']), float(a['longitude']),
                                               float(b['latitude']), float(b['longitude'])))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h)))) * DETOUR_FACTOR


def stride_m(travelers):
    return min(0.55 if p['mobility'] == 'limited' or p['age'] >= 65
               else 0.45 if p['age'] <= 8 else 0.7 for p in travelers)


def walking_steps(meters, travelers):
    return math.ceil(meters / stride_m(travelers))


def is_boat(poi):
    """坐船类项目（夜游/游船/游艇/画舫/观光船）：游览主要在水上，景点内步数按坐船算。"""
    name = poi.get('name') or ''
    return any(word in name for word in BOAT_WORDS)


def poi_steps(poi):
    if is_boat(poi):
        return BOAT_STEPS
    return CATEGORY_STEPS.get(poi.get('category'), DEFAULT_POI_STEPS)


def stair_risk(poi):
    return '可能有台阶（未核实）' if any(c in (poi['name'] + (poi.get('category') or ''))
                                            for c in '山峰寺塔岭洞') else ''


def transfer(a, b, travelers, threshold=800, taxi_at_threshold=False, flag_long_ride=False):
    meters = distance_m(a, b)
    taxi = meters >= threshold if taxi_at_threshold else meters > threshold
    steps = TAXI_STEPS if taxi else walking_steps(meters, travelers)
    row = dict(kind='transfer', name=f"{a['name']} → {b['name']}",
               mode='打车' if taxi else '步行', distance_m=round(meters, 1),
               walking_m=round(steps * stride_m(travelers) if taxi else meters, 1),
               steps=steps, estimated=True)
    # 体力版把长距离打车计成成本：有行动受限同行人时，单段超 10 公里提示车程较长。
    if taxi:
        row['taxi_m'] = round(meters, 1)
        if flag_long_ride and meters > LONG_RIDE_M:
            row['long_ride'] = True
    return row


def day_taxi_km(rows):
    """当天打车总公里数（估算，球面距离乘绕行系数，非导航里程）。"""
    return round(sum(r['distance_m'] for r in rows if r.get('mode') == '打车') / 1000.0, 2)


def noon_rest_due(rows, cap, visited):
    """午休只在当天累计步数达到上限 35% 以上，或已安排至少 2 个点之后才插入。

    否则走完第一个点（例如坐船只走几百步）就回酒店，反而浪费半天。
    """
    return rows and (sum(r['steps'] for r in rows) >= NOON_REST_MIN_FRACTION * cap
                     or visited >= NOON_REST_MIN_POIS)


def _noon_rest(rows, poi, hotel, profile, threshold, limited):
    """Insert a noon rest after `poi`; return the place the next transfer starts from."""
    if hotel and distance_m(poi, hotel) <= 5000:
        rows.append(transfer(poi, hotel, profile['travelers'], threshold, False, limited))
        rows.append(dict(kind='rest', name='午间回酒店休息', mode='午休',
                         distance_m=0, walking_m=0, steps=0, estimated=True))
        return hotel
    rows.append(dict(kind='rest', name='午间就近休息（具体场所待确认；酒店未知或超过5公里）',
                     mode='午休', distance_m=round(200*stride_m(profile['travelers']), 1),
                     walking_m=round(200*stride_m(profile['travelers']), 1), steps=200, estimated=True))
    return poi


def bill_day(date, route, profile, hotel=None, ordinary=False):
    rows = []
    threshold = 2000 if ordinary else 800
    limited = any(t['mobility'] == 'limited' for t in profile['travelers'])
    cap = profile['daily_step_cap']
    previous = hotel
    rest_before = bool(route and '夜游' in route[0]['name'] and profile['need_noon_rest'] and not ordinary)
    if rest_before:
        rows.append(dict(kind='rest', name='午间酒店休息（当天首个活动为夜游）' if hotel else '午间就近休息（具体场所待确认）',
                         mode='午休', distance_m=0 if hotel else round(200*stride_m(profile['travelers']), 1),
                         walking_m=0 if hotel else round(200*stride_m(profile['travelers']), 1),
                         steps=0 if hotel else 200, estimated=True))
    for index, poi in enumerate(route):
        if previous:
            rows.append(transfer(previous, poi, profile['travelers'], threshold, ordinary, limited))
        rows.append(dict(kind='visit', name=poi['name'], mode='景点内步行',
                         distance_m=round(poi_steps(poi)*stride_m(profile['travelers']), 1),
                         walking_m=round(poi_steps(poi)*stride_m(profile['travelers']), 1),
                         steps=poi_steps(poi), risk=stair_risk(poi), estimated=True))
        previous = poi
        # 午休插入时机：只在步数达到上限 35% 或已走完 2 个点之后，避免逛完第一个点就回酒店。
        if profile['need_noon_rest'] and not ordinary and not rest_before \
                and not any(r['kind'] == 'rest' for r in rows) and noon_rest_due(rows, cap, index + 1):
            previous = _noon_rest(rows, poi, hotel, profile, threshold, limited)
    if hotel and route:
        rows.append(transfer(previous, hotel, profile['travelers'], threshold, ordinary, limited))
    total = 0
    for row in rows:
        total += row['steps']
        row['cumulative_steps'] = total
        row['over_cap'] = total > cap
    taxi_km = day_taxi_km(rows)
    return dict(date=date, pois=list(route), bill=rows, total_steps=total, cap=cap,
                over_cap=total > cap, taxi_km=taxi_km,
                taxi_over_budget=not ordinary and taxi_km > DAILY_TAXI_KM_BUDGET,
                long_rides=sum(bool(r.get('long_ride')) for r in rows), estimated=True)
