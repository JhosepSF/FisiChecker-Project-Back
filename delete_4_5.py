#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from django.db import connection
from audits.models import WebsiteAudit, WebsiteAuditResult

# Obtener los registros con ID 4 y 5
audit_4 = WebsiteAudit.objects.filter(id=4).first()
audit_5 = WebsiteAudit.objects.filter(id=5).first()

if audit_4:
    print(f"Eliminando audit #{audit_4.id} - {audit_4.url}")
    audit_4.delete()

if audit_5:
    print(f"Eliminando audit #{audit_5.id} - {audit_5.url}")
    audit_5.delete()

# Resetear el auto_increment a 4 para que el siguiente sea ID 4
with connection.cursor() as cursor:
    cursor.execute("ALTER TABLE audits_websiteaudit AUTO_INCREMENT = 4")
    cursor.execute("ALTER TABLE audits_websiteauditresult AUTO_INCREMENT = 1")

print("Audits 4 y 5 eliminados - Proximo ID sera 4")
