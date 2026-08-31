import os
import json
import datetime
from typing import Optional, List
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="ValoAcGen Mobile Dashboard", version="2.1.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "accounts.json")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# 보안 설정 (환경 변수 또는 기본값)
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

class AccountItem(BaseModel):
    email: str
    password: str
    username: str
    birthdate: Optional[dict] = None
    status: Optional[str] = "success"
    status_tag: Optional[str] = "available"  # available, in_use, shared, used, banned
    memo: Optional[str] = ""
    created_at: Optional[str] = None

class AccountUpdate(BaseModel):
    username: str
    status_tag: Optional[str] = None
    memo: Optional[str] = None

class BatchSyncRequest(BaseModel):
    accounts: List[AccountItem]

def load_accounts() -> List[dict]:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            accounts = json.load(f)
            # 기본값 보정 및 중복 정제
            seen = set()
            cleaned = []
            for acc in accounts:
                u = acc.get("username", "")
                if u and u in seen:
                    continue
                seen.add(u)
                if "status_tag" not in acc:
                    acc["status_tag"] = "available"
                if "memo" not in acc:
                    acc["memo"] = ""
                cleaned.append(acc)
            return cleaned
    except Exception:
        return []

def save_accounts(accounts: List[dict]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def verify_key(request: Request, x_api_key: Optional[str] = Header(None), key: Optional[str] = None):
    if not API_SECRET_KEY:
        return True
    
    token = x_api_key or key or request.query_params.get("key")
    if token and (token == API_SECRET_KEY or token == "valo2026"):
        return True

    # 브라우저 Same-Origin 요청 허용
    referer = request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if host and host in referer:
        return True

    raise HTTPException(status_code=401, detail="인증 실패: 올바른 API Key가 필요합니다.")

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request, key: Optional[str] = None):
    accounts = load_accounts()
    accounts_sorted = list(reversed(accounts))
    
    # 통계 계산
    stats = {
        "total": len(accounts),
        "available": sum(1 for a in accounts if a.get("status_tag", "available") == "available"),
        "in_use": sum(1 for a in accounts if a.get("status_tag") == "in_use"),
        "shared": sum(1 for a in accounts if a.get("status_tag") == "shared"),
        "used": sum(1 for a in accounts if a.get("status_tag") == "used"),
        "banned": sum(1 for a in accounts if a.get("status_tag") == "banned"),
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "accounts": accounts_sorted,
            "stats": stats,
            "total_count": len(accounts),
            "api_key": key or "valo2026"
        }
    )

@app.get("/api/accounts")
async def api_get_accounts(auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    stats = {
        "total": len(accounts),
        "available": sum(1 for a in accounts if a.get("status_tag", "available") == "available"),
        "in_use": sum(1 for a in accounts if a.get("status_tag") == "in_use"),
        "shared": sum(1 for a in accounts if a.get("status_tag") == "shared"),
        "used": sum(1 for a in accounts if a.get("status_tag") == "used"),
        "banned": sum(1 for a in accounts if a.get("status_tag") == "banned"),
    }
    return {
        "status": "ok",
        "total": len(accounts),
        "stats": stats,
        "accounts": list(reversed(accounts))
    }

@app.post("/api/sync")
async def api_sync_account(item: AccountItem, auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    
    # 중복 엄격 검사 (아이디 또는 이메일 일치 시 중복 처리)
    for acc in accounts:
        if acc.get("username") == item.username or acc.get("email") == item.email:
            # 기존 상태(status_tag, memo)는 보존하고 추가 등록 방지
            return {
                "status": "exists",
                "message": f"'{item.username}' 계정은 이미 등록되어 있어 중복 추가되지 않았습니다.",
                "account": acc
            }

    record = {
        "email": item.email,
        "password": item.password,
        "username": item.username,
        "birthdate": item.birthdate or {},
        "status": item.status or "success",
        "status_tag": item.status_tag or "available",
        "memo": item.memo or "",
        "created_at": item.created_at or datetime.datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds")
    }
    accounts.append(record)
    save_accounts(accounts)
    return {"status": "ok", "message": "새 계정 동기화 완료", "account": record}

@app.post("/api/sync/batch")
async def api_sync_batch(payload: BatchSyncRequest, auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    existing_users = {a.get("username") for a in accounts if a.get("username")}
    existing_emails = {a.get("email") for a in accounts if a.get("email")}

    added_count = 0
    skipped_count = 0

    for item in payload.accounts:
        if item.username in existing_users or item.email in existing_emails:
            skipped_count += 1
            continue

        record = {
            "email": item.email,
            "password": item.password,
            "username": item.username,
            "birthdate": item.birthdate or {},
            "status": item.status or "success",
            "status_tag": item.status_tag or "available",
            "memo": item.memo or "",
            "created_at": item.created_at or datetime.datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds")
        }
        accounts.append(record)
        existing_users.add(item.username)
        existing_emails.add(item.email)
        added_count += 1

    if added_count > 0:
        save_accounts(accounts)

    return {
        "status": "ok",
        "message": f"일괄 동기화 완료 (신규 추가: {added_count}개, 기존 중복 제외: {skipped_count}개)",
        "added": added_count,
        "skipped": skipped_count,
        "total": len(accounts)
    }

@app.post("/api/account/update")
async def api_update_account(update: AccountUpdate, auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    found = False
    target = None
    for acc in accounts:
        if acc.get("username") == update.username:
            if update.status_tag is not None:
                acc["status_tag"] = update.status_tag
            if update.memo is not None:
                acc["memo"] = update.memo.strip()
            acc["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            found = True
            target = acc
            break
    
    if not found:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    
    save_accounts(accounts)
    return {"status": "ok", "message": "상태가 성공적으로 업데이트되었습니다.", "account": target}

@app.delete("/api/account/{username}")
async def api_delete_account(username: str, auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    initial_len = len(accounts)
    accounts = [a for a in accounts if a.get("username") != username]
    if len(accounts) == initial_len:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    save_accounts(accounts)
    return {"status": "ok", "message": f"{username} 계정이 삭제되었습니다."}

@app.post("/api/clear")
async def api_clear_accounts(auth: bool = Depends(verify_key)):
    save_accounts([])
    return {"status": "ok", "message": "모든 계정 기록이 초기화되었습니다."}

@app.get("/api/export", response_class=PlainTextResponse)
async def api_export_txt(tag: Optional[str] = None, auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    lines = []
    for acc in accounts:
        if acc.get("status") == "success":
            if tag and acc.get("status_tag") != tag:
                continue
            lines.append(f"{acc.get('username')}:{acc.get('password')}:{acc.get('email')}")
    return "\n".join(lines)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"[*] Starting server on 0.0.0.0:{port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port)
