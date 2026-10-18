"""Markdown and JSON render the same plan object."""
import json
from .stamina import stair_risk


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def step_label(day):
    label = f"{day['total_steps']} / {day['cap']} 步（估算）"
    return f'<span style="color:red">{label}，超限</span>' if day['over_cap'] else label


def markdown(plan):
    p = plan['profile']
    lines = ['# 体力预算规划师', '', f"{p['city']} · {'、'.join(p['dates'])}", '',
             '所有距离与步数均为估算；打车接驳每段计 200 步（估算）。', '',
             '## 普通版 vs 体力版', '', '| 日期 | 普通版 | 普通版步数 | 体力版 | 体力版步数 |',
             '|---|---|---|---|---|']
    for normal, active in zip(plan['ordinary'], plan['stamina']):
        names = lambda d: ' → '.join(x['name'] for x in d['pois']) or '空闲（没有符合体力预算的候选）'
        lines.append(f"| {active['date']} | {cell(names(normal))} | {step_label(normal)} | {cell(names(active))} | {step_label(active)} |")
    lines += ['', '## 体力账单', '', '包含已选酒店出发、回程和午休接驳；景点内部米数由分类步数与同行最短步长换算（估算）。']
    for day in plan['stamina']:
        lines += ['', f"### {day['date']} · {step_label(day)}", '',
                  '| 路段 / 活动 | 方式 | 路程米（估算） | 步行米（估算） | 步数（估算） | 累计 / 上限（估算） | 风险 |',
                  '|---|---|---:|---:|---:|---|---|']
        for row in day['bill']:
            cumulative = f"{row['cumulative_steps']} / {day['cap']}"
            if row['over_cap']:
                cumulative = f'<span style="color:red">{cumulative} 超限</span>'
            lines.append(f"| {cell(row['name'])} | {row['mode']} | {row['distance_m']} | {row['walking_m']} | {row['steps']} | {cumulative} | {cell(row.get('risk', ''))} |")
    lines += ['', '## 酒店推荐', '']
    hotel = plan.get('hotel')
    if hotel:
        lines += [f"### {hotel['name']}", '', hotel['reason'], '', '报价为搜索返回价格，房型、人数、含税及可订情况以预订页面为准。']
        if plan.get('hotel_stay'):
            stay = plan['hotel_stay']
            lines += ['', f"查询入住 {stay['check_in']}，退房 {stay['check_out']}。"]
        image = hotel.get('mainPic') or hotel.get('picUrl')
        if image:
            lines += ['', f'![]({image})']
        if hotel.get('detailUrl'):
            lines += ['', f"[飞猪预订]({hotel['detailUrl']})"]
    else:
        lines += ['暂无满足坐标、价格与预算条件的酒店。']
    if plan.get('hotel_compare'):
        lines += ['', '## 酒店对比（同一行程，换酒店重算）', '',
                  '| 酒店 | 每晚报价 | 距首日景点（直线米） | 每天步数（估算） |', '|---|---|---:|---|']
        for h in plan['hotel_compare']:
            steps = '；'.join(f"{d['date']} {d['total_steps']}{'（超限）' if d['over_cap'] else ''}" for d in h['days'])
            lines.append(f"| {cell(h['name'])}{'（已选）' if h['chosen'] else ''} | {cell(h.get('price'))} | {h['distance_m']} | {steps} |")
    lines += ['', '## 景点与飞猪预订', '']
    seen = set()
    for day in plan['ordinary'] + plan['stamina']:
        for poi in day['pois']:
            if poi['name'] in seen:
                continue
            seen.add(poi['name'])
            lines += [f"### {poi['name']}", '']
            if stair_risk(poi):
                lines += [stair_risk(poi), '']
            ticket = poi.get('ticketInfo')
            if ticket and ticket.get('price') is not None:
                lines += [f"飞猪返回门票价格：{ticket['price']}（日期：{ticket.get('priceDate') or '未提供'}）", '']
            image = poi.get('picUrl') or poi.get('mainPic')
            if image:
                lines += [f'![]({image})', '']
            url = poi.get('jumpUrl') or poi.get('detailUrl')
            if url:
                lines += [f'[飞猪预订]({url})', '']
    lines += ['## 规划说明', '']
    for item in plan.get('explanation') or []:
        lines += [f"- {item['poi']}：{item['text']}"]
    lines += ['', '## 使用边界', ''] + ['- '+w for w in plan['warnings']]
    if plan.get('mode') == 'fallback':
        lines += ['', f"本次使用确定性规划兜底：{plan.get('fallback_reason') or '原因未记录'}"]
    if plan.get('tool_trace'):
        lines += ['', '## 智能体决策过程', '', '| # | 工具 | 参数 | 结果 |', '|---|---|---|---|']
        for i, step in enumerate(plan['tool_trace'], 1):
            args = '；'.join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in (step.get('args') or {}).items())
            outcome = step['error'] if step.get('error') else ('通过校验' if step.get('ok') else f"{step.get('n', 0)} 条")
            lines.append(f"| {i} | {step['tool']} | {cell(args)} | {cell(outcome)} |")
    lines += ['', '基于飞猪 fly.ai 实时数据', ''] + (plan.get('system_messages') or ['飞猪平台提示：本次接口未返回 systemMessage。'])
    return '\n'.join(lines).rstrip()+'\n'


def json_text(plan):
    return json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
