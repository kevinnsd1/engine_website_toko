from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from scrapers.cekresi_scraper import CekResiScraper
from database import DatabaseManager
import uvicorn
import asyncio
import os
import json

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

# --- BACKGROUND WORKER ---
async def auto_update_worker():
    """
    Background worker that runs every 1 hour to update statuses of items in the database.
    """
    while True:
        try:
            print("[Worker] Memulai pengecekan otomatis...")
            active_items = db.get_all_active_trackings()
            
            for item in active_items:
                item_code = item['item_code']
                resi = item['resi_number']
                courier = item['courier']
                
                print(f"[Worker] Mengecek {item_code} (Resi: {resi})...")
                result = await scraper.track(resi, courier)
                
                if result["success"]:
                    status = result["status"]
                    history = result["history"]
                    # Check if delivered (usually status contains 'Delivered' or 'Diterima')
                    is_delivered = "delivered" in status.lower() or "diterima" in status.lower()
                    
                    db.update_tracking_status(item_code, status, history, is_delivered)
                    print(f"[Worker] {item_code} UPDATED: {status}")
                
                # Small delay between items to avoid being blocked
                await asyncio.sleep(5)
                
            print("[Worker] Selesai. Istirahat 1 jam.")
        except Exception as e:
            print(f"[Worker] Error: {str(e)}")
        
        await asyncio.sleep(3600) # Wait for 1 hour

@app.on_event("startup")
async def startup_event():
    # Start the auto update worker in the background
    asyncio.create_task(auto_update_worker())

# --- ENDPOINTS ---

@app.get("/")
async def root():
    return {"message": "Tracking API with Auto-Update is active."}

@app.post("/register")
async def register_item(item_code: str, resi: str, courier: str = None):
    """
    Register a new item with its tracking number.
    """
    try:
        db.add_or_update_tracking(item_code, resi, courier)
        return {"success": True, "message": f"Item {item_code} registered with resi {resi}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{item_code}")
async def get_item_status(item_code: str):
    """
    Get the tracking status from the database for a specific item code.
    """
    data = db.get_tracking_by_item(item_code)
    if not data:
        raise HTTPException(status_code=404, detail="Item code not found.")
    return data

@app.get("/list")
async def list_all():
    """
    List all tracked items and their last known status.
    """
    return db.get_all_trackings()

@app.get("/track-direct")
async def track_direct(resi: str = Query(...), courier: str = Query(None)):
    """
    Original manual track endpoint (bypass database).
    """
    return await scraper.track(resi, courier)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
