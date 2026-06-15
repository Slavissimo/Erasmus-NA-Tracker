"""
Auto-scraper kôl Erasmus+ naprieč webmi národných agentúr.

FILOZOFIA: Tento scraper NIKDY nezapisuje "kolo otvorené" ako overený fakt.
Každý nález má stav 'auto' (auto-detekované) s odkazom na zdroj a úryvkom textu,
ktorý ho spustil. Človek nález potvrdí (-> 'confirmed') alebo zamietne (-> 'rejected')
cez admin rozhranie. Matica vizuálne odlišuje auto vs. potvrdené.

DÔLEŽITÉ OBMEDZENIA (povedz si ich nahlas pred tým, než tomu uveríš):
- 42 webov = 42 štruktúr. Detekcia je heuristická, nie sémantická.
- Viacjazyčnosť: signálne slová sú vo viacerých jazykoch, ale pokrytie nie je úplné.
- Niektoré weby môžu blokovať boty (403/Cloudflare) aj na produkcii -> stav 'blocked'.
- Falošné poplachy aj prehliadnutia sú očakávané. Preto human-in-the-loop.

Spustenie: python -m app.scraper
Na Renderi: ako Cron Job (raz denne).
"""
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent / "data"
AGENCIES = DATA_DIR / "national_agencies.json"
SNAPSHOTS = DATA_DIR / "snapshots.json"      # hash + text predošlej návštevy
FINDINGS = DATA_DIR / "round_findings.json"  # auto-detekcie + potvrdenia

# Signálne slová indikujúce výzvu/termín/kolo — viacjazyčne (orientačné pokrytie).
SIGNAL_WORDS = [
    # EN
    "deadline", "call for proposals", "second round", "2nd round", "round 2",
    "application", "submission", "now open", "apply",
    # SK / CZ
    "výzva", "termín", "uzávierka", "druhé kolo", "2. kolo", "podanie", "podávanie",
    "uzávěrka", "druhé kolo", "žádost",
    # PL
    "nabór", "termin", "drugi nabór", "wniosek", "konkurs",
    # DE
    "antragsfrist", "aufruf", "zweite runde", "einreichung", "frist",
    # FR
    "appel à propositions", "date limite", "deuxième tour", "candidature", "échéance",
    # ES / IT / PT
    "convocatoria", "plazo", "segunda ronda", "scadenza", "bando", "prazo", "candidatura",
    # action codes
    "ka210", "ka220", "ka152", "ka153", "ka154", "ka122", "ka151",
]

# Akcie/kolá, ktoré majú zmysel auto-detekovať (nepovinné 2. kolá ap.)
TRACKED = ["KA210-ADU", "KA210-YOU", "KA152-YOU", "KA153-YOU", "KA154-YOU",
           "KA122-ADU", "KA220-ADU", "KA220-YOU"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def load(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(path: Path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def clean_text(html: str) -> str:
    """Hrubé odstránenie tagov + normalizácia na čistý text."""
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def find_signals(text: str) -> list[dict]:
    """Vráti úryvky okolo signálnych slov (na ľudské posúdenie)."""
    low = text.lower()
    hits = []
    seen = set()
    for w in SIGNAL_WORDS:
        idx = low.find(w)
        if idx != -1:
            start = max(0, idx - 60)
            end = min(len(text), idx + len(w) + 80)
            snippet = text[start:end].strip()
            key = snippet[:40]
            if key not in seen:
                seen.add(key)
                hits.append({"word": w, "snippet": snippet})
    return hits[:8]  # max 8 úryvkov na NA, nech to nie je šum


def fetch(url: str) -> tuple[str, str | None]:
    """Vráti (status, text|None). status: 'ok'|'blocked'|'error'."""
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True,
                      headers={"User-Agent": UA, "Accept-Language": "en,sk,de,fr"})
        if r.status_code == 200:
            return "ok", r.text
        if r.status_code in (401, 403, 429):
            return "blocked", None
        return "error", None
    except Exception:
        return "error", None


def run():
    agencies = load(AGENCIES, {"agencies": []})["agencies"]
    snapshots = load(SNAPSHOTS, {})
    findings = load(FINDINGS, {"runs": [], "items": []})

    now = datetime.now(timezone.utc).isoformat()
    run_log = {"timestamp": now, "results": []}
    existing_keys = {(i["agency_code"], i["snippet"][:40]) for i in findings["items"]}

    for ag in agencies:
        code = ag["code"]
        url = ag.get("priorities_url") or ag.get("website")
        status, html = fetch(url)
        entry = {"agency_code": code, "country": ag["country"], "url": url,
                 "status": status, "changed": False, "signal_count": 0}

        if status == "ok" and html:
            text = clean_text(html)
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()
            prev = snapshots.get(code, {}).get("hash")
            changed = (prev is not None and prev != h)
            entry["changed"] = changed or prev is None
            snapshots[code] = {"hash": h, "last_seen": now, "len": len(text)}

            # signály hľadáme vždy (aj pri prvej návšteve)
            if entry["changed"]:
                signals = find_signals(text)
                entry["signal_count"] = len(signals)
                for s in signals:
                    key = (code, s["snippet"][:40])
                    if key not in existing_keys:
                        existing_keys.add(key)
                        findings["items"].append({
                            "agency_code": code,
                            "country": ag["country"],
                            "url": url,
                            "word": s["word"],
                            "snippet": s["snippet"],
                            "detected_at": now,
                            "status": "auto",          # auto | confirmed | rejected
                            "action_code": None,         # vyplní človek pri potvrdení
                            "round": None,
                        })
        run_log["results"].append(entry)

    findings["runs"] = (findings.get("runs", []) + [run_log])[-30:]  # história 30 behov
    save(SNAPSHOTS, snapshots)
    save(FINDINGS, findings)

    ok = sum(1 for r in run_log["results"] if r["status"] == "ok")
    blocked = sum(1 for r in run_log["results"] if r["status"] == "blocked")
    err = sum(1 for r in run_log["results"] if r["status"] == "error")
    new_auto = sum(1 for i in findings["items"] if i["detected_at"] == now)
    print(f"[scraper] {now}")
    print(f"[scraper] OK={ok}  blokované={blocked}  chyba={err}  (z {len(agencies)} NA)")
    print(f"[scraper] nových auto-nálezov: {new_auto}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
