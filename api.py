from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from scrapers.cekresi_scraper import CekResiScraper
from database import DatabaseManager
import uvicorn
import asyncio
import os
import json
import random
from pydantic import BaseModel, ConfigDict
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt

app = FastAPI(title="Shipping Tracking API with Auto-Update")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scraper = CekResiScraper()
db = DatabaseManager()

# ─── Auth Config ─────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer(auto_error=False)

SECRET_KEY = os.getenv("SECRET_KEY", "queenylook-super-secret-key-2025-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30  # Token berlaku 30 hari

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency — wajib ada token yang valid. Raise 401 jika tidak ada/invalid."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Token tidak ditemukan. Silakan login terlebih dahulu.")
    payload = decode_token(credentials.credentials)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Token tidak valid atau sudah kadaluarsa. Silakan login ulang.")
    return payload  # {"user_id": ..., "username": ..., "exp": ...}

def get_current_user_optional(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency — token opsional. Return None jika tidak ada token."""
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    return payload  # bisa None

# ─── Pydantic Models ─────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    created_at: datetime

class LoginRequest(BaseModel):
    username: str
    password: str

class ShipmentRegister(BaseModel):
    item_code: str
    resi: str
    courier: Optional[str] = None
    destination: Optional[str] = None

class ReturnCreate(BaseModel):
    sku_code: str
    product_name: Optional[str] = None
    resi_number: Optional[str] = None
    courier: Optional[str] = None
    reason: Optional[str] = None
    status: Optional[str] = "PENDING"

# ─── BACKGROUND WORKER ────────────────────────────────────────────────────────

async def auto_update_worker():
    """
    Background worker yang mengecek status resi secara otomatis.
    Mengecek SEMUA resi aktif dari semua user.
    Juga mendeteksi paket retur dan gagal kirim lalu mencatatnya.
    """
    while True:
        try:
            print("[Worker] Memulai pengecekan otomatis...")
            active_items = db.get_all_active_trackings()

            for item in active_items:
                item_code = item['item_code']
                resi      = item['resi_number']
                courier   = item['courier']
                user_id   = item.get('user_id')

                print(f"[Worker] Mengecek {item_code} (Resi: {resi})...")
                result = await scraper.track(resi, courier)

                if result["success"]:
                    status  = result["status"]
                    history = result["history"]
                    is_delivered = "delivered" in status.lower() or "diterima" in status.lower()

                    db.update_tracking_status(item_code, status, history, is_delivered, user_id=user_id)
                    print(f"[Worker] {item_code} UPDATED: {status}")

                    # --- Deteksi otomatis retur & gagal kirim ---
                    latest_desc = ""
                    if history and len(history) > 0:
                        h = history[0]
                        latest_desc = (h.get("description") or h.get("status") or "").lower()

                    is_returned = (
                        "return" in latest_desc or "retur" in latest_desc
                        or "return" in status.lower() or "retur" in status.lower()
                    )
                    is_failed = (
                        "delay" in latest_desc or "menolak" in latest_desc
                        or "gagal" in latest_desc or "failed" in latest_desc
                        or "rejected" in latest_desc
                    )
                    is_cancelled = (
                        "cancel" in latest_desc or "batal" in latest_desc
                        or "dibatalkan" in latest_desc or "cancellation" in latest_desc
                        or "void" in latest_desc or "canceled" in latest_desc
                        or "cancel" in status.lower() or "batal" in status.lower()
                        or "dibatalkan" in status.lower()
                    )

                    if is_returned or is_failed:
                        reason_type = "Paket Diretur" if is_returned else "Gagal Pengiriman"
                        raw_desc = ""
                        if history and len(history) > 0:
                            h = history[0]
                            raw_desc = h.get("description") or h.get("status") or ""
                        reason = f"{reason_type}: {raw_desc}" if raw_desc else reason_type

                        if not db.return_exists(item_code, user_id=user_id):
                            db.add_return(
                                sku_code=item_code, 
                                product_name=item_code, 
                                reason=reason, 
                                resi_number=resi, 
                                courier=courier, 
                                user_id=user_id,
                                status="PENDING"
                            )
                            print(f"[Worker] {item_code} -> {reason_type} dicatat ke tabel returns (User: {user_id})")

                    # --- Deteksi otomatis pembatalan ---
                    if is_cancelled:
                        raw_desc = ""
                        if history and len(history) > 0:
                            h = history[0]
                            raw_desc = h.get("description") or h.get("status") or ""
                        reason = f"Pembatalan otomatis terdeteksi: {raw_desc}" if raw_desc else "Paket Dibatalkan (terdeteksi otomatis)"

                        if not db.cancellation_exists(item_code, user_id=user_id):
                            db.add_cancellation(
                                item_code=item_code,
                                resi_number=resi,
                                courier=courier,
                                reason=reason,
                                user_id=user_id,
                            )
                            # Hapus dari tracking aktif karena sudah dibatalkan
                            db.delete_tracking(item_code, user_id=user_id)
                            print(f"[Worker] {item_code} -> Pembatalan dicatat & dihapus dari tracking aktif")

                # Jeda acak antar barang (5 - 15 detik)
                delay_between = random.randint(5, 15)
                await asyncio.sleep(delay_between)

            sleep_time = random.randint(2700, 5400)
            next_run_minutes = round(sleep_time / 60, 1)
            print(f"[Worker] Selesai. Istirahat selama {next_run_minutes} menit sebelum siklus berikutnya.")
            await asyncio.sleep(sleep_time)
        except Exception as e:
            print(f"[Worker] Error: {str(e)}")
            await asyncio.sleep(300)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_update_worker())

# ─── PUBLIC ENDPOINTS ─────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Tracking API with Auto-Update is active."}

# ─── AUTH ENDPOINTS ───────────────────────────────────────────────────────────

@app.post("/auth/register")
async def register_user(user: UserCreate):
    """Daftarkan user baru."""
    existing_user = db.get_user_by_username(user.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username sudah terdaftar")

    hashed_pwd = pwd_context.hash(user.password)
    try:
        db.create_user(user.username, hashed_pwd)
        return {"success": True, "message": "User berhasil didaftarkan"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/login")
async def login(request: LoginRequest):
    """
    Login user — kembalikan JWT token yang dipakai untuk semua request berikutnya.
    Token berlaku 30 hari.
    """
    user = db.get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=401, detail="Username atau password salah")

    if not pwd_context.verify(request.password, user['password']):
        raise HTTPException(status_code=401, detail="Username atau password salah")

    # Buat JWT token
    token_data = {
        "user_id": user['id'],
        "username": user['username'],
    }
    access_token = create_access_token(token_data)

    return {
        "success": True,
        "message": "Login berhasil",
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user['id'],
            "username": user['username']
        }
    }

@app.get("/users")
async def list_users():
    """List semua user (Hanya untuk keperluan debug/admin)."""
    return db.get_all_users()

# ─── TRACKING ENDPOINTS (PROTECTED) ──────────────────────────────────────────

async def _track_and_update(item_code: str, resi: str, courier: str, user_id: int):
    """Jalankan di background setelah register — tidak memblokir response."""
    try:
        print(f"[BG] Tracking {item_code} (Resi: {resi}, User: {user_id})...")
        result = await scraper.track(resi, courier)
        if result.get("success"):
            status       = result["status"]
            history      = result["history"]
            is_delivered = "delivered" in status.lower() or "diterima" in status.lower()
            db.update_tracking_status(item_code, status, history, is_delivered, user_id=user_id)
            print(f"[BG] {item_code} updated: {status}")
    except Exception as e:
        print(f"[BG] Track gagal untuk {item_code}: {e}")

@app.post("/register")
async def register_item(
    background_tasks: BackgroundTasks,
    data: ShipmentRegister = None,
    item_code: str = Query(None),
    resi: str = Query(None),
    courier: str = Query(None),
    destination: str = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Register resi — mendukung JSON body ATAU query params.
    Resi akan dikaitkan dengan user yang sedang login.
    Response langsung dikembalikan, tracking dijalankan di background.
    """
    _item_code = (data.item_code if data else None) or item_code
    _resi      = (data.resi      if data else None) or resi
    _courier   = (data.courier   if data else None) or courier
    _dest      = (data.destination if data else None) or destination
    _user_id   = current_user["user_id"]

    if not _item_code or not _resi:
        raise HTTPException(status_code=422, detail="item_code dan resi wajib diisi")

    try:
        db.add_or_update_tracking(_item_code, _resi, _courier, _dest, user_id=_user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan: {str(e)}")

    background_tasks.add_task(_track_and_update, _item_code, _resi, _courier or "", _user_id)

    return {"success": True, "message": f"Item {_item_code} registered with resi {_resi}"}

@app.get("/status/{item_code}")
async def get_item_status(
    item_code: str,
    current_user: dict = Depends(get_current_user),
):
    """Get tracking status dari database untuk item_code milik user yang sedang login."""
    user_id = current_user["user_id"]
    data = db.get_tracking_by_item(item_code, user_id=user_id)
    if not data:
        raise HTTPException(status_code=404, detail="Item code not found.")
    return data

@app.delete("/delete/{item_code}")
async def delete_shipment(
    item_code: str,
    current_user: dict = Depends(get_current_user),
):
    """Hapus data pengiriman berdasarkan item_code — hanya bisa hapus milik sendiri."""
    user_id = current_user["user_id"]
    try:
        db.delete_tracking(item_code, user_id=user_id)
        return {"success": True, "message": f"Item {item_code} berhasil dihapus"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/list")
async def list_all(current_user: dict = Depends(get_current_user)):
    """List semua resi milik user yang sedang login."""
    user_id = current_user["user_id"]
    return db.get_trackings_by_user(user_id)

@app.get("/track-direct")
async def track_direct(
    background_tasks: BackgroundTasks,
    resi: str = Query(...),
    courier: str = Query(None),
    item_code: str = Query(None),
    current_user: dict = Depends(get_current_user_optional),
):
    """
    Scrape status resi secara langsung.
    Jika item_code disertakan, hasil LANGSUNG disimpan ke DB (synchronous).
    """
    result = await scraper.track(resi, courier)

    user_id = current_user["user_id"] if current_user else None

    if item_code and result.get("success"):
        try:
            status       = result["status"]
            history      = result["history"]
            is_delivered = "delivered" in status.lower() or "diterima" in status.lower()
            db.update_tracking_status(item_code, status, history, is_delivered, user_id=user_id)
            print(f"[track-direct] {item_code} disimpan ke DB: {status}")
        except Exception as e:
            print(f"[track-direct] Gagal simpan DB: {e}")

    return result

# ─── RETURN ENDPOINTS ─────────────────────────────────────────────────────────

@app.get("/returns")
async def list_returns(current_user: dict = Depends(get_current_user)):
    """Ambil semua data retur milik user yang sedang login."""
    user_id = current_user["user_id"]
    return db.get_returns(user_id=user_id)

@app.post("/returns")
async def create_return(data: ReturnCreate, current_user: dict = Depends(get_current_user)):
    """
    Simpan data retur baru.
    Jika sku_code sudah ada untuk user ini (duplikat), tidak insert ulang.
    """
    user_id = current_user["user_id"]
    if db.return_exists(data.sku_code, user_id=user_id):
        return {"success": False, "message": f"Retur untuk {data.sku_code} sudah ada"}
    try:
        db.add_return(
            sku_code=data.sku_code, 
            product_name=data.product_name, 
            reason=data.reason, 
            resi_number=data.resi_number, 
            courier=data.courier, 
            user_id=user_id,
            status=data.status or "PENDING"
        )
        return {"success": True, "message": f"Retur {data.sku_code} berhasil dicatat"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/returns/{sku_code}")
async def delete_return(
    sku_code: str,
    current_user: dict = Depends(get_current_user),
):
    """Hapus catatan retur berdasarkan sku_code."""
    user_id = current_user["user_id"]
    try:
        if db.use_postgres:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM returns WHERE sku_code = %s AND user_id = %s", (sku_code, user_id))
                conn.commit()
        else:
            with db.get_connection() as conn:
                conn.execute("DELETE FROM returns WHERE sku_code = ? AND user_id = ?", (sku_code, user_id))
                conn.commit()
        return {"success": True, "message": f"Catatan retur {sku_code} dihapus"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── CANCELLATION ENDPOINTS ───────────────────────────────────────────────────

class CancellationCreate(BaseModel):
    item_code: str
    resi_number: Optional[str] = None
    courier: Optional[str] = None
    reason: Optional[str] = None

@app.get("/cancellations")
async def list_cancellations(current_user: dict = Depends(get_current_user)):
    """Ambil semua pembatalan milik user yang sedang login."""
    user_id = current_user["user_id"]
    return db.get_cancellations(user_id=user_id)

@app.post("/cancellations")
async def create_cancellation(
    data: CancellationCreate,
    current_user: dict = Depends(get_current_user),
):
    """
    Catat pembatalan paket baru.
    Otomatis menggunakan user_id dari token.
    """
    user_id = current_user["user_id"]
    try:
        db.add_cancellation(
            item_code=data.item_code,
            resi_number=data.resi_number,
            courier=data.courier,
            reason=data.reason,
            user_id=user_id,
        )
        # Hapus dari tracking jika ada
        try:
            db.delete_tracking(data.item_code, user_id=user_id)
        except Exception:
            pass
        return {"success": True, "message": f"Pembatalan {data.item_code} berhasil dicatat"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/cancellations/{item_code}")
async def delete_cancellation(
    item_code: str,
    current_user: dict = Depends(get_current_user),
):
    """Hapus catatan pembatalan berdasarkan item_code."""
    user_id = current_user["user_id"]
    try:
        if db.use_postgres:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM cancellations WHERE item_code = %s AND user_id = %s", (item_code, user_id))
                conn.commit()
        else:
            with db.get_connection() as conn:
                conn.execute("DELETE FROM cancellations WHERE item_code = ? AND user_id = ?", (item_code, user_id))
                conn.commit()
        return {"success": True, "message": f"Catatan pembatalan {item_code} dihapus"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
