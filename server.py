from fastapi import FastAPI, Header, HTTPException, Body
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import os, time, uuid, requests

APP_TOKEN = os.getenv("AURA_MCP_TOKEN", "devtoken")
SN_CALLBACK = os.getenv("AURA_SN_CALLBACK", "")
SN_CB_TOKEN = os.getenv("AURA_SN_CALLBACK_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

app = FastAPI(title="Aura MCP Scheduler")

# Demo coaches (expand if you want)
COACHES = [
    {"id":"coach_1", "display":"Abraham L.", "lang":"en", "tz":"America/New_York"},
    {"id":"coach_2", "display":"George W.",  "lang":"en", "tz":"America/Chicago"},
    {"id":"coach_1", "display":"", "lang":"en", "tz":"America/New_York"},
    {"id":"coach_2", "display":"",  "lang":"en", "tz":"America/Phoenix"},
]
SLOTS: Dict[str, Dict] = {}  # slot_id -> {coach_id, start, end, lang, status, cr_sys_id?}

def check_auth(auth_header: str):
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer")
    token = auth_header.split(" ",1)[1]
    if token != APP_TOKEN:
        raise HTTPException(status_code=403, detail="Bad token")

class FindSlotsIn(BaseModel):
    lang: str = Field(..., description="Preferred language, e.g. 'es' or 'en'")
    duration_minutes: int = Field(30, ge=15, le=120)
    time_zone: str = Field("America/New_York")
    window_days: int = Field(7, ge=1, le=14)
    limit: int = Field(5, ge=1, le=10)
    coaching_request_sys_id: Optional[str] = None

class Slot(BaseModel):
    slot_id: str
    start: str
    end: str
    coach_user_sys_id: str
    coach_display: str
    book_url: str

class FindSlotsOut(BaseModel):
    slots: List[Slot] = []

class BookIn(BaseModel):
    slot_id: str
    employee_email: Optional[str] = None
    employee_first_name: Optional[str] = None

class BookOut(BaseModel):
    status: str
    event_id: str
    start: str
    end: str

@app.post("/mcp/find_coach_slots", response_model=FindSlotsOut)
def find_coach_slots(payload: FindSlotsIn, authorization: Optional[str] = Header(None)):
    check_auth(authorization)

    matches = [c for c in COACHES if c["lang"] == payload.lang] or COACHES[:]

    out_slots = []
    for coach in matches:
        for i in range(1, payload.window_days+1):
            for hour in [10, 14]:  # 10:00 & 14:00 demo hours
                slot_id = str(uuid.uuid4())
                # Simple ISO demo timestamps (2025-10-21.. etc.). You can swap to "now + i days"
                start = f"2025-10-{20+i:02d}T{hour:02d}:00:00"
                end_hour = hour + (payload.duration_minutes // 60)
                end_min = payload.duration_minutes % 60
                end = f"2025-10-{20+i:02d}T{end_hour:02d}:{end_min:02d}:00"
                SLOTS[slot_id] = {
                    "coach_id": coach["id"],
                    "coach_display": coach["display"],
                    "lang": coach["lang"],
                    "start": start,
                    "end": end,
                    "status": "open",
                    "cr_sys_id": payload.coaching_request_sys_id
                }
                out_slots.append(Slot(
                    slot_id=slot_id,
                    start=start,
                    end=end,
                    coach_user_sys_id=coach["id"],
                    coach_display=coach["display"],
                    book_url=f"{BASE_URL}/mcp/book?token={APP_TOKEN}&slot_id={slot_id}"
                ))
                if len(out_slots) >= payload.limit:
                    break
            if len(out_slots) >= payload.limit:
                break
        if len(out_slots) >= payload.limit:
            break

    return FindSlotsOut(slots=out_slots)

@app.post("/mcp/book", response_model=BookOut)
def book_slot(payload: BookIn = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    slot = SLOTS.get(payload.slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot["status"] != "open":
        raise HTTPException(status_code=409, detail="Slot no longer available")

    slot["status"] = "booked"
    event_id = "evt_" + payload.slot_id[:8]

    if SN_CALLBACK:
        try:
            body = {
                "coaching_request_sys_id": slot.get("cr_sys_id"),
                "event_id": event_id,
                "selected_slot": {
                    "start": slot["start"],
                    "end": slot["end"],
                    "coach_display": slot["coach_display"]
                }
            }
            headers = {"Authorization": f"Bearer {SN_CB_TOKEN}", "Content-Type": "application/json"}
            requests.post(SN_CALLBACK, json=body, headers=headers, timeout=10)
        except Exception:
            pass

    return BookOut(status="booked", event_id=event_id, start=slot["start"], end=slot["end"])
