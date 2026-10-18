"""Run with: python -m uvicorn stamina.server:app --host 127.0.0.1"""
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cli import create_plan
from .config import ROOT

app = FastAPI(title='体力预算规划师')


class PlanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


@app.post('/plan')
def plan(request: PlanRequest):
    try:
        return create_plan(request.query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=503, detail='旅行数据或画像服务暂不可用，请重试') from None


# Same origin as /plan, so the page needs no CORS. Mounted last so /plan wins.
app.mount('/', StaticFiles(directory=ROOT/'web', html=True), name='web')
