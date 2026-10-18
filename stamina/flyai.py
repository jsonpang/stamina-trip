"""Thin wrapper over the official flyai CLI (npm i -g @fly-ai/flyai-cli).

Every command prints one line of JSON to stdout. We return the parsed dict and
never invent data: on failure the caller gets {"status": -1, "error": ...}.
"""
import json
import shutil
import subprocess

from . import config  # Load project .env before starting the CLI subprocess.

TIMEOUT_S = 60


def _flyai_bin() -> str:
    path = shutil.which("flyai")
    if not path:
        raise RuntimeError("flyai CLI not found; run: npm i -g @fly-ai/flyai-cli")
    return path


def run(command: str, **params) -> dict:
    args = [_flyai_bin(), command]
    for name, value in params.items():
        if value in (None, ""):
            continue
        args += ["--" + name.replace("_", "-"), str(value)]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"status": -1, "error": f"flyai {command} timed out after {TIMEOUT_S}s"}
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    # The CLI sometimes logs a libuv assertion on exit; the JSON line on stdout is still valid.
    for line in reversed(out.splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {"status": -1, "error": f"flyai {command} returned no JSON (exit {proc.returncode})"}


def search_hotel(dest_name, poi_name=None, check_in_date=None, check_out_date=None,
                 max_price=None, sort=None) -> dict:
    return run("search-hotel", dest_name=dest_name, poi_name=poi_name,
               check_in_date=check_in_date, check_out_date=check_out_date,
               max_price=max_price, sort=sort)


def search_poi(city_name, keyword=None, category=None) -> dict:
    return run("search-poi", city_name=city_name, keyword=keyword, category=category)
