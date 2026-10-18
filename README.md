# Stamina Trip（体力预算规划师）

2026 飞猪 AI 旅行创新大赛参赛作品（开发中）。按同行人的体力安排行程：老人、孩子、膝盖不好的人，一天能走多少、要不要坐车、哪里歇脚。

- 实时数据：飞猪官方 flyai CLI（酒店、景点）
- 推理：OpenAI 兼容接口；提交版使用阿里云百炼（通义千问）

## 运行

```bash
npm i -g @fly-ai/flyai-cli
pip install openai
cp .env.example .env   # 填 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY
python -X utf8 scripts/smoke.py
```
