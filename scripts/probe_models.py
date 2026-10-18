"""Check which endpoint/model pairs can do a tool call. Usage: python -X utf8 scripts/probe_models.py BASE_URL KEY_FILE MODEL [MODEL...]"""
import sys
from pathlib import Path

from openai import OpenAI

TOOLS = [{"type": "function", "function": {
    "name": "search_hotel", "description": "搜索酒店",
    "parameters": {"type": "object", "properties": {
        "dest_name": {"type": "string"}, "poi_name": {"type": "string"}},
        "required": ["dest_name"]}}}]

base, key_file, *models = sys.argv[1:]
client = OpenAI(base_url=base, api_key=Path(key_file).read_text(encoding="utf-8").strip(), timeout=90)
for model in models:
    try:
        r = client.chat.completions.create(
            model=model, tools=TOOLS, tool_choice="auto",
            messages=[{"role": "user", "content": "查一下杭州西湖附近的酒店"}])
        calls = r.choices[0].message.tool_calls
        print(f"OK   {model}: {[(c.function.name, c.function.arguments) for c in calls] if calls else 'no tool call: ' + (r.choices[0].message.content or '')[:80]}")
    except Exception as e:
        print(f"FAIL {model}: {str(e)[:160]}")
