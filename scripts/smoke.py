"""End-to-end check: LLM + flyai. Usage: python -X utf8 scripts/smoke.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stamina.agent import ask  # noqa: E402

r = ask("两位老人带一个孩子，11月7日到9日去杭州玩两天，想住西湖附近、少走路。推荐两家酒店和两个景点。")
print("rounds:", r["rounds"])
for t in r["trace"]:
    print("tool:", t)
print(r["answer"][:1500])
