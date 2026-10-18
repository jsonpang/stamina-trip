import json
import socket
from pathlib import Path

import pytest

from stamina.profile import validate_profile

FIXTURES = Path(__file__).parent/'fixtures'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original_connect = socket.socket.connect
    def blocked(*args, **kwargs):
        raise AssertionError('Tests must be offline')
    def local_eventloop_only(sock, address):
        # Windows asyncio uses loopback for its internal socketpair wakeup.
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_connect(sock, address)
        return blocked()
    monkeypatch.setattr(socket.socket, 'connect', local_eventloop_only)
    from stamina import flyai
    monkeypatch.setattr(flyai.subprocess, 'run', blocked)
    monkeypatch.setattr('stamina.profile.client_and_model', blocked)
    monkeypatch.setattr('stamina.llm.client_and_model', blocked)


@pytest.fixture
def profile():
    return validate_profile(dict(city='杭州', dates=['2026-11-07', '2026-11-08'],
        travelers=[dict(age=68, mobility='normal'), dict(age=68, mobility='limited'),
                   dict(age=6, mobility='normal')], daily_step_cap=6000,
        need_noon_rest=True, budget_per_night=None))


@pytest.fixture
def raw_pois():
    return [json.loads((FIXTURES/(n+'.json')).read_text(encoding='utf-8'))
            for n in ('poi_hangzhou', 'poi_city', 'poi_museum', 'poi_boat')]


@pytest.fixture
def raw_hotels():
    return json.loads((FIXTURES/'hotel_hangzhou.json').read_text(encoding='utf-8'))
