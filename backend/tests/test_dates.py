import pytest
from fastapi import HTTPException
from app.dates import normalize_date
from app.agent_models import AgentQuestion
from app.agent_tools import encoded


@pytest.mark.parametrize(('value','expected'),[
    ('10/17/2026','2026-10-17'),('1/2/2000','2000-01-02'),('2000-01-02','2000-01-02'),
    ('January 2nd, 2000','2000-01-02'),('Jan 2 2000','2000-01-02'),('2/29/2000','2000-02-29')])
def test_complete_dates_are_normalized(value,expected):
    assert normalize_date(value)==expected


@pytest.mark.parametrize('value',['2/29/2001','13/2/2000','April 31, 2000','March fifth','1/2/03','20260203','2026-2-3'])
def test_bad_or_incomplete_dates_are_not_guessed(value):
    with pytest.raises(ValueError):normalize_date(value)


def test_date_rules_use_normalized_value():
    q=AgentQuestion(id='birth',original_text='Birth date',simplified_question='What is your birth date?',input_type='date',validation={'kind':'past_date'})
    assert encoded(q,'January 2, 2000')=='2000-01-02'
    with pytest.raises(HTTPException) as error:encoded(q,'1/2/2999')
    assert error.value.status_code==422


@pytest.mark.parametrize('text',['January 2nd, 2000','2nd of January, 2000','2 January 2000'])
def test_spoken_transcript_styles_share_date_validation(text):
    q=AgentQuestion(id='date',original_text='Date',simplified_question='What date?',input_type='date')
    assert encoded(q,text)=='2000-01-02'
