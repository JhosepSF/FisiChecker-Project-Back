# audits/checks/criteria/p2/c_2_5_4_motion_actuation.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.5.4"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

# Pistas en JS/DOM de uso de sensores de movimiento/orientación
MOTION_JS_RE = re.compile(
    r"(devicemotion|deviceorientation|gyroscope|accelerometer|AbsoluteOrientationSensor|LinearAccelerationSensor|"
    r"GravitySensor|Magnetometer|AmbientLightSensor|shake\.js|tilt|shake|orientation\s*sensor)",
    re.I,
)

# Pistas textuales visibles (“inclina/sacude/etc.”)
MOTION_TEXT_RE = re.compile(
    r"(inclina|mueve el dispositivo|sacude|agita|gira el dispositivo|tilt|shake|rotate|move your device)",
    re.I,
)

DISABLE_HINTS_RE = re.compile(r"(desactiv(a|ar)|apagar|disable|off|bloquear\s*movimiento|sin\s*movimiento)", re.I)
ALTERNATIVE_HINTS_RE = re.compile(r"(bot[oó]n|button|tocar|tap|clic|click|usar controles|controles)", re.I)

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

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name)
            return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text","label","aria-label","title","inner_text","help_text"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return t.strip()
    except Exception:
        pass
    return ""

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "").strip()  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", "") or "")

def _scripts_text(ctx: PageContext) -> str:
    # Preferir campo del extractor si existe
    st = _s(getattr(ctx, "scripts_text", ""))
    if st:
        return st
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return ""
    out = []
    try:
        for sc in soup.find_all("script"):
            try:
                # .string puede ser None; get_text() recoge contenido
                txt = sc.get_text()  # type: ignore[attr-defined]
                if isinstance(txt, str) and txt.strip():
                    out.append(txt)
            except Exception:
                continue
    except Exception:
        pass
    return "\n".join(out)

def _looks_essential(blob: str) -> bool:
    return bool(re.search(r"(pedometer|podometro|medidor\s*de\s*pasos|juego\s*de\s*equilibrio|"
                          r"app\s*de\s*br[uú]jula|medir\s*orientaci[oó]n|terapia\s*fisioterapia)", blob, flags=re.I))

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.5.4 (A): Si una funcionalidad puede operarse mediante movimiento del dispositivo/usuario,
    también debe poder operarse con componentes de UI, y debe poder desactivarse la respuesta al movimiento.
    Excepción: cuando el movimiento sea esencial.
    """
    # 1) El extractor puede proveer un inventario directo:
    feats = getattr(ctx, "motion_features", None)
    runtime_like = isinstance(feats, dict)

    candidates = 0
    essential_like = 0
    has_ui_alternative = 0
    has_disable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    if runtime_like:
        # forma esperada:
        # { "uses_motion": bool, "items": [{ selector?, essential?, has_ui_alternative?, can_disable? , note? }, ...] }
        items = _as_list(feats.get("items", []))
        for it in items:
            if not isinstance(it, dict):
                continue
            uses = bool(it.get("uses_motion", True))
            if not uses:
                continue
            candidates += 1
            ess = bool(it.get("essential"))
            if ess:
                essential_like += 1
            if bool(it.get("has_ui_alternative")):
                has_ui_alternative += 1
            if bool(it.get("can_disable")):
                has_disable += 1

        # violación si hay candidatos (no esenciales) y falta alternativa y falta “disable”
        non_essential = max(0, candidates - essential_like)
        if non_essential > 0 and (has_ui_alternative == 0 or has_disable == 0):
            violations = 1
            offenders.append({
                "reason": "Se usa movimiento sin alternativa de UI y/o sin opción de desactivar.",
                "summary": {"candidates": candidates, "essential_like": essential_like,
                            "has_ui_alternative": has_ui_alternative, "has_disable": has_disable}
            })

    else:
        # 2) Heurística sobre scripts + texto visible
        scripts = _scripts_text(ctx)
        page_txt = _page_text(ctx)

        uses_motion = bool(MOTION_JS_RE.search(scripts)) or bool(MOTION_TEXT_RE.search(page_txt))
        if uses_motion:
            candidates = 1
            if _looks_essential(page_txt + " " + scripts):
                essential_like = 1

            # pistas de alternativa / disable
            if ALTERNATIVE_HINTS_RE.search(page_txt):
                has_ui_alternative = 1
            if DISABLE_HINTS_RE.search(page_txt):
                has_disable = 1

            non_essential = max(0, candidates - essential_like)
            if non_essential > 0 and (has_ui_alternative == 0 or has_disable == 0):
                violations = 1
                offenders.append({
                    "reason": "Se detectó uso de movimiento sin alternativa/disable claros (heurística).",
                    "evidence": {
                        "motion_text_hit": bool(MOTION_TEXT_RE.search(page_txt)),
                        "motion_js_hit": bool(MOTION_JS_RE.search(scripts))
                    }
                })

    ok_ratio = 1.0 if candidates == 0 else (0.0 if violations > 0 else 1.0)

    details: Dict[str, Any] = {
        "candidates": candidates,
        "essential_like": essential_like,
        "has_ui_alternative": has_ui_alternative,
        "has_disable": has_disable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: detección heurística de uso de movimiento (JS/texto). "
            "La norma exige alternativa de UI y capacidad de desactivar, salvo esencialidad."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede simular sensores:
      rctx.motion_test = [
        { "selector": str, "uses_device_motion": bool, "has_ui_alternative": bool,
          "can_disable": bool, "essential": bool, "notes": str|None }
      ]
    Falla si existe un ítem no esencial con uses_device_motion=True y (no has_ui_alternative o no can_disable).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.5.4; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "motion_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'motion_test', se reusó RAW.").strip()
        return d

    candidates = 0
    essential_like = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict):
            continue
        if not bool(it.get("uses_device_motion")):
            continue
        candidates += 1
        if bool(it.get("essential")):
            essential_like += 1
            continue
        alt = bool(it.get("has_ui_alternative"))
        dis = bool(it.get("can_disable"))

        if not (alt and dis):
            violations += 1
            offenders.append({
                "selector": _s(it.get("selector")),
                "reason": "Movimiento usado sin alternativa de UI y/o sin opción de desactivar (runtime).",
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if candidates == 0 else (1.0 if violations == 0 else 0.0)

    details: Dict[str, Any] = {
        "rendered": True,
        "candidates": candidates,
        "essential_like": essential_like,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación basada en pruebas de sensores/permiso y toggles de desactivación."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("violations", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            # Alternativa UI
            "Añade botones equivalentes (p. ej., 'Rotar', 'Siguiente/Anterior', 'Mover/Zoom +/-') con manejo por teclado y puntero.",
            # Toggle de desactivación
            (
                "<label><input type='checkbox' id='toggle-motion'> Desactivar respuesta al movimiento</label>\n"
                "<script>document.getElementById('toggle-motion').addEventListener('change', e => {\n"
                "  window.__motionDisabled = e.target.checked;\n"
                "});</script>"
            ),
            # Guard en JS
            (
                "if (window.__motionDisabled) return; // antes de procesar devicemotion/deviceorientation"
            ),
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.5.4 (Motion Actuation, A). "
        "Para cada offender, sugiere una alternativa de UI y un control para desactivar la respuesta al movimiento, "
        "incluyendo snippets JS/HTML mínimos. Devuelve JSON: "
        "{ suggestions: [{selector?, snippet, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_2_5_4(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

    # 1) detalles según modo
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
        manual_required = bool(ai_info.get("manual_review", False))

    # 3) passed / verdict / score
    candidates = int(details.get("candidates", 0) or 0)
    violations = int(details.get("violations", 0) or 0)
    passed = (candidates == 0) or (violations == 0)

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
        title=meta.get("title", "Activación por movimiento"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
