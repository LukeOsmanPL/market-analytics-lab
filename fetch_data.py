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


def _parse_wob_workbook():
    """Parsuje XLSX WOB. Zwraca slownik: {(country, product): [(date, value_eur_per_1000L), ...]}.

    Struktura pliku (na podstawie dokumentacji WOB):
      - tall format: kazdy wiersz to (date, country, product, price)
      - albo per-country sheets
    Parser probuje oba warianty defensywnie.
    """
    import openpyxl
    from io import BytesIO

    raw = _download_wob_xlsx()
    wb = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=True)
    print(f"  [WOB] arkusze: {wb.sheetnames}", flush=True)

    results = {}  # (country_name, product_name) -> [(date_iso, price)]

    # Znane nazwy produktow w WOB (do dopasowania)
    PRODUCT_ALIASES = {
        'Euro-Super 95': ['euro-super 95', 'eurosuper 95', 'euro super 95', 'gasoline'],
        'Automotive Gas Oil': ['automotive gas oil', 'diesel', 'gas oil'],
        'Heating Gas Oil': ['heating gas oil', 'heating oil'],
        'LPG': ['lpg', 'liquefied'],
        'Residual Fuel Oil': ['residual fuel oil'],
    }
    COUNTRY_ALIASES = {
        'Poland': ['poland', 'polska', 'pl '],
        'Euro Area': ['euro area', 'eu-27', 'eu 27', 'european union', 'eurozone'],
        'Germany': ['germany', 'deutschland'],
        'France': ['france'],
    }

    def match_alias(cell_value, aliases_dict):
        """Zwraca kanoniczna nazwe albo None."""
        if not cell_value: return None
        s = str(cell_value).strip().lower()
        for canonical, aliases in aliases_dict.items():
            for a in aliases:
                if a in s:
                    return canonical
        return None

    total_rows_scanned = 0
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        # Zbierz naglowki z pierwszych 5 wierszy (na wypadek zlozonych naglowkow)
        header_rows = []
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True)):
            header_rows.append(row)

        # Wykryj kolumny: szukamy kolumny 'date', kolumny z krajami, kolumny z produktami
        # Podejscie 1: WYSZUKAJ komorki z nazwami krajow w wierszach naglowka
        col_country_map = {}   # col_idx -> canonical country
        col_product_map = {}   # col_idx -> canonical product
        for hrow in header_rows:
            for col_idx, cell in enumerate(hrow):
                c_country = match_alias(cell, COUNTRY_ALIASES)
                if c_country:
                    col_country_map[col_idx] = c_country
                c_product = match_alias(cell, PRODUCT_ALIASES)
                if c_product:
                    col_product_map[col_idx] = c_product

        # Wariant A: sheet zawiera osobne kolumny per (country, product) - wtedy col_country_map lub col_product_map ma wpisy
        # Wariant B: sheet ma kolumny 'date', 'country', 'product', 'value' - tall format

        # Skanujemy wiersze danych
        for row_idx, row in enumerate(ws.iter_rows(min_row=6, values_only=True)):
            total_rows_scanned += 1
            if total_rows_scanned > 500000:  # safety
                break
            if not row or all(c is None for c in row):
                continue

            # Szukamy komorki z data (datetime)
            date_val = None
            for cell in row:
                if hasattr(cell, 'strftime'):
                    date_val = cell.strftime('%Y-%m-%d')
                    break
                # Moze byc str "2020-01-06" lub "06/01/2020"
                if isinstance(cell, str):
                    s = cell.strip()
                    # Sprobuj format YYYY-MM-DD
                    if len(s) == 10 and s[4] == '-' and s[7] == '-':
                        try:
                            datetime.strptime(s, '%Y-%m-%d')
                            date_val = s
                            break
                        except: pass

            if not date_val:
                continue

            # Tall format? Sprobuj znalezc country i product w komorkach tego wiersza
            row_country = None
            row_product = None
            row_value = None
            for cell in row:
                if cell is None: continue
                c = match_alias(cell, COUNTRY_ALIASES)
                if c and not row_country:
                    row_country = c
                p = match_alias(cell, PRODUCT_ALIASES)
                if p and not row_product:
                    row_product = p
                if isinstance(cell, (int, float)) and cell > 100 and cell < 5000:  # sensowna cena w EUR/1000L
                    row_value = float(cell)

            if row_country and row_product and row_value:
                key = (row_country, row_product)
                results.setdefault(key, []).append((date_val, row_value))
                continue

            # Wariant kolumnowy: iteruj po znanych kolumnach country/product
            for col_idx, cell in enumerate(row):
                if col_idx in col_country_map and col_idx in col_product_map:
                    if isinstance(cell, (int, float)) and cell > 100:
                        country = col_country_map[col_idx]
                        product = col_product_map[col_idx]
                        results.setdefault((country, product), []).append((date_val, float(cell)))

    # Statystyki
    print(f"  [WOB] przeskanowano {total_rows_scanned} wierszy", flush=True)
    for key, vals in list(results.items())[:10]:
        print(f"  [WOB] {key[0]}|{key[1]}: {len(vals)} obs", flush=True)

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
