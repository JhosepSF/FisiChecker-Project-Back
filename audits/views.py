# audits/views.py
from typing import Any, Mapping, cast
import traceback

from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.generics import ListAPIView, RetrieveAPIView

from .serializers import WebsiteAuditListSerializer, WebsiteAuditSerializer, AuditRequestSerializer
from .models import WebsiteAudit
from .audit import scrape_and_audit
from .utils.persist import persist_audit_with_results
from .checks.criteria.base import CheckMode
from .statistics import AuditStatistics

def _parse_mode(v: str) -> CheckMode:
    v2 = (v or "").strip().lower()
    if v2 in ("rendered", "r"):
        return CheckMode.RENDERED
    if v2 in ("ai",):
        return CheckMode.AI
    if v2 in ("auto", "a"):
        return CheckMode.AUTO
    return CheckMode.RAW

def _results_accessor_name() -> str | None:
    # Busca el accessor reverse hacia WebsiteAuditResult (p.ej. "websiteauditresult_set")
    for rel in WebsiteAudit._meta.related_objects:
        if rel.related_model is AuditRequestSerializer:
            return rel.get_accessor_name()
    return None

class AuditView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        s = AuditRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        vd: Mapping[str, Any] = cast(Mapping[str, Any], getattr(s, "validated_data", {}))
        url = vd.get("url")

        if not isinstance(url, str) or not url.strip():
            return Response({"detail": "Campo 'url' requerido o inválido."}, status=status.HTTP_400_BAD_REQUEST)

        # Modo y flag IA (query o body)
        mode_str = str(request.query_params.get("mode", request.data.get("mode", "raw")))
        run_mode = _parse_mode(mode_str)
        ai_flag = str(request.query_params.get("ai", request.data.get("ai", ""))).lower() in ("1", "true", "yes")

        # Cierra DB antes del trabajo largo
        try: connection.close()
        except Exception: pass

        try:
            data = scrape_and_audit(url, mode=run_mode, use_ai=ai_flag)
        except Exception as e:
            payload = {"detail": str(e)}
            if settings.DEBUG:
                payload["where"] = traceback.format_exc()
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        wcag = data.get("wcag") or data.get("results") or {}
        try:
            audit = persist_audit_with_results(
                url=url,
                response_meta=data,
                wcag=wcag,
                rendered=bool(data.get("rendered", False)),
                rendered_codes=data.get("rendered_codes"),
            )
        except OperationalError as e:
            return Response(
                {"detail": "Database unavailable while saving audit.", "db_error": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            payload = {"detail": str(e)}
            if settings.DEBUG:
                payload["where"] = traceback.format_exc()
            return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(WebsiteAuditSerializer(audit).data, status=status.HTTP_201_CREATED)


class AuditRetrieveView(RetrieveAPIView):
    queryset = WebsiteAudit.objects.all()
    serializer_class = WebsiteAuditSerializer


class AuditListView(ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = WebsiteAuditListSerializer

    def get_queryset(self):
        qs = WebsiteAudit.objects.all().order_by("-fetched_at")
        acc = _results_accessor_name()
        if acc:
            try:
                qs = qs.prefetch_related(acc)
            except Exception:
                # Si por algún motivo falla, seguimos sin prefetch para no romper la vista
                pass
        return qs


# ============= VISTAS DE ESTADÍSTICAS =============

class StatisticsGlobalView(APIView):
    """
    GET /api/statistics/global/
    Retorna estadísticas globales de todas las auditorías.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_global_statistics()
        return Response(stats)


class StatisticsVerdictDistributionView(APIView):
    """
    GET /api/statistics/verdicts/
    Retorna la distribución de veredictos (pass, fail, partial, na).
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_verdict_distribution()
        return Response(stats)


class StatisticsCriteriaView(APIView):
    """
    GET /api/statistics/criteria/
    Retorna estadísticas por criterio WCAG.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_criteria_statistics()
        return Response(stats)


class StatisticsLevelView(APIView):
    """
    GET /api/statistics/levels/
    Retorna estadísticas agrupadas por nivel (A, AA, AAA).
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_level_statistics()
        return Response(stats)


class StatisticsPrincipleView(APIView):
    """
    GET /api/statistics/principles/
    Retorna estadísticas agrupadas por principio WCAG.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_principle_statistics()
        return Response(stats)


class StatisticsTimelineView(APIView):
    """
    GET /api/statistics/timeline/?days=30
    Retorna estadísticas de auditorías a lo largo del tiempo.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        days = int(request.query_params.get('days', 30))
        stats = AuditStatistics.get_timeline_statistics(days)
        return Response(stats)


class StatisticsURLRankingView(APIView):
    """
    GET /api/statistics/ranking/?limit=10
    Retorna el ranking de URLs mejor y peor puntuadas.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        limit = int(request.query_params.get('limit', 10))
        stats = AuditStatistics.get_url_ranking(limit)
        return Response(stats)


class StatisticsSourceComparisonView(APIView):
    """
    GET /api/statistics/sources/
    Compara resultados entre diferentes fuentes (raw, rendered, mixed).
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_source_comparison()
        return Response(stats)


class StatisticsAuditDetailView(APIView):
    """
    GET /api/statistics/audit/<id>/
    Retorna estadísticas detalladas para una auditoría específica.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, audit_id):
        stats = AuditStatistics.get_detailed_audit_statistics(audit_id)
        if "error" in stats:
            return Response(stats, status=status.HTTP_404_NOT_FOUND)
        return Response(stats)


class StatisticsComprehensiveReportView(APIView):
    """
    GET /api/statistics/report/
    Genera un reporte completo con todas las estadísticas principales.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        report = AuditStatistics.get_comprehensive_report()
        return Response(report)


class StatisticsAccessibilityLevelsView(APIView):
    """
    GET /api/statistics/accessibility-levels/
    Calcula niveles de accesibilidad según Hilera et al. (2013).
    Clasifica sitios en: Alto, Moderado, Deficiente, Muy deficiente.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_accessibility_levels_hilera()
        return Response(stats)


class StatisticsAccessibilityByWCAGView(APIView):
    """
    GET /api/statistics/accessibility-by-wcag/
    Calcula niveles de accesibilidad por nivel WCAG (A, AA, AAA).
    Incluye el promedio de cumplimiento de los 3 niveles.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        stats = AuditStatistics.get_accessibility_levels_by_wcag_level()
        return Response(stats)
