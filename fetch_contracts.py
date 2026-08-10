#!/usr/bin/env python3
"""
Fetcher konkretnych kontraktow futures - HYBRYDOWY (EIA + Yahoo).

DWA MODELE DANYCH per produkt:
1) ROLLING (EIA API, darmowe, 20+ lat historii, tylko energia US):
   M1 = front month, M2 = 2nd nearest, M3, M4
   WTI, NG (Henry Hub), Heating Oil, RBOB Gasoline
   Zapisywane jako product.rolling = {"M1": [{date,value}...], "M2": [...], ...}

2) CONTRACTS (Yahoo Finance, spotty coverage, 1-2 lata na kontrakt):
   Konkretne wygasniecie (np. Mar 2025 = "202503")
   Wszystkie produkty gdzie yahoo ma dane (metale, zboza, softs, energia)
   Zapisywane jako product.contracts = {"202503": [{date,value}...], ...}

Wyjscie: data/contracts/{PID}.json:
{
  "product": "CL", "name": "WTI Crude Oil", "unit": "$/bbl", ...,
  "rolling": {"M1":[...], "M2":[...], "M3":[...], "M4":[...]},
  "contracts": {"202503":[...], "202506":[...], ...},
  "sources": {"rolling": "EIA", "contracts": "Yahoo"},
  "updated_at": "2026-08-..."
}

ENV: EIA_KEY (wymagane dla rolling)
CLI: python3 fetch_contracts.py [full|incremental]
"""
import os, sys, json, time
import urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent
CONTRACTS_DIR = ROOT / "data" / "contracts"
CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

MONTH_CODES = ["F","G","H","J","K","M","N","Q","U","V","X","Z"]
MONTH_NUM = {c: i+1 for i, c in enumerate(MONTH_CODES)}
MIN_DATE = "2000-01-01"
CURRENT_YEAR = datetime.now(timezone.utc).year

# Zakres lat dla Yahoo per-miesiac
YEAR_START = CURRENT_YEAR - 3    # Yahoo rzadko ma >3 lata na konkretny kontrakt
YEAR_END   = CURRENT_YEAR + 3    # nadchodzace 3 lata

EIA_KEY = os.environ.get("EIA_KEY", "").strip()
if not EIA_KEY:
    print("[WARN] EIA_KEY nie ustawione - rolling contracts (M1-M4) beda pominiete", flush=True)

# ---------------------------------------------------------------------------
# Definicje produktow.
#   eia_series: dict {"M1": "seria_id_M1", "M2": ...} dla rolling contracts
#     Puste = pomijamy rolling
#   yahoo_root: prefix tickera Yahoo dla per-miesiac (np. "CL" -> CLH25.NYM)
#   yahoo_exchange: suffix Yahoo (np. ".NYM", ".CMX", ".CBT")
#     Puste = pomijamy per-miesiac Yahoo
# ---------------------------------------------------------------------------
PRODUCTS_C = [
    # ============ ENERGIA - EIA rolling (dluga historia) + Yahoo per-miesiac ============
    dict(pid="CL", name="WTI Crude Oil (NYMEX)", unit="$/bbl",
         contract_size=1000, contract_unit="bbl", category="Energia", color="#ff8a65",
         eia_series={"M1":"PET.RCLC1.D", "M2":"PET.RCLC2.D", "M3":"PET.RCLC3.D", "M4":"PET.RCLC4.D"},
         yahoo_root="CL", yahoo_exchange=".NYM"),
    dict(pid="NG", name="Henry Hub NG (NYMEX)", unit="$/MMBtu",
         contract_size=10000, contract_unit="MMBtu", category="Energia", color="#4fc3f7",
         eia_series={"M1":"NG.RNGC1.D", "M2":"NG.RNGC2.D", "M3":"NG.RNGC3.D", "M4":"NG.RNGC4.D"},
         yahoo_root="NG", yahoo_exchange=".NYM"),
    dict(pid="HO", name="Heating Oil (NYMEX)", unit="$/gal",
         contract_size=42000, contract_unit="gal", category="Energia", color="#ff5722",
         eia_series={"M1":"PET.EER_EPD2F_PE1_Y35NY_DPG.D",
                     "M2":"PET.EER_EPD2F_PE2_Y35NY_DPG.D",
                     "M3":"PET.EER_EPD2F_PE3_Y35NY_DPG.D",
                     "M4":"PET.EER_EPD2F_PE4_Y35NY_DPG.D"},
         yahoo_root="HO", yahoo_exchange=".NYM"),
    dict(pid="RB", name="RBOB Gasoline (NYMEX)", unit="$/gal",
         contract_size=42000, contract_unit="gal", category="Energia", color="#ffb74d",
         eia_series={"M1":"PET.EER_EPMRU_PE1_Y35NY_DPG.D",
                     "M2":"PET.EER_EPMRU_PE2_Y35NY_DPG.D",
                     "M3":"PET.EER_EPMRU_PE3_Y35NY_DPG.D",
                     "M4":"PET.EER_EPMRU_PE4_Y35NY_DPG.D"},
         yahoo_root="RB", yahoo_exchange=".NYM"),
    dict(pid="BZ", name="Brent Crude (ICE)", unit="$/bbl",
         contract_size=1000, contract_unit="bbl", category="Energia", color="#ba68c8",
         eia_series=None,  # EIA nie ma futures Brent (tylko spot)
         yahoo_root="BZ", yahoo_exchange=".NYM"),

    # ============ METALE (COMEX) - tylko Yahoo per-miesiac ============
    dict(pid="GC", name="Gold (COMEX)", unit="$/oz",
         contract_size=100, contract_unit="oz", category="Metale", color="#ffd54f",
         eia_series=None, yahoo_root="GC", yahoo_exchange=".CMX"),
    dict(pid="SI", name="Silver (COMEX)", unit="$/oz",
         contract_size=5000, contract_unit="oz", category="Metale", color="#b0bec5",
         eia_series=None, yahoo_root="SI", yahoo_exchange=".CMX"),
    dict(pid="HG", name="Copper (COMEX)", unit="$/lb",
         contract_size=25000, contract_unit="lb", category="Metale", color="#d84315",
         eia_series=None, yahoo_root="HG", yahoo_exchange=".CMX"),
    dict(pid="PL_M", name="Platinum (NYMEX)", unit="$/oz",
         contract_size=50, contract_unit="oz", category="Metale", color="#78909c",
         eia_series=None, yahoo_root="PL", yahoo_exchange=".NYM"),
    dict(pid="PA", name="Palladium (NYMEX)", unit="$/oz",
         contract_size=100, contract_unit="oz", category="Metale", color="#8d6e63",
         eia_series=None, yahoo_root="PA", yahoo_exchange=".NYM"),

    # ============ ZBOZA (CBOT) - Yahoo, scale 0.01 (centy -> $) ============
    dict(pid="ZC", name="Corn (CBOT)", unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#fbc02d",
         eia_series=None, yahoo_root="ZC", yahoo_exchange=".CBT", yahoo_scale=0.01),
    dict(pid="ZW", name="Wheat SRW (CBOT)", unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#8d6e63",
         eia_series=None, yahoo_root="ZW", yahoo_exchange=".CBT", yahoo_scale=0.01),
    dict(pid="KE", name="Wheat HRW (KCBT)", unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#795548",
         eia_series=None, yahoo_root="KE", yahoo_exchange=".CBT", yahoo_scale=0.01),
    dict(pid="ZS", name="Soybean (CBOT)", unit="$/bu",
         contract_size=5000, contract_unit="bu", category="Rolne", color="#9ccc65",
         eia_series=None, yahoo_root="ZS", yahoo_exchange=".CBT", yahoo_scale=0.01),
    dict(pid="ZM", name="Soybean Meal (CBOT)", unit="$/short ton",
         contract_size=100, contract_unit="short ton", category="Rolne", color="#7cb342",
         eia_series=None, yahoo_root="ZM", yahoo_exchange=".CBT"),
    dict(pid="ZL", name="Soybean Oil (CBOT)", unit="$/lb",
         contract_size=60000, contract_unit="lb", category="Rolne", color="#c0ca33",
         eia_series=None, yahoo_root="ZL", yahoo_exchange=".CBT", yahoo_scale=0.01),

    # ============ SOFTS (ICE US) - Yahoo, exchange NYB ============
    dict(pid="KC", name="Coffee Arabica (ICE)", unit="$/lb",
         contract_size=37500, contract_unit="lb", category="Rolne", color="#6d4c41",
         eia_series=None, yahoo_root="KC", yahoo_exchange=".NYB", yahoo_scale=0.01),
    dict(pid="CC", name="Cocoa (ICE)", unit="$/mt",
         contract_size=10, contract_unit="mt", category="Rolne", color="#5d4037",
         eia_series=None, yahoo_root="CC", yahoo_exchange=".NYB"),
    dict(pid="SB", name="Sugar #11 (ICE)", unit="$/lb",
         contract_size=112000, contract_unit="lb", category="Rolne", color="#f8bbd0",
         eia_series=None, yahoo_root="SB", yahoo_exchange=".NYB", yahoo_scale=0.01),
    dict(pid="CT", name="Cotton (ICE)", unit="$/lb",
         contract_size=50000, contract_unit="lb", category="Rolne", color="#f5f5dc",
         eia_series=None, yahoo_root="CT", yahoo_exchange=".NYB", yahoo_scale=0.01),

    # ============ ZYWIEC (CME) - Yahoo ============
    dict(pid="LE", name="Live Cattle (CME)", unit="$/lb",
         contract_size=40000, contract_unit="lb", category="Rolne", color="#8d6e63",
         eia_series=None, yahoo_root="LE", yahoo_exchange=".CME", yahoo_scale=0.01),
    dict(pid="HE", name="Lean Hogs (CME)", unit="$/lb",
         contract_size=40000, contract_unit="lb", category="Rolne", color="#e91e63",
         eia_series=None, yahoo_root="HE", yahoo_exchange=".CME", yahoo_scale=0.01),
]


# ============================================================================
# EIA API - rolling contracts (M1-M4) z dluga historia
# ============================================================================
def fetch_eia_series(series_id: str) -> list:
    """Pobiera jedna serie z EIA v2 API. Zwraca [{date,value}...]."""
    if not EIA_KEY: return []
    # EIA v2 endpoint - petroleum lub natural-gas
    dataset = "natural-gas/pri/fut" if series_id.startswith("NG.") else "petroleum/pri/fut"
    # Uwaga: series_id musi byc bez prefiksu "PET." lub "NG." dla v2 API
    clean_series = series_id.split(".", 1)[1] if "." in series_id else series_id
    params = urllib.parse.urlencode([
        ("api_key", EIA_KEY),
        ("frequency", "daily"),
        ("data[0]", "value"),
        ("facets[series][]", clean_series),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
        ("offset", "0"),
        ("length", "5000"),
    ])
    url = f"https://api.eia.gov/v2/{dataset}/data/?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "market-analytics-lab/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"    [EIA {series_id}] HTTP {e.code}: {e.reason}", flush=True)
        return []
    except Exception as e:
        print(f"    [EIA {series_id}] EXC: {e}", flush=True)
        return []
    rows = data.get("response", {}).get("data", []) or []
    obs = []
    for r in rows:
        d = (r.get("period") or "")[:10]
        v = r.get("value")
        if not d or v is None: continue
        try: v = float(v)
        except (TypeError, ValueError): continue
        if v <= 0 or d < MIN_DATE: continue
        obs.append({"date": d, "value": round(v, 4)})
    obs.sort(key=lambda o: o["date"])
    # dedup po dacie
    seen = {o["date"]: o["value"] for o in obs}
    return [{"date": d, "value": v} for d, v in sorted(seen.items())]


def fetch_eia_rolling(product_meta: dict) -> dict:
    """Pobiera M1-M4 dla produktu. Zwraca {"M1":[...], "M2":[...], "M3":[...], "M4":[...]}."""
    if not product_meta.get("eia_series"): return {}
    out = {}
    for key, sid in product_meta["eia_series"].items():
        obs = fetch_eia_series(sid)
        if obs:
            out[key] = obs
            print(f"    [EIA] {product_meta['pid']}.{key} ({sid}): {len(obs)} obs, "
                  f"{obs[0]['date']}..{obs[-1]['date']}", flush=True)
        else:
            print(f"    [EIA] {product_meta['pid']}.{key} ({sid}): PUSTO", flush=True)
    return out


# ============================================================================
# YAHOO FINANCE - konkretne miesiace via yfinance
# ============================================================================
_YF_IMPORTED = False

def _import_yfinance():
    global _YF_IMPORTED
    if _YF_IMPORTED: return True
    try:
        import yfinance  # noqa
        _YF_IMPORTED = True
        return True
    except ImportError:
        print("[FATAL] yfinance nie zainstalowany - dodaj do requirements.txt", flush=True)
        return False


def yahoo_ticker(root: str, month_code: str, year: int, exchange: str) -> str:
    """CLH25.NYM = WTI March 2025."""
    yy = f"{year % 100:02d}"
    return f"{root.upper()}{month_code}{yy}{exchange}"


def fetch_yahoo_contract(ticker: str, unit_scale: float = 1.0) -> list:
    """Pobiera 1 kontrakt via yfinance. Zwraca [] jesli brak."""
    if not _import_yfinance(): return []
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="max", auto_adjust=False, actions=False)
    except Exception as e:
        return []
    if df is None or df.empty: return []
    obs = []
    for ts, row in df.iterrows():
        close = row.get("Close")
        if close is None: continue
        try: v = float(close) * unit_scale
        except (TypeError, ValueError): continue
        if v <= 0: continue
        d = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        if d < MIN_DATE: continue
        obs.append({"date": d, "value": round(v, 4)})
    obs.sort(key=lambda o: o["date"])
    seen = {o["date"]: o["value"] for o in obs}
    return [{"date": d, "value": v} for d, v in sorted(seen.items())]


def fetch_yahoo_all_contracts(product_meta: dict, mode: str) -> dict:
    """Iteruje po latach x miesiacach, prubuje sciagac. Zwraca {"YYYYMM":[...],...}"""
    if not product_meta.get("yahoo_root") or not product_meta.get("yahoo_exchange"):
        return {}
    root = product_meta["yahoo_root"]
    exch = product_meta["yahoo_exchange"]
    scale = product_meta.get("yahoo_scale", 1.0)
    out = {}
    ok_count = 0
    fail_count = 0
    for year in range(YEAR_START, YEAR_END + 1):
        for mc in MONTH_CODES:
            ticker = yahoo_ticker(root, mc, year, exch)
            obs = fetch_yahoo_contract(ticker, scale)
            if obs:
                key = f"{year:04d}{MONTH_NUM[mc]:02d}"
                out[key] = obs
                ok_count += 1
                if ok_count <= 3 or ok_count % 10 == 0:
                    print(f"    [YF] {ticker}: {len(obs)} obs, "
                          f"{obs[0]['date']}..{obs[-1]['date']}", flush=True)
            else:
                fail_count += 1
    print(f"    [YF] {product_meta['pid']}: ok={ok_count}, fail={fail_count} (probowano {ok_count+fail_count})", flush=True)
    return out


# ============================================================================
# STORAGE
# ============================================================================
def merge_history(existing, fresh):
    if not existing and not fresh: return []
    combined = {o["date"]: o["value"] for o in (existing or [])}
    for o in (fresh or []):
        combined[o["date"]] = o["value"]
    return [{"date": d, "value": v} for d, v in sorted(combined.items())]


def merge_dict(existing_dict, fresh_dict):
    """Laczy dwa slowniki serii - kazdy klucz merge'owany osobno."""
    out = dict(existing_dict or {})
    for k, v in (fresh_dict or {}).items():
        out[k] = merge_history(out.get(k, []), v)
    return out


def load_existing(pid: str) -> dict:
    fp = CONTRACTS_DIR / f"{pid}.json"
    if not fp.exists(): return {}
    try:
        with fp.open() as f: return json.load(f)
    except Exception:
        return {}


def save_product(pid: str, meta: dict, rolling: dict, contracts: dict):
    fp = CONTRACTS_DIR / f"{pid}.json"
    out = {
        "product": pid,
        "name": meta["name"],
        "unit": meta["unit"],
        "contract_size": meta["contract_size"],
        "contract_unit": meta["contract_unit"],
        "category": meta["category"],
        "color": meta["color"],
        "rolling": rolling or {},
        "contracts": contracts or {},
        "sources": {
            "rolling": "EIA" if rolling else None,
            "contracts": "Yahoo" if contracts else None,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with fp.open("w") as f:
        json.dump(out, f, ensure_ascii=False)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "incremental"
    print(f"[fetch_contracts v2 HYBRID] mode={mode}, produktow={len(PRODUCTS_C)}, "
          f"years={YEAR_START}..{YEAR_END}", flush=True)
    print(f"[fetch_contracts] EIA_KEY: {'SET' if EIA_KEY else 'MISSING'}", flush=True)

    _import_yfinance()

    total_rolling = 0
    total_contracts = 0
    for p in PRODUCTS_C:
        pid = p["pid"]
        print(f"\n=== [{pid}] {p['name']} ===", flush=True)
        existing = load_existing(pid)
        old_rolling = existing.get("rolling", {})
        old_contracts = existing.get("contracts", {})

        # 1) EIA rolling M1-M4 (jesli produkt ma seria EIA)
        new_rolling = {}
        if p.get("eia_series") and EIA_KEY:
            print(f"  --- EIA rolling ---", flush=True)
            new_rolling = fetch_eia_rolling(p)
        merged_rolling = merge_dict(old_rolling, new_rolling)
        total_rolling += sum(len(v) for v in new_rolling.values())

        # 2) Yahoo konkretne miesiace
        new_contracts = {}
        if p.get("yahoo_root") and p.get("yahoo_exchange"):
            print(f"  --- Yahoo per-miesiac ({YEAR_START}..{YEAR_END}) ---", flush=True)
            new_contracts = fetch_yahoo_all_contracts(p, mode)
        merged_contracts = merge_dict(old_contracts, new_contracts)
        total_contracts += sum(len(v) for v in new_contracts.values())

        # Zapisz nawet jesli sam 1 z 2 zrodel zadzialal
        if merged_rolling or merged_contracts:
            save_product(pid, p, merged_rolling, merged_contracts)
            print(f"  [SAVED] {pid}: rolling={len(merged_rolling)} serii, "
                  f"contracts={len(merged_contracts)} kontraktow", flush=True)
        else:
            print(f"  [SKIP] {pid}: brak danych z zadnego zrodla", flush=True)

    # Manifest
    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "products": [
            {"pid": p["pid"], "name": p["name"], "unit": p["unit"],
             "contract_size": p["contract_size"], "contract_unit": p["contract_unit"],
             "category": p["category"], "color": p["color"],
             "has_rolling": bool(p.get("eia_series")),
             "has_contracts": bool(p.get("yahoo_root")),
             }
            for p in PRODUCTS_C
        ],
    }
    with (CONTRACTS_DIR / "_manifest.json").open("w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n[KONIEC] rolling_pkt={total_rolling}, contracts_pkt={total_contracts}", flush=True)


if __name__ == "__main__":
    main()
