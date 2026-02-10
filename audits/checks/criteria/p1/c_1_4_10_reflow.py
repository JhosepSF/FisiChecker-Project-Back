# audits/checks/criteria/p1/c_1_4_10_reflow.py
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

CODE = "1.4.10"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _str_or_empty(v: Any) -> str:
    return "" if v is None else str(v)

_CSS_NUM_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt|em|rem|%)\s*$", re.I)

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
    s = _str_or_empty(v).lower()
    return any(sub in s for sub in subs)

def _get_attr_str(el: Any, name: str) -> str:
    """Devuelve el atributo como str ('' si no existe), tolerando Tag o dict y listas."""
    if el is None:
        return ""
    v = None
    if isinstance(el, dict):
        v = el.get(name)
    else:
        try:
            if hasattr(el, "get"):
                v = el.get(name)  # Tag BS4
            else:
                v = getattr(el, name, None)
        except Exception:
            v = None
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        return " ".join(str(x) for x in v if x is not None)
    return str(v)

# -------------------------------------------------------------------
# Heurísticas (RAW)
# -------------------------------------------------------------------

RISK_OVERFLOWX = {"scroll", "auto"}
NO_WRAP_VALUES = {"nowrap", "pre", "pre-wrap", "pre-line"}  # (pre-wrap puede partir, pero marcamos riesgo si hay long words)
LONG_WORD_RE = re.compile(r"[A-Za-z0-9_]{40,}")  # cadenas largas sin espacios (URLs, tokens)

def _container_overflow_x(item: Dict[str, Any]) -> bool:
    of = _str_or_empty(item.get("overflow_x") or item.get("overflow-x") or item.get("computed_overflow_x"))
    of2 = _str_or_empty(item.get("overflow") or item.get("computed_overflow"))
    return any(x in of.lower() for x in RISK_OVERFLOWX) or any(x in of2.lower() for x in RISK_OVERFLOWX)

def _container_fixed_w_gt_320(item: Dict[str, Any]) -> bool:
    """
    Riesgo si width / min-width fijo en px > 320 (sin media query).
    """
    w = _to_px(item.get("width") or item.get("css_width") or item.get("style_width") or item.get("computed_width"))
    mw = _to_px(item.get("min_width") or item.get("min-width") or item.get("computed_min_width"))
    # si ambos None, no marcamos
    if w is None and mw is None:
        return False
    for val in (w, mw):
        if isinstance(val, (int, float)) and val > 320 + 0.1:
            return True
    return False

def _text_nowrap_risk(item: Dict[str, Any]) -> bool:
    ws = _str_or_empty(item.get("white_space") or item.get("white-space") or item.get("computed_white_space")).lower()
    if ws in NO_WRAP_VALUES:
        return True
    # si hay texto largo sin espacios y no hay word-wrap, también riesgo
    txt = _str_or_empty(item.get("text") or item.get("inner_text") or item.get("value") or item.get("label_text"))
    if LONG_WORD_RE.search(txt or ""):
        wrap = _str_or_empty(item.get("word_wrap") or item.get("overflow_wrap") or item.get("word-break") or item.get("computed_word_wrap")).lower()
        if not any(x in wrap for x in ("break-word","anywhere","break-all")):
            return True
    return False

def _media_not_responsive(item: Dict[str, Any]) -> bool:
    """
    Imágenes/video/iframe sin max-width:100% (o width fijo > 320).
    Señales: width fijo > 320, o flag is_responsive=False.
    """
    if _bool(item.get("is_responsive")):
        return False
    w = _to_px(item.get("width") or item.get("computed_width") or item.get("natural_width"))
    if isinstance(w, (int, float)) and w > 320 + 0.1:
        return True
    mw = _to_px(item.get("max_width") or item.get("max-width") or item.get("computed_max_width"))
    # si tenemos evidencia de max-width<=320 OK, no riesgo
    if isinstance(mw, (int, float)) and mw <= 320 + 0.1:
        return False
    # si no sabemos, no marcamos; solo cuando hay clara evidencia
    return False

def _is_two_dimensional_exception(el: Dict[str, Any]) -> bool:
    """
    Excepciones permitidas por 1.4.10 para desplazamiento bidimensional:
      imágenes, mapas, diagramas, gráficos, video, juegos, y tablas de datos complejas.
    """
    role = _str_or_empty(el.get("role"))
    tag = _str_or_empty(el.get("tag")).lower()
    cls = _str_or_empty(el.get("class")).lower()

    if tag in {"img","canvas","svg","video"}:
        return True
    if "map" in role or "diagram" in role or "chart" in role or "graph" in role:
        return True
    if "game" in role or "game" in cls:
        return True
    # tablas de datos (si el extractor las marca como tales)
    if tag == "table" or "data-table" in cls or "datatable" in cls:
        return True
    return False

# -------------------------------------------------------------------
# Núcleo del criterio
# -------------------------------------------------------------------

def _collect_layout_candidates(ctx: PageContext) -> Dict[str, List[Dict[str, Any]]]:
    """
    Recolecta elementos relevantes:
      - contenedores: sections/containers/cards/regions/modals
      - texto: paragraphs/text_nodes/labels/links/buttons
      - media: imgs/videos/iframes
      - tablas
    """
    groups: Dict[str, List[Dict[str, Any]]] = {
        "containers": [],
        "text": [],
        "media": [],
        "tables": [],
    }
    for src in ("containers","sections","cards","regions","modals"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict):
                groups["containers"].append(n)
    for src in ("paragraphs","text_nodes","labels","links","buttons"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict):
                groups["text"].append(n)
    for src in ("imgs","images","videos","iframes"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict):
                # añade pista de tag si no está
                if "tag" not in n and src in {"imgs","images"}:
                    n["tag"] = "img"
                elif "tag" not in n and src == "videos":
                    n["tag"] = "video"
                elif "tag" not in n and src == "iframes":
                    n["tag"] = "iframe"
                groups["media"].append(n)
    for t in _as_list(getattr(ctx, "tables", [])):
        if isinstance(t, dict):
            t.setdefault("tag", "table")
            groups["tables"].append(t)
    return groups

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    1.4.10 (AA) – Reflow: El contenido debe presentarse sin pérdida de información o funcionalidad
    y sin requerir desplazamiento en dos dimensiones cuando el viewport es de 320 CSS px de ancho
    (equivalente a ~400% de zoom en una anchura de 1280px).
    Se permiten excepciones (piezas que esencialmente requieren 2D): imágenes, mapas, diagramas, gráficos,
    video, juegos y tablas de datos complejas.
    RAW (heurístico):
      - contenedores con width/min-width fijo > 320px
      - overflow-x: scroll/auto en contenedores no exentos
      - textos con white-space:nowrap o palabras largas sin wrap
      - medios no responsivos (img/video/iframe fijos >320px) sin max-width adecuado
      - tablas: no se contabilizan como violación (excepción) pero se registran
    """
    g = _collect_layout_candidates(ctx)

    fixed_w_offenders: List[Dict[str, Any]] = []
    overflowx_offenders: List[Dict[str, Any]] = []
    nowrap_offenders: List[Dict[str, Any]] = []
    media_offenders: List[Dict[str, Any]] = []

    # contenedores
    for c in g["containers"]:
        if _container_fixed_w_gt_320(c):
            fixed_w_offenders.append({
                "type": "container_fixed_width",
                "id": _str_or_empty(c.get("id")),
                "class": _str_or_empty(c.get("class")),
                "width": _str_or_empty(c.get("width") or c.get("css_width") or c.get("style_width") or c.get("computed_width")),
                "min_width": _str_or_empty(c.get("min_width") or c.get("min-width") or c.get("computed_min_width")),
                "reason": "Contenedor con width/min-width fijo > 320px (riesgo de no reflow)."
            })
        if _container_overflow_x(c) and not _is_two_dimensional_exception(c):
            overflowx_offenders.append({
                "type": "container_overflowx",
                "id": _str_or_empty(c.get("id")),
                "class": _str_or_empty(c.get("class")),
                "overflow": _str_or_empty(c.get("overflow") or c.get("computed_overflow") or c.get("overflow_x") or c.get("computed_overflow_x")),
                "reason": "overflow-x=scroll/auto en contenedor no exento (riesgo de desplazamiento horizontal)."
            })

    # texto
    for t in g["text"]:
        if _text_nowrap_risk(t):
            nowrap_offenders.append({
                "type": "text_nowrap",
                "source": _str_or_empty(t.get("__source") or "text"),
                "snippet": _str_or_empty(t.get("text") or t.get("inner_text"))[:120],
                "white_space": _str_or_empty(t.get("white_space") or t.get("white-space") or t.get("computed_white_space")),
                "reason": "Texto con 'white-space: nowrap' o palabras largas sin wrap (riesgo de overflow horizontal)."
            })

    # medios
    for m in g["media"]:
        if _is_two_dimensional_exception(m):
            # imágenes/video son excepción si requieren 2D, pero igual registramos si no son responsivos
            if _media_not_responsive(m):
                media_offenders.append({
                    "type": "media_not_responsive",
                    "tag": _str_or_empty(m.get("tag")),
                    "src": _get_attr_str(m, "src")[:180],
                    "width": _str_or_empty(m.get("width") or m.get("computed_width") or m.get("natural_width")),
                    "reason": "Medio con ancho fijo >320px y sin evidencia de max-width (no bloquea el PASS si es excepción, pero es mala práctica)."
                })
            continue
        # iframes y embeds no listados como excepción → riesgo si no responsivos
        if _media_not_responsive(m):
            media_offenders.append({
                "type": "media_not_responsive",
                "tag": _str_or_empty(m.get("tag")),
                "src": _get_attr_str(m, "src")[:180],
                "width": _str_or_empty(m.get("width") or m.get("computed_width") or m.get("natural_width")),
                "reason": "Embed/iframe no responsivo (riesgo de desplazamiento horizontal)."
            })

    # tablas (exentas)
    tables_count = len(g["tables"])

    # Métrica y veredicto heurístico
    violations = len(fixed_w_offenders) + len(overflowx_offenders) + len(nowrap_offenders)

    # si no hay absolutamente nada evaluable → N/A
    total_exam = len(g["containers"]) + len(g["text"]) + len(g["media"]) + tables_count
    if total_exam == 0:
        return {
            "containers_examined": 0,
            "text_examined": 0,
            "media_examined": 0,
            "tables_detected": 0,
            "fixed_width_offenders": [],
            "overflowx_offenders": [],
            "nowrap_offenders": [],
            "media_warnings": [],
            "violations": 0,
            "ok_ratio": None,
            "na": True,
            "note": (
                "RAW: 1.4.10 (Reflow) – sin elementos evaluables en la página; se marca como N/A."
            ),
        }

    # NOTA: media_offenders no suman a 'violations' si son parte de la excepción; aquí solo anotamos como warning.
    denom = max(1.0, float(len(g["containers"]) + len(g["text"])))
    ok_ratio = 1.0 if (violations == 0) else max(0.0, min(1.0, 1.0 - (violations / denom)))

    details: Dict[str, Any] = {
        "containers_examined": len(g["containers"]),
        "text_examined": len(g["text"]),
        "media_examined": len(g["media"]),
        "tables_detected": tables_count,
        "fixed_width_offenders": fixed_w_offenders,
        "overflowx_offenders": overflowx_offenders,
        "nowrap_offenders": nowrap_offenders,
        "media_warnings": media_offenders,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4),
        "note": (
            "RAW: 1.4.10 (Reflow) – se buscan width/min-width >320px, overflow-x en contenedores no exentos, "
            "y texto con nowrap o palabras largas sin wrap. Medios no responsivos se registran como warning. "
            "Tablas/medios complejos cuentan como excepción bidimensional."
        ),
    }
    return details

# -------------------------------------------------------------------
# Rendered (prueba real a 320px / 400%)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED tu extractor puede simular 'reflow' de dos formas válidas:
      A) Viewport a 320 CSS px (p.ej. setViewportSize(320, ...))
      B) Zoom del 400% (si el layout base es 1280px)
    y exponer un objeto 'reflow_test' (ver docstring original).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.10; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    rt = getattr(rctx, "reflow_test", None)
    if not isinstance(rt, dict):
        # si tampoco había nada evaluable en RAW, conservar N/A
        if d.get("containers_examined",0)==0 and d.get("text_examined",0)==0 and d.get("media_examined",0)==0 and d.get("tables_detected",0)==0:
            d["na"] = True
            d["ok_ratio"] = None
        d["note"] = (d.get("note", "") + " | RENDERED: no se proporcionó 'reflow_test'.").strip()
        return d

    requires_h = bool(rt.get("requires_horizontal_scroll"))
    overflow_elems = int(rt.get("overflowing_elements") or 0)
    offscreen_focusable = int(rt.get("offscreen_focusable") or 0)
    hidden_critical = int(rt.get("hidden_critical_content") or 0)
    loss_info = bool(rt.get("loss_of_information"))
    loss_func = bool(rt.get("loss_of_functionality"))

    # En RENDERED tratamos estas señales como pruebas fuertes
    hard_viol = 0
    if requires_h:
        hard_viol += 1
    if loss_info or loss_func:
        hard_viol += 1
    if offscreen_focusable > 0 or hidden_critical > 0:
        hard_viol += 1

    if hard_viol > 0:
        d.setdefault("offenders", [])
        d["offenders"].append({
            "type": "reflow_rendered",
            "requires_horizontal_scroll": requires_h,
            "overflowing_elements": overflow_elems,
            "offscreen_focusable": offscreen_focusable,
            "hidden_critical_content": hidden_critical,
            "loss_of_information": loss_info,
            "loss_of_functionality": loss_func,
            "reason": "A 320px/400% se requiere desplazamiento horizontal o hay pérdida de info/funcionalidad."
        })
        d["violations"] = int(d.get("violations", 0)) + 1
        d["ok_ratio"] = 0.0

    d["note"] = (d.get("note","") + " | RENDERED: prueba de reflow aplicada a 320px/400%.").strip()
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone fixes típicos para Reflow.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs_help = (details.get("violations", 0) or 0) > 0 or (details.get("overflowx_offenders") or []) or (details.get("nowrap_offenders") or []) or (details.get("fixed_width_offenders") or [])
    if not needs_help:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "violations": details.get("violations", 0),
            "containers_examined": details.get("containers_examined", 0),
            "text_examined": details.get("text_examined", 0),
            "media_examined": details.get("media_examined", 0),
        },
        "fixed_width_offenders": details.get("fixed_width_offenders", [])[:20],
        "overflowx_offenders": details.get("overflowx_offenders", [])[:20],
        "nowrap_offenders": details.get("nowrap_offenders", [])[:20],
        "media_warnings": details.get("media_warnings", [])[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.10 (Reflow). "
        "Propón fixes CSS/HTML concretos: "
        " - Reemplazar width/min-width fijos por max-width:100% y widths relativos (%, fr); "
        " - Evitar overflow-x en contenedores no exentos; "
        " - Permitir wrapping: overflow-wrap:anywhere; word-break:break-word; "
        " - Hacer iframes/videos responsivos (width:100%; aspect-ratio; object-fit); "
        " - Para tablas de datos, permitir scroll horizontal dentro del contenedor con aria-describedby que explique. "
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

def run_1_4_10(
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
    if details.get("na") is True:
        verdict = "na"
        passed = False  # 'pass' sólo cuando realmente pasa
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")
    else:
        passed = (int(details.get("violations", 0) or 0) == 0)
        verdict = verdict_from_counts(details, passed)
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=(verdict == "pass"),
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Reflow"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required
    )
