# audits/models.py
from __future__ import annotations
from django.db import models
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

class WebsiteAudit(models.Model):
    id: int  # Pylance type hint
    url = models.URLField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    elapsed_ms = models.IntegerField(null=True, blank=True)
    page_title = models.CharField(max_length=512, null=True, blank=True)
    score = models.FloatField(null=True, blank=True)

    # Conservamos el JSON completo por compatibilidad / dif fácil
    results = models.JSONField(default=dict, blank=True)
    raw = models.BooleanField(default=False)
    rendered = models.BooleanField(default=False)
    ia = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["url", "-fetched_at"]),
            models.Index(fields=["url", "rendered", "-fetched_at"]),
        ]
        ordering = ["-fetched_at"]

    def __str__(self):
        return f"{self.url} [{self.fetched_at:%Y-%m-%d %H:%M}]"


class WebsiteAuditResult(models.Model):
    VERDICT_CHOICES = [
        ("pass", "Pass"),
        ("fail", "Fail"),
        ("partial", "Partial"),
        ("na", "Not Applicable"),
    ]
    SOURCE_CHOICES = [
        ("raw", "Raw"),
        ("rendered", "Rendered"),
        ("mixed", "Mixed"),
    ]

    id: int  # Pylance type hint
    audit = models.ForeignKey(
        WebsiteAudit,
        on_delete=models.CASCADE,
        related_name="criterion_results"
    )
    code = models.CharField(max_length=16)         # p.ej. "1.4.3"
    title = models.CharField(max_length=160, blank=True)
    level = models.CharField(max_length=3, blank=True)       # "A" | "AA" | "AAA"
    principle = models.CharField(max_length=20, blank=True)  # "Perceptible" etc.
    verdict = models.CharField(max_length=10, choices=VERDICT_CHOICES)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="raw")

    # 👇 NUEVO: score 0–2 (None si N/A)
    score = models.SmallIntegerField(null=True, blank=True)

    score_hint = models.FloatField(null=True, blank=True)    # ratios/porcentajes útiles
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("audit", "code")]   # 1 fila por criterio y auditoría
        indexes = [models.Index(fields=["code", "verdict", "source"])]
