# audits/checks/criteria/p2/c_2_5_6_concurrent_input_mechanisms.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.5.6"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

# Pistas de restricción en CSS/JS/texto
TOUCH_ONLY_TEXT_RE = re.compile(r"(solo\s*t[aá]ctil|touch\s*only|solo\s*touch|no\s*rat[oó]n|no\s*mouse)", re.IGNORECASE)
MOUSE_ONLY_TEXT_RE = re.compile(r"(solo\s*rat[oó]n|mouse\s*only|no\s*t[aá]ctil|no\s*touch)", re.IGNORECASE)
KB_BLOCK_TEXT_RE   = re.compile(r"(no\s*teclado|keyboard\s*disabled|sin\s*teclado)", re.IGNORECASE)

JS_BLOCK_RE = re.compile(
    r"(?:"
    r"preventDefault\(\)\s*;?\s*.*?(?:keydown|keypress)"  # ; opcional y DOTALL para abarcar saltos de línea
    r"|document\.onkeydown\s*=\s*function"
    r"|window\.onkeydown\s*="
    r"|addEventListener\(\s*['\"](?:touchstart|touchend)['\"].*?\)"
    r"|onpointerdown\s*="
    r"|ontouchstart\s*="
    r")",
    re.IGNORECASE | re.DOTALL
)

CSS_BLOCK_RE = re.compile(
    r"(?:pointer-events\s*:\s*none|touch-action\s*:\s*none|user-select\s*:\s*none)",
    re.IGNORECASE
)

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name); return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "").strip()  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", "") or "")

def _scripts_text(ctx: PageContext) -> str:
    st = _s(getattr(ctx, "scripts_text", ""))
    if st: return st
    soup = getattr(ctx, "soup", None)
    if soup is None: return ""
    out = []
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
    out = []
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
    2.5.6 (AAA): El contenido no debe restringir el uso de mecanismos de entrada disponibles en la plataforma.
    RAW marca riesgo cuando:
      - El texto dice 'solo táctil / solo ratón / sin teclado'.
      - El JS global bloquea teclado o solo escucha touch sin click/pointer de respaldo.
      - El CSS aplica 'pointer-events:none' o 'touch-action:none' de forma general.
    """
    page_txt = _page_text(ctx)
    scripts = _scripts_text(ctx)
    css = _styles_text(ctx)

    applicable = 1  # por defecto, toda página puede aplicar
    risks = 0
    offenders: List[Dict[str, Any]] = []

    if TOUCH_ONLY_TEXT_RE.search(page_txt) or MOUSE_ONLY_TEXT_RE.search(page_txt) or KB_BLOCK_TEXT_RE.search(page_txt):
        risks += 1
        offenders.append({"reason": "Texto sugiere restricción de modalidad (solo touch/mouse o sin teclado).", "evidence": "visible-text"})

    if JS_BLOCK_RE.search(scripts):
        risks += 1
        offenders.append({"reason": "JS podría bloquear teclado o depender solo de touch sin respaldo.", "evidence": "scripts"})

    if CSS_BLOCK_RE.search(css):
        risks += 1
        offenders.append({"reason": "CSS podría impedir modalidades (pointer-events:none / touch-action:none / user-select:none).", "evidence": "styles"})

    ok_ratio = 1.0 if applicable == 0 else (0.0 if risks > 0 else 1.0)

    details: Dict[str, Any] = {
        "applicable": applicable,
        "risks_detected": risks,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: heurística de restricciones de modalidad en texto/JS/CSS. "
            "La confirmación robusta requiere pruebas en RENDERED."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED (prueba de modalidades)
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    El extractor puede aportar:
      rctx.concurrent_input_test = [
        { "selector": str,
          "supports_pointer": bool, "supports_touch": bool, "supports_keyboard": bool,
          "restricts_switching": bool,  # p.ej., desactiva pointer si hay touch activo
          "notes": str|None }
      ]
    Violación si cualquier ítem relevante restringe el cambio de modalidad o deshabilita una modalidad disponible.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.5.6; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "concurrent_input_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'concurrent_input_test', se reusó RAW.").strip()
        return d

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict):
            continue
        # consideramos aplicable si es interactivo
        applicable += 1
        restricts = bool(it.get("restricts_switching"))
        sp = bool(it.get("supports_pointer"))
        st = bool(it.get("supports_touch"))
        sk = bool(it.get("supports_keyboard"))

        # Violaciones:
        # 1) Restricción explícita de cambio.
        # 2) Deshabilitar alguna modalidad disponible (p.ej., bloquear pointer/mouse en desktop, o touch en móvil) — el extractor decide contexto.
        if restricts or not (sp or st) or (not sk and (sp or st)):
            violations += 1
            offenders.append({
                "selector": _s(it.get("selector")),
                "supports_pointer": sp, "supports_touch": st, "supports_keyboard": sk,
                "restricts_switching": restricts,
                "reason": "Restricción de modalidades o falta de respaldo multimodal (runtime).",
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)

    details: Dict[str, Any] = {
        "rendered": True,
        "targets_examined": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: prueba de soporte a mouse/touch/teclado y cambio entre modalidades."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}
    needs = (details.get("risks_detected", 0) or 0) > 0 or (details.get("violations", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "guidelines": [
            "Usar Pointer Events (pointerdown/up/click) con fallback a 'click' en vez de solo 'touchstart'.",
            "No bloquear teclas globalmente; manejar atajos de forma contextual y accesible.",
            "Evitar 'pointer-events:none' o 'touch-action:none' globales; aplicarlos solo a casos puntuales.",
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.5.6 (Concurrent Input Mechanisms, AAA). "
        "Propón cambios para soportar y permitir alternar entre mouse/touch/teclado sin restricciones. "
        "Devuelve JSON: { suggestions: [{selector?, change, snippet?, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_2_5_6(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."
            src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx); src = "rendered"
    else:
        details = _compute_counts_raw(ctx); src = "raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info; src = "ai"
        manual_required = bool(ai_info.get("manual_review", False))

    applicable = int(details.get("targets_examined", 0) or details.get("applicable", 0) or 0)
    violations = int(details.get("violations", 0) or 0) + int(details.get("risks_detected", 0) or 0)
    passed = (applicable == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level", "AAA"), principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Mecanismos de entrada concurrentes"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
