# audits/checks/criteria/p2/c_2_3_2_three_flashes.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict
from ..applicability import ensure_na_if_no_applicable, normalize_pass_for_applicable

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.3.2"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

def _bool(v: Any) -> bool:
    sv = _lower(v)
    return sv in ("true", "1", "yes")

def _to_seconds(v: Any) -> Optional[float]:
    """
    Convierte duraciones a segundos (acepta: num, '500ms','0.2s','1.5m','2h').
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    sv = _lower(v)
    if sv == "":
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)?\s*$", sv)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or "s"
    if unit == "ms": return num / 1000.0
    if unit == "s":  return num
    if unit == "m":  return num * 60.0
    if unit == "h":  return num * 3600.0
    return None

MAX_FLASHES_PER_SEC = 3.0  # AAA: sin excepciones

# -------------------------------------------------------------------
# Heurísticas de candidatos (similares a 2.3.1)
# -------------------------------------------------------------------

def _looks_flashy_animation(a: Dict[str, Any]) -> Tuple[bool, Optional[float]]:
    """
    Heurística básica para animaciones:
      - Duración muy corta / alternancias (opacity/visibility/color) → candidato de flashing.
      - Si hay iteration_count alto/infinito, estimamos flashes/seg ~ alternancias / duración.
    Devuelve (es_candidato_flashy, est_flashes_per_sec | None)
    """
    dur = _to_seconds(a.get("duration_s") or a.get("animation_duration") or a.get("duration"))
    if dur is None or dur <= 0:
        # Algunos extractores dan frecuencia directamente
        freq = a.get("frequency_hz")
        if isinstance(freq, (int, float)) and freq > 0:
            return (freq > MAX_FLASHES_PER_SEC, float(freq))
        return (False, None)

    props = _lower(a.get("properties") or a.get("animation_name") or a.get("keyframes") or "")
    toggles_opacity = ("opacity" in props) or ("visibility" in props)
    toggles_color   = ("background" in props) or ("color" in props) or ("filter" in props)
    alternations = 0
    if toggles_opacity: alternations += 1
    if toggles_color:   alternations += 1
    if alternations == 0 and "blink" in props:
        alternations = 1

    if alternations == 0:
        return (False, None)

    fps = (alternations / max(dur, 1e-6))
    is_flashy = fps > MAX_FLASHES_PER_SEC or dur <= 0.25  # sospecha si ciclo extremadamente corto
    return (is_flashy, fps)

def _looks_flashy_gif(meta: Dict[str, Any]) -> Tuple[bool, Optional[float]]:
    """
    Estima flashes/seg para GIF si hay 'frame_delay_ms'.
    Conservador: 0.5 * fps (asumiendo alternancia claro/oscuro).
    """
    fd_ms = meta.get("frame_delay_ms")
    if isinstance(fd_ms, (int, float)) and fd_ms > 0:
        fps = 1000.0 / float(fd_ms)
        flashes = 0.5 * fps
        return (flashes > MAX_FLASHES_PER_SEC, flashes)
    return (False, None)

def _candidate_from_class_hints(n: Dict[str, Any]) -> bool:
    cls = _lower(n.get("class"))
    return any(h in cls for h in ("strobe","strobing","flash","flashing","blink","blinking","rapid","pulse-fast","pulse-rapid"))

# -------------------------------------------------------------------
# Recolección de candidatos (RAW)
# -------------------------------------------------------------------

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Fuentes: animations, videos (flash_events), GIFs (gif_meta), hints por clase.
    """
    out: List[Dict[str, Any]] = []

    for a in _as_list(getattr(ctx, "animations", [])):
        if not isinstance(a, dict):
            continue
        flashy, fps = _looks_flashy_animation(a)
        out.append({
            "kind": "animation",
            "selector": _s(a.get("selector") or a.get("id")),
            "label": _s(a.get("label") or a.get("aria-label")),
            "flashy": flashy,
            "est_flashes_per_sec": fps,
            "source": "animations"
        })

    for v in _as_list(getattr(ctx, "videos", [])):
        if not isinstance(v, dict):
            continue
        flashy = _bool(v.get("strobe_warning")) or _bool(v.get("has_strobe"))
        fps = None
        evs = _as_list(v.get("flash_events"))
        if evs:
            try:
                # evs: lista de tiempos (s) de flashes detectados
                evs_sorted = sorted([float(x) for x in evs if isinstance(x, (int, float, str))])
                i = 0
                max_in_window = 0
                for j in range(len(evs_sorted)):
                    while evs_sorted[j] - evs_sorted[i] > 1.0:
                        i += 1
                    max_in_window = max(max_in_window, j - i + 1)
                fps = float(max_in_window)
                flashy = flashy or (fps > MAX_FLASHES_PER_SEC)
            except Exception:
                pass
        out.append({
            "kind": "video",
            "selector": _s(v.get("selector") or v.get("id") or v.get("src")),
            "label": _s(v.get("label") or v.get("aria-label") or v.get("title")),
            "flashy": flashy,
            "est_flashes_per_sec": fps,
            "source": "videos"
        })

    for im in _as_list(getattr(ctx, "imgs", [])):
        if isinstance(im, dict):
            src = _lower(_s(im.get("src")))
            is_gif = src.endswith(".gif") or _bool(im.get("is_gif"))
            meta = im.get("gif_meta") or {}
            alt  = _s(im.get("alt"))
        else:
            # si es un tag Soup
            try:
                src = _lower(im.get("src")) if hasattr(im, "get") else ""
            except Exception:
                src = ""
            is_gif = src.endswith(".gif")
            meta = {}
            alt = ""
        if is_gif:
            flashy, fps = _looks_flashy_gif(meta if isinstance(meta, dict) else {})
            out.append({
                "kind": "gif",
                "selector": src[:120],
                "label": alt,
                "flashy": flashy,
                "est_flashes_per_sec": fps,
                "source": "imgs"
            })

    for coll in ("widgets","custom_components","banners","headers","sections","cards","panels"):
        for n in _as_list(getattr(ctx, coll, [])):
            if not isinstance(n, dict):
                continue
            if _candidate_from_class_hints(n):
                out.append({
                    "kind": "hint",
                    "selector": _s(n.get("selector") or n.get("id")),
                    "label": _s(n.get("label") or n.get("aria-label") or n.get("heading") or n.get("text")),
                    "flashy": True,
                    "est_flashes_per_sec": None,
                    "source": f"class_hint:{coll}"
                })

    return out

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _is_applicable(item: Dict[str, Any]) -> bool:
    """
    Aplica si hay indicios de flashing (flashy=True) o si se estiman >0 flashes/seg.
    """
    if bool(item.get("flashy")):
        return True
    fps = item.get("est_flashes_per_sec")
    return isinstance(fps, (int, float)) and fps > 0.0

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW (AAA): violación solo cuando se mide/estima >3 destellos/s en alguna ventana de 1s.
    Si no hay medición (solo hints), marcamos 'unknown' y requerimos revisión manual.
    """
    items = _collect_candidates(ctx)

    examined = len(items)
    applicable = 0
    compliant = 0
    violations = 0
    unknown = 0
    offenders: List[Dict[str, Any]] = []

    for it in items:
        if not _is_applicable(it):
            continue
        applicable += 1

        fps = it.get("est_flashes_per_sec")
        if isinstance(fps, (int, float)):
            if float(fps) > MAX_FLASHES_PER_SEC:
                violations += 1
                offenders.append({
                    "kind": it.get("kind"),
                    "selector": it.get("selector"),
                    "label": it.get("label"),
                    "est_flashes_per_sec": float(fps),
                    "reason": "Estimado/medido >3 destellos/s (AAA no permite excepciones)."
                })
            else:
                compliant += 1
        else:
            unknown += 1
            offenders.append({
                "kind": it.get("kind"),
                "selector": it.get("selector"),
                "label": it.get("label"),
                "est_flashes_per_sec": None,
                "reason": "Candidato a flashing sin medición de frecuencia. Revisión manual requerida."
            })

    # ok_ratio solo considera casos con medición (aplicable - unknown)
    denom = max(1, applicable - unknown)
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / denom)), 4)

    details: Dict[str, Any] = {
        "items_examined": examined,
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "unknown": unknown,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.3.2 (AAA) prohíbe más de 3 destellos en cualquier segundo, sin excepciones. "
            "Solo fallamos automáticamente si hay medición/estimación >3/s. "
            "Si solo hay indicios (hints) sin medición, marcamos 'unknown' y pedimos revisión manual."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (medición en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar:
      rctx.flash_test = [
        {
          "selector": str,
          "max_flashes_per_1s": number,    # máximo contado en ventana de 1s
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.3.2; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "flash_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'flash_test'.").strip()
        return d

    applicable = 0
    compliant = 0
    violations = 0
    unknown = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue

        mps = t.get("max_flashes_per_1s")
        if not isinstance(mps, (int, float)) or float(mps) <= 0.0:
            # hay candidato pero sin medición válida → unknown
            unknown += 1
            offenders.append({
                "selector": _s(t.get("selector")),
                "max_flashes_per_1s": None,
                "reason": "En ejecución: candidato sin medición válida. Revisión manual."
            })
            continue

        applicable += 1
        if float(mps) > MAX_FLASHES_PER_SEC:
            violations += 1
            offenders.append({
                "selector": _s(t.get("selector")),
                "max_flashes_per_1s": float(mps),
                "reason": "En ejecución: >3 destellos/s (AAA)."
            })
        else:
            compliant += 1

    denom = max(1, applicable - unknown)
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / denom)), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "unknown": d.get("unknown", 0) + unknown,
        "ok_ratio": ok_ratio,
        "offenders": (d.get("offenders", []) or []) + offenders,
        "note": (d.get("note","") + " | RENDERED: medición directa de destellos/s.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: reduce/elimna flashing y garantiza ≤3/s si no se puede evitar:
      - Aumentar duración de ciclo (≥ 333 ms por alternancia).
      - Sustituir blink/flash por transiciones suaves.
      - Eliminar flashing no esencial o desactivarlo por defecto.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs_help = (details.get("violations", 0) or 0) > 0 or (details.get("unknown", 0) or 0) > 0
    if not needs_help:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "unknown": details.get("unknown", 0),
        },
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
    }
    prompt = (
        "Eres auditor WCAG 2.3.2 (Three Flashes, AAA). "
        "Para cada offender, sugiere cómo garantizar ≤3 destellos/s o eliminar el flashing: "
        "- Aumentar la duración del ciclo (mínimo ~333 ms por transición); "
        "- Cambiar a transiciones suaves (opacity/transform) sin flashing; "
        "- Desactivar animaciones no esenciales por defecto. "
        "Devuelve JSON: { suggestions: [{selector?, reason, css_fix?, js_fix?, design_alt?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_3_2(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
    # 1) Detalles según modo
    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx)
            details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."
            src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx)
            src = "rendered"
    else:
        details = _compute_counts_raw(ctx)
        src = "raw"

    # 2) IA opcional
    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = ai_info.get("manual_review", False)

    # 3) Aplicabilidad / NA
    ensure_na_if_no_applicable(details, applicable_keys=("applicable",),
                               note_suffix="no se detectaron eventos de destello evaluables")

    # 4) passed / verdict / score
    passed = normalize_pass_for_applicable(details, violations_key="violations", applicable_keys=("applicable",))

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Tres destellos"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("unknown", 0) or 0) > 0
    )
