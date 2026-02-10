# audits/audit.py
import time
from typing import Dict, Any, List, Optional, Tuple

from django.db import connection

from .wcag.context import build_context, PageContext, choose_display_title
from .utils.html_loader import soup_from_url
from .utils.rendered_loader import rendered_context_for_url
from .checks.criteria.base import CheckMode, CriterionOutcome
from .checks.criteria.registry import get_check, list_available_codes

def _verdict_counts(outcomes):
    c = {"pass": 0, "fail": 0, "partial": 0, "na": 0}
    for o in outcomes:
        v = (o.verdict or "").lower()
        if v in c: c[v] += 1
    return c

def _used_codes_by_source(outcomes):
    ai = [o.code for o in outcomes if (o.source or "").lower() == "ai"]
    rendered = [o.code for o in outcomes if (o.source or "").lower() == "rendered"]
    raw = [o.code for o in outcomes if (o.source or "").lower() in ("raw","")]
    return {"ai": ai, "rendered": rendered, "raw": raw}

def _mode_effective(outcomes):
    any_ai = any((o.source or "").lower() == "ai" for o in outcomes)
    any_rendered = any((o.source or "").lower() == "rendered" for o in outcomes)
    if any_ai: return "AI"
    if any_rendered: return "RENDERED"
    return "RAW"

# === Config de score
SCORE_INCLUDE_AAA = False
LEVEL_WEIGHTS = {"A": 1.0, "AA": 1.0, "AAA": 1.0}
# Penaliza el score por baja cobertura (muchos NA)
STRICT_COVERAGE_PENALTY = True

# === Matriz liviana de capacidades: qué criterios requieren Rendered o se benefician de IA
CRITERIA_CAPS: Dict[str, Dict[str, Any]] = {
    # Perceptible
    "1.1.1": {"raw_ok": True,  "ai_helpful": True},
    "1.3.1": {"raw_ok": True,  "rendered_better": True},
    "1.3.5": {"raw_ok": True,  "rendered_better": True, "ai_helpful": True},
    "1.3.6": {"raw_ok": True,  "rendered_better": True, "ai_helpful": True},
    "1.4.1": {"raw_ok": True},
    "1.4.2": {"raw_ok": True},
    "1.4.3": {"raw_ok": False, "needs_rendered": True},   # contraste real
    "1.4.4": {"raw_ok": True},
    "1.4.5": {"raw_ok": True},
    "1.4.6": {"raw_ok": False, "needs_rendered": True},   # AAA contraste mejorado
    "1.4.7": {"raw_ok": True},
    "1.4.8": {"raw_ok": True},
    "1.4.9": {"raw_ok": True},
    "1.4.10": {"raw_ok": False, "needs_rendered": True},  # reflow/overflow
    "1.4.11": {"raw_ok": False, "needs_rendered": True},  # contraste no-texto
    "1.4.12": {"raw_ok": True},
    "1.4.13": {"raw_ok": True},

    # Operable
    "2.1.1": {"raw_ok": True, "rendered_better": True},
    "2.1.2": {"raw_ok": True},
    "2.1.3": {"raw_ok": True},
    "2.1.4": {"raw_ok": True},
    "2.2.1": {"raw_ok": True, "rendered_better": True},
    "2.2.2": {"raw_ok": True},
    "2.2.3": {"raw_ok": True},
    "2.2.4": {"raw_ok": True},
    "2.2.5": {"raw_ok": True},
    "2.2.6": {"raw_ok": True},
    "2.3.1": {"raw_ok": True},
    "2.3.2": {"raw_ok": True},
    "2.3.3": {"raw_ok": True},
    "2.4.1": {"raw_ok": True},
    "2.4.2": {"raw_ok": True},
    "2.4.3": {"raw_ok": True, "rendered_better": True},
    "2.4.4": {"raw_ok": True},
    "2.4.5": {"raw_ok": True},
    "2.4.6": {"raw_ok": True},
    "2.4.7": {"raw_ok": False, "needs_rendered": True},   # foco visible
    "2.4.8": {"raw_ok": True},
    "2.4.9": {"raw_ok": True},
    "2.4.10": {"raw_ok": True},
    "2.5.1": {"raw_ok": True, "rendered_better": True},
    "2.5.2": {"raw_ok": True},
    "2.5.3": {"raw_ok": True},
    "2.5.4": {"raw_ok": True},
    "2.5.5": {"raw_ok": False, "needs_rendered": True},   # tamaño objetivo
    "2.5.6": {"raw_ok": True},

    # Comprensible
    "3.1.1": {"raw_ok": True},
    "3.1.2": {"raw_ok": True},
    "3.1.3": {"raw_ok": True},
    "3.1.4": {"raw_ok": True},
    "3.1.5": {"raw_ok": True},
    "3.1.6": {"raw_ok": True},
    "3.2.1": {"raw_ok": False, "needs_rendered": True},   # cambios de contexto por focus
    "3.2.2": {"raw_ok": False, "needs_rendered": True},
    "3.2.3": {"raw_ok": True},
    "3.2.4": {"raw_ok": True},
    "3.2.5": {"raw_ok": True},
    "3.3.1": {"raw_ok": True, "ai_helpful": True},
    "3.3.2": {"raw_ok": True, "ai_helpful": True},
    "3.3.3": {"raw_ok": True, "ai_helpful": True},
    "3.3.4": {"raw_ok": True, "ai_helpful": True},
    "3.3.5": {"raw_ok": True, "ai_helpful": True},
    "3.3.6": {"raw_ok": True, "ai_helpful": True},

    # Robusto
    "4.1.1": {"raw_ok": True},
    "4.1.2": {"raw_ok": True, "rendered_better": True},
    "4.1.3": {"raw_ok": False, "needs_rendered": True},   # anuncios en vivo
}

def _caps_for(code: str) -> Dict[str, Any]:
    if code in CRITERIA_CAPS:
        return CRITERIA_CAPS[code]
    # soporte prefijo tipo "1.2.*"
    for k, v in CRITERIA_CAPS.items():
        if k.endswith(".*") and code.startswith(k[:-2]):
            return v
    return {}

def _compute_score(criterion_results: List[CriterionOutcome]) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Excluye 'na' del denominador. Cuenta sólo pass/fail.
    """
    total_weight = 0.0
    total_weight_all = 0.0
    acc = 0.0
    per_level_counts = {
        "A":  {"total": 0, "passed": 0},
        "AA": {"total": 0, "passed": 0},
        "AAA": {"total": 0, "passed": 0},
    }
    for outcome in criterion_results:
        lvl = (outcome.level or "A").upper()
        if lvl == "AAA" and not SCORE_INCLUDE_AAA:
            continue
        w = LEVEL_WEIGHTS.get(lvl, 1.0)
        total_weight_all += w

        if outcome.verdict == "na":
            # NA cuenta para cobertura, no para score base
            per_level_counts[lvl]["total"] += 1
            continue

        total_weight += w
        val = 1.0 if outcome.verdict == "pass" else 0.0
        acc += val * w
        per_level_counts[lvl]["total"] += 1
        if outcome.verdict == "pass":
            per_level_counts[lvl]["passed"] += 1

    if total_weight == 0:
        return (None, per_level_counts)

    base_score = acc / total_weight
    coverage = (total_weight / total_weight_all) if total_weight_all > 0 else 1.0
    final_score = base_score * coverage if STRICT_COVERAGE_PENALTY else base_score

    per_level_counts["_coverage"] = round(coverage, 4)
    per_level_counts["_base_score"] = round(base_score, 4)

    return (round(final_score, 4), per_level_counts)

def _outcome_to_dict(out: CriterionOutcome) -> Dict[str, Any]:
    return {
        "code": out.code,
        "title": out.title,
        "level": out.level,
        "principle": out.principle,
        "verdict": out.verdict,
        "source": out.source,
        "score": out.score_0_2,
        "score_hint": out.score_hint,
        "details": out.details,
    }

def _wcag_map_from_outcomes(criterion_results: List[CriterionOutcome]) -> Dict[str, Any]:
    wcag: Dict[str, Any] = {}
    for out in criterion_results:
        wcag[out.code] = {
            "passed": bool(out.verdict == "pass"),
            "details": out.details,
            "status": out.verdict,
            "score_0_2": out.score_0_2,
            "source": out.source  # 👈 AÑADIR source
        }
    return wcag

def _normalize_outcome_na(out: CriterionOutcome) -> CriterionOutcome:
    """
    Si el criterio marcó 'na' en details, fuerza verdict='na' y un score neutro.
    Además, aplica heurísticas genéricas NA cuando no hay nada que medir.
    """
    d = out.details or {}

    # Respeta bandera NA explícita
    if d.get("na") is True:
        out.verdict = "na"
        out.score_0_2 = 1  # neutro
        return out

    # Heurística NA (conocidos):
    # 1.4.3 / 1.4.6: si no hay texto medible (tested_* == 0)
    if out.code in ("1.4.3", "1.4.6"):
        td = d.get("tested_desktop") or 0
        tm = d.get("tested_mobile") or 0
        if (td == 0) and (tm == 0):
            d["na"] = True
            out.verdict = "na"
            out.score_0_2 = 1

    # 2.4.7 Foco visible: si no hay focusables
    if out.code == "2.4.7":
        if isinstance(d.get("tested"), int) and d.get("tested", 0) == 0:
            d["na"] = True
            out.verdict = "na"
            out.score_0_2 = 1

    # 1.4.11: si no hay componentes no-texto testeados
    if out.code == "1.4.11":
        if isinstance(d.get("tested"), int) and d.get("tested", 0) == 0:
            d["na"] = True
            out.verdict = "na"
            out.score_0_2 = 1

    out.details = d
    return out

def _should_try_rendered(run_mode: CheckMode, code: str) -> bool:
    # En modo RENDERED, AI, o AUTO con use_ai, intenta rendered para todos los criterios que lo soporten
    if run_mode in (CheckMode.RENDERED, CheckMode.AI):
        return True
    # En modo AUTO, usa rendered solo para criterios que lo necesitan o mejoran con él
    caps = _caps_for(code)
    return bool(caps.get("needs_rendered") or caps.get("rendered_better"))

def scrape_and_audit(
    url: str,
    selected_codes: Optional[List[str]] = None,
    mode: CheckMode = CheckMode.AUTO,   # raw | rendered | ai | auto
    use_ai: bool = False                # agrega pasada IA (sugerencias) en cualquier modo
) -> Dict[str, Any]:

    # Cierra cualquier conexión abierta antes de trabajo largo
    try:
        connection.close()
    except Exception:
        pass

    t0 = time.time()
    soup, meta = soup_from_url(url, timeout=20)
    elapsed_ms = int((time.time() - t0) * 1000)
    ctx = build_context(soup)

    title_choice = choose_display_title(url, soup, ctx.title_text)
    display_title = (title_choice["display_title"] or "")[:512]

    available = list_available_codes()
    to_run = [c for c in (selected_codes or available) if c in available]

    outcomes: List[CriterionOutcome] = []
    rendered_ctx: Optional[PageContext] = None
    rendered_used_codes: List[str] = []
    html_for_ai: str = ""

    # Si de antemano sabemos que haremos rendered para varios criterios, abrimos una sola vez
    # En modo AUTO con IA, también precargamos rendered para tener contexto completo
    print(f"DEBUG preload_rendered: mode={mode}, use_ai={use_ai}")
    preload_rendered = (mode in (CheckMode.RENDERED, CheckMode.AI)) or (mode == CheckMode.AUTO and use_ai)
    print(f"preload_rendered = {preload_rendered}")
    if preload_rendered:
        try:
            rendered_ctx, html_for_ai = rendered_context_for_url(url, timeout_ms=60000)
        except Exception as e:
            rendered_ctx = None
            print(f"[WARN] No se pudo cargar rendered context: {e}")

    for code in to_run:
        fn = get_check(code)

        # 1) RAW siempre primero (rápido)
        try:
            out_raw = fn(ctx, mode=CheckMode.RAW)
        except TypeError:
            # compat antigua
            out_raw = fn(ctx)

        chosen = out_raw

        # 2) Rendered si el modo o el criterio lo sugiere
        if _should_try_rendered(mode, code):
            if rendered_ctx is None:
                try:
                    rendered_ctx, html_for_ai = rendered_context_for_url(url, timeout_ms=15000)
                except Exception:
                    rendered_ctx = None
            if rendered_ctx is not None:
                try:
                    out_r = fn(ctx, mode=CheckMode.RENDERED, rendered_ctx=rendered_ctx)
                    chosen = out_r
                    rendered_used_codes.append(code)
                except Exception as e:
                    chosen.details["rendered_run_error"] = str(e)

        # 3) IA opcional: solo en criterios donde sea útil (marcados en CRITERIA_CAPS)
        caps = _caps_for(code)
        is_ai_helpful = caps.get("ai_helpful", False)
        
        # DEBUG: agregar info a detalles
        chosen.details["_debug_mode"] = str(mode)
        chosen.details["_debug_use_ai"] = use_ai
        chosen.details["_debug_ai_helpful"] = is_ai_helpful
        
        # En modo AI puro, ejecuta IA en todos. Con use_ai=True, solo en los marcados como útiles.
        should_run_ai = (mode == CheckMode.AI) or (use_ai and is_ai_helpful)
        chosen.details["_debug_should_run_ai"] = should_run_ai
        
        if should_run_ai:
            try:
                # La IA debe usar el mejor contexto disponible: rendered si existe, sino raw
                ai_ctx = rendered_ctx if rendered_ctx is not None else ctx
                out_ai = fn(
                    ai_ctx,
                    mode=CheckMode.AI,
                    rendered_ctx=rendered_ctx,
                    html_for_ai=html_for_ai[:20000] if isinstance(html_for_ai, str) else None
                )
                if out_ai:
                    # Reemplaza el outcome para que el source/veredicto/score sean los de IA
                    chosen = out_ai
                    chosen.details["_debug_ai_executed"] = True
                # Si no hay respuesta útil, conservamos el chosen anterior
            except Exception as e:
                # Registra el error en details para debugging
                chosen.details = dict(chosen.details or {})
                chosen.details["ai_error"] = str(e)
                chosen.details["_debug_ai_error"] = True

        # 4) Normaliza NA cuando aplique
        chosen = _normalize_outcome_na(chosen)
        outcomes.append(chosen)

    score_value, per_level = _compute_score(outcomes)
    wcag_map = _wcag_map_from_outcomes(outcomes)
    crit_list = [_outcome_to_dict(o) for o in outcomes]

    # recomendaciones según capacidades y NAs
    consider_rendered: List[str] = []
    consider_ai: List[str] = []
    for o in outcomes:
        caps = _caps_for(o.code)
        d = o.details or {}
        if d.get("na") is True and caps.get("needs_rendered"):
            consider_rendered.append(o.code)
        if caps.get("ai_helpful") and "ai_info" not in d:
            consider_ai.append(o.code)

    verdict_counts = _verdict_counts(outcomes)
    used = _used_codes_by_source(outcomes)
    effective_mode = _mode_effective(outcomes)
    
    return {
        "status_code": meta.get("status_code"),
        "elapsed_ms": elapsed_ms,
        "page_title": display_title,
        "lang": ctx.lang,
        "score": score_value,
        "wcag": wcag_map,
        "criterion_results": crit_list,
        "score_breakdown": per_level,
        "rendered": bool(rendered_used_codes),
        "rendered_codes": rendered_used_codes,
        "rendered_codes": used["rendered"],   
        "ai_codes": used["ai"],               
        "mode_effective": effective_mode,     
        "verdict_counts": verdict_counts,   
        "recommendations": {
            "consider_rendered_for": sorted(set(consider_rendered)),
            "consider_ai_for": sorted(set(consider_ai)) if (use_ai or mode == CheckMode.AI) else []
        }
    }
