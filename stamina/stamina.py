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
BOAT_WORDS = ('夜游', '游船', '游轮', '游艇', '画舫', '观光船')
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


def person_stride(person):
    return 0.55 if person['mobility'] == 'limited' or person['age'] >= 65 else 0.45 if person['age'] <= 8 else 0.7


def person_default_cap(person):
    return 6000 if person['mobility'] == 'limited' or person['age'] >= 65 else 7000 if person['age'] <= 8 else 12000


def reference_traveler(travelers):
    """每日步数上限保护的那个人：默认上限最低者，同档优先行动受限者。步数按此人步长计。"""
    return min(travelers, key=lambda p: (person_default_cap(p), p['mobility'] != 'limited', -p['age']))


def stride_m(travelers):
    return person_stride(reference_traveler(travelers))


def per_person_steps(rows, travelers):
    """每个同行人各自约走多少步：同样的步行米数除以各自步长（估算）。"""
    meters = sum(r['walking_m'] for r in rows)
    reference = reference_traveler(travelers)
    return [dict(age=p['age'], mobility=p['mobility'], stride_m=person_stride(p),
                 steps=round(meters / person_stride(p)), reference=p is reference) for p in travelers]


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
        # 午休插入时机：只在步数达到上限 35% 或已走完 2 个点之后，避免逛完第一个点就回酒店；
        # 之后必须还有景点，否则只是收工回酒店。
        if profile['need_noon_rest'] and not ordinary and not rest_before \
                and not any(r['kind'] == 'rest' for r in rows) and index < len(route) - 1 \
                and noon_rest_due(rows, cap, index + 1):
            previous = _noon_rest(rows, poi, hotel, profile, threshold, limited)
    # 午休已回到酒店且之后没有景点时，不再加一段酒店到酒店。
    if hotel and route and previous is not hotel:
        rows.append(transfer(previous, hotel, profile['travelers'], threshold, ordinary, limited))
    return _close_day(date, route, rows, profile, ordinary)


def _close_day(date, route, rows, profile, ordinary):
    cap = profile['daily_step_cap']
    total = 0
    for row in rows:
        total += row['steps']
        row['cumulative_steps'] = total
        row['over_cap'] = total > cap
    taxi_km = day_taxi_km(rows)
    return dict(date=date, pois=list(route), bill=rows, total_steps=total, cap=cap,
                per_person=per_person_steps(rows, profile['travelers']),
                over_cap=total > cap, taxi_km=taxi_km,
                taxi_over_budget=not ordinary and taxi_km > DAILY_TAXI_KM_BUDGET,
                long_rides=sum(bool(r.get('long_ride')) for r in rows),
                noon_rest_missing=bool(profile['need_noon_rest'] and not ordinary and len(route) >= 2
                                       and not any(r['kind'] == 'rest' for r in rows)),
                estimated=True)


# 园内模式：乐园里项目之间只能步行；项目内步数按类型估算，排队站立不计步。
PARK_RADIUS_M = 2500  # 距乐园主坐标的直线距离，判定是否园内项目
SHOW_WORDS = ('剧场', '剧院', '演出', '秀', '欢唱', '盛会')  # 巡游多为站着看，不算坐
THRILL_WORDS = ('过山车', '矿山车', '光轮', '漂流', '飞行器', '跳楼')
RIDE_WORDS = THRILL_WORDS + ('奇遇', '营救', '专列', '奇航', '历险', '之战', '旋转', '飞椅', '嘉年华', '小火车')
HALL_WORDS = ('馆', '池', '展')
PARK_ITEM_STEPS = {'show': 150, 'ride': 300, 'hall': 800, 'area': 1500, 'other': 600}
PARK_ITEM_MODES = {'show': '坐着看演出', 'ride': '乘坐项目', 'hall': '展馆参观', 'area': '园区游览', 'other': '园内游览'}


def park_item_kind(item):
    name, category = item.get('name') or '', item.get('category') or ''
    if category == '剧院剧场' or any(w in name for w in SHOW_WORDS):
        return 'show'
    if any(w in name for w in RIDE_WORDS):
        return 'ride'
    if category == '海洋馆' or any(w in name for w in HALL_WORDS):
        return 'hall'
    if category in ('公园乐园', '文创街区', '主题乐园') or name.endswith(('世界', '岛', '湾', '花园', '大街', '小镇', '城')):
        return 'area'
    return 'other'


def park_item_risk(item, travelers):
    risks = [stair_risk(item)] if stair_risk(item) else []
    if any(w in (item.get('name') or '') for w in THRILL_WORDS) and any(t['age'] <= 12 for t in travelers):
        risks.append('儿童可能受身高限制（未核实）')
    return '；'.join(risks)


def walk(a, b, travelers):
    meters = distance_m(a, b)
    return dict(kind='transfer', name=f"{a['name']} → {b['name']}", mode='园内步行',
                distance_m=round(meters, 1), walking_m=round(meters, 1),
                steps=walking_steps(meters, travelers), estimated=True)


def bill_park_day(date, park, items, profile, hotel=None, ordinary=False):
    """一天在同一个乐园：酒店往返乐园入口照常计，入口与项目之间、项目之间全部步行。"""
    travelers = profile['travelers']
    limited = any(t['mobility'] == 'limited' for t in travelers)
    rows = []
    if hotel and items:
        rows.append(transfer(hotel, park, travelers, 2000 if ordinary else 800, ordinary, limited))
    previous = park
    for index, item in enumerate(items):
        rows.append(walk(previous, item, travelers))
        kind = park_item_kind(item)
        steps = PARK_ITEM_STEPS[kind]
        rows.append(dict(kind='visit', name=item['name'], mode=PARK_ITEM_MODES[kind],
                         distance_m=round(steps*stride_m(travelers), 1), walking_m=round(steps*stride_m(travelers), 1),
                         steps=steps, risk=park_item_risk(item, travelers), seated=kind == 'show', estimated=True))
        previous = item
        if profile['need_noon_rest'] and not ordinary and not any(r['kind'] == 'rest' for r in rows) \
                and index < len(items) - 1 and noon_rest_due(rows, profile['daily_step_cap'], index + 1):
            rows.append(dict(kind='rest', name='园内午间坐下休息（餐厅或座位，场所待确认）', mode='午休',
                             distance_m=0, walking_m=0, steps=0, estimated=True))
    if items:
        rows.append(walk(previous, park, travelers))
        if hotel:
            rows.append(transfer(park, hotel, travelers, 2000 if ordinary else 800, ordinary, limited))
    return dict(_close_day(date, items, rows, profile, ordinary), park=park['name'])
