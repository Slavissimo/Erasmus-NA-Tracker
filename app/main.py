"""
Erasmus+ National Agency Tracker
Sleduje otvorené možnosti KA1/KA2 naprieč národnými agentúrami Erasmus+
pre sektory mládeže a vzdelávania dospelých.
"""
import json
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FINDINGS_PATH = DATA_DIR / "round_findings.json"

# Admin token na potvrdzovanie nálezov. Na Renderi nastav env var ADMIN_TOKEN.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me-local")

# Scraper spúšťame priamo vo web procese (nie samostatný cron), aby zápisy
# nálezov videl web. Zapni cez env var RUN_SCRAPER=1.
if os.environ.get("RUN_SCRAPER") == "1":
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.scraper import run as run_scraper

    scheduler = BackgroundScheduler(daemon=True)
    # každý deň o 06:00 (čas servera/UTC)
    scheduler.add_job(run_scraper, "cron", hour=6, minute=0, id="daily_scrape")
    scheduler.start()


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


def load_findings() -> dict:
    if FINDINGS_PATH.exists():
        with open(FINDINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"runs": [], "items": []}


def save_findings(obj: dict):
    with open(FINDINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def build_matrix():
    """Matica NA × akcia × kolo: kombinuje potvrdené nálezy + auto-detekcie."""
    agencies = load_json("national_agencies.json")["agencies"]
    findings = load_findings()
    # zoskup nálezy podľa agentúry
    by_agency: dict[str, list] = {}
    for it in findings["items"]:
        by_agency.setdefault(it["agency_code"], []).append(it)
    rows = []
    for ag in agencies:
        items = by_agency.get(ag["code"], [])
        confirmed = [i for i in items if i["status"] == "confirmed"]
        auto = [i for i in items if i["status"] == "auto"]
        rows.append({
            "code": ag["code"], "country": ag["country"], "name": ag["name"],
            "sectors": ag["sectors"], "website": ag["website"],
            "priorities_url": ag["priorities_url"],
            "confirmed": confirmed, "auto": auto,
            "n_confirmed": len(confirmed), "n_auto": len(auto),
        })
    return rows, findings


@app.get("/api/matrix")
def api_matrix(action_code: str | None = None, round: int | None = None,
               only_confirmed: bool = False, admin: str | None = None):
    is_admin = admin is not None and admin == ADMIN_TOKEN
    rows, findings = build_matrix()
    # Public callers never receive auto findings via the API.
    if not is_admin:
        for r in rows:
            r["auto"] = []
            r["n_auto"] = 0
    last_run = findings["runs"][-1] if findings["runs"] else None
    if action_code or round is not None or only_confirmed:
        filtered = []
        for r in rows:
            pool = r["confirmed"] if (only_confirmed or not is_admin) else r["confirmed"] + r["auto"]
            match = [i for i in pool
                     if (action_code is None or i.get("action_code") == action_code)
                     and (round is None or i.get("round") == round)]
            if match:
                fr = dict(r)
                fr["matched"] = match
                filtered.append(fr)
        return JSONResponse({"rows": filtered, "last_run": last_run})
    return JSONResponse({"rows": rows, "last_run": last_run})


@app.post("/api/findings/{idx}/confirm")
def confirm_finding(idx: int, action_code: str, round: int, token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Invalid admin token")
    findings = load_findings()
    if idx < 0 or idx >= len(findings["items"]):
        raise HTTPException(404, "Finding not found")
    findings["items"][idx]["status"] = "confirmed"
    findings["items"][idx]["action_code"] = action_code
    findings["items"][idx]["round"] = round
    save_findings(findings)
    return {"ok": True, "item": findings["items"][idx]}


@app.post("/api/findings/{idx}/reject")
def reject_finding(idx: int, token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Invalid admin token")
    findings = load_findings()
    if idx < 0 or idx >= len(findings["items"]):
        raise HTTPException(404, "Finding not found")
    findings["items"][idx]["status"] = "rejected"
    save_findings(findings)
    return {"ok": True}


@app.post("/api/scrape-now")
def scrape_now(token: str):
    """Manual scraper trigger (for testing after deploy)."""
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Invalid admin token")
    from app.scraper import run as run_scraper
    run_scraper()
    findings = load_findings()
    last_run = findings["runs"][-1] if findings["runs"] else None
    return {"ok": True, "last_run": last_run}


@app.get("/api/health")
def health():
    return {"status": "ok", "date": date.today().isoformat()}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, admin: str | None = None):
    is_admin = admin is not None and admin == ADMIN_TOKEN
    agencies_data = load_json("national_agencies.json")
    actions_data = load_json("actions_2026.json")
    actions = enrich_actions(actions_data["actions"])

    ka1 = [a for a in actions if a["key_action"] == "KA1"]
    ka2 = [a for a in actions if a["key_action"] == "KA2"]
    open_count = sum(1 for a in actions if a["status"] == "open")

    matrix_rows, findings = build_matrix()
    last_run = findings["runs"][-1] if findings["runs"] else None
    # Pending findings only matter for admins.
    pending = [{"idx": i, **it} for i, it in enumerate(findings["items"])
               if it["status"] == "auto"] if is_admin else []
    n_open_nas = sum(1 for r in matrix_rows if r["n_confirmed"] > 0)

    # Public users see only confirmed rounds — strip auto findings from cards.
    if not is_admin:
        for r in matrix_rows:
            r["auto"] = []
            r["n_auto"] = 0

    return templates.TemplateResponse("index.html", {
        "request": request,
        "is_admin": is_admin,
        "agencies": agencies_data["agencies"],
        "ka1": ka1,
        "ka2": ka2,
        "priorities": actions_data["horizontal_priorities"],
        "open_count": open_count,
        "total_actions": len(actions),
        "agency_count": len(agencies_data["agencies"]),
        "today": date.today().isoformat(),
        "meta": actions_data["_meta"],
        "matrix": matrix_rows,
        "pending": pending,
        "last_run": last_run,
        "n_open_nas": n_open_nas,
        "tracked_actions": actions,
    })
