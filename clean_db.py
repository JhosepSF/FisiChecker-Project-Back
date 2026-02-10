#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from django.db import connection
from audits.models import WebsiteAudit, WebsiteAuditResult

# Eliminar todos los registros
WebsiteAuditResult.objects.all().delete()
WebsiteAudit.objects.all().delete()

# Resetear el auto_increment de las tablas
with connection.cursor() as cursor:
    cursor.execute("ALTER TABLE audits_websiteaudit AUTO_INCREMENT = 1")
    cursor.execute("ALTER TABLE audits_websiteauditresult AUTO_INCREMENT = 1")

print("BD limpia - IDs reseteados a 1")
