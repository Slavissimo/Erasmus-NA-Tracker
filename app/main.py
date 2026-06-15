"""
Erasmus+ National Agency Tracker
Sleduje otvorené možnosti KA1/KA2 naprieč národnými agentúrami Erasmus+
pre sektory mládeže a vzdelávania dospelých.
"""
import json
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

app = FastAPI(title="Erasmus+ NA Tracker", version="1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def load_json(filename: str) -> dict:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def parse_d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def enrich_actions(actions: list[dict]) -> list[dict]:
    """Pridá k akciám info o tom, či je termín otvorený a koľko dní zostáva."""
    today = date.today()
    out = []
    for a in actions:
        deadlines = [parse_d(d) for d in a.get("deadlines_2026", [])]
        upcoming = sorted([d for d in deadlines if d >= today])
        item = dict(a)
        if upcoming:
            nxt = upcoming[0]
            item["status"] = "open"
            item["next_deadline"] = nxt.isoformat()
            item["days_left"] = (nxt - today).days
        else:
            item["status"] = "closed"
            item["next_deadline"] = None
            item["days_left"] = None
        out.append(item)
    return out


@app.get("/api/agencies")
def api_agencies(sector: str | None = None):
    data = load_json("national_agencies.json")
    agencies = data["agencies"]
    if sector:
        agencies = [a for a in agencies if sector in a.get("sectors", [])]
    return JSONResponse({"meta": data["_meta"], "agencies": agencies})


@app.get("/api/actions")
def api_actions(key_action: str | None = None, sector: str | None = None,
                status: str | None = None):
    data = load_json("actions_2026.json")
    actions = enrich_actions(data["actions"])
    if key_action:
        actions = [a for a in actions if a["key_action"] == key_action]
    if sector:
        actions = [a for a in actions if a["sector"] == sector]
    if status:
        actions = [a for a in actions if a["status"] == status]
    return JSONResponse({
        "meta": data["_meta"],
        "horizontal_priorities": data["horizontal_priorities"],
        "actions": actions,
    })


@app.get("/api/health")
def health():
    return {"status": "ok", "date": date.today().isoformat()}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    agencies_data = load_json("national_agencies.json")
    actions_data = load_json("actions_2026.json")
    actions = enrich_actions(actions_data["actions"])

    ka1 = [a for a in actions if a["key_action"] == "KA1"]
    ka2 = [a for a in actions if a["key_action"] == "KA2"]
    open_count = sum(1 for a in actions if a["status"] == "open")

    return templates.TemplateResponse("index.html", {
        "request": request,
        "agencies": agencies_data["agencies"],
        "ka1": ka1,
        "ka2": ka2,
        "priorities": actions_data["horizontal_priorities"],
        "open_count": open_count,
        "total_actions": len(actions),
        "agency_count": len(agencies_data["agencies"]),
        "today": date.today().isoformat(),
        "meta": actions_data["_meta"],
    })
