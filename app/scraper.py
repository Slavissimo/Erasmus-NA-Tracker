"""
Auto-scraper for Erasmus+ application rounds across National Agency (NA) websites.

PHILOSOPHY: This scraper NEVER writes "round is open" as a verified fact. Every
hit is stored with status 'auto' (auto-detected), together with the EXACT source
URL where it was found and the text snippet that triggered it. A human confirms
(-> 'confirmed') or rejects (-> 'rejected') each finding in the admin view. The
public matrix shows only confirmed findings.

HOW SOURCE URL WORKS: For each NA the scraper fetches the landing page, then
follows up to a few in-page links whose anchor text or URL looks call-related
(one level deep). Signals found on a sub-page are stored with that sub-page's
URL, so you get the article/announcement link, not just the landing page.

KNOWN LIMITATIONS:
- 42 sites = 42 structures. Detection is heuristic, not semantic.
- Multilingual: signal-word coverage is broad but not complete -> may miss things.
- Some sites block bots (403/Cloudflare) or time out -> status 'blocked'/'error'.
- False positives and misses are expected. Hence human-in-the-loop.

Run: python -m app.scraper
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

DATA_DIR = Path(__file__).resolve().parent / "data"
AGENCIES = DATA_DIR / "national_agencies.json"
SNAPSHOTS = DATA_DIR / "snapshots.json"
FINDINGS = DATA_DIR / "round_findings.json"

SIGNAL_WORDS = [
    "deadline", "call for proposals", "second round", "2nd round", "round 2",
    "application", "submission", "now open", "apply",
    "výzva", "termín", "uzávierka", "druhé kolo", "2. kolo", "podanie", "podávanie",
    "uzávěrka", "žádost",
    "nabór", "termin", "drugi nabór", "wniosek", "konkurs",
    "antragsfrist", "aufruf", "zweite runde", "einreichung", "frist",
    "appel à propositions", "date limite", "deuxième tour", "candidature", "échéance",
    "convocatoria", "plazo", "segunda ronda", "scadenza", "bando", "prazo", "candidatura",
    "ka210", "ka220", "ka152", "ka153", "ka154", "ka122", "ka151",
]

LINK_HINTS = ["call", "deadline", "výzv", "termín", "nabór", "aufruf", "antrag",
              "appel", "convocator", "bando", "round", "kolo", "ka2", "ka1",
              "apply", "fund", "grant", "news", "aktualit", "novink"]

TRACKED = ["KA210-ADU", "KA210-YOU", "KA152-YOU", "KA153-YOU", "KA154-YOU",
           "KA122-ADU", "KA220-ADU", "KA220-YOU"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

MAX_SUBPAGES = 4


def load(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(path: Path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def clean_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def find_signals(text: str) -> list:
    low = text.lower()
    hits, seen = [], set()
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
    return hits[:8]


def extract_links(html: str, base_url: str) -> list:
    base_host = urlparse(base_url).netloc
    out, seen = [], set()
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         html, flags=re.I | re.S):
        href, anchor = m.group(1), clean_text(m.group(2))
        full = urljoin(base_url, href)
        host = urlparse(full).netloc
        if not host or host != base_host or not full.startswith("http"):
            continue
        hint_src = (anchor + " " + href).lower()
        if any(h in hint_src for h in LINK_HINTS):
            if full not in seen:
                seen.add(full)
                out.append((full, anchor))
    return out[:MAX_SUBPAGES]


def fetch(url: str):
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


def scan_agency(ag: dict):
    landing = ag.get("priorities_url") or ag.get("website")
    status, html = fetch(landing)
    if status != "ok" or not html:
        return status, []
    found = []
    for s in find_signals(clean_text(html)):
        found.append({**s, "source_url": landing})
    for sub_url, anchor in extract_links(html, landing):
        st, sub_html = fetch(sub_url)
        if st == "ok" and sub_html:
            for s in find_signals(clean_text(sub_html)):
                found.append({**s, "source_url": sub_url, "via": anchor[:60]})
    uniq, seen = [], set()
    for f in found:
        k = (f["snippet"][:40], f["source_url"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return "ok", uniq[:10]


def combined_hash(findings: list) -> str:
    blob = "|".join(sorted(f["snippet"][:40] + f["source_url"] for f in findings))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run():
    agencies = load(AGENCIES, {"agencies": []})["agencies"]
    snapshots = load(SNAPSHOTS, {})
    findings = load(FINDINGS, {"runs": [], "items": []})
    now = datetime.now(timezone.utc).isoformat()
    run_log = {"timestamp": now, "results": []}
    existing = {(i["agency_code"], i["snippet"][:40], i.get("source_url") or i.get("url"))
                for i in findings["items"]}

    for ag in agencies:
        code = ag["code"]
        status, hits = scan_agency(ag)
        entry = {"agency_code": code, "country": ag["country"],
                 "status": status, "changed": False, "signal_count": 0}
        if status == "ok":
            h = combined_hash(hits)
            prev = snapshots.get(code, {}).get("hash")
            entry["changed"] = (prev is None or prev != h)
            snapshots[code] = {"hash": h, "last_seen": now}
            entry["signal_count"] = len(hits)
            if entry["changed"]:
                for s in hits:
                    key = (code, s["snippet"][:40], s["source_url"])
                    if key not in existing:
                        existing.add(key)
                        findings["items"].append({
                            "agency_code": code, "country": ag["country"],
                            "url": s["source_url"], "via": s.get("via"),
                            "word": s["word"], "snippet": s["snippet"],
                            "detected_at": now, "status": "auto",
                            "action_code": None, "round": None,
                        })
        run_log["results"].append(entry)

    findings["runs"] = (findings.get("runs", []) + [run_log])[-30:]
    save(SNAPSHOTS, snapshots)
    save(FINDINGS, findings)
    ok = sum(1 for r in run_log["results"] if r["status"] == "ok")
    blocked = sum(1 for r in run_log["results"] if r["status"] == "blocked")
    err = sum(1 for r in run_log["results"] if r["status"] == "error")
    new_auto = sum(1 for i in findings["items"] if i["detected_at"] == now)
    print(f"[scraper] {now}")
    print(f"[scraper] OK={ok}  blocked={blocked}  error={err}  (of {len(agencies)} NAs)")
    print(f"[scraper] new auto-findings: {new_auto}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
