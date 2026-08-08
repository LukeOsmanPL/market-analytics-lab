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
    # Klucze uzywaja kodow ISO alpha-2 wg struktury pliku WOB (PL_, DE_, EU_, ...)
    dict(id="PL_PB95_WOB", source="wob", series="PL|Euro-Super 95",
         name="Pb95 detal PL (EU WOB)",   unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#4db6ac"),
    dict(id="PL_ON_WOB",   source="wob", series="PL|Automotive Gas Oil",
         name="ON detal PL (EU WOB)",     unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#26a69a"),
    dict(id="PL_LPG_WOB",  source="wob", series="PL|LPG",
         name="LPG detal PL (EU WOB)",    unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#80cbc4"),
    dict(id="PL_HEAT_WOB", source="wob", series="PL|Heating Gas Oil",
         name="Olej opałowy PL (EU WOB)", unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#00897b"),
    # Odniesienie EU-27 i Eurozone
    dict(id="EU_PB95_WOB", source="wob", series="EU|Euro-Super 95",
         name="Pb95 detal UE-27 (WOB)",   unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Europa", color="#9575cd"),
    dict(id="EU_ON_WOB",   source="wob", series="EU|Automotive Gas Oil",
         name="ON detal UE-27 (WOB)",     unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Europa", color="#7e57c2"),
    dict(id="DE_PB95_WOB", source="wob", series="DE|Euro-Super 95",
         name="Pb95 detal Niemcy (WOB)",  unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Europa", color="#b39ddb"),
    dict(id="DE_ON_WOB",   source="wob", series="DE|Automotive Gas Oil",
         name="ON detal Niemcy (WOB)",    unit="€/1000L",
         contract_size=1, contract_unit="L",
         category="Europa", color="#9575cd"),

    # Polska: hurt Orlen (append-only, scraping z cenypaliw.fyi - historia narasta od dzis)
    dict(id="PL_ORLEN_PB95", source="orlen_scrape", series="PB95",
         name="Orlen Pb95 hurt",          unit="zł/L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#ff8f00"),
    dict(id="PL_ORLEN_PB98", source="orlen_scrape", series="PB98",
         name="Orlen Pb98 hurt",          unit="zł/L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#ff6f00"),
    dict(id="PL_ORLEN_ON",   source="orlen_scrape", series="ON",
         name="Orlen ON hurt",            unit="zł/L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#ef6c00"),
    dict(id="PL_ORLEN_EKOTERM", source="orlen_scrape", series="ON_EKOTERM",
         name="Orlen ON Ekoterm hurt",    unit="zł/L",
         contract_size=1, contract_unit="L",
         category="Lokalne PL", color="#e65100"),

    # Dodatkowe kraje EU (WOB) - do porownan miedzynarodowych
    dict(id="FR_PB95_WOB", source="wob", series="FR|Euro-Super 95",
         name="Pb95 detal Francja (WOB)", unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#5c6bc0"),
    dict(id="FR_ON_WOB",   source="wob", series="FR|Automotive Gas Oil",
         name="ON detal Francja (WOB)",   unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#3f51b5"),
    dict(id="ES_PB95_WOB", source="wob", series="ES|Euro-Super 95",
         name="Pb95 detal Hiszpania (WOB)", unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#ec407a"),
    dict(id="ES_ON_WOB",   source="wob", series="ES|Automotive Gas Oil",
         name="ON detal Hiszpania (WOB)", unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#d81b60"),
    dict(id="IT_PB95_WOB", source="wob", series="IT|Euro-Super 95",
         name="Pb95 detal Włochy (WOB)",  unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#66bb6a"),
    dict(id="IT_ON_WOB",   source="wob", series="IT|Automotive Gas Oil",
         name="ON detal Włochy (WOB)",    unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#43a047"),
    dict(id="CZ_PB95_WOB", source="wob", series="CZ|Euro-Super 95",
         name="Pb95 detal Czechy (WOB)",  unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#26a69a"),
    dict(id="CZ_ON_WOB",   source="wob", series="CZ|Automotive Gas Oil",
         name="ON detal Czechy (WOB)",    unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#00897b"),
    dict(id="HU_PB95_WOB", source="wob", series="HU|Euro-Super 95",
         name="Pb95 detal Węgry (WOB)",   unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#ff7043"),
    dict(id="HU_ON_WOB",   source="wob", series="HU|Automotive Gas Oil",
         name="ON detal Węgry (WOB)",     unit="€/1000L",
         contract_size=1, contract_unit="L", category="Europa", color="#f4511e"),

    # Kursy walutowe (do konwersji miedzy jednostkami w rożnych walutach)
    dict(id="FX_EURUSD", source="yahoo", series="EURUSD=X",
         name="EUR/USD (kurs)", unit="USD/EUR",
         contract_size=1, contract_unit="EUR", category="Waluty", color="#42a5f5"),
    dict(id="FX_EURPLN", source="yahoo", series="EURPLN=X",
         name="EUR/PLN (kurs)", unit="PLN/EUR",
         contract_size=1, contract_unit="EUR", category="Waluty", color="#7e57c2"),
    dict(id="FX_USDPLN", source="yahoo", series="PLN=X",
         name="USD/PLN (kurs)", unit="PLN/USD",
         contract_size=1, contract_unit="USD", category="Waluty", color="#26a69a"),
    dict(id="FX_GBPUSD", source="yahoo", series="GBPUSD=X",
         name="GBP/USD (kurs)", unit="USD/GBP",
         contract_size=1, contract_unit="GBP", category="Waluty", color="#5c6bc0"),
    dict(id="FX_USDJPY", source="yahoo", series="JPY=X",
         name="USD/JPY (kurs)", unit="JPY/USD",
         contract_size=1, contract_unit="USD", category="Waluty", color="#ec407a"),
    dict(id="FX_USDCHF", source="yahoo", series="CHF=X",
         name="USD/CHF (kurs)", unit="CHF/USD",
         contract_size=1, contract_unit="USD", category="Waluty", color="#ef5350"),

    # Elektryka hurt (day-ahead) - dzienne, Ember Energy (CSV, bez rejestracji)
    dict(id="PL_POWER", source="ember", series="Poland",
         name="Elektryka hurt Polska",      unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#ffca28"),
    dict(id="DE_POWER", source="ember", series="Germany",
         name="Elektryka hurt Niemcy",      unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#ff9800"),
    dict(id="FR_POWER", source="ember", series="France",
         name="Elektryka hurt Francja",     unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#5c6bc0"),
    dict(id="ES_POWER", source="ember", series="Spain",
         name="Elektryka hurt Hiszpania",   unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#ec407a"),
    dict(id="IT_POWER", source="ember", series="Italy",
         name="Elektryka hurt Włochy",      unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#66bb6a"),
    dict(id="CZ_POWER", source="ember", series="Czech Republic",
         name="Elektryka hurt Czechy",      unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#26a69a"),
    dict(id="SK_POWER", source="ember", series="Slovakia",
         name="Elektryka hurt Słowacja",    unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#42a5f5"),
    dict(id="HU_POWER", source="ember", series="Hungary",
         name="Elektryka hurt Węgry",       unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#ff7043"),
    dict(id="NL_POWER", source="ember", series="Netherlands",
         name="Elektryka hurt Holandia",    unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#ffb74d"),
    dict(id="GB_POWER", source="ember", series="United Kingdom",
         name="Elektryka hurt UK",          unit="€/MWh",
         contract_size=1, contract_unit="MWh", category="Elektryka", color="#7e57c2"),

    # CFTC COT - pozycja NETTO Money Managers (Long - Short) per market, tygodniowo
    # Klasyczny wskaźnik kontrariański - ekstremum netto sygnalizuje odwrócenie
    dict(id="COT_WTI_NET",    source="cftc", series="CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
         name="COT WTI - Money Mgr netto",  unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#ff8a65"),
    dict(id="COT_BRENT_NET",  source="cftc", series="BRENT CRUDE OIL LAST DAY - NEW YORK MERCANTILE EXCHANGE",
         name="COT Brent - Money Mgr netto",unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#ba68c8"),
    dict(id="COT_NG_NET",     source="cftc", series="NATURAL GAS - NEW YORK MERCANTILE EXCHANGE",
         name="COT NG - Money Mgr netto",   unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#4fc3f7"),
    dict(id="COT_GOLD_NET",   source="cftc", series="GOLD - COMMODITY EXCHANGE INC.",
         name="COT Gold - Money Mgr netto", unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#ffd54f"),
    dict(id="COT_SILVER_NET", source="cftc", series="SILVER - COMMODITY EXCHANGE INC.",
         name="COT Silver - Money Mgr netto", unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#b0bec5"),
    dict(id="COT_COPPER_NET", source="cftc", series="COPPER-GRADE #1 - COMMODITY EXCHANGE INC.",
         name="COT Copper - Money Mgr netto", unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#d84315"),
    dict(id="COT_CORN_NET",   source="cftc", series="CORN - CHICAGO BOARD OF TRADE",
         name="COT Corn - Money Mgr netto", unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#fbc02d"),
    dict(id="COT_WHEAT_NET",  source="cftc", series="WHEAT-SRW - CHICAGO BOARD OF TRADE",
         name="COT Wheat - Money Mgr netto",unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#8d6e63"),
    dict(id="COT_SOYBEAN_NET",source="cftc", series="SOYBEANS - CHICAGO BOARD OF TRADE",
         name="COT Soybean - Money Mgr netto", unit="kontrakty", contract_size=1, contract_unit="kontrakty",
         category="COT", color="#7cb342"),

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

    print(f"  [WOB] wymiary: {ws.max_row} wierszy x {ws.max_column} kolumn", flush=True)

    # Struktura WOB:
    #   R2 = nazwa produktu po francusku (np. 'Euro-super 95', 'Gas oil automob')
    #   R4+ = dane: kol 1 = data, kol 2 = 'EU_' marker, kol 3-8 = 6 produktow EU,
    #             kol 9 = 'EUR_' marker, kol 10-15 = 6 produktow EUR, itd.
    #   Kazdy kraj: 1 kolumna markera + 6 kolumn produktow.

    # Kanonizacja nazw produktow (po francusku w R2 -> nazwy angielskie)
    def normalize_product(s):
        if not s: return None
        s = str(s).strip().lower()
        if 'euro-super 95' in s or 'euro super 95' in s: return 'Euro-Super 95'
        if 'gas oil automob' in s or 'diesel' in s:      return 'Automotive Gas Oil'
        if 'gas oil de cha' in s or 'heating' in s:      return 'Heating Gas Oil'
        if 'gpl' in s or 'lpg' in s:                     return 'LPG'
        if 'fuel oil -schw' in s.replace(' ', ''):       return 'Residual Fuel Oil (low S)'
        if 'fuel oil - sch' in s or 'fuel oil -sch' in s: return 'Residual Fuel Oil (high S)'
        return None

    # Mapa kolumn produktow z R2
    product_by_col = {}
    for c in range(2, ws.max_column + 1):
        v = cell(2, c)
        prod = normalize_product(v)
        if prod:
            product_by_col[c] = prod

    print(f"  [WOB] kolumn z produktami: {len(product_by_col)}", flush=True)

    # Znajdz pierwszy wiersz z danymi (data + kod kraju typu 'EU_', 'PL_', 'DE_')
    first_data_row = None
    for r in range(3, 10):
        v1 = cell(r, 1)
        if hasattr(v1, 'strftime'):
            first_data_row = r
            break
        if isinstance(v1, str):
            try:
                _dt.strptime(v1[:10], '%Y-%m-%d')
                first_data_row = r
                break
            except: pass
    if first_data_row is None:
        first_data_row = 4
    print(f"  [WOB] pierwsze dane w wierszu {first_data_row}", flush=True)

    # Wykryj kolumny markerow krajow z pierwszego wiersza danych (wartosci konczace sie na '_')
    country_by_col = {}  # col -> country_code (bez '_')
    for c in range(1, ws.max_column + 1):
        v = cell(first_data_row, c)
        if isinstance(v, str) and v.endswith('_') and 1 <= len(v) <= 5:
            country_by_col[c] = v.rstrip('_')

    print(f"  [WOB] wykryte kolumny markerow krajow: {len(country_by_col)}", flush=True)
    print(f"  [WOB] kody krajow: {sorted(set(country_by_col.values()))}", flush=True)

    # Dla kazdej kolumny produktu znajdz najblizszy poprzedzajacy marker kraju
    sorted_country_cols = sorted(country_by_col.keys())
    col_to_cp = {}  # col -> (country_code, product_name)
    for prod_col, product_name in product_by_col.items():
        # znajdz country marker column najblizszy z lewej (<= prod_col)
        cc_code = None
        for cc in sorted_country_cols:
            if cc <= prod_col:
                cc_code = country_by_col[cc]
            else:
                break
        if cc_code:
            col_to_cp[prod_col] = (cc_code, product_name)

    print(f"  [WOB] zmapowanych par kraj+produkt: {len(col_to_cp)}", flush=True)
    seen_countries = set(cp[0] for cp in col_to_cp.values())
    print(f"  [WOB] kraje w mapie: {sorted(seen_countries)}", flush=True)

    # Skanuj wiersze danych
    results = {}
    n_scanned = 0
    n_valid = 0
    for r in range(first_data_row, ws.max_row + 1):
        n_scanned += 1
        date_val = cell(r, 1)
        date_str = None
        if hasattr(date_val, 'strftime'):
            date_str = date_val.strftime('%Y-%m-%d')
        elif isinstance(date_val, str):
            try:
                date_str = _dt.strptime(date_val[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
            except: pass
        if not date_str:
            continue
        for col, (country, product) in col_to_cp.items():
            val = cell(r, col)
            if isinstance(val, (int, float)) and 0 < val < 100000:
                results.setdefault((country, product), []).append((date_str, float(val)))
                n_valid += 1

    print(f"  [WOB] przeskanowano {n_scanned} wierszy danych, {n_valid} valid values", flush=True)
    # Pokaz kilka przykladow zeby zwalidowac
    for k in [('PL', 'Euro-Super 95'), ('PL', 'Automotive Gas Oil'), ('PL', 'LPG'), ('EU', 'Euro-Super 95'), ('DE', 'Euro-Super 95')]:
        vals = results.get(k, [])
        if vals:
            print(f"  [WOB] check {k[0]}|{k[1]}: {len(vals)} obs, ostatnia {vals[-1]}", flush=True)
        else:
            print(f"  [WOB] check {k[0]}|{k[1]}: BRAK", flush=True)

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


_CFTC_CACHE = None

def _fetch_cftc_all():
    """Pobiera dane CFTC COT dla wszystkich zdefiniowanych rynkow COT_* w jednym API call.
    Zwraca slownik {market_name: [{date, value=long-short}]}.
    Wskaznik: Managed Money Net = long_all - short_all (klasyczny miernik kontrariański).
    """
    global _CFTC_CACHE
    if _CFTC_CACHE is not None:
        return _CFTC_CACHE

    import urllib.parse
    markets = [p["series"] for p in PRODUCTS if p["source"] == "cftc"]
    if not markets:
        _CFTC_CACHE = {}
        return _CFTC_CACHE

    # Zbuduj klauzule WHERE z listy rynkow (escapuj apostrofy w SoQL)
    market_list = ",".join("'" + m.replace("'", "''") + "'" for m in markets)
    where = f"market_and_exchange_names in ({market_list})"
    params = urllib.parse.urlencode({
        "$select": "market_and_exchange_names,report_date_as_yyyy_mm_dd,m_money_positions_long_all,m_money_positions_short_all",
        "$where": where,
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": "50000",
    })
    url = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json?" + params

    print(f"  [CFTC] pobieram COT dla {len(markets)} rynkow ...", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "energy-analytics/1.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            rows = json.load(r)
        print(f"  [CFTC] pobrano {len(rows)} wierszy", flush=True)
    except Exception as e:
        print(f"  [CFTC] BLAD: {e}", flush=True)
        _CFTC_CACHE = {}
        return _CFTC_CACHE

    result = {}
    counts_per_market = {}
    for row in rows:
        market = row.get("market_and_exchange_names", "").strip()
        raw_date = row.get("report_date_as_yyyy_mm_dd", "") or ""
        date_str = raw_date[:10] if raw_date else ""
        try:
            long_p = float(row.get("m_money_positions_long_all") or 0)
            short_p = float(row.get("m_money_positions_short_all") or 0)
        except (ValueError, TypeError):
            continue
        if not market or not date_str:
            continue
        net = long_p - short_p
        result.setdefault(market, []).append({"date": date_str, "value": net})
        counts_per_market[market] = counts_per_market.get(market, 0) + 1

    # Sortuj i deduplikuj per market
    for market in list(result.keys()):
        seen = {}
        for o in result[market]:
            seen[o["date"]] = o["value"]
        result[market] = [{"date": d, "value": v} for d, v in sorted(seen.items())]

    for m, c in counts_per_market.items():
        print(f"  [CFTC] {m[:50]}...: {c} wierszy", flush=True)

    _CFTC_CACHE = result
    return _CFTC_CACHE


def fetch_cftc(market_name: str) -> list:
    """Zwraca liste {date, value} dla podanego rynku."""
    return _fetch_cftc_all().get(market_name, [])


_EMBER_CACHE = None
EMBER_URL = "https://files.ember-energy.org/public-downloads/price/outputs/european_wholesale_electricity_price_data_daily.csv"

def _parse_ember():
    """Parsuje CSV z Ember Energy (day-ahead ceny hurtowe elektryki w Europie).
    Zwraca slownik: {country_name: [{date, value}, ...]}."""
    global _EMBER_CACHE
    if _EMBER_CACHE is not None:
        return _EMBER_CACHE
    print(f"  [EMBER] pobieram CSV z Ember Energy ...", flush=True)
    try:
        req = urllib.request.Request(EMBER_URL, headers={"User-Agent": "Mozilla/5.0 (energy-analytics)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode('utf-8', errors='replace')
        print(f"  [EMBER] pobrano {len(raw)/1024:.1f} KB", flush=True)
    except Exception as e:
        print(f"  [EMBER] BLAD: {e}", flush=True)
        _EMBER_CACHE = {}
        return _EMBER_CACHE

    lines = raw.strip().split('\n')
    if len(lines) < 2:
        _EMBER_CACHE = {}
        return _EMBER_CACHE

    # Auto-detekcja kolumn z naglowka
    header = [h.strip().strip('"') for h in lines[0].split(',')]
    print(f"  [EMBER] header: {header}", flush=True)
    col_country = col_date = col_price = None
    for i, h in enumerate(header):
        hl = h.lower()
        if col_country is None and ('country' in hl and 'iso' not in hl and 'code' not in hl):
            col_country = i
        if col_date is None and 'date' in hl:
            col_date = i
        if col_price is None and ('price' in hl or 'eur' in hl):
            col_price = i

    if col_country is None or col_date is None or col_price is None:
        print(f"  [EMBER] BLAD: nie znaleziono kolumn (country={col_country}, date={col_date}, price={col_price})", flush=True)
        _EMBER_CACHE = {}
        return _EMBER_CACHE

    print(f"  [EMBER] kolumny: country={col_country}, date={col_date}, price={col_price}", flush=True)

    results = {}
    n_ok = 0
    for line in lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(',')]
        if len(parts) <= max(col_country, col_date, col_price):
            continue
        country = parts[col_country]
        date_s = parts[col_date][:10]
        try:
            price = float(parts[col_price])
        except ValueError:
            continue
        # Waliduj date
        try:
            datetime.strptime(date_s, '%Y-%m-%d')
        except ValueError:
            continue
        results.setdefault(country, []).append({'date': date_s, 'value': price})
        n_ok += 1

    # Sortuj per country
    for country in results:
        results[country].sort(key=lambda o: o['date'])

    print(f"  [EMBER] wczytano {n_ok} obserwacji, {len(results)} krajow", flush=True)
    for c in ['Poland', 'Germany', 'France']:
        v = results.get(c, [])
        if v:
            print(f"  [EMBER] {c}: {len(v)} obs, ostatnia {v[-1]}", flush=True)
        else:
            print(f"  [EMBER] {c}: BRAK", flush=True)

    _EMBER_CACHE = results
    return results


def fetch_ember(country: str) -> list:
    """Zwraca liste {date, value} dla podanego kraju."""
    return _parse_ember().get(country, [])


_ORLEN_CACHE = None

def _scrape_orlen_current():
    """Scrapuje aktualne hurtowe ceny Orlen z cenypaliw.fyi. Zwraca dict {klucz: cena_pln_per_L}."""
    global _ORLEN_CACHE
    if _ORLEN_CACHE is not None:
        return _ORLEN_CACHE
    import re
    url = "https://cenypaliw.fyi/"
    print(f"  [ORLEN] scraping {url} ...", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (energy-analytics)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode('utf-8', errors='replace')
        print(f"  [ORLEN] pobrano {len(html)/1024:.1f} KB HTML", flush=True)
    except Exception as e:
        print(f"  [ORLEN] BLAD pobierania: {e}", flush=True)
        _ORLEN_CACHE = {}
        return _ORLEN_CACHE

    # Najpierw wyodrebnij sekcje z tabela hurtowych cen (zeby nie chwytac retail)
    # Format tabeli: "PB 95: 5.33 PLN/litr" (netto) - hurt Orlen
    result = {}
    # Znajdz obszar tabeli hurtowych
    section_m = re.search(
        r'(?:Tabela\s+hurtowych\s+cen\s+paliw|hurtowe\s+ceny\s+paliw)(.{0,5000})',
        html, re.DOTALL | re.IGNORECASE
    )
    section = section_m.group(1) if section_m else html
    print(f"  [ORLEN] szukam w sekcji {len(section)} znakow (znaleziona sekcja hurt: {bool(section_m)})", flush=True)

    # Patterny: kazdy produkt szuka nazwy + separatora + ceny + jednostki
    # Sekcja hurt uzywa formatu "PB 95: 5.33 PLN/litr netto"
    patterns = {
        'PB95': [
            r'PB\s*95[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*PLN',
            r'PB\s*95[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*z[łl]',
        ],
        'PB98': [
            r'PB\s*98[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*PLN',
            r'PB\s*98[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*z[łl]',
        ],
        'ON': [
            # ON ale nie ON Ekoterm - negative lookahead
            r'(?<![a-zA-Z])ON(?!\s*Ekoterm)\s*(?:\(Diesel\))?[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*PLN',
            r'(?<![a-zA-Z])ON(?!\s*Ekoterm)\s*(?:\(Diesel\))?[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*z[łl]',
        ],
        'ON_EKOTERM': [
            r'ON\s*Ekoterm[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*PLN',
            r'Ekoterm[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*PLN',
            r'ON\s*Ekoterm[^0-9]{1,30}?(\d[\d,\.]{1,6})\s*z[łl]',
        ],
    }
    for key, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, section, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(',', '.'))
                    # Hurt Orlen sensowny zakres: 3-9 zl/l (retail wychodzi wyzej)
                    if 3.0 < v < 9.0:
                        result[key] = v
                        break
                except: pass
    print(f"  [ORLEN] znalezione ceny: {result}", flush=True)
    _ORLEN_CACHE = result
    return result


def fetch_orlen_append(product_key: str, existing_obs: list) -> list:
    """Dopisuje/nadpisuje dzisiejsza cene do istniejacej historii Orlen.
    Nadpisuje jesli data juz jest (na wypadek gdyby wczesniejszy run zapisal zla wartosc).
    """
    from datetime import datetime as _dt2, timezone as _tz2
    today = _dt2.now(_tz2.utc).strftime('%Y-%m-%d')
    prices = _scrape_orlen_current()
    today_val = prices.get(product_key)
    obs = [o for o in (existing_obs or []) if o.get('date') != today]  # usun dzisiejsza jesli byla
    if today_val is not None:
        obs.append({'date': today, 'value': today_val})
        obs.sort(key=lambda o: o['date'])
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


def _load_existing_prices():
    """Zwraca istniejacy prices.json (jesli jest) jako slownik products {pid: [obs]}."""
    fp = DATA_DIR / "prices.json"
    if not fp.exists():
        return {}
    try:
        with fp.open() as f:
            data = json.load(f)
        return data.get('products', {})
    except Exception as e:
        print(f"[WARN] Nie moge odczytac istniejacego prices.json: {e}", flush=True)
        return {}


def main():
    print(f"Start: {datetime.now(timezone.utc).isoformat()}")
    print(f"Zakres historii: od {START_DATE}")

    existing = _load_existing_prices()
    print(f"Wczytano istniejaca historie: {len(existing)} produktow", flush=True)

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
            elif p["source"] == "orlen_scrape":
                # Append-only: rozszerz istniejaca historie o dzisiejsza cene
                obs = fetch_orlen_append(p["series"], existing.get(pid, []))
            elif p["source"] == "ember":
                obs = fetch_ember(p["series"])
            elif p["source"] == "cftc":
                obs = fetch_cftc(p["series"])
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
