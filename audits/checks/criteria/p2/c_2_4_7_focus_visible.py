# audits/checks/criteria/p2/c_2_4_7_focus_visible.py
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

CODE = "2.4.7"

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

def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = _s(v)
        if s == "":
            return None
        return float(s)
    except Exception:
        return None

def _is_focusable_dict(n: Dict[str, Any]) -> bool:
    """
    Heurística de “potencialmente focusable” para RAW:
    a[href], button, input/select/textarea no disabled/hidden, tabindex >= 0, roles interactivos comunes.
    """
    tag = _lower(n.get("tag"))
    role = _lower(n.get("role"))
    href = _s(n.get("href"))
    tabindex = _s(n.get("tabindex"))
    contenteditable = _lower(n.get("contenteditable"))
    disabled = _bool(n.get("disabled"))
    hidden_attr = _bool(n.get("hidden"))
    aria_hidden = _bool(n.get("aria-hidden"))

    if disabled or hidden_attr:
        return False

    if tag in ("a","button","input","select","textarea","summary"):
        if tag == "a":
            return bool(href)
        return True

    # tabindex numérico
    if tabindex != "":
        try:
            ti = int(tabindex)
            return ti >= 0
        except Exception:
            pass

    if contenteditable in ("true","plaintext-only"):
        return True

    if role in ("button","link","checkbox","radio","combobox","switch","menuitem","menuitemcheckbox","menuitemradio","tab","option","slider","spinbutton"):
        return True

    # aria-hidden no lo invalida aquí (solo RENDERED lo usa para violación de foco visible si recibiera foco)
    return False

def _extract_focusables_from_dom(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Usa ctx.focusables si existe; si no, deriva de anchors/inputs/etc. (solo dicts).
    """
    base = [x for x in _as_list(getattr(ctx, "focusables", [])) if isinstance(x, dict)]
    if base:
        return base

    out: List[Dict[str, Any]] = []
    # anchors
    for a in _as_list(getattr(ctx, "anchors", [])):
        if isinstance(a, dict) and _is_focusable_dict(a):
            out.append({
                "selector": _s(a.get("selector") or a.get("id") or a.get("href")),
                "tag": _lower(a.get("tag") or "a"),
                "href": _s(a.get("href")),
                "tabindex": _s(a.get("tabindex")),
                "role": _lower(a.get("role")),
                "class": _s(a.get("class")),
                "source": "anchors"
            })
    # form controls
    for coll in ("inputs","form_controls","buttons","selects","textareas"):
        for n in _as_list(getattr(ctx, coll, [])):
            if isinstance(n, dict) and _is_focusable_dict(n):
                out.append({
                    "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                    "tag": _lower(n.get("tag") or ""),
                    "type": _lower(n.get("type") or ""),
                    "tabindex": _s(n.get("tabindex")),
                    "role": _lower(n.get("role")),
                    "class": _s(n.get("class")),
                    "source": coll
                })
    # genéricos con tabindex
    for n in _as_list(getattr(ctx, "nodes_with_tabindex", [])):
        if isinstance(n, dict) and _is_focusable_dict(n):
            out.append({
                "selector": _s(n.get("selector") or n.get("id")),
                "tag": _lower(n.get("tag") or ""),
                "tabindex": _s(n.get("tabindex")),
                "role": _lower(n.get("role")),
                "class": _s(n.get("class")),
                "source": "nodes_with_tabindex"
            })
    return out

# -------------------------------------------------------------------
# Señales CSS (RAW)
# -------------------------------------------------------------------

def _collect_css_focus_meta(ctx: PageContext) -> Dict[str, Any]:
    """
    Intenta leer señales del extractor sobre estilos de foco:
      ctx.css_features = {
        "focus_rules": int,               # cantidad de selectores con :focus
        "focus_visible_rules": int,       # cantidad de selectores con :focus-visible o .focus-visible polyfill
        "outline_none_rules": int,        # ocurrencias de 'outline: none/0'
        "outline_none_global": bool,      # si se detectó reset global (p.ej., *:focus {outline:0} o a:focus{outline:0})
        "has_outline_replacement": bool,  # si hay reemplazo visible (box-shadow/border/background) atado a :focus
      }
      ctx.stylesheets_text (opcional, string) para heurística débil.
    """
    cssf = getattr(ctx, "css_features", {}) or {}
    out = {
        "focus_rules": int(cssf.get("focus_rules") or 0),
        "focus_visible_rules": int(cssf.get("focus_visible_rules") or 0),
        "outline_none_rules": int(cssf.get("outline_none_rules") or 0),
        "outline_none_global": bool(cssf.get("outline_none_global")),
        "has_outline_replacement": bool(cssf.get("has_outline_replacement")),
    }

    # Heurística débil sobre texto CSS si no hubo parsing
    if sum(out.values()) == 0:
        css_text = _s(getattr(ctx, "stylesheets_text", ""))
        if css_text:
            try:
                out["outline_none_rules"] = len(re.findall(r"outline\s*:\s*(none|0)\b", css_text, flags=re.I))
                out["focus_rules"] = len(re.findall(r":focus(?!-within|-visible)", css_text, flags=re.I))
                out["focus_visible_rules"] = len(re.findall(r":focus-visible|\.(focus\-visible)", css_text, flags=re.I))
                # reemplazo visible (súper heurístico)
                out["has_outline_replacement"] = bool(re.search(r":focus[^{}]*?(box-shadow|border|background|outline-color)", css_text, flags=re.I))
                out["outline_none_global"] = bool(re.search(r"\*\s*:\s*focus\s*\{[^}]*outline\s*:\s*(none|0)", css_text, flags=re.I))
            except Exception:
                pass

    return out

# -------------------------------------------------------------------
# Evaluación RAW
# -------------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.7 (AA): Todo componente que puede recibir foco por teclado debe mostrar un indicador visible de foco.
    RAW (estático) no puede “probar” visibilidad; en cambio:
      - Señala riesgo si hay 'outline:none/0' (especialmente global) sin reemplazo aparente.
      - Señala riesgo si NO hay ninguna regla :focus / :focus-visible.
    """
    focusables = _extract_focusables_from_dom(ctx)
    total_focusables = len(focusables)
    cssm = _collect_css_focus_meta(ctx)

    # Señales de riesgo
    risky_outline_reset = cssm["outline_none_rules"] > 0 and not cssm["has_outline_replacement"]
    no_focus_rules = (cssm["focus_rules"] + cssm["focus_visible_rules"]) == 0 and total_focusables > 0

    violations_suspicions = 0
    offenders: List[Dict[str, Any]] = []

    if risky_outline_reset:
        violations_suspicions += 1
        offenders.append({
            "reason": "Se detectó 'outline:none/0' sin reemplazo aparente de indicador de foco.",
            "css_meta": cssm
        })
    if no_focus_rules:
        violations_suspicions += 1
        offenders.append({
            "reason": "No se detectaron reglas :focus/:focus-visible pese a existir elementos focusables.",
            "css_meta": cssm
        })

    applicable = 1 if total_focusables > 0 else 0
    ok_ratio = 1.0 if applicable == 0 else (0.0 if violations_suspicions > 0 else 1.0)

    details: Dict[str, Any] = {
        "focusables_found": total_focusables,
        "applicable": applicable,
        "css_focus_meta": cssm,
        "violations_suspicions": violations_suspicions,
        "offenders": offenders,
        "ok_ratio": ok_ratio,
        "note": (
            "RAW: 2.4.7 requiere indicador visible de foco. En estático, solo inferimos riesgo "
            "por resets de 'outline' sin reemplazo y ausencia total de reglas :focus/:focus-visible. "
            "La validación real se realiza en RENDERED tabulando componentes."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (verificación en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede tabular y medir el indicador:
      rctx.focus_indicator_test = [
        {
          "selector": str,
          "receives_keyboard_focus": bool,   # confirmó que recibe foco con Tab/Shift+Tab
          "visible_indicator": bool,         # el indicador es visible a simple vista
          "indicator_types": List[str],      # ["outline","box-shadow","border","bg-change","underline","other"]
          "min_thickness_px": float|None,    # grosor mínimo estimado del borde/outline/shadow
          "contrast_ratio": float|None,      # contraste aproximado del indicador vs entorno (informativo)
          "notes": str|None
        }, ...
      ]
    La norma AA solo exige visibilidad; contraste/grosor se usan como pistas para sugerencias.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.7; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "focus_indicator_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'focus_indicator_test'.").strip()
        return d

    applicable = 0
    tested = 0
    violations = 0
    weak_indicators = 0  # no falla AA; lo marcamos como sugerencia
    offenders: List[Dict[str, Any]] = []
    suggestions: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue
        receives = bool(t.get("receives_keyboard_focus"))
        if not receives:
            # si no recibe foco, no entra a la muestra aplicable
            continue
        applicable += 1
        tested += 1

        visible = bool(t.get("visible_indicator"))
        if not visible:
            violations += 1
            offenders.append({
                "selector": _s(t.get("selector")),
                "reason": "El elemento recibió foco por teclado pero el indicador no fue visible."
            })
            continue

        # Sugerencias suaves: grosor/contraste bajos (informativo; no AA)
        thick = _num(t.get("min_thickness_px")) or 0.0
        cr = _num(t.get("contrast_ratio"))
        if thick < 1.0 or (cr is not None and cr < 3.0):
            weak_indicators += 1
            suggestions.append({
                "selector": _s(t.get("selector")),
                "indicator_types": _as_list(t.get("indicator_types")),
                "min_thickness_px": thick,
                "contrast_ratio": cr,
                "note": "Indicador visible pero débil (sugerencia)."
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)

    d.update({
        "applicable": applicable,
        "tested": tested,
        "violations_runtime": violations,
        "weak_indicators": weak_indicators,
        "ok_ratio": ok_ratio,
        "offenders": _as_list(d.get("offenders")) + offenders,
        "suggestions": suggestions,
        "note": (d.get("note","") + " | RENDERED: se validó visibilidad real del indicador de foco. "
                "El grosor/contraste se reporta solo como recomendación (no normativo en 2.4.7).").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone reglas CSS seguras para foco visible:
      - Usar :focus-visible cuando sea posible, o :focus como fallback.
      - Evitar 'outline: none' sin reemplazo claro.
      - Indicadores robustos (outline/box-shadow/border) que no dependan solo de color de fondo.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("violations_suspicions", 0) or 0) > 0 or (details.get("violations_runtime", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "css_focus_meta": details.get("css_focus_meta", {}),
        "offenders": (details.get("offenders", []) or [])[:20],
        "weak_indicators": (details.get("suggestions", []) or [])[:10],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": {
            "outline": ":focus-visible{ outline: 2px solid currentColor; outline-offset: 2px; }",
            "shadow": ":focus-visible{ box-shadow: 0 0 0 3px rgba(0,0,0,.6); outline: none; }",
            "border": ":focus-visible{ border: 2px solid #005fcc; }",
            "fallback": ":focus{ outline: 2px solid #1a73e8; outline-offset: 2px; }"
        }
    }
    prompt = (
        "Eres auditor WCAG 2.4.7 (Focus Visible, AA). "
        "Para cada offender, sugiere un indicador de foco visible robusto (CSS) y evita 'outline:none' sin sustituto. "
        "Devuelve JSON: { suggestions: [{selector?, css_rule, rationale}], "
        "soft_tweaks?: [{selector?, css_rule, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_4_7(
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

    # 3) passed / verdict / score
    applicable = int(details.get("applicable", 0) or 0)

    # En RENDERED: falla si hubo cualquier elemento que recibió foco sin indicador visible
    vr = int(details.get("violations_runtime", 0) or 0)

    # En RAW: si solo tenemos sospechas (outline none sin reemplazo o sin reglas de foco), marcamos como no-apto
    vraw = int(details.get("violations_suspicions", 0) or 0)
    
    violations = vr + vraw
    
    # Ultra estricto: PASS solo si 100%, PARTIAL >= 80%, FAIL < 80%
    if applicable == 0 or violations == 0:
        passed = True
        details["ratio"] = 1.0
    else:
        ok_count = applicable - violations
        ratio = ok_count / applicable
        details["ratio"] = ratio
        # PARTIAL si >= 80%, FAIL si < 80%
        if ratio >= 0.80:
            passed = True  # verdict_from_counts detectará partial
        else:
            passed = False

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AA"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Enfoque visible"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
