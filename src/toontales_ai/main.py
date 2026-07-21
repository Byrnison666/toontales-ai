from fastapi import FastAPI

from toontales_ai.api.v1.auth import router as auth_router
from toontales_ai.api.v1.runs import router as runs_router
from toontales_ai.api.v1.ws import router as ws_router

app = FastAPI(title="ToonTales AI")

app.include_router(auth_router)
app.include_router(runs_router)
app.include_router(ws_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
