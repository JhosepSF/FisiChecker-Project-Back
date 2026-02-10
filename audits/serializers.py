# audits/serializers.py
from rest_framework import serializers
from django.db.models import QuerySet
from typing import List, Optional, Any
from .models import WebsiteAudit, WebsiteAuditResult

def _results_accessor_name() -> Optional[str]:
    for rel in WebsiteAudit._meta.related_objects:
        if rel.related_model is WebsiteAuditResult:
            return rel.get_accessor_name()
    return None

class AuditRequestSerializer(serializers.Serializer):
    url = serializers.URLField()

class WebsiteAuditResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsiteAuditResult
        fields = [
            "code", "title", "level", "principle",
            "verdict", "source",
            "score",           # 👈 AÑADIR
            "score_hint", "details"
        ]

class WebsiteAuditSerializer(serializers.ModelSerializer):
    criterion_results = WebsiteAuditResultSerializer(many=True, read_only=True)

    class Meta:
        model = WebsiteAudit
        fields = [
            "id", "url", "fetched_at", "status_code", "elapsed_ms",
            "page_title", "score", "results", "rendered", "criterion_results"
        ]

class WebsiteAuditListSerializer(serializers.ModelSerializer):
    mode_effective = serializers.SerializerMethodField()
    verdict_counts = serializers.SerializerMethodField()
    rendered_codes_count = serializers.SerializerMethodField()
    ai_codes_count = serializers.SerializerMethodField()

    class Meta:
        model = WebsiteAudit
        fields = [
            "id", "url", "fetched_at", "page_title", "score",
            "status_code", "elapsed_ms",
            "rendered",
            "mode_effective",
            "verdict_counts",
            "rendered_codes_count",
            "ai_codes_count",
        ]

    # --- Helpers seguros para Pylance ---
    def _get_results_manager(self, obj: WebsiteAudit) -> Optional[Any]:
        # 1) accessor real si existe (p.ej. "websiteauditresult_set" o un related_name custom)
        acc = _results_accessor_name()
        rel = getattr(obj, acc, None) if acc else None
        # 2) atajos habituales, por compatibilidad
        if rel is None:
            rel = getattr(obj, "results", None)
        if rel is None:
            rel = getattr(obj, "websiteauditresult_set", None)
        return rel if hasattr(rel, "all") else None

    def _iter_results(self, obj: WebsiteAudit) -> List[WebsiteAuditResult]:
        rel = self._get_results_manager(obj)
        if rel is not None:
            try:
                qs = rel.all()
                return list(qs) if isinstance(qs, QuerySet) else list(qs)
            except Exception:
                pass
        # Fallback sin prefetch
        return list(WebsiteAuditResult.objects.filter(audit=obj))

    def get_mode_effective(self, obj: WebsiteAudit) -> str:
        res = self._iter_results(obj)
        any_ai = any((r.source or "").lower() == "ai" for r in res)
        any_rendered = any((r.source or "").lower() == "rendered" for r in res)
        if any_ai:
            return "AI"
        if any_rendered:
            return "RENDERED"
        return "RAW"

    def get_verdict_counts(self, obj: WebsiteAudit):
        c = {"pass": 0, "fail": 0, "partial": 0, "na": 0}
        for r in self._iter_results(obj):
            v = (r.verdict or "").lower()
            if v in c:
                c[v] += 1
        return c

    def get_rendered_codes_count(self, obj: WebsiteAudit) -> int:
        return sum(1 for r in self._iter_results(obj) if (r.source or "").lower() == "rendered")

    def get_ai_codes_count(self, obj: WebsiteAudit) -> int:
        return sum(1 for r in self._iter_results(obj) if (r.source or "").lower() == "ai")