#!/usr/bin/env python3
"""
Pobiera dzienne ceny commodities z FRED (Federal Reserve St. Louis)
i EIA (U.S. Energy Information Administration).

Wymaga zmiennych srodowiskowych:
  FRED_KEY - klucz API FRED
  EIA_KEY  - klucz API EIA

Wynik:
  data/prices.json - wszystkie serie w jednym pliku
  data/meta.json   - metadane produktow
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

FRED_KEY = os.environ.get("FRED_KEY", "").strip()
EIA_KEY = os.environ.get("EIA_KEY", "").strip()

if not FRED_KEY or not EIA_KEY:
    print("BLAD: Ustaw zmienne srodowiskowe FRED_KEY i EIA_KEY", file=sys.stderr)
    sys.exit(1)

START_DATE = "2014-01-01"

PRODUCTS = [
    dict(id="NG",    source="fred", series="DHHNGSP",
         name="Henry Hub (gaz US)",       unit="$/MMBtu",
         contract_size=10000, contract_unit="MMBtu",
         category="Energia", color="#4fc3f7"),
    dict(id="WTI",   source="fred", series="DCOILWTICO",
         name="WTI Crude (ropa US)",      unit="$/bbl",
         contract_size=1000,  contract_unit="bbl",
         category="Energia", color="#ff8a65"),
    dict(id="BRENT", source="fred", series="DCOILBRENTEU",
         name="Brent Crude (ropa)",       unit="$/bbl",
         contract_size=1000,  contract_unit="bbl",
         category="Energia", color="#ba68c8"),
    dict(id="HEAT",  source="fred", series="DHOILNYH",
         name="Heating Oil / ULSD (NY)",  unit="$/gal",
         contract_size=42000, contract_unit="gal",
         category="Energia", color="#ff5722"),
    dict(id="RBOB",  source="fred", series="DGASUSGULF",
         name="Benzyna (US Gulf spot)",   unit="$/gal",
         contract_size=42000, contract_unit="gal",
         category="Energia", color="#ffb74d"),
    dict(id="GAS_RETAIL_US", source="fred", series="GASREGW",
         name="Benzyna detal USA (avg)",  unit="$/gal",
         contract_size=1, contract_unit="gal",
         category="Energia", color="#ffa000"),
    dict(id="GOLD",   source="fred", series="GOLDAMGBD228NLBM",
         name="Zloto (LBMA AM fix)",      unit="$/oz",
         contract_size=100,   contract_unit="oz",
         category="Metale", color="#ffd54f"),
    dict(id="SILVER", source="fred", series="SLVPRUSD",
         name="Srebro (LBMA)",            unit="$/oz",
         contract_size=5000,  contract_unit="oz",
         category="Metale", color="#b0bec5"),
]


def fetch_fred(series_id):
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
        f"&observation_start={START_DATE}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "energy-analytics/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    obs = []
    for o in data.get("observations", []):
        v = o.get("value", "")
        if v and v != ".":
            try:
                obs.append({"date": o["date"], "value": float(v)})
            except ValueError:
                pass
    return obs


def main():
    print(f"Start: {datetime.now(timezone.utc).isoformat()}")
    print(f"Zakres historii: od {START_DATE}")

    products_out = {}
    meta_out = []
    failed = []

    for p in PRODUCTS:
        pid = p["id"]
        print(f"\n[{pid}] pobieram {p['source']}:{p['series']} ...", flush=True)
        try:
            if p["source"] == "fred":
                obs = fetch_fred(p["series"])
            else:
                print(f"  [SKIP] zrodlo {p['source']} nieobslugiwane")
                continue
            if not obs:
                print(f"  [WARN] brak obserwacji")
                failed.append(pid)
                continue
            products_out[pid] = obs
            first, last = obs[0], obs[-1]
            print(f"  [OK] {len(obs)} obs, od {first['date']} do {last['date']}, "
                  f"ostatnia = {last['value']} {p['unit']}")
            meta_out.append({
                "id": pid, "name": p["name"], "unit": p["unit"],
                "contract_size": p["contract_size"], "contract_unit": p["contract_unit"],
                "category": p["category"], "color": p["color"],
                "source": p["source"], "series": p["series"],
                "first_date": first["date"], "last_date": last["date"],
                "n_observations": len(obs),
            })
        except urllib.error.HTTPError as e:
            print(f"  [BLAD HTTP {e.code}] {e.reason}")
            failed.append(pid)
        except Exception as e:
            print(f"  [BLAD] {type(e).__name__}: {e}")
            failed.append(pid)
        time.sleep(0.3)

    prices_file = DATA_DIR / "prices.json"
    meta_file = DATA_DIR / "meta.json"

    with prices_file.open("w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "start_date": START_DATE,
            "products": products_out,
        }, f, separators=(",", ":"))

    with meta_file.open("w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "products": meta_out, "failed": failed,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Zapisano {prices_file} ({prices_file.stat().st_size/1024:.1f} KB)")
    print(f"Zapisano {meta_file}")
    print(f"Udane serie: {len(products_out)} | Nieudane: {len(failed)}")
    if failed:
        print(f"Nieudane: {', '.join(failed)}")


if __name__ == "__main__":
    main()
