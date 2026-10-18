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


def poi_steps(poi):
    if '游船' in poi['name']:
        return 300
    return CATEGORY_STEPS.get(poi.get('category'), DEFAULT_POI_STEPS)


def stair_risk(poi):
    return '可能有台阶（未核实）' if any(c in (poi['name'] + (poi.get('category') or ''))
                                            for c in '山峰寺塔岭洞') else ''


def transfer(a, b, travelers, threshold=800, taxi_at_threshold=False):
    meters = distance_m(a, b)
    taxi = meters >= threshold if taxi_at_threshold else meters > threshold
    steps = TAXI_STEPS if taxi else walking_steps(meters, travelers)
    return dict(kind='transfer', name=f"{a['name']} → {b['name']}",
                mode='打车' if taxi else '步行', distance_m=round(meters, 1),
                walking_m=round(steps * stride_m(travelers) if taxi else meters, 1),
                steps=steps, estimated=True)


def bill_day(date, route, profile, hotel=None, ordinary=False):
    rows = []
    threshold = 2000 if ordinary else 800
    previous = hotel
    rest_before = bool(route and '夜游' in route[0]['name'] and profile['need_noon_rest'] and not ordinary)
    if rest_before:
        rows.append(dict(kind='rest', name='午间酒店休息（当天首个活动为夜游）' if hotel else '午间就近休息（具体场所待确认）',
                         mode='午休', distance_m=0 if hotel else round(200*stride_m(profile['travelers']), 1),
                         walking_m=0 if hotel else round(200*stride_m(profile['travelers']), 1),
                         steps=0 if hotel else 200, estimated=True))
    for index, poi in enumerate(route):
        if previous:
            rows.append(transfer(previous, poi, profile['travelers'], threshold, ordinary))
        rows.append(dict(kind='visit', name=poi['name'], mode='景点内步行',
                         distance_m=round(poi_steps(poi)*stride_m(profile['travelers']), 1),
                         walking_m=round(poi_steps(poi)*stride_m(profile['travelers']), 1),
                         steps=poi_steps(poi), risk=stair_risk(poi), estimated=True))
        previous = poi
        if index == 0 and profile['need_noon_rest'] and not ordinary and not rest_before:
            if hotel and distance_m(poi, hotel) <= 5000:
                rows.append(transfer(poi, hotel, profile['travelers'], threshold))
                rows.append(dict(kind='rest', name='午间回酒店休息', mode='午休',
                                 distance_m=0, walking_m=0, steps=0, estimated=True))
                previous = hotel
            else:
                rows.append(dict(kind='rest', name='午间就近休息（具体场所待确认；酒店未知或超过5公里）',
                                 mode='午休', distance_m=round(200*stride_m(profile['travelers']), 1),
                                 walking_m=round(200*stride_m(profile['travelers']), 1), steps=200, estimated=True))
    if hotel and route:
        rows.append(transfer(previous, hotel, profile['travelers'], threshold, ordinary))
    total = 0
    for row in rows:
        total += row['steps']
        row['cumulative_steps'] = total
        row['over_cap'] = total > profile['daily_step_cap']
    return dict(date=date, pois=list(route), bill=rows, total_steps=total,
                cap=profile['daily_step_cap'], over_cap=total > profile['daily_step_cap'], estimated=True)
