"""Conservative sentence-level filter grounded in each POI's description."""
import re

PROTECTED_TERMS = ('电梯', '无障碍', '观光车', '索道', '轮椅')
# Additional physical claims observed during live verification are also source-gated.
PHYSICAL_TERMS = ('平坦', '休息区域', '休息区', '座椅', '宽敞', '室内', '坡度')


def filter_claims(text, description, poi_name=''):
    kept, removed = [], []
    for sentence in re.findall(r'[^。！？.!?\n]+[。！？.!?]?|\n', text):
        unsupported = [word for word in PROTECTED_TERMS + PHYSICAL_TERMS if word in sentence and word not in (description or '')]
        if unsupported:
            removed.append(dict(poi=poi_name, sentence=sentence.strip(), unsupported_terms=unsupported))
        else:
            kept.append(sentence)
    return ''.join(kept).strip(), removed


def explain_plan(plan, complete=None):
    from .llm import client_and_model
    from .stamina import poi_steps
    pois = {p['name']: p for day in plan['stamina'] for p in day['pois']}
    payload = dict(profile=plan['profile'],
                   days=[dict(date=d['date'], total_steps=d['total_steps'],
                              pois=[dict(name=p['name'], estimated_steps=poi_steps(p)) for p in d['pois']],
                              bill=d['bill']) for d in plan['stamina']],
                   descriptions={name: p.get('description', '') for name, p in pois.items()})
    import json
    messages = [{'role': 'system', 'content': '只依据给定画像和已计算的结果解释选择理由，不能选择景点、酒店、排序或计算步数。'
                 '文字仅讨论已给定的估算步数、累计步数、上限、午休和打车，不得做新计算。'
                 '不要描述景色、场馆、道路、地形、室内外环境或任何设施；不要添加票务、开放时间等事实。'
                 '输出 JSON {"explanations":[{"poi":"精确景点名","text":"一句理由"}]}。'
                 '每条只涉及该景点，保持简短；数字必须原样引用已给定计算值。'},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    try:
        if complete is None:
            client, model = client_and_model()
            def complete(msgs):
                return client.chat.completions.create(model=model, messages=msgs,
                    response_format={'type': 'json_object'}, temperature=0).choices[0].message.content
        result = json.loads(complete(messages))
        explanations = result['explanations']
        if not isinstance(explanations, list):
            raise ValueError('invalid explanations')
        kept = []
        for entry in explanations:
            name, text = entry['poi'], entry['text']
            if name not in pois or not isinstance(text, str):
                continue
            clean, removed = filter_claims(text, pois[name].get('description', ''), name)
            plan['removed_claims'].extend(removed)
            if clean:
                kept.append(dict(poi=name, text=clean))
        plan['explanation'] = kept
    except Exception:
        plan['explanation'] = []
        plan['warnings'].append('解释文字服务不可用或格式错误；确定性计算结果仍可使用。')
    return plan
