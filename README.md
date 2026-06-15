# Erasmus+ National Agency Tracker

Web aplikácia, ktorá sleduje, **ktoré národné agentúry (NA) otvorili ktoré kolo**
podávania projektov KA1/KA2 — aby si vedel, v ktorých krajinách hľadať partnerov.
Zamerané na sektory mládeže a vzdelávania dospelých.

## Hlavná funkcia: matica NA × akcia × kolo
- Pre každú NA vidíš, či otvorila podávanie pre danú akciu a kolo.
- **Filter**: „ukáž len NA, ktoré otvorili kolo X pre akciu Y" → zoznam krajín.
- **Export**: skopíruje zoznam krajín pre aktuálny filter (na partner search).
- Dva druhy nálezov:
  - **Potvrdené** (zelené) — overené človekom, môžeš im veriť.
  - **Auto** (žlté) — strojová detekcia zo scrapera, treba overiť.

## Ako funguje scraper — a jeho obmedzenia (čítaj!)
`app/scraper.py` raz denne stiahne weby všetkých 42 NA, porovná s predošlou
verziou a pri zmene hľadá signálne slová (deadline, výzva, druhé kolo, KA210…)
vo viacerých jazykoch. Nález NIKDY nezapíše ako fakt — uloží ho ako `auto`
s odkazom na zdroj a úryvkom textu. Ty ho v sekcii „Nálezy na overenie"
potvrdíš (priradíš akciu + kolo) alebo zamietneš.

**Prečo to nemôže byť 100% spoľahlivé (rozhodol si sa pre full-auto s týmto rizikom):**
- 42 webov = 42 rôznych štruktúr; detekcia je heuristická, nie sémantická.
- Viacjazyčnosť: pokrytie signálnych slov nie je úplné → môže prehliadnuť nález.
- Niektoré weby blokujú boty (403/Cloudflare) → stav `blocked`, žiadne dáta.
- Falošné poplachy aj prehliadnutia sú očakávané → preto human-in-the-loop.

Po deployi uvidíš v poslednom behu počty OK / blokované / chyba, takže budeš
vedieť, ktorým weboch scraping reálne funguje.

## DÔLEŽITÉ: dva háčiky na Renderi

### 1. Oddelený filesystem web vs. cron
Na Renderi má **web služba a cron job samostatný disk**. Scraper (cron) by zapísal
`round_findings.json` na svoj disk, ktorý web nevidí. Riešenia (vyber jedno):
- **(odporúčané) Render Persistent Disk** pripojený k obom službám na `/data`,
  a v kóde prepni `DATA_DIR` na `/data`. (Persistent disk je platená funkcia.)
- **Alebo** zluč scraper do web služby: namiesto cronu spúšťaj scraper z appky
  cez `BackgroundTasks` / APScheduler raz denne (beží v rámci web procesu).
- **Alebo** scraper zapisuje do externého úložiska (napr. malá Postgres na Renderi,
  alebo commit do gitu cez API). Najrobustnejšie, ale viac práce.
Pre rýchly štart: spusti scraper ručne lokálne a výsledný JSON commitni do repa.

### 2. Free web služba zaspáva
Po ~15 min nečinnosti zaspí; prvé načítanie potom trvá 30–50 s. Normálne pre free tier.

## Admin token
Potvrdzovanie/zamietanie nálezov vyžaduje token. Nastav `ADMIN_TOKEN` v Render
(Environment). Lokálne je default `change-me-local`. V UI sa pýta raz za session.

## Lokálne spustenie
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://127.0.0.1:8000
python -m app.scraper                  # ručné spustenie scrapera
```

## Štruktúra dát (všetko v app/data/, upravuje sa bez zmeny kódu)
- `national_agencies.json` — zoznam 42 NA.
- `actions_2026.json` — akcie KA1/KA2, termíny EÚ, horizontálne priority.
- `round_findings.json` — auto-nálezy + potvrdenia (generuje scraper + admin).
- `snapshots.json` — hash predošlých návštev webov (na detekciu zmien).

## API
- `GET /api/matrix?action_code=KA210-ADU&round=2&only_confirmed=true`
- `GET /api/agencies?sector=youth` · `GET /api/actions`
- `POST /api/findings/{idx}/confirm?action_code=..&round=..&token=..`
- `POST /api/findings/{idx}/reject?token=..`

## Public vs. admin view
- **Public** (the plain URL): sees only confirmed rounds in the matrix + filter +
  country-list export. No auto findings, no review section, no buttons.
- **Admin**: open the site with `?admin=YOUR_TOKEN` in the URL, e.g.
  `https://erasmus-na-tracker.onrender.com/?admin=YOUR_TOKEN`. Then you also see
  auto findings and the "Findings to review" section to confirm/reject.

NOTE: This is a soft gate, fine for a public list of Erasmus rounds. The token in
the URL is not strong security — don't put confidential data behind it. The
confirm/reject API endpoints are token-protected so the public can't change data.

## Source URLs (where a finding came from)
The scraper fetches each NA landing page, then follows up to a few call-related
links one level deep, and stores the EXACT sub-page URL where a signal was found
(plus the anchor text it came through, shown as "via:"). So source links point to
the actual announcement/article, not just the landing page. Sites that block bots
or have no crawlable links will still only yield the landing page or nothing.
