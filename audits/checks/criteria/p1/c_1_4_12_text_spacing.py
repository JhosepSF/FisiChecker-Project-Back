# audits/checks/criteria/p1/c_1_4_12_text_spacing.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional (mismo mecanismo que 1.1.x–1.4.x)
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.12"

# -------------------------------------------------------------------
# Utilidades y parsing simple CSS
# -------------------------------------------------------------------

_CSS_NUM_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt|em|rem|%)\s*$", re.I)

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _str(v: Any) -> str:
    return "" if v is None else str(v)

def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _to_px(val: Any, base_px: float = 16.0) -> Optional[float]:
    """
    Convierte valores CSS simples a px si es posible.
    Acepta: número → px, '18px', '14pt', '1.25rem', '120%' (de base).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    m = _CSS_NUM_RE.match(s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "px":
        return num
    if unit == "pt":
        return num * 96.0 / 72.0
    if unit in ("em", "rem"):
        return num * base_px
    if unit == "%":
        return (num / 100.0) * base_px
    return None

def _has_any_substring(v: Any, subs: List[str]) -> bool:
    s = _str(v).lower()
    return any(sub in s for sub in subs)

# -------------------------------------------------------------------
# Heurísticas de riesgo para 1.4.12 (RAW)
# -------------------------------------------------------------------
# 1.4.12 exige que, si el usuario aplica:
#   - line-height: 1.5
#   - spacing after paragraphs: 2× (p. ej., margin-bottom >= 2 * font-size)
#   - letter-spacing: 0.12em
#   - word-spacing: 0.16em
# no haya pérdida de contenido o funcionalidad (no solapado/recorte/ocultación).
# No exige que esos valores estén por defecto; detectamos cosas que típicamente bloquean:
#  - contenedores de texto con altura fija + overflow: hidden/clip
#  - clamps/truncado (ellipsis, line-clamp)
#  - no-wrap en bloques largos
#  - estilos difíciles de sobreescribir en esos ejes (raro, pero marcamos si el extractor lo indica)

NOWRAP_VALUES = {"nowrap", "pre", "pre-wrap", "pre-line"}  # nowrap es el problemático; pre-wrap/line solo marcan riesgo con palabras largas
ELLIPSIS_HINTS = ("text-overflow: ellipsis", "ellipsis")
CLAMP_KEYS = ("line_clamp", "-webkit-line-clamp", "webkit_line_clamp")

def _white_space_value(item: Dict[str, Any]) -> str:
    return (_str(item.get("white_space") or item.get("white-space") or item.get("computed_white_space"))).strip().lower()

def _overflow_value(item: Dict[str, Any]) -> str:
    ovx = _str(item.get("overflow_x") or item.get("overflow-x") or item.get("computed_overflow_x"))
    ov = _str(item.get("overflow") or item.get("computed_overflow"))
    return (ovx or ov).lower()

def _has_fixed_height_clip_risk(item: Dict[str, Any]) -> bool:
    """
    Riesgo fuerte: height/max-height en px + overflow oculto/clip → sube la probabilidad
    de que al aumentar espaciamientos haya recortes/solapes.
    """
    h = _to_px(item.get("height") or item.get("computed_height") or item.get("style_height"))
    mh = _to_px(item.get("max_height") or item.get("max-height") or item.get("computed_max_height"))
    ov = _overflow_value(item)
    if any(tok in ov for tok in ("hidden", "clip")) and (h is not None or mh is not None):
        return True
    # Fallback: si hay una altura muy baja frente al font-size
    fs = _to_px(item.get("font_size") or item.get("computed_font_size") or 16.0) or 16.0
    if h is not None and h <= fs * 1.2 and any(tok in ov for tok in ("hidden", "clip")):
        return True
    return False

def _has_clamp_or_ellipsis(item: Dict[str, Any]) -> bool:
    """
    Señales de truncado (suelen romper 1.4.12 al aumentar espaciados).
    """
    # text-overflow: ellipsis
    if _has_any_substring(item.get("text_overflow") or item.get("computed_text_overflow"), ["ellipsis"]):
        return True
    # -webkit-line-clamp o equivalentes expuestos por el extractor
    for k in CLAMP_KEYS:
        v = item.get(k)
        if isinstance(v, (int, float)) and int(v) > 0:
            return True
        if _has_any_substring(v, ["line-clamp", "webkit-line-clamp"]):
            return True
    # hints en class/inline style
    if _has_any_substring(item.get("class"), ["line-clamp", "clamp", "truncate", "text-ellipsis"]):
        return True
    if _has_any_substring(item.get("style"), ["text-overflow: ellipsis", "line-clamp"]):
        return True
    return False

LONG_WORD_RE = re.compile(r"[A-Za-z0-9_]{40,}")

def _has_nowrap_risk(item: Dict[str, Any]) -> bool:
    ws = _white_space_value(item)
    if ws == "nowrap":
        return True
    # palabras largas sin wrap + no hay break rules
    txt = _str(item.get("text") or item.get("inner_text") or item.get("value") or item.get("label_text"))
    if LONG_WORD_RE.search(txt):
        wrap = _str(item.get("word_wrap") or item.get("overflow_wrap") or item.get("word-break") or item.get("computed_word_wrap")).lower()
        if not any(x in wrap for x in ("break-word","anywhere","break-all")):
            return True
    return False

def _has_hard_to_override_flags(item: Dict[str, Any]) -> bool:
    """
    Si el extractor indica que las propiedades relevantes se establecen con !important
    (o inline de forma agresiva), lo registramos como riesgo (aunque en cascada, los
    'user important' deberían prevalecer).
    """
    important_props = set()
    ip = item.get("important_props")
    if isinstance(ip, list):
        important_props.update([str(p).strip().lower() for p in ip if p is not None])
    for prop in ("line-height","letter-spacing","word-spacing","margin-bottom"):
        if _bool(item.get(prop.replace("-","_") + "_important")):
            important_props.add(prop)
    return len(important_props) > 0

# -------------------------------------------------------------------
# Núcleo del criterio (RAW)
# -------------------------------------------------------------------

def _collect_text_blocks(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Consideramos bloques y nodos de texto relevantes donde los ajustes de espaciado impactan:
      paragraphs, text_nodes largos, labels, list_items, headings, blockquotes, etc.
    """
    blocks: List[Dict[str, Any]] = []
    for src in ("paragraphs","text_nodes","labels","list_items","headings","blockquotes"):
        for n in _as_list(getattr(ctx, src, [])):
            if not isinstance(n, dict):
                continue
            item = dict(n)
            txt = _str(item.get("text") or item.get("inner_text"))
            if not txt.strip():
                continue
            item["__source"] = src
            blocks.append(item)
    return blocks

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW (heurístico):
      Señalamos riesgos típicos de ruptura cuando se incrementan line-height, letter/word spacing y
      espaciado post-párrafo, tal como establece 1.4.12. No se requiere que esos valores estén por defecto;
      solo que, si el usuario los aplica, no se pierda contenido/funcionalidad.
    """
    blocks = _collect_text_blocks(ctx)

    examined = len(blocks)
    risks_fixed_height = 0
    risks_ellipsis = 0
    risks_nowrap = 0
    risks_hard_override = 0

    offenders: List[Dict[str, Any]] = []

    for b in blocks:
        local_risk = False

        if _has_fixed_height_clip_risk(b):
            risks_fixed_height += 1
            local_risk = True
            offenders.append({
                "type": "fixed_height_clip",
                "source": b.get("__source"),
                "snippet": _str(b.get("text"))[:120],
                "overflow": _overflow_value(b),
                "height": _str(b.get("height") or b.get("computed_height") or b.get("style_height")),
                "reason": "Altura fija con overflow oculto/clip: puede recortar al aumentar espaciados."
            })

        if _has_clamp_or_ellipsis(b):
            risks_ellipsis += 1
            local_risk = True
            offenders.append({
                "type": "clamp_or_ellipsis",
                "source": b.get("__source"),
                "snippet": _str(b.get("text"))[:120],
                "reason": "Truncado (ellipsis/line-clamp) puede ocultar contenido al aumentar espaciados."
            })

        if _has_nowrap_risk(b):
            risks_nowrap += 1
            local_risk = True
            offenders.append({
                "type": "nowrap_or_longword",
                "source": b.get("__source"),
                "snippet": _str(b.get("text"))[:120],
                "white_space": _white_space_value(b),
                "reason": "No permite salto de línea o palabras largas sin wrap: puede causar solape/recorte."
            })

        if _has_hard_to_override_flags(b):
            risks_hard_override += 1
            local_risk = True
            offenders.append({
                "type": "hard_to_override",
                "source": b.get("__source"),
                "snippet": _str(b.get("text"))[:120],
                "reason": "Propiedades relevantes marcadas como !important/inline agresivo (riesgo de no ser sobreescritas)."
            })

        # Puedes extender con más señales (position:absolute con alturas fijas, etc.)

    # En RAW no afirmamos violación a menos que el extractor lo indique explícitamente.
    # Si quieres marcar violación dura cuando existan muchos riesgos, puedes hacerlo;
    # aquí preferimos pedir RENDERED para confirmar.
    violations = 0
    ok_ratio = 1.0 if examined == 0 else round(max(0.0, min(1.0, (examined - (risks_fixed_height + risks_ellipsis + risks_nowrap)) / examined)), 4)

    details: Dict[str, Any] = {
        "blocks_examined": examined,
        "risks_fixed_height": risks_fixed_height,
        "risks_truncation": risks_ellipsis,
        "risks_nowrap": risks_nowrap,
        "risks_hard_override": risks_hard_override,
        "violations": violations,         # en RAW mantenemos 0 (solicitar RENDERED)
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.4.12 exige que, si el usuario aplica line-height 1.5, espaciado post-párrafo 2×, "
            "letter-spacing 0.12em y word-spacing 0.16em, no se pierda contenido/funcionalidad. "
            "Se señalan riesgos típicos (alturas fijas + overflow oculto, truncado, nowrap). "
            "La confirmación fiable requiere prueba en RENDERED aplicando dichos estilos."
        )
    }
    
    # En ausencia total de elementos relevantes, no afirmes PASS: es N/A
    if examined == 0:
        details["na"] = True
        details["ok_ratio"] = None
    else:
        details["na"] = False
    
    return details

# -------------------------------------------------------------------
# Rendered (aplicando estilos de prueba 1.4.12)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede inyectar estilos de prueba (user overrides) y devolver:
      rctx.text_spacing_test = {
        "applied": True,
        "line_height": 1.5,
        "paragraph_spacing_em": 2.0,     # o ratio equivalente
        "letter_spacing_em": 0.12,
        "word_spacing_em": 0.16,
        "overlap_count": int,            # nodos con solape de cajas
        "clipped_count": int,            # nodos con recorte visible
        "hidden_content_count": int,     # nodos con contenido oculto/ inaccesible
        "horizontal_scroll": bool,       # opcional
        "loss_of_functionality": bool,   # p. ej., botones inalcanzables
        "problem_nodes": [ {selector|snippet|role...}, ... ]
      }
    Si no se provee, se reusa la heurística RAW.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.12; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tst = getattr(rctx, "text_spacing_test", None)
    if not isinstance(tst, dict) or not tst.get("applied"):
        d["test_applied"] = False
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'text_spacing_test' aplicado.").strip()
        # Si además no hay bloques examinados, es N/A (no hay evidencia para evaluar)
        if int(d.get("blocks_examined", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
        return d

    d["test_applied"] = True

    overlap = int(tst.get("overlap_count") or 0)
    clipped = int(tst.get("clipped_count") or 0)
    hidden = int(tst.get("hidden_content_count") or 0)
    loss_fn = bool(tst.get("loss_of_functionality"))
    # horizontal scroll no está explícitamente prohibido por 1.4.12, pero lo registramos
    hscroll = bool(tst.get("horizontal_scroll"))

    hard_viol = 0
    if overlap > 0 or clipped > 0 or hidden > 0 or loss_fn:
        hard_viol = 1

    if hard_viol:
        d.setdefault("offenders", [])
        d["offenders"].append({
            "type": "text_spacing_rendered",
            "overlap": overlap,
            "clipped": clipped,
            "hidden_content": hidden,
            "loss_of_functionality": loss_fn,
            "horizontal_scroll": hscroll,
            "examples": (tst.get("problem_nodes") or [])[:15],
            "reason": "Con estilos de prueba 1.4.12 aplicados, hay solape/recorte/ocultación o pérdida de funcionalidad."
        })
        d["violations"] = int(d.get("violations", 0)) + 1
        d["ok_ratio"] = 0.0

    d["note"] = (d.get("note","") + " | RENDERED: estilos 1.4.12 aplicados y verificados en ejecución.").strip()
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere correcciones típicas para soportar 1.4.12:
      - Evitar height/max-height fijos para bloques de texto; usar min-height/auto.
      - Quitar truncados/line-clamp para contenido esencial o permitir 'expandir'.
      - Permitir wrapping (overflow-wrap:anywhere, word-break:break-word).
      - Evitar overflow:hidden/clip en contenedores de texto, salvo casos controlados.
      - No fijar 'white-space: nowrap' en bloques de lectura.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs_help = (details.get("violations", 0) or 0) > 0 or len(details.get("offenders", []) or []) > 0
    if not needs_help:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "blocks_examined": details.get("blocks_examined", 0),
            "risks_fixed_height": details.get("risks_fixed_height", 0),
            "risks_truncation": details.get("risks_truncation", 0),
            "risks_nowrap": details.get("risks_nowrap", 0),
            "violations": details.get("violations", 0)
        },
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.12 (Text Spacing, AA). "
        "Propón fixes concretos para soportar estilos de prueba (LH 1.5, P spacing 2x, letter 0.12em, word 0.16em): "
        "1) Reemplazar height/max-height fijos por min-height/auto; "
        "2) Evitar text-overflow:ellipsis / line-clamp en contenido esencial o proveer expansión; "
        "3) Permitir wrap con overflow-wrap:anywhere; "
        "4) Evitar overflow:hidden/clip en contenedores de texto; "
        "5) No usar white-space:nowrap en bloques de lectura. "
        "Devuelve JSON: { suggestions: [{type, reason, css_fix?, html_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_1_4_12(
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
    score_hint = details.get("ok_ratio")
    # Si quedó marcado como N/A en los contadores, respétalo
    if details.get("na") is True:
        verdict = "na"
        passed = False
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        # Solo hay evidencia si examinamos algo en RAW o si en RENDERED se aplicó la prueba
        has_evidence = (int(details.get("blocks_examined", 0) or 0) > 0) or bool(details.get("test_applied"))
        if not has_evidence:
            verdict = "na"
            passed = False
            score0 = score_from_verdict(verdict)
            score_hint = None
        else:
            violations = int(details.get("violations", 0) or 0)
            passed = (violations == 0)
            verdict = verdict_from_counts(details, passed)
            score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=(verdict == "pass"),
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Espaciado del texto"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required or (verdict == "na")
    )