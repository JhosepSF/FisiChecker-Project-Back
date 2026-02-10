#!/usr/bin/env python
"""Ejecuta auditoria AUTO + IA y guarda resultados clave."""
import os
import json
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FisiChecker.settings")
django.setup()

from audits.audit import scrape_and_audit
from audits.checks.criteria.base import CheckMode

url = "https://www.compartamos.com.pe/Peru"

result = scrape_and_audit(url, mode=CheckMode.AUTO, use_ai=True)

out = {
    "url": url,
    "score": result.get("score"),
    "verdict_counts": result.get("verdict_counts"),
    "ai_codes": result.get("ai_codes"),
}

with open("audit_auto_ai_result.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(json.dumps(out, ensure_ascii=False, indent=2))
