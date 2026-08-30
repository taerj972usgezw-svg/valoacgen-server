import os
import json
import datetime
from typing import Optional, List
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="ValoAcGen Mobile Dashboard", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "accounts.json")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# 보안 설정 (환경 변수 또는 기본값)
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "valo2026")

class AccountItem(BaseModel):
    email: str
    password: str
    username: str
    birthdate: Optional[dict] = None
    status: Optional[str] = "success"
    created_at: Optional[str] = None

def load_accounts() -> List[dict]:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_accounts(accounts: List[dict]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def verify_key(request: Request, x_api_key: Optional[str] = Header(None), key: Optional[str] = None):
    # Header 또는 Query param으로 API Key 확인
    token = x_api_key or key or request.query_params.get("key")
    if API_SECRET_KEY and API_SECRET_KEY != "":
        if token != API_SECRET_KEY:
            raise HTTPException(status_code=401, detail="인증 실패: 올바른 API Key가 필요합니다.")
    return True

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request, key: Optional[str] = None):
    # 대시보드 페이지
    accounts = load_accounts()
    # 최신 순으로 정렬
    accounts_sorted = list(reversed(accounts))
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "accounts": accounts_sorted,
            "total_count": len(accounts),
            "api_key": key or ""
        }
    )

@app.get("/api/accounts")
async def api_get_accounts(auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    return {"status": "ok", "total": len(accounts), "accounts": list(reversed(accounts))}

@app.post("/api/sync")
async def api_sync_account(item: AccountItem, auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    record = {
        "email": item.email,
        "password": item.password,
        "username": item.username,
        "birthdate": item.birthdate or {},
        "status": item.status or "success",
        "created_at": item.created_at or datetime.datetime.now().isoformat(timespec="seconds")
    }
    # 중복 체크 (username 기준)
    if not any(a.get("username") == item.username for a in accounts):
        accounts.append(record)
        save_accounts(accounts)
        return {"status": "ok", "message": "동기화 완료", "account": record}
    return {"status": "exists", "message": "이미 존재하는 계정입니다."}

@app.post("/api/clear")
async def api_clear_accounts(auth: bool = Depends(verify_key)):
    save_accounts([])
    return {"status": "ok", "message": "모든 계정 기록이 초기화되었습니다."}

@app.get("/api/export", response_class=PlainTextResponse)
async def api_export_txt(auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    lines = []
    for acc in accounts:
        if acc.get("status") == "success":
            lines.append(f"{acc.get('username')}:{acc.get('password')}:{acc.get('email')}")
    return "\n".join(lines)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"[*] Starting server on 0.0.0.0:{port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port)
