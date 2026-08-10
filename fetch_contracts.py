#!/usr/bin/env python3
"""
Fetcher konkretnych kontraktów miesięcznych futures ze Stooq (CSV, darmowe).
Ściąga historię dla wygasłych i aktualnych kontraktów per produkt/miesiąc/rok.

Struktura Stooq: {root}{month_code}{yy}.f
  month code: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun,
              N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
  yy: dwie ostatnie cyfry roku (25 = 2025)
  przyklad: clf25.f = WTI Jan 2025

Cykl miesiecy handlowych rozny per produkt (nie wszystkie miesiace istnieja
na kazdym rynku). Fetcher probuje wszystkie 12 i zapisuje tylko te ktore
zwrocily dane.

Format wyjscia: data/contracts/{PID}.json
  {
    "product": "CL", "name": "...", "unit": "$/bbl", "contract_size": 1000,
    "months_traded": ["F","G",...],  // auto-wykryte
    "contracts": {
      "202501": [{"date": "2020-01-15", "value": 58.23}, ...],
      ...
    },
    "updated_at": "2026-08-09T..."
  }

Incremental: jesli plik istnieje, laczy nowe dane ze stara historia (merge_history).
"""
import json, sys, time
import urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
CONTRACTS_DIR = ROOT / "data" / "contracts"
CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

# Miesiac -> kod CME/CBOT
MONTH_CODES = ["F","G","H","J","K","M","N","Q","U","V","X","Z"]
MONTH_NUM = {c: i+1 for i, c in enumerate(MONTH_CODES)}

# Zakres lat do probowania (backfill + forward)
CURRENT_YEAR = datetime.now(timezone.utc).year
YEAR_START = CURRENT_YEAR - 15   # 15 lat wstecz
YEAR_END   = CURRENT_YEAR + 4    # 4 lata w przod (nadchodzace kontrakty)

# START_DATE dla filtracji zbyt starych danych (Stooq czasem zwraca smiecie)
MIN_DATE = "2005-01-01"

# ---------------------------------------------------------------------------
# Definicje produktow. root = Stooq root symbol (male litery, bez sufiksow)
# ---------------------------------------------------------------------------
PRODUCTS_C = [
    # Energia (NYMEX/ICE)
    dict(pid="CL", root="cl", name="WTI Crude (NYMEX)",        unit="$/bbl",
         contract_size=1000, contract_unit="bbl", category="Energia", color="#ff8a65"),
    dict(pid="BZ", root="cb", name="Brent Crude (ICE)",        unit="$/bbl",
         contract_size=1000, contract_unit="bbl", category="Energia", color="#ba68c8"),
    dict(pid="NG", root="ng", name="Henry Hub NG (NYMEX)",     unit="$/MMBtu",
         contract_size=10000, contract_unit="MMBtu", category="Energia", color="#4fc3f7"),
    dict(pid="HO", root="ho", name="Heating Oil / ULSD (NYMEX)", unit="$/gal",
         contract_size=42000, contract_unit="gal", category="Energia", color="#ff5722"),
    dict(pid="RB", root="rb", name="RBOB Gasoline (NYMEX)",    unit="$/gal",
         contract_size=42000, contract_unit="gal", category="Energia", color="#ffb74d"),
    # Metale (COMEX)
    dict(pid="GC", root="gc", name="Gold (COMEX)",             unit="$/oz",
         contract_size=100, contract_unit="oz", category="Metale", color="#ffd54f"),
    dict(pid="SI", root="si", name="Silver (COMEX)",           unit="$/oz",
         contract_size=5000, contract_unit="oz", category="Metale", color="#b0bec5"),
    dict(pid="HG", root="hg", name="Copper (COMEX)",           unit="$/lb",
         contract_size=25000, contract_unit="lb", category="Metale", color="#d84315"),
    dict(pid="PL", root="pl", name="Platinum (NYMEX)",         unit="$/oz",
         contract_size=50, contract_unit="oz", category="Metale", color="#78909c"),
    dict(pid="PA", root="pa", name="Palladium (NYMEX)",        unit="$/oz",
         contract_size=100, contract_unit="oz", category="Metale", color="#8d6e63"),
    # Zboza / oleiste (CBOT) - Stooq zwraca w centach/bushel -> mnozymy przez 0.01
    dict(pid="ZC", root="zc", name="Corn (CBOT)",              unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#fbc02d",
         unit_scale=0.01),
    dict(pid="ZW", root="zw", name="Wheat SRW (CBOT)",         unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#8d6e63",
         unit_scale=0.01),
    dict(pid="KE", root="ke", name="Wheat HRW (KCBT)",         unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#795548",
         unit_scale=0.01),
    dict(pid="ZS", root="zs", name="Soybean (CBOT)",           unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#9ccc65",
         unit_scale=0.01),
    dict(pid="ZM", root="zm", name="Soybean Meal (CBOT)",      unit="$/short ton",
         contract_size=100, contract_unit="short ton", category="Rolne", color="#7cb342"),
    dict(pid="ZL", root="zl", name="Soybean Oil (CBOT)",       unit="$/lb",
         contract_size=60000, contract_unit="lb", category="Rolne", color="#c0ca33",
         unit_scale=0.01),
    # Softs (ICE)
    dict(pid="KC", root="kc", name="Coffee Arabica (ICE)",     unit="$/lb",
         contract_size=37500, contract_unit="lb", category="Rolne", color="#6d4c41",
         unit_scale=0.01),
    dict(pid="CC", root="cc", name="Cocoa (ICE)",              unit="$/mt",
         contract_size=10, contract_unit="mt", category="Rolne", color="#5d4037"),
    dict(pid="SB", root="sb", name="Sugar #11 (ICE)",          unit="$/lb",
         contract_size=112000, contract_unit="lb", category="Rolne", color="#f8bbd0",
         unit_scale=0.01),
    dict(pid="CT", root="ct", name="Cotton (ICE)",             unit="$/lb",
         contract_size=50000, contract_unit="lb", category="Rolne", color="#f5f5dc",
         unit_scale=0.01),
    # Zywiec (CME)
    dict(pid="LE", root="le", name="Live Cattle (CME)",        unit="$/lb",
         contract_size=40000, contract_unit="lb", category="Rolne", color="#8d6e63",
         unit_scale=0.01),
    dict(pid="HE", root="he", name="Lean Hogs (CME)",          unit="$/lb",
         contract_size=40000, contract_unit="lb", category="Rolne", color="#e91e63",
         unit_scale=0.01),
]


def stooq_url(root: str, month_code: str, year: int) -> str:
    yy = f"{year % 100:02d}"
    sym = f"{root}{month_code.lower()}{yy}.f"
    return f"https://stooq.com/q/d/l/?s={urllib.parse.quote(sym)}&i=d"


_STOOQ_DEBUG_COUNT = 0
_STOOQ_DEBUG_LIMIT = 20  # log pierwsze N zapytań szczegółowo

def fetch_contract(root: str, month_code: str, year: int, unit_scale: float = 1.0):
    """Pobiera 1 kontrakt ze Stooq. Zwraca liste {date,value}, [] (brak) lub None (throttling)."""
    global _STOOQ_DEBUG_COUNT
    url = stooq_url(root, month_code, year)
    debug_this = _STOOQ_DEBUG_COUNT < _STOOQ_DEBUG_LIMIT
    _STOOQ_DEBUG_COUNT += 1
    try:
        # UZYWAM prawdziwego browser UA - Stooq czasem blokuje botów
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/csv,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=45) as r:
            status = r.status
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if debug_this:
            print(f"    [DBG] {url} -> HTTP {e.code} {e.reason}", flush=True)
        return None if e.code == 429 else []
    except Exception as e:
        if debug_this:
            print(f"    [DBG] {url} -> EXC {type(e).__name__}: {e}", flush=True)
        return None if "Too many" in str(e) or "429" in str(e) else []

    # Debug: pokaz pierwsze N zapytan (URL + status + skrocona odpowiedz)
    if debug_this:
        preview = raw[:150].replace("\n", " | ")
        print(f"    [DBG] {url} -> HTTP {status}, {len(raw)}B: {preview!r}", flush=True)

    if not raw:
        return []
    # Stooq gdy brak symbolu zwraca text/html z komunikatem "Brak danych" - wykrywamy
    if raw.strip().lower().startswith(("<!doctype", "<html", "no data", "brak")):
        return []
    if "Date" not in raw.split("\n", 1)[0]:
        return []
    import csv, io
    obs = []
    for row in csv.DictReader(io.StringIO(raw)):
        d = (row.get("Date") or "").strip()
        c = (row.get("Close") or "").strip()
        if not d or not c or d < MIN_DATE: continue
        try:
            v = float(c) * unit_scale
        except ValueError:
            continue
        # skip niesensowne wartosci (Stooq czasem zwraca 0 dla nieotwartych sesji)
        if v <= 0: continue
        obs.append({"date": d, "value": round(v, 4)})
    obs.sort(key=lambda o: o["date"])
    return obs


def merge_history(existing, fresh):
    """Union po dacie: nowe wartosci nadpisuja stare (revised prices), stare pozostaja."""
    if not existing and not fresh: return []
    combined = {o["date"]: o["value"] for o in (existing or [])}
    for o in (fresh or []):
        combined[o["date"]] = o["value"]
    return [{"date": d, "value": v} for d, v in sorted(combined.items())]


def load_existing(pid: str) -> dict:
    fp = CONTRACTS_DIR / f"{pid}.json"
    if not fp.exists(): return {}
    try:
        with fp.open() as f:
            return json.load(f)
    except Exception:
        return {}


def save_product(pid: str, meta: dict, data: dict):
    fp = CONTRACTS_DIR / f"{pid}.json"
    out = {
        "product": pid,
        "name": meta["name"],
        "unit": meta["unit"],
        "contract_size": meta["contract_size"],
        "contract_unit": meta["contract_unit"],
        "category": meta["category"],
        "color": meta["color"],
        "months_traded": sorted(set(m[-2:] for m in data.keys())),
        "contracts": data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with fp.open("w") as f:
        json.dump(out, f, ensure_ascii=False)   # bez indent - kompaktowo


def main():
    # Argumenty CLI: pierwsze CLI = "full" | "incremental" (default: incremental)
    mode = sys.argv[1] if len(sys.argv) > 1 else "incremental"
    print(f"[fetch_contracts] mode={mode}, produktow={len(PRODUCTS_C)}, "
          f"years={YEAR_START}..{YEAR_END}", flush=True)

    total_fetched = 0
    total_skipped = 0
    for p in PRODUCTS_C:
        pid = p["pid"]
        root = p["root"]
        unit_scale = p.get("unit_scale", 1.0)
        print(f"\n=== [{pid}] {p['name']} (root={root}) ===", flush=True)
        existing_wrapper = load_existing(pid)
        existing_contracts = existing_wrapper.get("contracts", {})
        new_contracts = dict(existing_contracts)  # kopia

        for year in range(YEAR_START, YEAR_END + 1):
            for mc in MONTH_CODES:
                key = f"{year:04d}{MONTH_NUM[mc]:02d}"  # np "202507"
                exp_date = f"{year:04d}-{MONTH_NUM[mc]:02d}-01"
                old = existing_contracts.get(key, [])

                # W trybie incremental: pomijamy kontrakty ktore wygasly ponad 90 dni temu
                # (zapisana historia sie nie zmieni) i maja jakiekolwiek dane
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if mode == "incremental" and old:
                    # Jesli ostatnia data w kontrakcie > 90 dni po expiracji (bezpieczna wartosc)
                    from datetime import timedelta
                    exp = datetime.strptime(exp_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > exp + timedelta(days=90) and len(old) > 5:
                        total_skipped += 1
                        continue

                obs = fetch_contract(root, mc, year, unit_scale)
                if obs is None:  # throttling
                    print(f"  [{pid}] {key} THROTTLE - sleep 30s", flush=True)
                    time.sleep(30)
                    obs = fetch_contract(root, mc, year, unit_scale) or []
                if not obs:
                    continue
                merged = merge_history(old, obs)
                new_contracts[key] = merged
                delta = len(merged) - len(old)
                print(f"  [{pid}] {key}: {len(merged)} pkt (+{delta} nowych, "
                      f"{obs[0]['date']}..{obs[-1]['date']})", flush=True)
                total_fetched += 1
                # Delikatny throttle - Stooq nie lubi >5 req/s
                time.sleep(0.25)

        # Zapisz produkt (nawet jesli 0 zmian, zeby updated_at sie odswiezyl przy full run)
        if new_contracts or existing_contracts:
            save_product(pid, p, new_contracts)
            print(f"  [{pid}] zapisano {len(new_contracts)} kontraktow", flush=True)

    # Zapisz manifest ze spisem produktow (do lazy-loading w UI)
    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "products": [
            {"pid": p["pid"], "name": p["name"], "unit": p["unit"],
             "contract_size": p["contract_size"], "contract_unit": p["contract_unit"],
             "category": p["category"], "color": p["color"]}
            for p in PRODUCTS_C
        ],
    }
    with (CONTRACTS_DIR / "_manifest.json").open("w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n[fetch_contracts] KONIEC: fetched={total_fetched}, skipped(incremental)={total_skipped}",
          flush=True)


if __name__ == "__main__":
    main()
