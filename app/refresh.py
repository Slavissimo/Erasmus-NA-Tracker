"""
Voliteľný modul: pokus o obnovenie termínov z oficiálneho portálu Komisie.

Portál https://webgate.ec.europa.eu/app-forms/af-ui-opportunities/ je SPA,
ktorá načítava dáta cez interné JSON API. Tento modul sa pokúsi zavolať
toto API a aktualizovať lokálne dáta. Ak sa štruktúra API zmení (čo sa
pri nedokumentovaných endpointoch stáva), modul zlyhá GRACEFULLY a appka
ďalej beží na kurátorovaných dátach z actions_2026.json.

Spustenie ručne:  python -m app.refresh
Alebo cez cron/Render scheduled job.

DÔLEŽITÉ: Toto je "best-effort" pomôcka, nie spoľahlivý zdroj pravdy.
Kurátorované JSON ostáva primárnym zdrojom.
"""
import json
import sys
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent / "data"

# Kandidátne endpointy - portál ich môže časom zmeniť.
CANDIDATE_ENDPOINTS = [
    "https://webgate.ec.europa.eu/app-forms/af-rest-services/rest/opportunities/list",
    "https://webgate.ec.europa.eu/erasmus-esc/index/opportunities",
]


def try_fetch() -> dict | None:
    headers = {"Accept": "application/json", "User-Agent": "ErasmusTracker/1.0"}
    for url in CANDIDATE_ENDPOINTS:
        try:
            r = httpx.get(url, headers=headers, timeout=20.0)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return r.json()
        except Exception as e:
            print(f"[refresh] {url} zlyhalo: {e}", file=sys.stderr)
    return None


def main():
    data = try_fetch()
    if not data:
        print("[refresh] Žiadny endpoint nevrátil dáta. Ponechávam kurátorované "
              "actions_2026.json. (Toto je očakávané, ak portál zmenil API.)")
        return 1
    # Sem by prišla transformácia data -> formát actions_2026.json.
    # Štruktúru treba zmapovať podľa reálnej odpovede API pri prvom úspešnom volaní.
    print("[refresh] Endpoint odpovedal. Skontroluj štruktúru a doplň mapovanie.")
    out = DATA_DIR / "portal_raw_snapshot.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[refresh] Surová odpoveď uložená do {out} na inšpekciu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
