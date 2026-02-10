# audits/checks/criteria/p2/c_2_2_5_re_authenticating.py
from typing import Dict, Any, List, Optional, Tuple

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict
from ..applicability import ensure_na_if_no_applicable, normalize_pass_for_applicable

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.2.5"

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

# -------------------------------------------------------------------
# Qué exige 2.2.5 (AAA)
# -------------------------------------------------------------------
# Si una sesión autenticada expira durante una actividad del usuario, al volver a autenticarse
# el usuario puede continuar sin pérdida de datos. (No basta con volver al inicio.)
# Ejemplos de cumplimiento:
#   - Modal inline de re-login que conserva el DOM/estado y devuelve al mismo paso.
#   - Autosave (borradores) y restauración automática tras reautenticación.
#   - Redirección a login + returnURL + restauración (ej. re-hidratar campos del formulario).
#
# Violación típica:
#   - Expira sesión, redirige a login y tras autenticarse se pierde todo lo que el usuario hacía
#     (campos, paso del wizard, selección en carrito, etc.).

# -------------------------------------------------------------------
# Recolección de candidatos (RAW)
# -------------------------------------------------------------------

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Preferimos estructuras explícitas del extractor si existen:
      - session_timeout: { seconds?, essential?, real_time?, ... }
      - reauth_policies: [{ preserves_data_on_reauth, returns_same_step, autosave_draft, restore_draft_available, inline_reauth_modal }]
      - protected_routes / auth_required_sections
      - forms / wizards / carts con 'is_critical_flow'
    Si no existen, inferimos aplicabilidad por la presencia de 'session_timeout' + flujos críticos.
    """
    items: List[Dict[str, Any]] = []

    st = getattr(ctx, "session_timeout", None)
    if isinstance(st, dict):
        items.append({
            "__source": "session_timeout",
            "type": "session_timeout",
            "seconds": st.get("seconds"),
            "essential": _bool(st.get("essential")),
            "real_time": _bool(st.get("real_time")),
            # Señales de cumplimiento si el extractor las detecta:
            "has_warning": _bool(st.get("has_warning")),
            "can_extend": _bool(st.get("can_extend")),
            # Metas de 2.2.5 (no obligatorias en 2.2.1, pero sí aquí):
            "preserves_data_on_reauth": _bool(st.get("preserves_data_on_reauth")),
            "returns_same_step": _bool(st.get("returns_same_step")),
            "autosave_draft": _bool(st.get("autosave_draft")),
            "restore_draft_available": _bool(st.get("restore_draft_available")),
            "inline_reauth_modal": _bool(st.get("inline_reauth_modal")),
        })

    for pol in _as_list(getattr(ctx, "reauth_policies", [])):
        if isinstance(pol, dict):
            it = dict(pol)
            it["__source"] = "reauth_policies"
            items.append(it)

    # Señales de que hay tareas críticas que podrían perderse
    critical_hits = 0
    for coll in ("forms","wizards","carts","checkouts","profile_edit","backoffice_tools"):
        lst = _as_list(getattr(ctx, coll, []))
        for it in lst:
            if not isinstance(it, dict):
                continue
            if _bool(it.get("is_critical_flow")) or _bool(it.get("requires_auth")):
                critical_hits += 1

    # Si no hay ítems, pero sí crítica + timeout → añade candidato genérico
    if not items and critical_hits > 0 and isinstance(st, dict):
        items.append({
            "__source": "inferred",
            "type": "session_timeout",
            "preserves_data_on_reauth": False,  # desconocido → tratamos como False conservador en RAW
            "returns_same_step": False,
            "autosave_draft": False,
            "restore_draft_available": False,
            "inline_reauth_modal": False,
        })

    return items

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _assess_item(it: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    """
    Devuelve (aplicable, cumple, reasons[]).
    Aplicable si existe expiración de sesión *y* hay tareas/flujo que pueden perder datos.
    Cumple si:
      - preserves_data_on_reauth OR returns_same_step, o
      - autosave_draft AND restore_draft_available, o
      - inline_reauth_modal (mantiene estado/DOM y devuelve foco al invocador)
    """
    reasons: List[str] = []

    # Determinar aplicabilidad
    typ = _lower(it.get("type") or "")
    if typ != "session_timeout":
        # Políticas explícitas también aplican si se refieren a reautenticación
        if not any(k in it for k in ("preserves_data_on_reauth","returns_same_step","autosave_draft","restore_draft_available","inline_reauth_modal")):
            return False, True, ["No se detecta caso de reautenticación aplicable."]

    applicable = True  # si entró aquí con banderas de reauth / timeout, lo consideramos aplicable

    preserves = _bool(it.get("preserves_data_on_reauth"))
    same_step = _bool(it.get("returns_same_step"))
    autosave = _bool(it.get("autosave_draft"))
    restore  = _bool(it.get("restore_draft_available"))
    inline   = _bool(it.get("inline_reauth_modal"))

    # Criterios de cumplimiento
    if preserves or same_step or (autosave and restore) or inline:
        return applicable, True, ["Reautenticación conserva datos/estado o restaura borrador y vuelve al mismo paso."]

    return applicable, False, ["Tras reautenticación no se garantiza preservación/restauración del estado/datos."]

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: si hay expiración de sesión, el sitio debe permitir reautenticación sin pérdida de datos ni estado
    (mismo paso). Señales de cumplimiento: modal inline, autosave + restore, returnURL con rehidratación, etc.
    """
    items = _collect_candidates(ctx)

    examined = len(items)
    applicable = 0
    compliant = 0
    violations = 0
    unknown = 0

    offenders: List[Dict[str, Any]] = []

    if examined == 0:
        # Sin datos para afirmar que hay expiración → no aplicable (NA)
        return {
            "items_examined": 0,
            "applicable": 0,
            "compliant": 0,
            "violations": 0,
            "unknown": 0,
            "ok_ratio": 1.0,
            "offenders": [],
            "note": "RAW: No se detectó expiración de sesión ni políticas de reautenticación; 2.2.5 no aplica."
        }

    for it in items:
        applicable_t, ok_t, reasons = _assess_item(it)
        if not applicable_t:
            unknown += 1
            continue
        applicable += 1
        if ok_t:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "source": it.get("__source"),
                "type": _lower(it.get("type") or "session_timeout"),
                "preserves_data_on_reauth": _bool(it.get("preserves_data_on_reauth")),
                "returns_same_step": _bool(it.get("returns_same_step")),
                "autosave_draft": _bool(it.get("autosave_draft")),
                "restore_draft_available": _bool(it.get("restore_draft_available")),
                "inline_reauth_modal": _bool(it.get("inline_reauth_modal")),
                "reason": "; ".join(reasons)
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "items_examined": examined,
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "unknown": unknown,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.2.5 (AAA) exige que, si expira la sesión, al reautenticar el usuario pueda continuar "
            "sin perder datos ni estado (mismo paso). Se consideran soluciones: modal inline de re-login, "
            "autosave + restore, o restauración tras returnURL con rehidratación de datos."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (verificación en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer:
      rctx.reauth_test = [
        {
          "flow": "checkout|wizard|profile|form|other",
          "after_timeout_redirected_to_login": bool,
          "reauth_performed": bool,
          "restored_form_values": bool,
          "returned_to_same_step": bool,
          "draft_restored": bool,
          "lost_unsaved_data": bool,
          "inline_reauth_modal": bool,
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.2.5; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "reauth_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'reauth_test'.").strip()
        return d

    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue

        # Aplicable si realmente hubo reautenticación (o intento tras timeout)
        if not (_bool(t.get("after_timeout_redirected_to_login")) or _bool(t.get("inline_reauth_modal"))):
            continue

        applicable += 1

        restored = _bool(t.get("restored_form_values")) or _bool(t.get("draft_restored"))
        same_step = _bool(t.get("returned_to_same_step"))
        inline = _bool(t.get("inline_reauth_modal"))
        lost = _bool(t.get("lost_unsaved_data"))

        if (restored or same_step or inline) and not lost:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "flow": _s(t.get("flow")),
                "reason": "En ejecución: tras reautenticación no se restauró estado/datos o se perdió información.",
                "observed": {
                    "restored_form_values": bool(t.get("restored_form_values")),
                    "draft_restored": bool(t.get("draft_restored")),
                    "returned_to_same_step": bool(t.get("returned_to_same_step")),
                    "lost_unsaved_data": bool(t.get("lost_unsaved_data")),
                    "inline_reauth_modal": bool(t.get("inline_reauth_modal")),
                }
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de restauración de datos/estado y continuidad del flujo.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere estrategias para cumplir 2.2.5:
      - Modal inline de reautenticación que conserve DOM/estado y devuelva el foco al disparador.
      - Autosave periódico (server-side) + restauración al reingresar (o localStorage cifrado + submit tras login).
      - ReturnURL + rehidratación de formulario (incluye archivos si aplica, p. ej., referencias a uploads en staging).
      - Mantener 'wizard step' en URL/estado y reabrir el mismo paso post-login.
      - Evitar pérdida de carrito/ediciones/selecciones; persistir en sesión/DB.
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
        },
        "offenders": offs[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.2.5 (Re-authenticating, AAA). "
        "Para cada offender, propone soluciones concretas: "
        "- Reautenticación inline (modal) conservando el estado y devolviendo foco; "
        "- Autosave de formularios y restauración tras login; "
        "- Uso de returnURL + rehidratación del formulario/paso; "
        "- Persistir carrito/ediciones/selecciones en servidor; "
        "- Evitar pérdida de datos al expirar la sesión. "
        "Devuelve JSON: { suggestions: [{target?, reason, ui_fix?, js_fix?, server_fix?, persistence_strategy?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_2_5(
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
                               note_suffix="no se detectaron expiraciones de sesión o escenarios de reautenticación aplicables")

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
        title=meta.get("title", "Reautenticación"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
