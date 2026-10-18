import datetime as dt
import json

import pytest

from stamina.profile import parse_profile, validate_profile


@pytest.mark.parametrize('age,mobility,cap', [(68,'normal',6000),(35,'limited',6000),
                                             (6,'normal',7000),(35,'normal',12000)])
def test_default_caps(profile, age, mobility, cap):
    profile.update(travelers=[dict(age=age, mobility=mobility)], daily_step_cap=None)
    assert validate_profile(profile)['daily_step_cap'] == cap


def test_weakest_default(profile):
    profile['daily_step_cap'] = None
    assert validate_profile(profile)['daily_step_cap'] == 6000


def test_retry_once(profile):
    calls = []
    def complete(messages):
        calls.append(messages[:])
        return 'invalid' if len(calls) == 1 else json.dumps(profile)
    assert parse_profile('杭州两天', complete, dt.date(2026,10,18)) == profile
    assert len(calls) == 2
    assert '2026-10-18' in calls[0][0]['content']


def test_retry_failure():
    calls = []
    def complete(messages):
        calls.append(1)
        return '{}'
    with pytest.raises(ValueError, match='两次失败'):
        parse_profile('杭州', complete)
    assert len(calls) == 2


@pytest.mark.parametrize('field,value', [('daily_step_cap',True),('daily_step_cap',-1),
    ('need_noon_rest','yes'),('budget_per_night',float('nan')),('dates',['2026-02-30']),
    ('travelers',[{'age':-1,'mobility':'normal'}])])
def test_invalid_fields(profile, field, value):
    profile[field] = value
    with pytest.raises(ValueError):
        validate_profile(profile)
