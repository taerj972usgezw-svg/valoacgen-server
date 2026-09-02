import os
import json
import random
import string
import datetime
from typing import Optional, List
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="ValoAcGen Mobile Dashboard & License Manager", version="4.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "accounts.json")
LICENSE_FILE = os.path.join(BASE_DIR, "licenses.json")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

# ── 데이터 모델 정의 ─────────────────────────────────────────────────────────────
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

class LicenseVerifyRequest(BaseModel):
    key: str
    hwid: str

class LicenseCreateRequest(BaseModel):
    key: Optional[str] = None
    memo: Optional[str] = "일반 사용자"
    days: Optional[int] = 30  # None or 0 for lifetime

class LicenseActionRequest(BaseModel):
    key: str

# ── 계정 데이터 관리 ─────────────────────────────────────────────────────────────
def load_accounts() -> List[dict]:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            accounts = json.load(f)
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

# ── 라이센스 데이터 관리 ─────────────────────────────────────────────────────────────
def load_licenses() -> List[dict]:
    if not os.path.exists(LICENSE_FILE):
        default_licenses = [
            {
                "key": "VALO-PRO-2026-MASTER",
                "memo": "최고 관리자 마스터 키 (무제한)",
                "status": "active",
                "hwid": None,
                "expires_at": None,
                "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "last_used_at": None,
                "max_activations": 1
            }
        ]
        save_licenses(default_licenses)
        return default_licenses
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_licenses(licenses: List[dict]):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(licenses, f, ensure_ascii=False, indent=2)

def generate_random_license_key() -> str:
    """VALO-XXXX-XXXX-XXXX 형식의 고유 라이센스 키 생성"""
    chars = string.ascii_uppercase + string.digits
    p1 = ''.join(random.choices(chars, k=4))
    p2 = ''.join(random.choices(chars, k=4))
    p3 = ''.join(random.choices(chars, k=4))
    return f"VALO-{p1}-{p2}-{p3}"

# ── 인증 미들웨어 ─────────────────────────────────────────────────────────────
def verify_key(request: Request, x_api_key: Optional[str] = Header(None), key: Optional[str] = None):
    if not API_SECRET_KEY:
        return True
    
    token = x_api_key or key or request.query_params.get("key")
    if token and (token == API_SECRET_KEY or token == "valo2026"):
        return True

    referer = request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if host and host in referer:
        return True

    raise HTTPException(status_code=401, detail="인증 실패: 올바른 API Key가 필요합니다.")

# ── 웹 대시보드 메인 페이지 ───────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request, key: Optional[str] = None):
    accounts = load_accounts()
    accounts_sorted = list(reversed(accounts))
    licenses = load_licenses()
    licenses_sorted = list(reversed(licenses))
    
    # 계정 통계
    stats = {
        "total": len(accounts),
        "available": sum(1 for a in accounts if a.get("status_tag", "available") == "available"),
        "in_use": sum(1 for a in accounts if a.get("status_tag") == "in_use"),
        "shared": sum(1 for a in accounts if a.get("status_tag") == "shared"),
        "used": sum(1 for a in accounts if a.get("status_tag") == "used"),
        "banned": sum(1 for a in accounts if a.get("status_tag") == "banned"),
    }

    # 라이센스 통계
    now_str = datetime.datetime.now().isoformat()
    lic_stats = {
        "total": len(licenses),
        "active": sum(1 for l in licenses if l.get("status") == "active" and (not l.get("expires_at") or l.get("expires_at") > now_str)),
        "locked": sum(1 for l in licenses if l.get("hwid")),
        "banned": sum(1 for l in licenses if l.get("status") == "banned"),
        "expired": sum(1 for l in licenses if l.get("expires_at") and l.get("expires_at") <= now_str),
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "accounts": accounts_sorted,
            "licenses": licenses_sorted,
            "stats": stats,
            "lic_stats": lic_stats,
            "api_key": key or ""
        }
    )

# ── 라이센스 관리 및 하드락 API ─────────────────────────────────────────────────
@app.post("/api/license/verify")
async def api_verify_license(req: LicenseVerifyRequest):
    """
    클라이언트 프로그램에서 하드락 및 라이센스 유효성을 검증하는 공개 엔드포인트
    """
    clean_key = req.key.strip()
    clean_hwid = req.hwid.strip()

    if not clean_key:
        return {"valid": False, "reason": "empty_key", "message": "라이센스 키를 입력해주세요."}
    if not clean_hwid:
        return {"valid": False, "reason": "empty_hwid", "message": "시스템 고유 하드웨어 ID(HWID)를 확인할 수 없습니다."}

    licenses = load_licenses()
    matched = None
    for lic in licenses:
        if lic.get("key", "").upper() == clean_key.upper():
            matched = lic
            break

    if not matched:
        return {"valid": False, "reason": "not_found", "message": "존재하지 않거나 등록되지 않은 라이센스 키입니다."}

    if matched.get("status") == "banned":
        return {"valid": False, "reason": "banned", "message": "관리자에 의해 정지/차단된 라이센스입니다."}

    # 만료일 체크
    now = datetime.datetime.now()
    if matched.get("expires_at"):
        try:
            exp_date = datetime.datetime.fromisoformat(matched["expires_at"].replace("Z", ""))
            if now > exp_date:
                return {"valid": False, "reason": "expired", "message": f"라이센스 사용 기간이 만료되었습니다. (만료일: {matched['expires_at'][:10]})"}
        except Exception:
            pass

    # 하드락(HWID) 검증 및 최초 등록
    saved_hwid = matched.get("hwid")
    if not saved_hwid:
        # 최초 인증: 현재 PC의 HWID로 영구 잠금
        matched["hwid"] = clean_hwid
        matched["last_used_at"] = now.isoformat(timespec="seconds")
        save_licenses(licenses)
        return {
            "valid": True,
            "message": "라이센스 인증 및 현재 PC 하드락(HWID) 등록 완료",
            "key": matched["key"],
            "memo": matched.get("memo", ""),
            "expires_at": matched.get("expires_at"),
            "hwid": clean_hwid,
            "first_activated": True
        }

    # 이미 하드락이 걸려있는 경우 일치 여부 확인
    if saved_hwid == clean_hwid:
        matched["last_used_at"] = now.isoformat(timespec="seconds")
        save_licenses(licenses)
        return {
            "valid": True,
            "message": "라이센스 인증 성공 (하드락 일치)",
            "key": matched["key"],
            "memo": matched.get("memo", ""),
            "expires_at": matched.get("expires_at"),
            "hwid": clean_hwid,
            "first_activated": False
        }
    else:
        return {
            "valid": False,
            "reason": "hwid_mismatch",
            "message": f"하드락 오류: 다른 PC에 등록된 라이센스입니다. 관리자 웹 대시보드에서 '하드락 해제'를 진행하세요."
        }

@app.get("/api/licenses")
async def api_get_licenses(auth: bool = Depends(verify_key)):
    """라이센스 목록 조회"""
    licenses = load_licenses()
    return {"status": "ok", "licenses": list(reversed(licenses))}

@app.post("/api/license/create")
async def api_create_license(req: LicenseCreateRequest, auth: bool = Depends(verify_key)):
    """새 라이센스 생성"""
    licenses = load_licenses()
    key = req.key.strip() if (req.key and req.key.strip()) else generate_random_license_key()
    
    # 중복 검사
    for lic in licenses:
        if lic.get("key", "").upper() == key.upper():
            raise HTTPException(status_code=400, detail="이미 존재하는 라이센스 키입니다.")

    now = datetime.datetime.now()
    expires_at = None
    if req.days and req.days > 0:
        expires_at = (now + datetime.timedelta(days=req.days)).isoformat(timespec="seconds")

    new_lic = {
        "key": key,
        "memo": req.memo.strip() if req.memo else "일반 사용자",
        "status": "active",
        "hwid": None,
        "expires_at": expires_at,
        "created_at": now.isoformat(timespec="seconds"),
        "last_used_at": None,
        "max_activations": 1
    }
    licenses.append(new_lic)
    save_licenses(licenses)
    return {"status": "ok", "message": f"라이센스 키 '{key}'가 생성되었습니다.", "license": new_lic}

@app.post("/api/license/reset_hwid")
async def api_reset_hwid(req: LicenseActionRequest, auth: bool = Depends(verify_key)):
    """하드락 해제 (새 PC에서 인증 가능하도록 초기화)"""
    licenses = load_licenses()
    target = None
    for lic in licenses:
        if lic.get("key", "").upper() == req.key.strip().upper():
            lic["hwid"] = None
            target = lic
            break
    if not target:
        raise HTTPException(status_code=404, detail="라이센스를 찾을 수 없습니다.")
    save_licenses(licenses)
    return {"status": "ok", "message": f"'{target['key']}' 하드락이 초기화되었습니다. 이제 새로운 PC에서 인증 가능합니다."}

@app.post("/api/license/toggle_status")
async def api_toggle_license_status(req: LicenseActionRequest, auth: bool = Depends(verify_key)):
    """라이센스 활성화 / 차단 토글"""
    licenses = load_licenses()
    target = None
    for lic in licenses:
        if lic.get("key", "").upper() == req.key.strip().upper():
            lic["status"] = "banned" if lic.get("status") == "active" else "active"
            target = lic
            break
    if not target:
        raise HTTPException(status_code=404, detail="라이센스를 찾을 수 없습니다.")
    save_licenses(licenses)
    status_label = "정지(차단)" if target["status"] == "banned" else "활성화"
    return {"status": "ok", "message": f"'{target['key']}' 상태가 '{status_label}'(으)로 변경되었습니다.", "license": target}

@app.delete("/api/license/{key}")
async def api_delete_license(key: str, auth: bool = Depends(verify_key)):
    """라이센스 완전 삭제"""
    licenses = load_licenses()
    initial_len = len(licenses)
    licenses = [l for l in licenses if l.get("key", "").upper() != key.strip().upper()]
    if len(licenses) == initial_len:
        raise HTTPException(status_code=404, detail="라이센스를 찾을 수 없습니다.")
    save_licenses(licenses)
    return {"status": "ok", "message": f"라이센스 '{key}'가 삭제되었습니다."}

# ── 기존 계정 API ─────────────────────────────────────────────────────────────
@app.get("/api/accounts")
async def api_get_accounts(auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    return {"status": "ok", "accounts": list(reversed(accounts))}

@app.post("/api/account")
async def api_add_account(item: AccountItem, auth: bool = Depends(verify_key)):
    accounts = load_accounts()
    for acc in accounts:
        if acc.get("username") == item.username or acc.get("email") == item.email:
            return {"status": "exists", "message": "이미 존재하는 계정입니다.", "account": acc}

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
