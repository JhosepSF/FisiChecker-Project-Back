# audits/checks/criteria/p2/c_2_2_4_interruptions.py
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

CODE = "2.2.4"

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

# Pistas de nombres/clases típicas de interrupciones
INTERRUPTIVE_CLASS_HINTS = (
    "modal","dialog","drawer","offcanvas","popover","popup","overlay",
    "toast","snackbar","notification","banner","interstitial",
    "newsletter","subscribe","chat-widget","support-widget","cookie-banner"
)

# -------------------------------------------------------------------
# Candidatos (RAW)
# -------------------------------------------------------------------

def _collect_from_ctx_lists(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Preferimos listas explícitas si tu extractor las expone:
      - interruptions / notifications / toasts / snackbars / banners / dialogs / modals / overlays / interstitials / chat_widgets / cookie_banners
    Cada item idealmente con flags:
      { auto_show, time_to_show_s, can_dismiss, can_snooze, can_disable, essential, emergency }
    """
    out: List[Dict[str, Any]] = []
    sources = (
        "interruptions","notifications","toasts","snackbars","banners",
        "dialogs","modals","overlays","interstitials","chat_widgets","cookie_banners"
    )
    for src in sources:
        for it in _as_list(getattr(ctx, src, [])):
            if not isinstance(it, dict):
                continue
            nn = dict(it)
            nn["__source"] = src
            out.append(nn)
    return out

def _collect_from_class_hints(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Heurística a partir de widgets/componentes con clases características
    cuando no existen listas específicas del extractor.
    """
    out: List[Dict[str, Any]] = []
    for coll in ("widgets","custom_components","banners","headers","sections","cards","panels","popups"):
        for n in _as_list(getattr(ctx, coll, [])):
            if not isinstance(n, dict):
                continue
            cls = _lower(n.get("class"))
            if any(h in cls for h in INTERRUPTIVE_CLASS_HINTS):
                out.append({
                    "__source": f"class_hint:{coll}",
                    "selector": _s(n.get("selector") or n.get("id")),
                    "label": _s(n.get("label") or n.get("aria-label") or n.get("heading") or n.get("text")),
                    "auto_show": True,            # heurístico: suelen auto-emerger
                    "time_to_show_s": None,
                    "can_dismiss": _bool(n.get("can_dismiss")),
                    "can_snooze": _bool(n.get("can_snooze")),
                    "can_disable": _bool(n.get("can_disable")),
                    "essential": _bool(n.get("essential")),
                    "emergency": _bool(n.get("emergency")),
                })
    return out

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    cands.extend(_collect_from_ctx_lists(ctx))
    cands.extend(_collect_from_class_hints(ctx))
    return cands

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _is_applicable_interruption(it: Dict[str, Any]) -> bool:
    """
    Aplica si es una interrupción (aparece automáticamente) y NO es emergencia.
    WCAG 2.2.4 (AAA): las interrupciones (incluyendo actualizaciones de contenido) pueden posponerse o suprimirse,
    excepto en emergencias. Consideramos 'essential' como no aplicable por asimilación (no estándar, pero útil).
    """
    if _bool(it.get("emergency")):
        return False
    if _bool(it.get("essential")):
        return False
    auto = _bool(it.get("auto_show")) or True  # heurístico (si llegó aquí por hints, suele auto-mostarse)
    return auto

def _has_mechanism_to_delay_or_suppress(it: Dict[str, Any]) -> bool:
    """
    Cumple si hay al menos una opción:
      - posponer (dismiss/snooze), o
      - suprimir (desactivar/mutar/no volver a mostrar)
    """
    can_dismiss = _bool(it.get("can_dismiss"))
    can_snooze  = _bool(it.get("can_snooze"))
    can_disable = _bool(it.get("can_disable")) or _bool(it.get("can_mute")) or _bool(it.get("dont_show_again"))
    return can_dismiss or can_snooze or can_disable

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: identifica interrupciones (modales, notificaciones, banners, toasts, interstitials)
    y marca violación si (aplicable) y no existe mecanismo para posponer (dismiss/snooze)
    o suprimir (desactivar/mute/no volver a mostrar). Emergencias quedan excluidas.
    """
    items = _collect_candidates(ctx)

    examined = len(items)
    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []
    types_count: Dict[str, int] = {}

    for it in items:
        typ = _lower(it.get("type") or it.get("__source") or "interruption")
        types_count[typ] = types_count.get(typ, 0) + 1

        if not _is_applicable_interruption(it):
            continue
        applicable += 1

        if _has_mechanism_to_delay_or_suppress(it):
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "type": typ,
                "source": it.get("__source"),
                "selector": it.get("selector"),
                "label": _s(it.get("label") or it.get("title") or it.get("aria-label")),
                "reason": "Interrupción sin mecanismo para posponer (dismiss/snooze) o suprimir (desactivar/mute)."
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
            "RAW: 2.2.4 (AAA) exige que las interrupciones puedan posponerse o suprimirse, salvo emergencias. "
            "Se consideran interrupciones: modales automáticos, toasts/snackbars, banners, popovers intersticiales, widgets de chat, etc."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (verificación en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED tu extractor puede exponer:
      rctx.interruptions_test = [
        {
          "type": "modal|toast|snackbar|banner|notification|interstitial|popup|chat_widget|cookie_banner|other",
          "selector": str,
          "auto_show": bool,                 # aparece sin interacción
          "time_to_show_s": number | None,   # segundos hasta emerger
          "has_dismiss": bool,               # botón/acción cerrar que no reaparece inmediatamente
          "has_snooze": bool,                # 'recordarme luego', 'posponer'
          "has_disable": bool,               # 'no volver a mostrar', 'silenciar'
          "emergency": bool,
          "essential": bool,
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.2.4; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "interruptions_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'interruptions_test'.").strip()
        return d

    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue

        if _bool(t.get("emergency")) or _bool(t.get("essential")):
            continue

        auto = _bool(t.get("auto_show"))
        if not auto:
            continue

        applicable += 1

        has_mech = _bool(t.get("has_dismiss")) or _bool(t.get("has_snooze")) or _bool(t.get("has_disable"))

        if has_mech:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "type": _lower(t.get("type") or "interruption"),
                "selector": _s(t.get("selector")),
                "time_to_show_s": _to_seconds(t.get("time_to_show_s")),
                "reason": "En ejecución: interrupción automática sin opción de posponer (dismiss/snooze) ni suprimir (desactivar/mute)."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de auto-aparición y mecanismos de posponer/suprimir.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere medidas para permitir posponer/suprimir interrupciones:
      - Añadir botón Cerrar (dismiss) y 'Recordar más tarde' (snooze).
      - Preferencia 'No volver a mostrar' o 'Silenciar notificaciones'.
      - No robar foco ni atrapar el foco; permitir continuar la tarea sin bloquear.
      - Para banners/cookies/newsletters: cierre accesible por teclado, y opción de no re-aparecer.
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
        "Eres auditor WCAG 2.2.4 (Interruptions, AAA). "
        "Para cada offender, sugiere mecanismos para posponer o suprimir: "
        "- Botón Cerrar (dismiss) y opción Posponer (snooze); "
        "- Preferencia 'No volver a mostrar' / 'Silenciar'; "
        "- No atrapar foco; permitir continuar tarea; "
        "- Accesible por teclado. "
        "Devuelve JSON: { suggestions: [{type, selector?, reason, ui_fix?, js_fix?, aria_fix?, keyboard_support?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_2_4(
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
                               note_suffix="no se detectaron interrupciones automáticas aplicables")

    # 4) passed / verdict / score (si NA no otorgamos PASS, mantenemos passed False)
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
        title=meta.get("title", "Interrupciones"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
