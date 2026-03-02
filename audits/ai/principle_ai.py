# audits/ai/principle_ai.py
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple, Set, TYPE_CHECKING

from ..checks.criteria.base import CriterionOutcome
from ..wcag.constants import WCAG_META

if TYPE_CHECKING:
    from ..checks.criteria.base import CheckMode

try:
    from .ollama_client import ask_json
except Exception:  # pragma: no cover - fallback when Ollama no disponible
    ask_json = None  # type: ignore

logger = logging.getLogger("audits.ai")

_PRINCIPLE_PROMPT = (
    "Eres un auditor experto en accesibilidad WCAG dedicado al principio {principle}. "
    "Recibirás problemas ya detectados (código, título, nivel, veredicto y pistas) y debes sintetizar "
    "las causas comunes, el impacto para las personas usuarias y sugerir hasta tres acciones concretas. "
    "Responde SOLO en JSON con la forma: {{\"principle\": str, \"summary\": str, "
    "\"recommendations\": [{{\"action\": str, \"impact\": str}}], \"priority\": \"alta|media|baja\" }}."
)

_MAX_ISSUES_PER_PRINCIPLE = 4
_MAX_TEXT = 420


def _trim(value: Any, limit: int = _MAX_TEXT) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _offenders_preview(details: Dict[str, Any]) -> str:
    offenders = details.get("offenders")
    if not offenders:
        return ""
    try:
        serialized = json.dumps(offenders, ensure_ascii=False)
    except Exception:
        serialized = str(offenders)
    return _trim(serialized)


def _extract_metrics(details: Dict[str, Any]) -> Dict[str, Any]:
    interesting = ("fails", "tested", "images_total", "missing_alt", "labels_missing", "headings_empty")
    out: Dict[str, Any] = {}
    for key in interesting:
        if key in details:
            out[key] = details[key]
    return out


class PrincipleAIAggregator:
    def __init__(self, mode: str = "AUTO") -> None:
        self._issues: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._codes: Set[str] = set()
        self._mode = str(mode).upper()

    def add_outcome(self, outcome: CriterionOutcome) -> None:
        # En modo AI puro, procesar todos los criterios (incluso pass/na)
        # En otros modos (AUTO+ai), solo fail/partial
        skip_non_issues = self._mode != "AI"
        if skip_non_issues and outcome.verdict not in ("fail", "partial"):
            logger.debug(
                "Skipping AI aggregation for %s because verdict=%s (mode=%s)",
                outcome.code,
                outcome.verdict,
                self._mode,
            )
            return
        principle = outcome.principle or WCAG_META.get(outcome.code, {}).get("principle") or "Otros"
        issue = self._build_issue(outcome)
        if not issue:
            return
        self._issues[principle].append(issue)
        self._codes.add(outcome.code)
        logger.debug(
            "Queued outcome %s for principle %s (verdict=%s)",
            outcome.code,
            principle,
            outcome.verdict,
        )

    def has_issues(self) -> bool:
        return bool(self._issues)

    def _process_principle(self, principle: str, issues: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Procesa un principio individual (para paralelización)"""
        if ask_json is None:  # Verificación de seguridad
            return principle, {"error": "ask_json not available", "principle": principle}
        
        ctx = {
            "principle": principle,
            "issues": issues[:_MAX_ISSUES_PER_PRINCIPLE],
        }
        prompt = _PRINCIPLE_PROMPT.format(principle=principle)
        start = time.perf_counter()
        resp: Dict[str, Any]
        try:
            # Timeout aumentado a 600s (10 min) y 3 reintentos para llamadas paralelas
            resp = ask_json(prompt=prompt, context=json.dumps(ctx, ensure_ascii=False), timeout=600, max_retries=3)
        except Exception as exc:  # pragma: no cover - dependiente de IA externa
            resp = {"error": str(exc), "principle": principle}
        duration_ms = int((time.perf_counter() - start) * 1000)
        resp["_duration_ms"] = duration_ms
        logger.info(
            "  [OK] Principio '%s': %d criterios -> %dms",
            principle,
            len(ctx["issues"]),
            duration_ms,
        )
        return principle, resp

    def run(self) -> Tuple[Dict[str, Any], List[str]]:
        if not self._issues or ask_json is None:
            logger.info(
                "Principle AI skipped: has_issues=%s ask_json_available=%s",
                bool(self._issues),
                ask_json is not None,
            )
            return ({}, [])

        # Timing total del agregador
        total_start = time.perf_counter()
        total_issues_count = sum(len(issues) for issues in self._issues.values())
        
        logger.info(
            "[IA] Iniciando análisis de %d principios con %d criterios (secuencial)",
            len(self._issues),
            total_issues_count,
        )

        # Ejecutar análisis de principios secuencialmente (Ollama no soporta paralelismo bien)
        reports: Dict[str, Any] = {}
        for principle, issues in self._issues.items():
            try:
                principle, resp = self._process_principle(principle, issues)
                reports[principle] = resp
            except Exception as exc:
                logger.error("Error procesando principio %s: %s", principle, exc)
                reports[principle] = {"error": str(exc), "principle": principle}
        
        total_duration = int((time.perf_counter() - total_start) * 1000)
        logger.info(
            "[IA] Análisis completado en %dms total. Principios procesados: %s",
            total_duration,
            ", ".join(reports.keys()),
        )
        
        return reports, sorted(self._codes)

    def _build_issue(self, outcome: CriterionOutcome) -> Dict[str, Any]:
        details = outcome.details or {}
        summary = details.get("note") or details.get("message")
        evidence = _offenders_preview(details)
        if not summary and not evidence:
            summary = details.get("warning") or details.get("summary") or ""
        return {
            "code": outcome.code,
            "title": outcome.title,
            "level": outcome.level,
            "verdict": outcome.verdict,
            "metrics": _extract_metrics(details),
            "summary": _trim(summary),
            "evidence": evidence,
        }
