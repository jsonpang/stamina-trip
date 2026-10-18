"""Offline deterministic replay of captured flyai responses."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from stamina.planner import collect_and_plan
from stamina.profile import validate_profile
from stamina.render import markdown, json_text


def main():
    def read(name):
        return json.loads((ROOT/'tests'/'fixtures'/(name+'.json')).read_text(encoding='utf-8'))
    def poi(city, **params):
        name = {'城市观光': 'poi_city', '博物馆': 'poi_museum'}.get(params.get('category'))
        return read(name or ('poi_boat' if params.get('keyword') else 'poi_hangzhou'))
    profile = validate_profile(dict(city='杭州', dates=['2026-11-07', '2026-11-08'],
        travelers=[dict(age=68, mobility='normal'), dict(age=68, mobility='limited'),
                   dict(age=6, mobility='normal')], daily_step_cap=6000,
        need_noon_rest=True, budget_per_night=None))
    plan = collect_and_plan(profile, poi, lambda *a, **k: read('hotel_hangzhou'))
    plan['data_retrieved_at'] = read('metadata')['retrieved_at']
    plan['warnings'].append('离线回放历史夹具；本次没有重新查询实时数据或调用 LLM。')
    (ROOT/'out').mkdir(exist_ok=True)
    (ROOT/'out'/'replay.md').write_text(markdown(plan), encoding='utf-8')
    (ROOT/'out'/'replay.json').write_text(json_text(plan), encoding='utf-8')
    for normal, active in zip(plan['ordinary'], plan['stamina']):
        assert active['total_steps'] <= 6000 < normal['total_steps']
        print(f"{active['date']}: ordinary={normal['total_steps']}, stamina={active['total_steps']}/6000 (estimated)")


if __name__ == '__main__':
    main()
