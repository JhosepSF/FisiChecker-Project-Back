#!/usr/bin/env python
"""Benchmark rápido del auditor para una lista de URLs."""
import os
import csv
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from audits.audit import scrape_and_audit
from audits.checks.criteria.base import CheckMode

URLS = [
    "https://interbank.pe/",
    "https://www.mibanco.com.pe/",
    "https://www.compartamos.com.pe/Peru",
    "https://alfinbanco.pe/",
    "https://www.bbva.pe/",
]

out_path = "benchmark_results.csv"

fields = [
    "url",
    "status_code",
    "elapsed_ms",
    "score",
    "pass",
    "partial",
    "fail",
    "na",
]

rows = []

for url in URLS:
    print(f"Audit: {url}")
    result = scrape_and_audit(url, mode=CheckMode.RAW, use_ai=False)
    counts = result.get("verdict_counts", {})
    row = {
        "url": url,
        "status_code": result.get("status_code"),
        "elapsed_ms": result.get("elapsed_ms"),
        "score": result.get("score"),
        "pass": counts.get("pass", 0),
        "partial": counts.get("partial", 0),
        "fail": counts.get("fail", 0),
        "na": counts.get("na", 0),
    }
    rows.append(row)

with open(out_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

print(f"\n✅ CSV generado: {out_path}")
