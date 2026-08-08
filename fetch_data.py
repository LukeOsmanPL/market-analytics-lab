#!/usr/bin/env python3
"""
Pobiera dzienne ceny commodities z:
  - FRED (Federal Reserve St. Louis) - energia
  - Yahoo Finance (przez pakiet yfinance) - metale, zboza, tropikalne

Wymaga zmiennych srodowiskowych:
  FRED_KEY - klucz API FRED
  EIA_KEY  - klucz API EIA (obecnie nieuzywany, w rezerwie)

Wynik:
  data/prices.json - wszystkie serie w jednym pliku
  data/meta.json   - metadane
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

if not FRED_KEY:
    print("BLAD: Ustaw zmienna srodowiskowa FRED_KEY", file=sys.stderr)
    sys.exit(1)

START_DATE = "1995-01-01"  # 30 lat historii; nie wszystkie serie sięgają tak daleko - fetch zwraca co jest dostępne

# ---------------------------------------------------------------------------
# Produkty
#
# source:
#   fred    - pobiera z api.stlouisfed.org
#   yahoo   - pobiera przez yfinance
# unit_scale:
#   opcjonalny mnoznik do zastosowania na cenach (np. 0.01 dla ¢ -> $)
#   uzywane zeby wszystkie zboza/kawa mialy jednolite jednostki $
# ---------------------------------------------------------------------------
PRODUCTS = [
    # Energia (FRED) - potwierdzone dzialaja
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

    # Metale (Yahoo Finance)
    dict(id="GOLD",     source="yahoo", series="GC=F",
         name="Zloto (COMEX)",            unit="$/oz",
         contract_size=100,   contract_unit="oz",
         category="Metale", color="#ffd54f"),
    dict(id="SILVER",   source="yahoo", series="SI=F",
         name="Srebro (COMEX)",           unit="$/oz",
         contract_size=5000,  contract_unit="oz",
         category="Metale", color="#b0bec5"),
    dict(id="COPPER",   source="yahoo", series="HG=F",
         name="Miedz (COMEX)",            unit="$/lb",
         contract_size=25000, contract_unit="lb",
         category="Metale", color="#d84315"),
    dict(id="PLATINUM", source="yahoo", series="PL=F",
         name="Platyna (NYMEX)",          unit="$/oz",
         contract_size=50,    contract_unit="oz",
         category="Metale", color="#78909c"),

    # Zboza (Yahoo Finance) - Yahoo daje ceny w centach; przeliczamy na dolary
    dict(id="CORN",    source="yahoo", series="ZC=F", unit_scale=0.01,
         name="Kukurydza (CBOT Chicago)", unit="$/bu",
         contract_size=5000, contract_unit="bu",
         category="Rolne", color="#fbc02d"),
    dict(id="WHEAT",   source="yahoo", series="ZW=F", unit_scale=0.01,
         name="Pszenica SRW (CBOT)",      unit="$/bu",
         contract_size=5000, contract_unit="bu",
         category="Rolne", color="#8d6e63"),
    dict(id="WHEAT_KC", source="yahoo", series="KE=F", unit_scale=0.01,
         name="Pszenica HRW (Kansas)",    unit="$/bu",
         contract_size=5000, contract_unit="bu",
         category="Rolne", color="#a1887f"),
    dict(id="WHEAT_MW", source="yahoo", series="MW=F", unit_scale=0.01,
         name="Pszenica Spring (MGEX)",   unit="$/bu",
         contract_size=5000, contract_unit="bu",
         category="Rolne", color="#4e342e"),
    dict(id="SOYBEAN", source="yahoo", series="ZS=F", unit_scale=0.01,
         name="Soja (CBOT)",              unit="$/bu",
         contract_size=5000, contract_unit="bu",
         category="Rolne", color="#7cb342"),
    dict(id="SOYMEAL", source="yahoo", series="ZM=F",
         name="Mączka sojowa (CBOT)",     unit="$/ton",
         contract_size=100, contract_unit="short tons",
         category="Rolne", color="#689f38"),
    dict(id="SOYOIL",  source="yahoo", series="ZL=F", unit_scale=0.01,
         name="Olej sojowy (CBOT)",       unit="$/lb",
         contract_size=60000, contract_unit="lb",
         category="Rolne", color="#f9a825"),

    # Polska: retail (detal) z EU Weekly Oil Bulletin - historia tygodniowa od 2005
    dict(id="PL_PB95_WOB", source="wob", series="Poland|Euro-Super 95",
         name="Pb95 detal PL (EU WOB)",   unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#4db6ac"),
    dict(id="PL_ON_WOB",   source="wob", series="Poland|Automotive Gas Oil",
         name="ON detal PL (EU WOB)",     unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#26a69a"),
    dict(id="PL_LPG_WOB",  source="wob", series="Poland|LPG",
         name="LPG detal PL (EU WOB)",    unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#80cbc4"),
    dict(id="PL_HEAT_WOB", source="wob", series="Poland|Heating Gas Oil",
         name="Olej opałowy PL (EU WOB)", unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#00897b"),
    # Odniesienie EU
    dict(id="EU_PB95_WOB", source="wob", series="Euro Area|Euro-Super 95",
         name="Pb95 detal Eurozone (WOB)",unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Europa", color="#9575cd"),
    dict(id="EU_ON_WOB",   source="wob", series="Euro Area|Automotive Gas Oil",
         name="ON detal Eurozone (WOB)",  unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Europa", color="#7e57c2"),

    # MATIF Paryz (Euronext) - best-effort, Yahoo bywa kaprysny dla EU futures
    dict(id="MATIF_WHEAT", source="yahoo", series="EBM.PA",
         name="Pszenica młynarska (MATIF Paris)", unit="€/t",
         contract_size=50, contract_unit="t",
         category="Rolne", color="#ff7043"),
    dict(id="MATIF_CORN",  source="yahoo", series="EMA.PA",
         name="Kukurydza (MATIF Paris)",  unit="€/t",
         contract_size=50, contract_unit="t",
         category="Rolne", color="#ffab40"),
    dict(id="MATIF_RAPESEED", source="yahoo", series="RS=F",
         name="Rzepak (ICE Winnipeg)",    unit="CAD/t",
         contract_size=20, contract_unit="t",
         category="Rolne", color="#c0ca33"),

    # Europa - gaz i inne benchmarki europejskie
    dict(id="TTF",   source="yahoo", series="TTF=F",
         name="TTF (gaz EU, Amsterdam)",  unit="€/MWh",
         contract_size=1000, contract_unit="MWh",
         category="Europa", color="#66bb6a"),
    dict(id="EU_NG_MO", source="fred", series="PNGASEUUSDM",
         name="Gaz EU (WB, miesieczny)", unit="$/MMBtu",
         contract_size=1, contract_unit="MMBtu",
         category="Europa", color="#81c784"),
    dict(id="COAL_AU", source="fred", series="PCOALAUUSDM",
         name="Wegiel Australia (WB, miesieczny)", unit="$/mt",
         contract_size=1, contract_unit="mt",
         category="Energia", color="#455a64"),
    dict(id="LNG_JP",  source="fred", series="PNGASJPUSDM",
         name="LNG Japonia (WB, miesieczny)", unit="$/MMBtu",
         contract_size=1, contract_unit="MMBtu",
         category="Energia", color="#e57373"),

    # Tropikalne (Yahoo Finance)
    dict(id="COFFEE",  source="yahoo", series="KC=F", unit_scale=0.01,
         name="Kawa Arabica (ICE)",       unit="$/lb",
         contract_size=37500, contract_unit="lb",
         category="Rolne", color="#6d4c41"),
    dict(id="COCOA",   source="yahoo", series="CC=F",
         name="Kakao (ICE)",              unit="$/mt",
         contract_size=10,   contract_unit="mt",
         category="Rolne", color="#5d4037"),
    dict(id="SUGAR",   source="yahoo", series="SB=F", unit_scale=0.01,
         name="Cukier (ICE 11)",          unit="$/lb",
         contract_size=112000, contract_unit="lb",
         category="Rolne", color="#f8bbd0"),
]


def fetch_fred(series_id: str) -> list:
    """Zwraca liste {date, value} dla serii FRED."""
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


WOB_URL = ("https://energy.ec.europa.eu/document/download/"
           "906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
           "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx")
_WOB_CACHE = None  # cache pobranego XLSX - jeden download na cala petle produktow

def _download_wob_xlsx():
    """Downloaduje WOB XLSX raz i cache'uje surowe bajty."""
    global _WOB_CACHE
    if _WOB_CACHE is not None:
        return _WOB_CACHE
    print(f"  [WOB] pobieram XLSX z ec.europa.eu ...", flush=True)
    req = urllib.request.Request(WOB_URL, headers={"User-Agent": "Mozilla/5.0 (energy-analytics)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        _WOB_CACHE = r.read()
    print(f"  [WOB] pobrano {len(_WOB_CACHE)/1024/1024:.1f} MB", flush=True)
    return _WOB_CACHE


_WOB_PARSED = None

def _parse_wob_workbook():
    """Parsuje XLSX WOB (wielopoziomowe naglowki: kraj + produkt).
    Zwraca slownik: {(country, product): [(date_iso, price), ...]}.
    Wynik cache'owany globalnie - pobierany raz na uruchomienie skryptu.
    """
    global _WOB_PARSED
    if _WOB_PARSED is not None:
        return _WOB_PARSED

    import openpyxl
    from io import BytesIO
    from datetime import datetime as _dt

    raw = _download_wob_xlsx()
    wb = openpyxl.load_workbook(BytesIO(raw), read_only=False, data_only=True)
    print(f"  [WOB] arkusze: {wb.sheetnames}", flush=True)

    # Interesuje nas "Prices with taxes" (retail z podatkami - najbardziej porownywalne z cenami na stacjach)
    if 'Prices with taxes' not in wb.sheetnames:
        print(f"  [WOB] BLAD: brak arkusza 'Prices with taxes'", flush=True)
        _WOB_PARSED = {}
        return _WOB_PARSED
    ws = wb['Prices with taxes']

    # Merged cells: rozprowadz wartosc top-left po calym merge
    merged_values = {}
    for mrange in ws.merged_cells.ranges:
        top = ws.cell(row=mrange.min_row, column=mrange.min_col).value
        for r in range(mrange.min_row, mrange.max_row + 1):
            for c in range(mrange.min_col, mrange.max_col + 1):
                merged_values[(r, c)] = top

    def cell(r, c):
        v = merged_values.get((r, c))
        if v is not None: return v
        return ws.cell(row=r, column=c).value

    # DEBUG: pokaz pierwsze 8 wierszy zeby zrozumiec strukture
    max_col_check = min(ws.max_column, 100)
    print(f"  [WOB] wymiary: {ws.max_row} wierszy x {ws.max_column} kolumn", flush=True)
    print(f"  [WOB] === pierwsze wiersze (kolumny 1-20) ===", flush=True)
    for r in range(1, 9):
        vals = [str(cell(r, c))[:15] if cell(r, c) is not None else '' for c in range(1, 21)]
        print(f"  [WOB] R{r}: {vals}", flush=True)

    # Znajdz wiersze naglowka: country row (zawiera 'Poland' albo 'Belgium'/'Germany')
    # i product row (zawiera 'Euro-Super 95' albo 'Automotive Gas Oil')
    country_row = None
    product_row = None
    for r in range(1, 8):
        row_str = ' | '.join(str(cell(r, c) or '') for c in range(1, max_col_check + 1)).lower()
        if country_row is None and ('poland' in row_str or 'belgium' in row_str or 'germany' in row_str):
            country_row = r
            print(f"  [WOB] wykryto wiersz krajow: R{r}", flush=True)
        if product_row is None and ('euro-super' in row_str or 'gas oil' in row_str.replace('heating gas oil', '').replace('automotive gas oil', '') or 'gasoline' in row_str):
            product_row = r
            print(f"  [WOB] wykryto wiersz produktow: R{r}", flush=True)
        # Alternatywnie wykryj po innych markerach
        if product_row is None and ('automotive' in row_str or 'diesel' in row_str):
            product_row = r
            print(f"  [WOB] wykryto wiersz produktow (alt): R{r}", flush=True)

    if country_row is None or product_row is None:
        print(f"  [WOB] BLAD: naglowki nie znalezione (country={country_row}, product={product_row})", flush=True)
        _WOB_PARSED = {}
        return _WOB_PARSED

    # Zbuduj mape kolumn -> (country, product)
    col_map = {}
    for c in range(2, max_col_check + 1):  # kolumna 1 to zwykle data
        country = cell(country_row, c)
        product = cell(product_row, c)
        if country and product:
            country_s = str(country).strip()
            product_s = str(product).strip()
            # Odrzuc gdzie country wyglada jak inna wartosc (np. sub-header)
            if len(country_s) < 60 and len(product_s) < 60:
                col_map[c] = (country_s, product_s)

    print(f"  [WOB] zmapowanych kolumn: {len(col_map)}", flush=True)
    seen_countries = set(co for co, _ in col_map.values())
    seen_products = set(pr for _, pr in col_map.values())
    print(f"  [WOB] wykryte kraje ({len(seen_countries)}): {sorted(seen_countries)[:30]}", flush=True)
    print(f"  [WOB] wykryte produkty ({len(seen_products)}): {sorted(seen_products)}", flush=True)

    # Znajdz kolumne daty (pierwsza kolumna z datami w tresci)
    data_start_row = max(country_row, product_row) + 1
    date_col = None
    for test_col in [1, 2]:
        v = cell(data_start_row, test_col)
        if hasattr(v, 'strftime') or (isinstance(v, str) and len(v) >= 8):
            date_col = test_col
            break
    if date_col is None:
        date_col = 1
    print(f"  [WOB] data w kolumnie {date_col}, dane od wiersza {data_start_row}", flush=True)

    # Skanowanie danych
    results = {}
    n_scanned = 0
    n_valid = 0
    for r in range(data_start_row, ws.max_row + 1):
        n_scanned += 1
        date_val = cell(r, date_col)
        if not date_val:
            continue
        if hasattr(date_val, 'strftime'):
            date_str = date_val.strftime('%Y-%m-%d')
        elif isinstance(date_val, str):
            s = date_val.strip()
            date_str = None
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d.%m.%Y', '%Y/%m/%d'):
                try:
                    date_str = _dt.strptime(s[:10], fmt).strftime('%Y-%m-%d')
                    break
                except: pass
            if not date_str:
                continue
        else:
            continue

        for col, (country, product) in col_map.items():
            val = cell(r, col)
            if isinstance(val, (int, float)) and val > 0 and val < 100000:
                results.setdefault((country, product), []).append((date_str, float(val)))
                n_valid += 1

    print(f"  [WOB] przeskanowano {n_scanned} wierszy, {n_valid} valid data points", flush=True)
    # Sample: kilka par
    for k, v in list(results.items())[:8]:
        print(f"  [WOB] sample: {k[0]}|{k[1]}: {len(v)} obs, pierwsza {v[0]}, ostatnia {v[-1]}", flush=True)

    _WOB_PARSED = results
    return results


def fetch_wob(series_key: str) -> list:
    """Zwraca liste {date, value} dla klucza 'Country|Product'."""
    parsed = _parse_wob_workbook()
    if '|' not in series_key:
        return []
    country, product = series_key.split('|', 1)
    obs_tuples = parsed.get((country, product), [])
    if not obs_tuples:
        # sprobuj bez case-sensitivity - moze mapping niestandardowy
        for (c, p), vals in parsed.items():
            if c.lower() == country.lower() and p.lower() == product.lower():
                obs_tuples = vals
                break
    # Deduplikacja po dacie, sortowanie
    seen = {}
    for d, v in obs_tuples:
        seen[d] = v
    obs = [{"date": d, "value": v} for d, v in sorted(seen.items())]
    return obs


def fetch_yahoo(ticker: str, unit_scale: float = 1.0) -> list:
    """Zwraca liste {date, value} z Yahoo Finance przez yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("Brakuje pakietu yfinance - dodaj do requirements.txt")

    t = yf.Ticker(ticker)
    df = t.history(start=START_DATE, auto_adjust=False, actions=False)
    if df is None or df.empty:
        return []
    obs = []
    for ts, row in df.iterrows():
        close = row.get("Close")
        if close is None:
            continue
        try:
            v = float(close) * unit_scale
        except (TypeError, ValueError):
            continue
        # ts moze byc pd.Timestamp; wez ISO date
        date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        obs.append({"date": date_str, "value": round(v, 4)})
    return obs


def main():
    print(f"Start: {datetime.now(timezone.utc).isoformat()}")
    print(f"Zakres historii: od {START_DATE}")

    products_out = {}
    meta_out = []
    failed = []

    for p in PRODUCTS:
        pid = p["id"]
        scale = p.get("unit_scale", 1.0)
        scale_note = f" (skala x{scale})" if scale != 1.0 else ""
        print(f"\n[{pid}] {p['source']}:{p['series']}{scale_note} ...", flush=True)
        try:
            if p["source"] == "fred":
                obs = fetch_fred(p["series"])
            elif p["source"] == "yahoo":
                obs = fetch_yahoo(p["series"], scale)
            elif p["source"] == "wob":
                obs = fetch_wob(p["series"])
            else:
                print(f"  [SKIP] nieznane zrodlo {p['source']}")
                continue

            if not obs:
                print(f"  [WARN] brak obserwacji")
                failed.append(pid)
                continue

            products_out[pid] = obs
            first, last = obs[0], obs[-1]
            print(f"  [OK] {len(obs)} obs, {first['date']} -> {last['date']}, "
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
