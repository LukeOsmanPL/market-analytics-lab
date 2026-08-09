#!/usr/bin/env python3
"""
Sprawdza reguly alertow z data/alerts_config.json wobec aktualnych danych.
Wyniki zapisuje do data/alerts_log.json. Opcjonalnie wysyla email (SMTP).

Zmienne srodowiskowe (email opcjonalne):
  SMTP_HOST (domyslnie smtp.gmail.com)
  SMTP_USER (np. twoj@gmail.com)
  SMTP_PASS (Gmail App Password - z myaccount.google.com/apppasswords)
  ALERT_EMAIL_TO (domyslnie SMTP_USER)
"""
import json, os, sys, statistics, smtplib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.mime.text import MIMEText

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# Wczytaj ceny
prices_file = DATA_DIR / "prices.json"
if not prices_file.exists():
    print("BRAK data/prices.json - nic do sprawdzenia")
    sys.exit(0)
with prices_file.open() as f:
    prices = json.load(f)
products = prices.get("products", {})
if not products:
    print("BRAK produktow w prices.json")
    sys.exit(0)

# Wczytaj konfig alertow
config_file = DATA_DIR / "alerts_config.json"
if not config_file.exists():
    print("BRAK data/alerts_config.json - alerty nieskonfigurowane")
    sys.exit(0)
with config_file.open() as f:
    config = json.load(f)
rules = config.get("rules", [])
if not rules:
    print("BRAK regul w alerts_config.json")
    sys.exit(0)

print(f"Sprawdzam {len(rules)} regul alertow")


def get_series(pid):
    return products.get(pid, [])


def zscore(vals, window):
    if len(vals) < max(window, 3): return None
    w = vals[-window:]
    m = statistics.mean(w)
    try: sd = statistics.stdev(w)
    except statistics.StatisticsError: return None
    if sd == 0: return None
    return (vals[-1] - m) / sd


def check_product_above(rule):
    obs = get_series(rule["product"])
    if not obs: return None
    last = obs[-1]
    if last["value"] > rule["threshold"]:
        return f"{rule['product']} = {last['value']:.2f} > {rule['threshold']} ({last['date']})"
    return None

def check_product_below(rule):
    obs = get_series(rule["product"])
    if not obs: return None
    last = obs[-1]
    if last["value"] < rule["threshold"]:
        return f"{rule['product']} = {last['value']:.2f} < {rule['threshold']} ({last['date']})"
    return None

def check_product_zscore(rule):
    obs = get_series(rule["product"])
    if not obs: return None
    vals = [o["value"] for o in obs]
    window = rule.get("window", 60)
    z = zscore(vals, window)
    if z is None: return None
    if abs(z) >= rule["threshold"]:
        arrow = "🔴 SHORT" if z > 0 else "🟢 LONG"
        return f"{rule['product']} z-score={z:+.2f} {arrow} (|z|>={rule['threshold']}, {obs[-1]['date']})"
    return None

def check_spread_zscore(rule):
    legs = rule.get("legs", [])
    per_leg = []
    for leg in legs:
        obs = get_series(leg["pid"])
        if not obs: return None
        per_leg.append({o["date"]: o["value"] for o in obs})
    if not per_leg: return None
    common = set.intersection(*[set(d.keys()) for d in per_leg])
    if not common: return None
    dates = sorted(common)
    spread_vals = []
    for d in dates:
        try:
            s = sum(leg["side"] * leg.get("qty", 1) * per_leg[i][d] for i, leg in enumerate(legs))
        except (TypeError, KeyError):
            continue
        spread_vals.append(s)
    window = rule.get("window", 252)
    z = zscore(spread_vals, window)
    if z is None: return None
    if abs(z) >= rule["threshold"]:
        formula = " ".join(f"{'+' if l['side']>0 else '−'}{abs(l.get('qty',1))}×{l['pid']}" for l in legs)
        arrow = "🔴 SHORT" if z > 0 else "🟢 LONG"
        return f"Spread [{formula}] z-score={z:+.2f} {arrow} ({dates[-1]})"
    return None

def check_pct_change(rule):
    obs = get_series(rule["product"])
    if not obs or len(obs) < 2: return None
    days = rule.get("days", 30)
    last = obs[-1]
    # znajdz cene sprzed 'days' dni
    target = datetime.fromisoformat(last["date"]) - timedelta(days=days)
    target_str = target.strftime("%Y-%m-%d")
    prior = None
    for o in reversed(obs[:-1]):
        if o["date"] <= target_str:
            prior = o
            break
    if prior is None:
        prior = obs[0]
    if prior["value"] == 0: return None
    change = (last["value"] / prior["value"] - 1) * 100
    threshold = rule["threshold"]
    if abs(change) >= abs(threshold):
        if (threshold > 0 and change > 0) or (threshold < 0 and change < 0) or rule.get("both_directions"):
            return f"{rule['product']} zmiana {days}d = {change:+.2f}% (próg {threshold}%, {last['date']})"
    return None


CHECKERS = {
    "product_above": check_product_above,
    "product_below": check_product_below,
    "product_zscore": check_product_zscore,
    "spread_zscore": check_spread_zscore,
    "pct_change": check_pct_change,
}

triggered_now = []
for i, rule in enumerate(rules):
    ttype = rule.get("type")
    fn = CHECKERS.get(ttype)
    if not fn:
        print(f"  [SKIP] rule {i}: nieznany typ '{ttype}'")
        continue
    try:
        msg = fn(rule)
    except Exception as e:
        print(f"  [BLAD] rule {i}: {type(e).__name__}: {e}")
        continue
    if msg:
        note = rule.get("note", "")
        entry = {
            "rule_index": i,
            "rule_id": rule.get("id", f"rule_{i}"),
            "type": ttype,
            "message": msg,
            "note": note,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        triggered_now.append(entry)
        print(f"  [ALERT] {msg}")

# Wczytaj istniejacy log alertow
alerts_log_file = DATA_DIR / "alerts_log.json"
existing_alerts = []
if alerts_log_file.exists():
    try:
        with alerts_log_file.open() as f:
            existing_alerts = json.load(f).get("alerts", [])
    except Exception:
        pass

# Dedup dla EMAIL: nie wysylaj powtorki jesli ta sama regula strzelala w ostatnich 3 dniach
cutoff_recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
recently_triggered_ids = set()
for a in existing_alerts:
    at = a.get("at", "")
    if at >= cutoff_recent:
        recently_triggered_ids.add(a.get("rule_id"))
truly_new = [t for t in triggered_now if t["rule_id"] not in recently_triggered_ids]

# Zapisz zaktualizowany log (przycinamy do 1000 ostatnich)
combined = (existing_alerts + triggered_now)[-1000:]
with alerts_log_file.open("w") as f:
    json.dump({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "alerts": combined,
    }, f, indent=2, ensure_ascii=False)
print(f"\nZapisano {len(combined)} alertow w logu")
print(f"Wykryto {len(triggered_now)} teraz, w tym {len(truly_new)} NOWYCH (nie ostatnie 3 dni)")

# Email tylko dla NOWYCH alertow
smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
smtp_user = os.environ.get("SMTP_USER", "").strip()
smtp_pass = os.environ.get("SMTP_PASS", "").strip()
alert_to = (os.environ.get("ALERT_EMAIL_TO") or smtp_user).strip()

if not truly_new:
    print("Brak nowych alertow - email nie wysylany")
elif not (smtp_user and smtp_pass and alert_to):
    print("SMTP niekonfigurowane - alerty tylko w logu")
else:
    body_lines = [f"Wykryto {len(truly_new)} nowych alertow w Market Analytics Lab:", ""]
    for t in truly_new:
        body_lines.append(f"• {t['message']}")
        if t.get("note"):
            body_lines.append(f"  → {t['note']}")
        body_lines.append("")
    body_lines.extend([
        "---",
        "https://lukeosmanpl.github.io/market-analytics-lab/",
        "Konfiguracja: data/alerts_config.json w repo",
    ])
    msg = MIMEText("\n".join(body_lines), _charset="utf-8")
    msg["Subject"] = f"[MAL] {len(truly_new)} alerty · {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    msg["From"] = smtp_user
    msg["To"] = alert_to
    try:
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=30) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"Wyslano email do {alert_to}")
    except Exception as e:
        print(f"BLAD email: {type(e).__name__}: {e}")
