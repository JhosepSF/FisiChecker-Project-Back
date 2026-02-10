# audits/checks/criteria/p3/c_3_2_5_change_on_request.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.2.5"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

META_REFRESH_RE = re.compile(r'<meta[^>]+http\-equiv\s*=\s*["\']refresh["\'][^>]*>', re.I)
JS_AUTO_NAV_RE  = re.compile(r"(setTimeout|setInterval)\s*\(.*?(location\.(href|assign|replace)|window\.open|history\.(pushState|replaceState))", re.I|re.S)
JS_DIRECT_NAV_RE = re.compile(r"(location\.(href|assign|replace)\s*=|document\.location|window\.open\s*\()", re.I)
AUTO_SUBMIT_RE  = re.compile(r"\.submit\s*\(", re.I)

WARNING_TEXT_RE = re.compile(
    r"(se\s+actualizar[aá]\s+autom[aá]ticamente|redirigir[aá]\s+autom[aá]ticamente|"
    r"auto(\s*|\-)?refresh|auto(\s*|\-)?redirect|auto(\s*|\-)?submit|"
    r"esta\s+p[aá]gina\s+cambiar[aá]\s+sin\s*interacci[oó]n)",
    re.I
)

TOGGLE_TEXT_RE = re.compile(
    r"(detener|parar|pausar|desactivar|apagar|stop|pause|disable)\s+(actualizaci[oó]n|auto|autom[aá]tico|redirect|refresh|cambio)",
    re.I
)

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _get_page_html(ctx: PageContext) -> str:
    # opcional: si tu extractor guarda el HTML
    return _s(getattr(ctx, "html", ""))

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "")  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", "") or "")

def _scripts_text(ctx: PageContext) -> str:
    st = _s(getattr(ctx, "scripts_text", ""))
    if st: return st
    soup = getattr(ctx, "soup", None)
    if soup is None: return ""
    out: List[str] = []
    try:
        for sc in soup.find_all("script"):
            try:
                txt = sc.get_text()  # type: ignore[attr-defined]
                if isinstance(txt, str) and txt.strip():
                    out.append(txt)
            except Exception:
                continue
    except Exception:
        pass
    return "\n".join(out)

def _styles_text(ctx: PageContext) -> str:
    css = _s(getattr(ctx, "stylesheets_text", ""))
    if css: return css
    soup = getattr(ctx, "soup", None)
    if soup is None: return ""
    out: List[str] = []
    try:
        for st in soup.find_all("style"):
            try:
                t = st.get_text()  # type: ignore[attr-defined]
                if isinstance(t, str) and t.strip():
                    out.append(t)
            except Exception:
                continue
    except Exception:
        pass
    return "\n".join(out)

# ------------------------------------------------------------
# RAW (heurístico)
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.2.5 (AAA): Cambios de contexto solo ocurren a petición (no automáticos).
    RAW:
      - Meta refresh → violación.
      - JS que navega/redirect con temporizador → violación.
      - Envíos automáticos sin interacción → violación (heurístico).
      - Si hay aviso claro y control para desactivar/pausar el cambio, se atenúa.
    """
    html = _get_page_html(ctx)
    scripts = _scripts_text(ctx)
    text = _page_text(ctx)

    meta_refresh = bool(META_REFRESH_RE.search(html))
    js_auto_nav  = bool(JS_AUTO_NAV_RE.search(scripts))
    js_direct_nav = bool(JS_DIRECT_NAV_RE.search(scripts))
    auto_submit  = bool(AUTO_SUBMIT_RE.search(scripts))

    has_warning = bool(WARNING_TEXT_RE.search(text))
    has_toggle  = bool(TOGGLE_TEXT_RE.search(text))

    # Contabiliza violaciones
    violations = 0
    offenders: List[Dict[str, Any]] = []

    if meta_refresh:
        violations += 1
        offenders.append({"type":"meta-refresh","reason":"Meta refresh detectado (cambio automático)."})
    if js_auto_nav:
        violations += 1
        offenders.append({"type":"js-auto-nav","reason":"JS con temporizador que navega (cambio automático)."})
    # js_direct_nav podría ser por evento de usuario; lo marcamos como riesgo
    js_risk = js_direct_nav and not has_warning and not has_toggle
    if js_risk:
        violations += 1
        offenders.append({"type":"js-direct-nav","reason":"JS que navega; sin evidencia de control/aviso (heurístico)."})
    if auto_submit and not has_warning:
        violations += 1
        offenders.append({"type":"auto-submit","reason":"Envío automático sin aviso (heurístico)."})
    
    # Si hay control para desactivar y aviso, reduce (pero AAA suele exigir 'solo a petición')
    if has_toggle and has_warning and violations > 0:
        # atenuación: quita una unidad si había múltiples fuentes
        violations = max(0, violations - 1)
        offenders.append({"type":"mitigated","reason":"Existe aviso y control para detener/pausar cambio."})

    applicable = 1  # siempre potencialmente aplicable
    ok_ratio = 1.0 if violations == 0 else 0.0
    details: Dict[str, Any] = {
        "applicable": applicable,
        "meta_refresh": meta_refresh,
        "js_auto_nav": js_auto_nav,
        "js_direct_nav": js_direct_nav,
        "auto_submit": auto_submit,
        "has_warning": has_warning,
        "has_toggle": has_toggle,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: meta refresh, temporizadores que redirigen y auto-submit se consideran cambios automáticos. "
            "Se atenúa si hay aviso y control para desactivar/pausar, aunque AAA pide idealmente 'solo a petición'."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED (observación en ejecución)
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.change_on_request_test = [
      { "type": "navigation|submit|modal|refresh",
        "auto_triggered": bool,      # sucede sin interacción
        "has_user_control": bool,    # existe control para pausar/desactivar
        "has_warning": bool,         # aviso previo claro
        "notes": str|None }
    ]
    Violación si auto_triggered == True y (has_user_control == False o no hay advertencia)
    (AAA es estricto: idealmente NO debe haber auto_triggered; el control/aviso solo mitiga).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.2.5; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "change_on_request_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'change_on_request_test', se reusó RAW."
        return d

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        applicable += 1
        auto = bool(it.get("auto_triggered"))
        has_ctrl = bool(it.get("has_user_control"))
        has_warn = bool(it.get("has_warning"))
        if auto and not (has_ctrl and has_warn):
            violations += 1
            offenders.append({
                "type": _s(it.get("type")),
                "reason": "Cambio automático sin control/aviso suficiente (runtime).",
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    return {
        "rendered": True,
        "applicable": 1 if applicable > 0 else 0,
        "cases_examined": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: observación de cambios automáticos y presencia de control/aviso."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message":"IA no configurada."}
    need = int(details.get("violations", 0) or 0) > 0
    if not need:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:15],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Eliminar <meta http-equiv='refresh'> y mostrar un botón 'Continuar'.",
            "Mover location.assign(...) dentro de un handler de click/submit con confirmación.",
            "Reemplazar autosubmit por <button type='submit'> explícito.",
            "Si el auto-refresh es necesario (p. ej., dashboards), añadir conmutador 'Pausar actualización automática' y guardado de preferencia."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.2.5 (Change on Request, AAA). "
        "Propón cambios concretos para que los cambios de contexto se inicien solo a petición. "
        "Devuelve JSON: { suggestions:[{change, snippet?, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_2_5(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); details["warning"]="Se pidió RENDERED sin rendered_ctx; fallback a RAW."; src="raw"
        else:
            details = _compute_counts_rendered(rendered_ctx); src="rendered"
    else:
        details = _compute_counts_raw(ctx); src="raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai = _ai_review(details, html_sample=html_for_ai); details["ai_info"]=ai; src="ai"
        manual_required = bool(ai.get("manual_required", False))

    violations = int(details.get("violations", 0) or 0)
    passed = (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0  = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AAA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Cambio a petición"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
