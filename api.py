from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
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

# Password hashing setup
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Pydantic models for request/response
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

# --- BACKGROUND WORKER ---
async def auto_update_worker():
    """
    Background worker yang mengecek status resi secara otomatis.
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
                
                print(f"[Worker] Mengecek {item_code} (Resi: {resi})...")
                result = await scraper.track(resi, courier)
                
                if result["success"]:
                    status  = result["status"]
                    history = result["history"]
                    is_delivered = "delivered" in status.lower() or "diterima" in status.lower()
                    
                    db.update_tracking_status(item_code, status, history, is_delivered)
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

                    if is_returned or is_failed:
                        reason_type = "Paket Diretur" if is_returned else "Gagal Pengiriman"
                        raw_desc = ""
                        if history and len(history) > 0:
                            h = history[0]
                            raw_desc = h.get("description") or h.get("status") or ""
                        reason = f"{reason_type}: {raw_desc}" if raw_desc else reason_type

                        # Cek duplikat sebelum catat
                        if not db.return_exists(item_code):
                            db.add_return(item_code, item_code, reason, "PENDING")
                            print(f"[Worker] {item_code} -> {reason_type} dicatat ke tabel returns")

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
    # Start the auto update worker in the background
    asyncio.create_task(auto_update_worker())

# --- ENDPOINTS ---

@app.get("/")
async def root():
    return {"message": "Tracking API with Auto-Update is active."}

async def _track_and_update(item_code: str, resi: str, courier: str):
    """Jalankan di background setelah register — tidak memblokir response."""
    try:
        print(f"[BG] Tracking {item_code} (Resi: {resi})...")
        result = await scraper.track(resi, courier)
        if result.get("success"):
            status      = result["status"]
            history     = result["history"]
            is_delivered = "delivered" in status.lower() or "diterima" in status.lower()
            db.update_tracking_status(item_code, status, history, is_delivered)
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
    destination: str = Query(None)
):
    """
    Register resi - mendukung JSON body ATAU query params.
    Response langsung dikembalikan, tracking dijalankan di background.
    """
    _item_code = (data.item_code if data else None) or item_code
    _resi      = (data.resi      if data else None) or resi
    _courier   = (data.courier   if data else None) or courier
    _dest      = (data.destination if data else None) or destination

    if not _item_code or not _resi:
        raise HTTPException(status_code=422, detail="item_code dan resi wajib diisi")

    try:
        db.add_or_update_tracking(_item_code, _resi, _courier, _dest)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan: {str(e)}")

    # Jalankan scraping di background — response langsung cepat
    background_tasks.add_task(_track_and_update, _item_code, _resi, _courier or "")

    return {"success": True, "message": f"Item {_item_code} registered with resi {_resi}"}


@app.get("/status/{item_code}")
async def get_item_status(item_code: str):
    """
    Get the tracking status from the database for a specific item code.
    """
    data = db.get_tracking_by_item(item_code)
    if not data:
        raise HTTPException(status_code=404, detail="Item code not found.")
    return data

@app.delete("/delete/{item_code}")
async def delete_shipment(item_code: str):
    """
    Hapus data pengiriman berdasarkan item_code.
    """
    try:
        db.delete_tracking(item_code)
        return {"success": True, "message": f"Item {item_code} berhasil dihapus"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/list")
async def list_all():
    """
    List all tracked items and their last known status.
    """
    return db.get_all_trackings()

@app.get("/track-direct")
async def track_direct(
    background_tasks: BackgroundTasks,
    resi: str = Query(...),
    courier: str = Query(None),
    item_code: str = Query(None)
):
    """
    Scrape status resi secara langsung.
    Jika item_code disertakan, hasil LANGSUNG disimpan ke DB (synchronous)
    agar status tidak hilang saat halaman di-refresh.
    """
    result = await scraper.track(resi, courier)

    # DB write SYNCHRONOUS — pastikan DB sudah terupdate sebelum response dikembalikan
    if item_code and result.get("success"):
        try:
            status       = result["status"]
            history      = result["history"]
            is_delivered = "delivered" in status.lower() or "diterima" in status.lower()
            db.update_tracking_status(item_code, status, history, is_delivered)
            print(f"[track-direct] {item_code} disimpan ke DB: {status}")
        except Exception as e:
            print(f"[track-direct] Gagal simpan DB: {e}")

    return result

@app.get("/returns")
async def list_returns():
    """Ambil semua data retur."""
    return db.get_returns()

class ReturnCreate(BaseModel):
    sku_code: str
    product_name: Optional[str] = None
    reason: Optional[str] = None
    status: Optional[str] = "PENDING"

@app.post("/returns")
async def create_return(data: ReturnCreate):
    """
    Simpan data retur baru.
    Jika sku_code sudah ada (duplikat), tidak insert ulang.
    """
    if db.return_exists(data.sku_code):
        return {"success": False, "message": f"Retur untuk {data.sku_code} sudah ada"}
    try:
        db.add_return(data.sku_code, data.product_name, data.reason, data.status or "PENDING")
        return {"success": True, "message": f"Retur {data.sku_code} berhasil dicatat"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- USER ENDPOINTS ---

@app.post("/auth/register")
async def register_user(user: UserCreate):
    """
    Daftarkan user baru.
    """
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
    Login user dan kembalikan status sukses.
    """
    user = db.get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=401, detail="Username atau password salah")
    
    if not pwd_context.verify(request.password, user['password']):
        raise HTTPException(status_code=401, detail="Username atau password salah")
    
    return {
        "success": True, 
        "message": "Login berhasil",
        "user": {
            "id": user['id'],
            "username": user['username']
        }
    }

@app.get("/users")
async def list_users():
    """
    List semua user (Hanya untuk keperluan debug/admin).
    """
    return db.get_all_users()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
