"""python -X utf8 -m stamina.cli '旅行需求'"""
import argparse
from pathlib import Path

from .config import ROOT
from .profile import parse_profile
from .planner import collect_and_plan
from .guardrails import explain_plan
from .render import markdown, json_text


def create_plan(query):
    plan = explain_plan(collect_and_plan(parse_profile(query)))
    from .config import llm_settings
    plan['llm_model'] = llm_settings()[1]
    return plan


def main():
    parser = argparse.ArgumentParser(description='体力预算规划师')
    parser.add_argument('query')
    args = parser.parse_args()
    try:
        plan = create_plan(args.query)
        out = ROOT/'out'
        out.mkdir(exist_ok=True)
        (out/'plan.md').write_text(markdown(plan), encoding='utf-8')
        (out/'plan.json').write_text(json_text(plan), encoding='utf-8')
    except Exception as exc:
        # Do not echo arbitrary service errors or credentials.
        print('规划失败：' + (str(exc) if isinstance(exc, ValueError) else '请检查画像服务、飞猪 CLI 和网络连接'))
        return 1
    for ordinary, active in zip(plan['ordinary'], plan['stamina']):
        print(f"{active['date']} 普通版 {ordinary['total_steps']} 步；体力版 {active['total_steps']} / {active['cap']} 步（均为估算）")
    print('已写入 out/plan.md 和 out/plan.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
