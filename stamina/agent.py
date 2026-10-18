"""Minimal tool-calling loop: the model picks flyai searches, then answers."""
import datetime
import json

from . import tools
from .llm import client_and_model

SYSTEM = "你是旅行规划助手。所有酒店、景点、价格必须来自工具返回的数据，不得编造。"
MAX_ROUNDS = 6


def ask(question: str) -> dict:
    client, model = client_and_model()
    today = datetime.date.today().isoformat()
    system = f"{SYSTEM}\n今天是 {today}；用户没说年份时，日期取今天之后最近的那一天。"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    trace = []
    for round_no in range(1, MAX_ROUNDS + 1):
        last = round_no == MAX_ROUNDS
        resp = client.chat.completions.create(
            model=model, messages=messages,
            tools=None if last else tools.SPECS, temperature=0.2)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"answer": msg.content or "", "rounds": round_no, "trace": trace}
        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = tools.call(tc.function.name, args)
            except (json.JSONDecodeError, TypeError) as e:
                args, result = tc.function.arguments, {"error": f"bad arguments: {e}"}
            trace.append({"tool": tc.function.name, "args": args, "n": len(result.get("items", []))})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False)})
    return {"answer": "", "rounds": MAX_ROUNDS, "trace": trace}
