# audits/checks/criteria/base.py
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

class CheckMode(str, Enum):
    RAW = "raw"            # HTML estático (rápido)
    RENDERED = "rendered"  # DOM/CSS computado (Playwright)
    AI = "ai"              # Soporte con LLM
    AUTO = "auto"          # Orquestador decide: RAW → RENDERED → AI

@dataclass
class CriterionOutcome:
    code: str
    passed: Optional[bool]           # True/False/None
    verdict: str                     # "pass" | "partial" | "fail" | "na"
    score_0_2: Optional[int]         # 2/1/0 o None (si NA)
    details: Dict[str, Any]          # conteos, notas, hallazgos

    # Metadatos de WCAG (opcionalmente rellenados por el caller o con fallback en UI)
    level: Optional[str] = None      # "A" | "AA" | "AAA"
    principle: Optional[str] = None  # "Perceptible", "Operable", etc.
    title: Optional[str] = None      # Texto descriptivo del criterio

    # Fuente de la medición
    source: str = "raw"              # "raw" | "rendered" | "ai"

    # Sugerencia de score (ratio, etc.)
    score_hint: Optional[float] = None

    # Indica si requiere revisión humana (la heurística no es suficiente)
    manual_required: bool = False

    # --- NUEVO: señales para el orquestador ---
    undecided: bool = False          # No puedo decidir aún (insuficiente con este modo)
    needs_rendered: bool = False     # Sugerir usar DOM/CSS renderizado
    needs_ai: bool = False           # Sugerir usar IA para juzgar semántica/complejidad
    note: Optional[str] = None       # Mensaje breve explicativo (opcional)

def verdict_from_counts(details: Dict[str, Any], passed_flag: bool) -> str:
    """
    Calcula 'pass|partial|fail|na' en base a:
      - bandera 'na' en details
      - booleano 'passed'
      - ratios como 'ratio' o 'ok_ratio'
      - conteos 'tested'/'fails' o similares (images_total/missing_alt, links_total/meaningful)
    """
    # 1) Caso NA explícito
    if details.get("na") is True:
        return "na"

    # 2) Si el check devolvió passed=True/False explícito:
    if isinstance(passed_flag, bool):
        if passed_flag:
            # Puede ser pass o partial si hay evidencia de parcialidad
            tested = details.get("tested") \
                     or details.get("images_total") \
                     or details.get("links_total")

            fails = details.get("fails") \
                    or details.get("missing_alt") \
                    or details.get("invalid_count")

            ratio = details.get("ratio") or details.get("ok_ratio")
            if isinstance(ratio, (int, float)) and 0.0 < ratio < 1.0:
                return "partial"
            if isinstance(tested, (int, float)) and isinstance(fails, (int, float)) and tested > 0:
                if 0 < fails < tested:
                    return "partial"
            return "pass"
        else:
            # Fail declarado, pero puede ser partial si el fallo no es total
            tested = details.get("tested") \
                     or details.get("images_total") \
                     or details.get("links_total")

            fails = details.get("fails") \
                    or details.get("missing_alt") \
                    or details.get("invalid_count")

            ratio = details.get("ratio") or details.get("ok_ratio")
            if isinstance(ratio, (int, float)) and 0.0 < ratio < 1.0:
                return "partial"
            if isinstance(tested, (int, float)) and isinstance(fails, (int, float)) and tested > 0:
                if 0 < fails < tested:
                    return "partial"
            return "fail"

    # 3) Sin passed_flag: intentamos con ratio
    ratio = details.get("ratio") or details.get("ok_ratio")
    if isinstance(ratio, (int, float)):
        if ratio >= 0.999:
            return "pass"
        if ratio <= 0.001:
            return "fail"
        return "partial"

    # 4) Sin ratio: intentamos con tested/fails u otros conteos típicos
    tested = details.get("tested") \
             or details.get("images_total") \
             or details.get("links_total")

    fails = details.get("fails") \
            or details.get("missing_alt") \
            or details.get("invalid_count")

    if isinstance(tested, (int, float)) and isinstance(fails, (int, float)) and tested > 0:
        if fails <= 0:
            return "pass"
        if fails >= tested:
            return "fail"
        return "partial"

    # 5) Si no hay datos, ser conservadores (fail); el criterio puede marcar 'undecided'
    return "fail"

def score_from_verdict(v: str) -> Optional[int]:
    """
    Traduce verdict → score 0..2. Deja 'na' en None si prefieres no puntuarlo.
    """
    if v == "pass":
        return 2
    if v == "partial":
        return 1
    if v == "fail":
        return 0
    return None
