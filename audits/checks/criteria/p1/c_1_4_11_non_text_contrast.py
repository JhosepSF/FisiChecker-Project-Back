# audits/checks/criteria/p1/c_1_4_11_non_text_contrast.py
from typing import Dict, Any, List, Optional, Tuple
import re
import math

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "1.4.11"

# -------------------------
# Utilidades
# -------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _s(v: Any) -> str:
    return "" if v is None else str(v)

# --- Color parsing / contraste ---

_HEX3 = re.compile(r"^#([0-9a-fA-F]{3})$")
_HEX4 = re.compile(r"^#([0-9a-fA-F]{4})$")
_HEX6 = re.compile(r"^#([0-9a-fA-F]{6})$")
_HEX8 = re.compile(r"^#([0-9a-fA-F]{8})$")
_RGB  = re.compile(r"^rgb\(\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*\)$", re.I)
_RGBA = re.compile(r"^rgba\(\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9.]+)\s*\)$", re.I)

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

def _parse_hex_triplet(h: str) -> Optional[Tuple[float,float,float]]:
    s = h.strip()
    m = _HEX6.match(s)
    if m:
        v = m.group(1)
        r = int(v[0:2], 16) / 255.0
        g = int(v[2:4], 16) / 255.0
        b = int(v[4:6], 16) / 255.0
        return r, g, b
    m = _HEX3.match(s)
    if m:
        v = m.group(1)
        r = int(v[0]*2, 16) / 255.0
        g = int(v[1]*2, 16) / 255.0
        b = int(v[2]*2, 16) / 255.0
        return r, g, b
    m = _HEX8.match(s)
    if m:
        v = m.group(1)
        r = int(v[0:2], 16) / 255.0
        g = int(v[2:4], 16) / 255.0
        b = int(v[4:6], 16) / 255.0
        # ignoramos alpha
        return r, g, b
    m = _HEX4.match(s)
    if m:
        v = m.group(1)
        r = int(v[0]*2, 16) / 255.0
        g = int(v[1]*2, 16) / 255.0
        b = int(v[2]*2, 16) / 255.0
        return r, g, b
    return None

def _parse_rgb(s: str) -> Optional[Tuple[float,float,float]]:
    s2 = s.strip()
    m = _RGB.match(s2)
    if m:
        r = int(m.group(1)) / 255.0
        g = int(m.group(2)) / 255.0
        b = int(m.group(3)) / 255.0
        return _clamp01(r), _clamp01(g), _clamp01(b)
    m = _RGBA.match(s2)
    if m:
        r = int(m.group(1)) / 255.0
        g = int(m.group(2)) / 255.0
        b = int(m.group(3)) / 255.0
        # ignoramos alpha (asumimos opaco sobre el fondo efectivo)
        return _clamp01(r), _clamp01(g), _clamp01(b)
    return None

def _parse_color(col: Any) -> Optional[Tuple[float,float,float]]:
    if not col:
        return None
    s = str(col).strip()
    if s.lower() in {"transparent", "none"}:
        return None
    if s.startswith("#"):
        return _parse_hex_triplet(s)
    if s.lower().startswith("rgb"):
        return _parse_rgb(s)
    # nombres CSS: usar valores de referencia mínimos
    NAMED = {
        "black": (0,0,0),
        "white": (1,1,1),
        "red": (1,0,0),
        "green": (0,0.5,0),
        "blue": (0,0,1),
        "gray": (0.5,0.5,0.5),
        "grey": (0.5,0.5,0.5),
        "yellow": (1,1,0),
        "orange": (1,0.647,0),
        "purple": (0.5,0,0.5),
        "teal": (0,0.5,0.5),
        "navy": (0,0,0.5),
        "silver": (0.75,0.75,0.75),
        "maroon": (0.5,0,0),
        "olive": (0.5,0.5,0),
        "lime": (0,1,0),
        "aqua": (0,1,1),
        "fuchsia": (1,0,1),
    }
    if s.lower() in NAMED:
        return NAMED[s.lower()]
    return None

def _srgb_to_lum(c: Tuple[float,float,float]) -> float:
    def lin(u):
        return u/12.92 if u <= 0.04045 else ((u + 0.055)/1.055)**2.4
    r, g, b = c
    R, G, B = lin(r), lin(g), lin(b)
    return 0.2126*R + 0.7152*G + 0.0722*B

def _contrast_ratio(c1: Tuple[float,float,float], c2: Tuple[float,float,float]) -> float:
    L1 = _srgb_to_lum(c1)
    L2 = _srgb_to_lum(c2)
    Lmax, Lmin = (L1, L2) if L1 >= L2 else (L2, L1)
    return (Lmax + 0.05) / (Lmin + 0.05)

def _pick_effective_bg(el: Dict[str, Any]) -> Optional[Tuple[float,float,float]]:
    for k in ("effective_bg_color","effective_background_color","container_bg_color",
              "computed_background_color","bg_under"):
        c = _parse_color(el.get(k))
        if c is not None:
            return c
    return None

def _pick_component_colors(el: Dict[str, Any]) -> List[Tuple[Tuple[float,float,float], Tuple[float,float,float], str]]:
    """
    Devuelve posibles pares (fg,bg,kind) para contrastar:
      - borde vs fondo
      - relleno vs fondo adyacente
      - ícono/glyph vs fondo
    Tomamos PASS si cualquiera de los pares cumple ≥3:1
    """
    pairs: List[Tuple[Tuple[float,float,float], Tuple[float,float,float], str]] = []
    bg = _pick_effective_bg(el)
    if bg is None:
        return pairs

    # borde
    for k in ("computed_border_color","border_color","outline_color","focus_ring_color","stroke"):
        fg = _parse_color(el.get(k))
        if fg is not None:
            pairs.append((fg, bg, "border"))

    # relleno del control (p.ej. botones “hollow” no ayudan, pero botones sólidos sí)
    for k in ("bg_color","background_color","computed_background_color","fill"):
        fg = _parse_color(el.get(k))
        if fg is not None:
            pairs.append((fg, bg, "fill"))

    # ícono/glyph dentro del control
    for k in ("icon_color","glyph_color","foreground_color","color"):
        fg = _parse_color(el.get(k))
        if fg is not None:
            pairs.append((fg, bg, "glyph"))

    return pairs

# -------------------------
# Núcleo (RAW)
# -------------------------

def _collect_components(ctx: PageContext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for src in ("buttons","links","form_controls","inputs","controls","widgets","switches","checkboxes","radios","tabs"):
        out.extend([n for n in _as_list(getattr(ctx, src, [])) if isinstance(n, dict)])
    # quitar decorativos / inactivos
    clean = []
    for n in out:
        if _bool(n.get("is_disabled")) or _bool(n.get("disabled")):
            continue
        if _bool(n.get("is_decorative")) or _bool(n.get("decorative")):
            continue
        if str(n.get("role") or "").lower() in {"presentation","none"}:
            continue
        clean.append(n)
    # deduplicar por id/xpath
    seen = set()
    uniq = []
    for n in clean:
        key = n.get("id") or n.get("xpath") or n.get("src") or id(n)
        if key in seen: continue
        seen.add(key)
        uniq.append(n)
    return uniq

def _collect_graphics(ctx: PageContext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # iconos/objetos gráficos significativos
    for src in ("icons","graphics","images","svgs"):
        out.extend([n for n in _as_list(getattr(ctx, src, [])) if isinstance(n, dict)])
    clean = []
    for n in out:
        if _bool(n.get("is_decorative")) or _bool(n.get("decorative")):
            continue
        if _bool(n.get("is_logo")) or "logo" in (_s(n.get("class")).lower()):
            # logotipos están excluidos por 1.4.11
            continue
        role = _s(n.get("role")).lower()
        if role in {"presentation","none"}:
            continue
        clean.append(n)
    return clean

def _evaluate_non_text_contrast(
    items: List[Dict[str, Any]], threshold: float = 3.0
) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    examined = 0
    passed = 0
    failed = 0
    unknown = 0
    offenders: List[Dict[str, Any]] = []

    for el in items:
        pairs = _pick_component_colors(el)
        if not pairs:
            unknown += 1
            continue

        examined += 1
        # PASS si cualquiera de los pares alcanza ≥ threshold
        ok = False
        worst_ratio = None
        worst_kind = None
        for fg, bg, kind in pairs:
            r = _contrast_ratio(fg, bg)
            if worst_ratio is None or r < worst_ratio:
                worst_ratio = r
                worst_kind = kind
            if r >= threshold:
                ok = True
                break

        if ok:
            passed += 1
        else:
            failed += 1
            offenders.append({
                "id": _s(el.get("id")),
                "class": _s(el.get("class")),
                "kind": worst_kind or "unknown",
                "worst_ratio": round(float(worst_ratio or 0.0), 3),
                "reason": f"Contraste < {threshold}:1 entre indicador no textual y fondo efectivo."
            })

    return examined, passed, failed, unknown, offenders

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: 1.4.11 (AA) – verifica contraste ≥3:1 para:
      - Indicadores no textuales necesarios para percibir/identificar componentes de UI/estados (bordes, rellenos, foco).
      - Objetos gráficos significativos (iconos, símbolos).
    Excluye: elementos inactivos, decorativos, logotipos.
    Requiere determinar un 'fondo efectivo' para medir con fiabilidad.
    """
    components = _collect_components(ctx)
    graphics   = _collect_graphics(ctx)

    c_ex, c_pass, c_fail, c_unk, c_off = _evaluate_non_text_contrast(components, threshold=3.0)
    g_ex, g_pass, g_fail, g_unk, g_off = _evaluate_non_text_contrast(graphics,   threshold=3.0)

    total_exam = c_ex + g_ex

    # N/A si no hay absolutamente nada evaluable
    if total_exam == 0:
        return {
            "components_examined": 0, "components_pass": 0, "components_fail": 0, "components_unknown": 0,
            "graphics_examined": 0,   "graphics_pass": 0,   "graphics_fail": 0,   "graphics_unknown": 0,
            "violations": 0,
            "ok_ratio": None,
            "na": True,
            "note": ("RAW: 1.4.11 – no hay componentes/objetos gráficos evaluables; se marca como N/A.")
        }

    violations = c_fail + g_fail
    ok_ratio = ( (total_exam - violations) / float(total_exam) ) if total_exam > 0 else None

    details: Dict[str, Any] = {
        "components_examined": c_ex, "components_pass": c_pass, "components_fail": c_fail, "components_unknown": c_unk,
        "graphics_examined": g_ex,   "graphics_pass": g_pass,   "graphics_fail": g_fail,   "graphics_unknown": g_unk,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4) if ok_ratio is not None else None,
        "offenders": c_off + g_off,
        "note": (
            "RAW: 1.4.11 (AA) requiere contraste ≥3:1 para información visual necesaria para identificar "
            "componentes de UI/estados (bordes, rellenos, foco) y objetos gráficos significativos. "
            "Se excluyen elementos inactivos, decorativos y logotipos. Se necesita fondo efectivo."
        )
    }
    return details

# -------------------------
# Rendered
# -------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED puedes exponer:
      rctx.non_text_contrast = [
        {id, kind:'border'|'fill'|'glyph', ratio: float, passes: bool, decorative?:bool, logo?:bool}
      ]
    Si no se provee, se reutiliza RAW con el contexto renderizado.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.11; no se pudo evaluar en modo renderizado."}

    # Si el extractor ya calculó ratios por-ítem:
    ntc = _as_list(getattr(rctx, "non_text_contrast", []) or [])

    if not ntc:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'non_text_contrast'.").strip()
        return d

    # filtra decorativos/logos
    rows = [r for r in ntc if not _bool(r.get("decorative")) and not _bool(r.get("logo"))]
    if not rows:
        return {
            "components_examined": 0, "components_pass": 0, "components_fail": 0, "components_unknown": 0,
            "graphics_examined": 0,   "graphics_pass": 0,   "graphics_fail": 0,   "graphics_unknown": 0,
            "violations": 0,
            "ok_ratio": None,
            "na": True,
            "rendered": True,
            "note": "RENDERED: 'non_text_contrast' presente pero sin ítems evaluables (decorativos/logos); N/A."
        }

    comp_ex = comp_pass = comp_fail = comp_unk = 0
    graph_ex = graph_pass = graph_fail = graph_unk = 0
    offenders: List[Dict[str, Any]] = []

    for r in rows:
        k = (_s(r.get("component_type")) or _s(r.get("kind")) or "").lower()
        ratio = r.get("ratio")
        passes = bool(r.get("passes"))

        # clasificamos heurísticamente como componente UI si hay role/control, si no como gráfico
        is_ui = k in {"border","fill","glyph"} and bool(r.get("is_ui_component") or r.get("ui"))
        if is_ui:
            comp_ex += 1
            if ratio is None:
                comp_unk += 1
            elif passes:
                comp_pass += 1
            else:
                comp_fail += 1
                offenders.append({
                    "id": _s(r.get("id")), "kind": k or "border",
                    "worst_ratio": round(float(ratio),3),
                    "reason": "Contraste no textual < 3:1 (RENDERED)."
                })
        else:
            graph_ex += 1
            if ratio is None:
                graph_unk += 1
            elif passes:
                graph_pass += 1
            else:
                graph_fail += 1
                offenders.append({
                    "id": _s(r.get("id")), "kind": k or "glyph",
                    "worst_ratio": round(float(ratio),3),
                    "reason": "Contraste no textual < 3:1 (RENDERED)."
                })

    total_exam = comp_ex + graph_ex
    if total_exam == 0:
        return {
            "components_examined": 0, "components_pass": 0, "components_fail": 0, "components_unknown": 0,
            "graphics_examined": 0,   "graphics_pass": 0,   "graphics_fail": 0,   "graphics_unknown": 0,
            "violations": 0,
            "ok_ratio": None,
            "na": True,
            "rendered": True,
            "note": "RENDERED: no hubo ítems evaluables en 'non_text_contrast'; N/A."
        }

    violations = comp_fail + graph_fail
    ok_ratio = (total_exam - violations) / float(total_exam) if total_exam > 0 else None

    return {
        "components_examined": comp_ex, "components_pass": comp_pass, "components_fail": comp_fail, "components_unknown": comp_unk,
        "graphics_examined": graph_ex,  "graphics_pass": graph_pass,  "graphics_fail": graph_fail,  "graphics_unknown": graph_unk,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4) if ok_ratio is not None else None,
        "offenders": offenders,
        "rendered": True,
        "note": "RENDERED: contraste calculado desde 'non_text_contrast'."
    }

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}
    if (details.get("violations", 0) or 0) == 0 and not details.get("offenders"):
        return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "offenders": (details.get("offenders") or [])[:20],
        "html_snippet": (html_sample or "")[:2400],
        "threshold": 3.0
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.11 (contraste no textual). "
        "Sugiere mejoras: aumentar contraste de bordes/foco, usar outline visibles, reforzar iconografía, etc. "
        "Devuelve JSON: { suggestions: [{id?, kind?, fix_css?, notes?}], manual_review?: bool }"
    )
    try:
        resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": resp, "manual_required": bool(resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_4_11(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
    # 1) detalles
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
        manual_required = ai_info.get("manual_required", False)

    # 3) veredicto/score
    if details.get("na") is True:
        verdict = "na"
        passed = False  # 'pass' solo cuando pasa de verdad
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")
    else:
        violations = int(details.get("violations", 0) or 0)
        examined = int(details.get("components_examined", 0) or 0) + int(details.get("graphics_examined", 0) or 0)
        # si por alguna razón examined==0 aquí, trátalo como N/A
        if examined == 0:
            verdict = "na"
            passed = False
            score0 = score_from_verdict(verdict)
            score_hint = None
        else:
            passed = (violations == 0)
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
        title=meta.get("title", "Contraste no textual"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required
    )
