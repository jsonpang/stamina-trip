"""Tools the agent may call. Each returns a compact JSON-able dict built only from flyai data."""
from . import flyai

SPECS = [
    {"type": "function", "function": {
        "name": "search_hotel",
        "description": "用飞猪实时数据搜索酒店。dest_name 必须是城市或区县；poi_name 用来找某个景点附近的酒店。",
        "parameters": {"type": "object", "properties": {
            "dest_name": {"type": "string"},
            "poi_name": {"type": "string"},
            "check_in_date": {"type": "string", "description": "YYYY-MM-DD"},
            "check_out_date": {"type": "string", "description": "YYYY-MM-DD"},
            "max_price": {"type": "integer", "description": "每晚最高价（元）"},
        }, "required": ["dest_name"]}}},
    {"type": "function", "function": {
        "name": "search_poi",
        "description": "用飞猪实时数据搜索景点，返回坐标、门票、简介。",
        "parameters": {"type": "object", "properties": {
            "city_name": {"type": "string"},
            "keyword": {"type": "string"},
            "category": {"type": "string"},
        }, "required": ["city_name"]}}},
]

HOTEL_FIELDS = ("name", "price", "star", "interestsPoi", "address", "latitude", "longitude", "detailUrl", "mainPic")
POI_FIELDS = ("name", "category", "address", "latitude", "longitude", "freePoiStatus", "ticketInfo", "jumpUrl", "mainPic")


def _trim(result: dict, fields: tuple, limit: int) -> dict:
    if result.get("status") != 0:
        return {"error": result.get("error") or result.get("message") or "flyai error"}
    items = (result.get("data") or {}).get("itemList") or []
    return {"items": [{k: it.get(k) for k in fields} for it in items[:limit]]}


def call(name: str, args: dict) -> dict:
    if name == "search_hotel":
        return _trim(flyai.search_hotel(**args), HOTEL_FIELDS, 6)
    if name == "search_poi":
        return _trim(flyai.search_poi(**args), POI_FIELDS, 6)
    return {"error": f"unknown tool {name}"}
