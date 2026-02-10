# audits/checks/criteria/p2/c_2_2_1_timing_adjustable.py
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

CODE = "2.2.1"

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
    Convierte duraciones simples a segundos.
    Acepta: números (se interpretan como segundos), '5s', '3m', '2h', '120000ms'
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _lower(v)
    if s == "":
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)?\s*$", s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or "s"
    if unit == "ms":
        return num / 1000.0
    if unit == "s":
        return num
    if unit == "m":
        return num * 60.0
    if unit == "h":
        return num * 3600.0
    return None

# Meta refresh: content="5; url=/foo"
META_REFRESH_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:;.*)?$", re.I)
COUNTDOWN_HINTS = ("countdown","timer","tiempo restante","time left","session expires","expira en","timeout")
AUTOPLAY_HINTS = ("autoplay","auto-play","auto advance","auto-advance","auto_slide","carousel","slider")

TWENTY_HOURS = 20 * 3600.0  # excepción de 20h

# -------------------------------------------------------------------
# Recolección (RAW)
# -------------------------------------------------------------------

def _extract_meta_refresh(ctx: PageContext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return out
    try:
        metas = soup.find_all("meta", attrs={"http-equiv": re.compile(r"refresh", re.I)})
    except Exception:
        metas = []
    for m in metas:
        try:
            content = (m.get("content") or "").strip()
            mm = META_REFRESH_RE.match(content)
            if mm:
                sec = float(mm.group(1))
                out.append({
                    "type": "meta_refresh",
                    "seconds": sec,
                    "can_turn_off": False,
                    "can_adjust": False,
                    "can_extend": False,
                    "has_warning": False,
                    "warn_seconds": None,
                    "essential": False,
                    "real_time": False,
                    "twenty_hours": sec >= TWENTY_HOURS,
                    "source": "meta",
                })
        except Exception:
            continue
    return out

def _collect_declared_timers(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Usa colecciones opcionales del extractor si existen.
    Esperados (opcionales):
      - ctx.timers: [{type, seconds, can_turn_off, can_adjust, can_extend, has_warning, warn_seconds, essential, real_time}]
      - ctx.session_timeout: {seconds, has_warning, warn_seconds, can_extend}
      - ctx.auto_advance_components: [{type:'carousel', interval_ms, can_pause, can_stop, can_adjust}]
      - ctx.countdown_widgets: [{seconds, can_extend, has_warning, warn_seconds}]
    """
    out: List[Dict[str, Any]] = []

    for t in _as_list(getattr(ctx, "timers", [])):
        if isinstance(t, dict):
            sec = _to_seconds(t.get("seconds"))
            out.append({
                "type": _lower(t.get("type") or "timer"),
                "seconds": sec,
                "can_turn_off": _bool(t.get("can_turn_off")),
                "can_adjust": _bool(t.get("can_adjust")),
                "can_extend": _bool(t.get("can_extend")),
                "has_warning": _bool(t.get("has_warning")),
                "warn_seconds": _to_seconds(t.get("warn_seconds")),
                "essential": _bool(t.get("essential")),
                "real_time": _bool(t.get("real_time")),
                "twenty_hours": (sec or 0) >= TWENTY_HOURS if sec is not None else False,
                "source": "timers",
            })

    st = getattr(ctx, "session_timeout", None)
    if isinstance(st, dict):
        sec = _to_seconds(st.get("seconds"))
        out.append({
            "type": "session_timeout",
            "seconds": sec,
            "can_turn_off": False,
            "can_adjust": False,
            "can_extend": _bool(st.get("can_extend")) or _bool(st.get("extend_available")),
            "has_warning": _bool(st.get("has_warning")) or True,  # muchos frameworks muestran aviso
            "warn_seconds": _to_seconds(st.get("warn_seconds")) or 20.0,
            "essential": False,
            "real_time": False,
            "twenty_hours": (sec or 0) >= TWENTY_HOURS if sec is not None else False,
            "source": "session_timeout",
        })

    for comp in _as_list(getattr(ctx, "auto_advance_components", [])):
        if isinstance(comp, dict):
            sec = _to_seconds(comp.get("interval_ms") or comp.get("interval"))
            out.append({
                "type": _lower(comp.get("type") or "auto_advance"),
                "seconds": sec,
                "can_turn_off": _bool(comp.get("can_stop")) or _bool(comp.get("can_pause")),
                "can_adjust": _bool(comp.get("can_adjust")),
                "can_extend": _bool(comp.get("can_extend")) or _bool(comp.get("can_pause")),
                "has_warning": False,
                "warn_seconds": None,
                "essential": False,
                "real_time": False,
                "twenty_hours": (sec or 0) >= TWENTY_HOURS if sec is not None else False,
                "source": "auto_advance_components",
            })

    for w in _as_list(getattr(ctx, "countdown_widgets", [])):
        if isinstance(w, dict):
            sec = _to_seconds(w.get("seconds"))
            out.append({
                "type": "countdown",
                "seconds": sec,
                "can_turn_off": False,
                "can_adjust": _bool(w.get("can_adjust")),
                "can_extend": _bool(w.get("can_extend")),
                "has_warning": _bool(w.get("has_warning")),
                "warn_seconds": _to_seconds(w.get("warn_seconds")),
                "essential": _bool(w.get("essential")),
                "real_time": _bool(w.get("real_time")),
                "twenty_hours": (sec or 0) >= TWENTY_HOURS if sec is not None else False,
                "source": "countdown_widgets",
            })

    return out

def _collect_from_text(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Heurística a partir de texto visible: “expira en 2:00”, “tiempo restante 30s”, etc.
    """
    out: List[Dict[str, Any]] = []
    txt = _lower(getattr(ctx, "page_text", "") or getattr(ctx, "title_text", ""))
    if not txt and getattr(ctx, "soup", None) is not None:
        try:
            txt = _lower(getattr(ctx, "soup").get_text())
        except Exception:
            txt = ""
    if any(h in txt for h in COUNTDOWN_HINTS):
        out.append({
            "type": "text_countdown_hint",
            "seconds": None,
            "can_turn_off": False,
            "can_adjust": False,
            "can_extend": False,
            "has_warning": False,
            "warn_seconds": None,
            "essential": False,
            "real_time": False,
            "twenty_hours": False,
            "source": "page_text",
            "hint": "Detectado texto que sugiere límite de tiempo."
        })
    return out

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    cands.extend(_extract_meta_refresh(ctx))
    cands.extend(_collect_declared_timers(ctx))
    cands.extend(_collect_from_text(ctx))
    return cands

# -------------------------------------------------------------------
# Evaluación de cumplimiento (RAW)
# -------------------------------------------------------------------

def _assess_timer(t: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    """
    Devuelve (aplicable, cumple, reasons[]).
    Regla (2.2.1): si hay límite de tiempo (y no cae en excepciones),
    debe existir al menos una opción: Apagar / Ajustar / Extender (≥10x) o aviso con opción de extender.
    Excepciones: tiempo ≥ 20h, tiempo real (p.ej. subastas en vivo), esencialidad.
    """
    reasons: List[str] = []

    # Determinar si es “tiempo límite” real
    sec = t.get("seconds")
    has_time = isinstance(sec, (int, float)) and sec > 0.0
    # Algunos hints textuales no tienen segundos → tratamos como aplicable “indeterminado”
    is_hint_only = (not has_time) and (t.get("type") == "text_countdown_hint")

    real_time = _bool(t.get("real_time"))
    essential = _bool(t.get("essential"))
    twenty = bool(t.get("twenty_hours"))

    if (not has_time) and (not is_hint_only):
        # No hay tiempo concreto → no aplicable
        return False, True, ["No se detectó límite de tiempo concreto."]

    # Excepciones
    if real_time:
        return True, True, ["Excepción: evento de tiempo real."]
    if essential:
        return True, True, ["Excepción: el límite de tiempo es esencial."]
    if twenty:
        return True, True, ["Excepción: límite de tiempo ≥ 20 horas."]

    # Comprobación de opciones A/B/C
    can_off = _bool(t.get("can_turn_off"))
    can_adj = _bool(t.get("can_adjust"))
    can_ext = _bool(t.get("can_extend"))
    has_warn = _bool(t.get("has_warning"))
    warn_sec = t.get("warn_seconds")
    has_warn_adequate = has_warn and (isinstance(warn_sec, (int, float)) and warn_sec >= 20.0)

    if can_off or can_adj or can_ext or has_warn_adequate:
        return True, True, ["Hay mecanismo para apagar/ajustar/extender o aviso ≥20s."]

    return True, False, ["No se detectó mecanismo para apagar, ajustar, extender ni aviso ≥20s."]

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: detecta límites de tiempo por meta refresh, timeouts de sesión, componentes con auto-avance y contadores.
    Marca como violación si (aplicable) y no hay forma de apagar/ajustar/extender ni aviso ≥20s, salvo excepciones.
    """
    cands = _collect_candidates(ctx)

    examined = len(cands)
    applicable = 0
    compliant = 0
    violations = 0

    offenders: List[Dict[str, Any]] = []
    types_count: Dict[str, int] = {}

    for t in cands:
        typ = _lower(t.get("type") or "timer")
        types_count[typ] = types_count.get(typ, 0) + 1

        applicable_t, ok_t, reasons = _assess_timer(t)
        if not applicable_t:
            continue
        applicable += 1
        if ok_t:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "type": typ,
                "seconds": t.get("seconds"),
                "source": t.get("source"),
                "reasons": reasons
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "timers_examined": examined,
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "types_count": types_count,
        "note": (
            "RAW: 2.2.1 exige opciones para límites de tiempo (apagar, ajustar o extender ≥10x) o avisar con ≥20s para extender. "
            "Excepciones: eventos en tiempo real, esenciales o ≥20h. Detectamos meta refresh, timeouts de sesión, auto-avance y contadores."
        )
    }
    
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
        details["note"] += " | NA: no se detectaron límites de tiempo aplicables."
    
    return details

# -------------------------------------------------------------------
# RENDERED (prueba real en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer:
      rctx.timing_test = [
        {
          "type": "session_timeout|meta_refresh|auto_advance|countdown|quiz_timer|other",
          "seconds": number,                    # duración detectada
          "can_turn_off": bool,
          "can_adjust": bool,
          "can_extend": bool,
          "has_warning": bool,
          "warn_seconds": number,               # ≥20s
          "real_time": bool,
          "essential": bool,
          "twenty_hours": bool,
          "observed_redirect_or_expire": bool,  # se observó expiración/redirect real
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.2.1; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "timing_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'timing_test'.").strip()
        # ➜ si tampoco hay aplicables (según RAW), es NA
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
            d["note"] += " | RENDERED→NA: sin límites de tiempo que evaluar."
        return d

    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue
        # Reusa evaluación, pero dando prioridad a lo observado
        t2 = dict(t)
        typ = _lower(t2.get("type") or "timer")
        applicable_t, ok_t, reasons = _assess_timer(t2)

        ws_val = _to_seconds(t2.get("warn_seconds"))
        observed_fail = bool(t2.get("observed_redirect_or_expire")) and not (
            _bool(t2.get("can_turn_off")) or _bool(t2.get("can_adjust")) or _bool(t2.get("can_extend")) or
            (_bool(t2.get("has_warning")) and (ws_val is not None and ws_val >= 20.0))
        )

        if applicable_t:
            applicable += 1
            if ok_t and not observed_fail:
                compliant += 1
            else:
                violations += 1
                offenders.append({
                    "type": typ,
                    "seconds": t2.get("seconds"),
                    "observed_redirect_or_expire": bool(t2.get("observed_redirect_or_expire")),
                    "reasons": reasons if not ok_t else ["En ejecución: expiración/redirección sin opción de extender/ajustar/apagar."]
                })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de expiraciones/redirecciones y opciones de extensión.").strip()
    })
    
    if applicable == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] += " | RENDERED→NA: sin límites de tiempo aplicables."
        
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere mitigaciones para límites de tiempo:
      - Añadir opción para desactivar/ajustar el límite (settings/checkbox).
      - Mostrar aviso con ≥20s restantes y botón para extender (idealmente varias veces hasta ≥10×).
      - En timeouts de sesión: modal de “¿seguir en la sesión?” que extienda sin perder datos.
      - Evitar meta refresh; usar redirección controlada tras confirmación.
      - Para auto-avance: botón Pausa/Detener y control de intervalo.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs_help = (details.get("violations", 0) or 0) > 0 or len(details.get("offenders", []) or []) > 0
    if not needs_help:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "types_count": details.get("types_count", {}),
        },
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.2.1 (Timing Adjustable, A). "
        "Para cada offender, sugiere soluciones prácticas: "
        "- Configuración para desactivar/ajustar el límite; "
        "- Aviso con ≥20s y botón para extender (posible múltiples veces hasta ≥10× el tiempo original); "
        "- Modal de timeout de sesión que mantenga el estado y extienda; "
        "- Reemplazar meta refresh por confirmación del usuario; "
        "- En auto-avance (carousel/slider), botones Pausa/Detener y control del intervalo. "
        "Devuelve JSON: { suggestions: [{type, reason, ui_fix?, js_fix?, server_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_2_1(
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
        details["note"] = (details.get("note","") + " | NA: sin límites de tiempo aplicables para 2.2.1.").strip()

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
            title=meta.get("title", "Tiempo ajustable"),
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
        title=meta.get("title", "Tiempo ajustable"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
