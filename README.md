# Energy Analytics

Aplikacja do analizy cen commodities energetycznych, metali i rolnych.
Dane historyczne pobierane codziennie z darmowych zrodel: FRED i EIA.

## Status

Etap 1: fetcher danych + GitHub Actions cron.

## Klucze API

Trzymane w GitHub Secrets (Settings → Secrets and variables → Actions):
- `FRED_KEY` — z https://fredaccount.stlouisfed.org/apikey
- `EIA_KEY`  — z https://www.eia.gov/opendata/register.php

## Test lokalny

```
export FRED_KEY=twoj_klucz_fred
export EIA_KEY=twoj_klucz_eia
python3 fetch_data.py
```
