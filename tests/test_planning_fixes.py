from stamina.planner import best_day
from stamina.stamina import bill_day, poi_steps, BOAT_STEPS


def poi(name, lat, lon, category='博物馆', order=0):
    return dict(id=name, name=name, category=category, latitude=str(lat), longitude=str(lon),
                source_order=order)


HOTEL = dict(name='酒店', latitude='30.25', longitude='120.16')


def test_noon_rest_not_after_short_first_stop(profile):
    boat, museum = poi('西湖游船', 30.251, 120.161), poi('浙江省博物馆', 30.252, 120.162)
    day = bill_day(profile['dates'][0], [boat, museum, poi('中国丝绸博物馆', 30.253, 120.163)], profile, HOTEL)
    kinds = [r['kind'] for r in day['bill']]
    # 游船只有约 500 步，不能逛完第一个点就回酒店；第二个点之后才午休。
    first_rest = kinds.index('rest')
    assert [r['name'] for r in day['bill'][:first_rest] if r['kind'] == 'visit'] == ['西湖游船', '浙江省博物馆']


def test_noon_rest_after_heavy_first_stop(profile):
    zoo = poi('杭州动物园', 30.251, 120.161, category='动物园')
    day = bill_day(profile['dates'][0], [zoo, poi('博物馆', 30.252, 120.162)], profile, HOTEL)
    visits_before_rest = [r['name'] for r in day['bill'][:[r['kind'] for r in day['bill']].index('rest')]
                          if r['kind'] == 'visit']
    assert visits_before_rest == ['杭州动物园']  # 5000 步 ≥ 6000×35%


def test_boat_words_count_as_boat_ride():
    for name in ('西湖夜游', '京杭大运河游船', '钱塘江游轮', '钱塘江游艇', '秦淮画舫', '珠江观光船'):
        assert poi_steps(dict(name=name, category='城市观光')) == BOAT_STEPS
    assert poi_steps(dict(name='西湖', category='城市观光')) != BOAT_STEPS


def test_taxi_km_reported_and_long_ride_flagged(profile):
    near, far = poi('近点', 30.25, 120.16), poi('远点', 30.36, 120.16)  # ~16 km apart
    day = bill_day(profile['dates'][0], [near, far], profile, HOTEL)
    assert day['taxi_km'] > 10
    assert any(r.get('long_ride') for r in day['bill'])  # limited 成员 + 单段 >10km
    profile['travelers'] = [dict(age=35, mobility='normal')]
    day = bill_day(profile['dates'][0], [near, far], profile, HOTEL)
    assert not any(r.get('long_ride') for r in day['bill'])


def test_best_day_avoids_taxi_over_budget(profile):
    profile['need_noon_rest'] = False
    near = poi('近点', 30.251, 120.161, order=0)
    far = poi('远点', 30.40, 120.16, order=1)  # 打车往返远超 20 km
    day = best_day(profile['dates'][0], [far, near], profile, HOTEL)
    assert day['taxi_km'] <= 20
    assert [p['name'] for p in day['pois']] == ['近点']


def test_no_hotel_to_hotel_leg_after_noon_rest(profile):
    zoo = poi('杭州动物园', 30.251, 120.161, category='动物园')
    day = bill_day(profile['dates'][0], [zoo], profile, HOTEL)
    # 午休必须后面还有景点；只有一个点就是收工回酒店，不插午休，也不出现酒店到酒店。
    assert not any(r['kind'] == 'rest' for r in day['bill'])
    assert not any(r['name'] == '酒店 → 酒店' for r in day['bill'])


def test_rest_missing_flagged_when_order_prevents_it(profile):
    boat, museum = poi('西湖游船', 30.251, 120.161), poi('浙江省博物馆', 30.252, 120.162)
    assert bill_day(profile['dates'][0], [boat, museum], profile, HOTEL)['noon_rest_missing']
    zoo = poi('杭州动物园', 30.251, 120.161, category='动物园')
    assert not bill_day(profile['dates'][0], [zoo, museum], profile, HOTEL)['noon_rest_missing']
