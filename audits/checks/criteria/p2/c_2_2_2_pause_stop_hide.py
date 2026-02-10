# audits/checks/criteria/p2/c_2_2_2_pause_stop_hide.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.2.2"

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

def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None: return None
        if isinstance(v, (int, float)): return float(v)
        sv = _lower(v)
        if sv == "": return None
        return float(sv)
    except Exception:
        return None

def _to_seconds(v: Any) -> Optional[float]:
    """
    Acepta: num (s), "5000ms", "5s", "1.5m", "2h"
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

# Pistas para candidatos
GIF_HINTS = (".gif",)
MARQUEE_TAG = "marquee"   # obsoleto, pero aún aparece
BLINK_TAG = "blink"       # obsoleto
MOVE_HINT_CLASSES = ("marquee","ticker","carousel","slider","auto-slide","auto_advance","scroller","scrolling","animate","moving","blink","typing")
ANIM_KEYS = ("animation_name","animation-duration","animation_duration","animation_iteration_count","animation-iteration-count")
UPDATE_HINTS = ("auto-update","live-update","feed-refresh","news-ticker","stock-ticker","live-scores")

FIVE_SECONDS = 5.0

# -------------------------------------------------------------------
# Recolección (RAW)
# -------------------------------------------------------------------

def _collect_html_tag_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Busca <marquee> / <blink> y GIFs (heurístico).
    """
    out: List[Dict[str, Any]] = []
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return out
    try:
        for m in soup.find_all(MARQUEE_TAG):
            out.append({
                "type": "scrolling",
                "source": "html_marquee",
                "auto_starts": True,
                "indefinite": True,
                "duration_s": None,
                "can_pause": False,
                "can_stop": False,
                "can_hide": False,
                "essential": False,
                "real_time": False,
                "parallel_content": True,
                "selector": getattr(m, "name", "marquee"),
                "snippet": (m.get_text() or "")[:120]
            })
    except Exception:
        pass
    try:
        for b in soup.find_all(BLINK_TAG):
            out.append({
                "type": "blinking",
                "source": "html_blink",
                "auto_starts": True,
                "indefinite": True,
                "duration_s": None,
                "can_pause": False,
                "can_stop": False,
                "can_hide": False,
                "essential": False,
                "real_time": False,
                "parallel_content": True,
                "selector": getattr(b, "name", "blink"),
                "snippet": (b.get_text() or "")[:120]
            })
    except Exception:
        pass
    try:
        for img in soup.find_all("img"):
            src = (img.get("src") or "").lower()
            if any(src.endswith(ext) for ext in GIF_HINTS):
                out.append({
                    "type": "animated_image",
                    "source": "img_gif",
                    "auto_starts": True,
                    "indefinite": True,      # heurístico
                    "duration_s": None,
                    "can_pause": False,
                    "can_stop": False,
                    "can_hide": False,
                    "essential": False,
                    "real_time": False,
                    "parallel_content": True,
                    "selector": "img[src*=gif]",
                    "snippet": src[:160]
                })
    except Exception:
        pass
    return out

def _collect_from_ctx_lists(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Usa colecciones opcionales del extractor si existen:
      - animations: [{duration_s, iteration_count, auto_starts, can_pause, can_stop, can_hide, essential, real_time, selector}]
      - moving_banners / tickers / carousels / sliders
      - auto_updates: feeds que cambian sin intervención
    """
    out: List[Dict[str, Any]] = []

    for a in _as_list(getattr(ctx, "animations", [])):
        if not isinstance(a, dict): continue
        dur = _to_seconds(a.get("duration_s") or a.get("animation_duration") or a.get("duration"))
        it  = _to_float(a.get("iteration_count") or a.get("animation_iteration_count"))
        infinite = False
        if isinstance(it, float):
            infinite = it <= 0 or it > 1000  # heurístico
        elif _lower(a.get("iteration_count") or "") in ("infinite","inf","-1"):
            infinite = True
        out.append({
            "type": "animation",
            "source": "animations",
            "auto_starts": _bool(a.get("auto_starts")) or True,
            "indefinite": infinite or (dur is not None and dur > FIVE_SECONDS and (it is None or it >= 2)),
            "duration_s": dur,
            "can_pause": _bool(a.get("can_pause")),
            "can_stop": _bool(a.get("can_stop")),
            "can_hide": _bool(a.get("can_hide")),
            "essential": _bool(a.get("essential")),
            "real_time": _bool(a.get("real_time")),
            "parallel_content": True,
            "selector": _s(a.get("selector") or a.get("id")),
            "snippet": _s(a.get("text") or a.get("label")),
        })

    for src in ("moving_banners","tickers","carousels","sliders","auto_advance_components"):
        for it in _as_list(getattr(ctx, src, [])):
            if not isinstance(it, dict): continue
            interval = _to_seconds(it.get("interval_ms") or it.get("interval"))
            out.append({
                "type": "moving" if src != "auto_advance_components" else _lower(it.get("type") or "auto_advance"),
                "source": src,
                "auto_starts": _bool(it.get("auto_start")) or _bool(it.get("auto")) or True,
                "indefinite": True,  # carruseles/auto-advance suelen ser indefinidos
                "duration_s": interval,
                "can_pause": _bool(it.get("can_pause")) or _bool(it.get("can_stop")),
                "can_stop": _bool(it.get("can_stop")),
                "can_hide": _bool(it.get("can_hide")),
                "essential": _bool(it.get("essential")),
                "real_time": _bool(it.get("real_time")),
                "parallel_content": True,
                "selector": _s(it.get("selector") or it.get("id")),
                "snippet": _s(it.get("label") or it.get("aria-label") or it.get("heading")),
            })

    for up in _as_list(getattr(ctx, "auto_updates", [])):
        if not isinstance(up, dict): continue
        freq = _to_seconds(up.get("update_interval") or up.get("interval"))
        out.append({
            "type": "auto_update",
            "source": "auto_updates",
            "auto_starts": True,
            "indefinite": True,
            "duration_s": freq,
            "can_pause": _bool(up.get("can_pause")),
            "can_stop": _bool(up.get("can_stop")),
            "can_hide": _bool(up.get("can_hide")),
            "can_adjust_frequency": _bool(up.get("can_adjust_frequency")),
            "essential": _bool(up.get("essential")),
            "real_time": _bool(up.get("real_time")),
            "parallel_content": True,
            "selector": _s(up.get("selector") or up.get("id")),
            "snippet": _s(up.get("label") or up.get("aria-label") or up.get("heading")),
        })

    return out

def _collect_class_hints(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Heurístico: elementos con clases estilo 'ticker', 'carousel', 'animate', etc.
    Útil cuando no hay listas específicas.
    """
    out: List[Dict[str, Any]] = []
    for coll in ("widgets","custom_components","banners","headers","sections","cards"):
        for n in _as_list(getattr(ctx, coll, [])):
            if not isinstance(n, dict): continue
            cls = _lower(n.get("class"))
            if any(h in cls for h in MOVE_HINT_CLASSES):
                out.append({
                    "type": "moving",
                    "source": f"class_hint:{coll}",
                    "auto_starts": True,
                    "indefinite": True,
                    "duration_s": None,
                    "can_pause": _bool(n.get("can_pause")),
                    "can_stop": _bool(n.get("can_stop")),
                    "can_hide": _bool(n.get("can_hide")),
                    "essential": _bool(n.get("essential")),
                    "real_time": _bool(n.get("real_time")),
                    "parallel_content": True,
                    "selector": _s(n.get("selector") or n.get("id")),
                    "snippet": _s(n.get("text") or n.get("label") or n.get("aria-label")),
                })
    return out

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    cands.extend(_collect_html_tag_candidates(ctx))
    cands.extend(_collect_from_ctx_lists(ctx))
    cands.extend(_collect_class_hints(ctx))
    return cands

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _is_applicable(item: Dict[str, Any]) -> bool:
    """
    Aplica si:
      - arranca automáticamente,
      - se mueve/parpadea/desplaza o se auto-actualiza,
      - dura >5s o es indefinido,
      - y se muestra en paralelo con otro contenido (heurístico = True).
    Excepciones: esencial, tiempo real.
    """
    if _bool(item.get("essential")) or _bool(item.get("real_time")):
        return False
    auto = _bool(item.get("auto_starts")) or True
    moving_like = _lower(item.get("type")) in ("animation","moving","scrolling","blinking","animated_image","auto_update","auto_advance")
    if not moving_like:
        return False
    dur = _to_seconds(item.get("duration_s"))
    lasts_long = bool(item.get("indefinite")) or (isinstance(dur, (int, float)) and dur > FIVE_SECONDS)
    parallel = bool(item.get("parallel_content")) or True
    return auto and lasts_long and parallel

def _has_mechanism(item: Dict[str, Any]) -> bool:
    """
    Cumple si hay mecanismo para:
      - 'moving/blinking/scrolling': pausar O detener O ocultar
      - 'auto_update': pausar O detener O controlar frecuencia
    """
    typ = _lower(item.get("type"))
    can_pause = _bool(item.get("can_pause"))
    can_stop  = _bool(item.get("can_stop"))
    can_hide  = _bool(item.get("can_hide"))
    can_adj   = _bool(item.get("can_adjust_frequency"))
    if typ == "auto_update":
        return can_pause or can_stop or can_adj
    return can_pause or can_stop or can_hide

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: identifica candidatos y marca violación si (aplicable) y no hay mecanismo
    para pausar/detener/ocultar (o ajustar frecuencia para auto-actualizaciones).
    """
    items = _collect_candidates(ctx)

    examined = len(items)
    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []
    types_count: Dict[str, int] = {}

    for it in items:
        typ = _lower(it.get("type") or "moving")
        types_count[typ] = types_count.get(typ, 0) + 1

        if not _is_applicable(it):
            continue
        applicable += 1

        if _has_mechanism(it):
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "type": typ,
                "source": it.get("source"),
                "selector": it.get("selector"),
                "snippet": (it.get("snippet") or "")[:160],
                "reason": "Contenido en movimiento/parpadeo/desplazamiento/auto-actualización >5s sin mecanismo de pausar/detener/ocultar (o ajustar frecuencia)."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "items_examined": examined,
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "types_count": types_count,
        "note": (
            "RAW: 2.2.2 exige mecanismo para pausar/detener/ocultar contenido que se mueve/parpadea/desplaza "
            "y dura >5s (o para auto-actualizaciones, pausar/detener/ajustar frecuencia). Excepciones: esencial o tiempo real."
        )
    }
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
        details["note"] += " | NA: no se detectaron contenidos en movimiento/parpadeo/desplazamiento/auto-actualización aplicables."
    return details

# -------------------------------------------------------------------
# RENDERED (prueba real)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED el extractor puede exponer:
      rctx.pause_stop_hide_test = [
        {
          "type": "moving|blinking|scrolling|auto_update|animation|auto_advance",
          "selector": str,
          "auto_starts": bool,
          "observed_duration_s": number | None,   # si se midió
          "indefinite": bool,
          "parallel_content": bool,
          "essential": bool,
          "real_time": bool,
          "controls": { "pause": bool, "stop": bool, "hide": bool, "adjust_frequency": bool },
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.2.2; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "pause_stop_hide_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'pause_stop_hide_test'.").strip()
        # ➜ NA si tampoco hubo aplicables en RAW
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
            d["note"] += " | RENDERED→NA: sin ítems aplicables."
        return d

    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue
        typ = _lower(t.get("type") or "moving")
        if _bool(t.get("essential")) or _bool(t.get("real_time")):
            continue

        auto = _bool(t.get("auto_starts"))
        dur  = _to_seconds(t.get("observed_duration_s"))
        indefinite = _bool(t.get("indefinite"))
        parallel = bool(t.get("parallel_content"))

        lasts_long = indefinite or (isinstance(dur, (int, float)) and dur > FIVE_SECONDS)

        if not (auto and lasts_long and parallel):
            continue

        applicable += 1

        ctrl = t.get("controls") or {}
        can_pause = _bool(ctrl.get("pause"))
        can_stop  = _bool(ctrl.get("stop"))
        can_hide  = _bool(ctrl.get("hide"))
        can_adj   = _bool(ctrl.get("adjust_frequency"))

        has_mech = (can_pause or can_stop or can_hide) if typ != "auto_update" else (can_pause or can_stop or can_adj)

        if has_mech:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "type": typ,
                "selector": _s(t.get("selector")),
                "reason": "En ejecución: sin mecanismo de pausar/detener/ocultar (o ajustar frecuencia para auto-actualizaciones).",
                "observed_duration_s": dur,
                "indefinite": bool(indefinite)
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de duración y existencia de controles.").strip()
    })
    if applicable == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] += " | RENDERED→NA: sin ítems aplicables."
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere soluciones: añadir botón Pausa/Detener/Ocultar, detener auto-advance,
    hacer accesible vía teclado, y permitir ajustar frecuencia en auto-actualizaciones.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offs = details.get("offenders", []) or []
    if not offs and (details.get("violations", 0) or 0) == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "types_count": details.get("types_count", {}),
        },
        "offenders": offs[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.2.2 (Pause, Stop, Hide, A). "
        "Para cada offender, sugiere fixes prácticos: "
        "- Añadir controles visibles y operables por teclado para Pausar/Detener/Ocultar; "
        "- Para auto-actualizaciones, permitir Pausa/Detener o ajustar la frecuencia; "
        "- Asegurar que los controles son alcanzables (tabindex, role='button', Enter/Espacio); "
        "- Evitar animaciones indefinidas sin controles; "
        "- No depender solo de hover para pausar. "
        "Devuelve JSON: { suggestions: [{type, selector?, reason, html_fix?, js_fix?, aria_fix?, keyboard_support?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_2_2(
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

    is_na = bool(details.get("na")) or int(details.get("applicable", 0) or 0) == 0
    if is_na:
        details["na"] = True
        if details.get("ok_ratio") == 1:
            details["ok_ratio"] = None
        details["note"] = (details.get("note","") + " | NA: sin ítems aplicables para 2.2.2.").strip()

        verdict = verdict_from_counts(details, True)  # 'passed' irrelevante en NA
        score0 = score_from_verdict(verdict)
        meta = WCAG_META.get(CODE, {})
        return CriterionOutcome(
            code=CODE,
            passed=False,  # irrelevante en NA
            verdict=verdict,
            score_0_2=score0,
            details=details,
            level=meta.get("level", "A"),
            principle=meta.get("principle", "Operable"),
            title=meta.get("title", "Pausar, detener, ocultar"),
            source=src,
            score_hint=details.get("ok_ratio"),
            manual_required=False
        )
    
    # 3) passed / verdict / score
    passed = (int(details.get("violations", 0) or 0) == 0) or (int(details.get("applicable", 0) or 0) == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "A"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Pausar, detener, ocultar"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
