# audits/checks/criteria/p1/c_1_4_4_resize_text.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.4"

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

_FONT_SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt|em|rem|%)\s*$", re.I)

def _font_unit_kind(v: Any) -> Optional[str]:
    """
    Devuelve el tipo de unidad si se reconoce: 'px','pt','em','rem','%'.
    Acepta números (tratados como px) o strings tipo '1rem','18px','120%'.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return "px"
    s = str(v).strip().lower()
    m = _FONT_SIZE_RE.match(s)
    if not m:
        return None
    return m.group(2)

def _get_text_items(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Recolecta candidatos con texto y (si hay) sus font-size:
      text_nodes, headings, paragraphs, buttons, links, labels, form_controls
    """
    out: List[Dict[str, Any]] = []
    for src in ("text_nodes","headings","paragraphs","buttons","links","labels","form_controls"):
        for n in _as_list(getattr(ctx, src, [])):
            item = dict(n) if isinstance(n, dict) else {}
            txt = str(item.get("text") or item.get("inner_text") or item.get("label_text") or item.get("aria-label") or item.get("title") or "").strip()
            if not txt:
                continue
            item["__source"] = src
            out.append(item)
    return out

def _viewport_blocks_zoom(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    """
    Detecta meta viewport que bloquea escalado/zoom, lo cual suele impedir alcanzar 200% en móvil.
    """
    mv = getattr(ctx, "meta_viewport", None)
    if not isinstance(mv, dict):
        return False, {}
    content = str(mv.get("content") or "")
    low = content.lower()
    blocks = any([
        "user-scalable=no" in low,
        "maximum-scale=1" in low,
        "maximum-scale=1.0" in low,
        "maximum-scale=0" in low
    ])
    # Nota: algunos sitios ponen maximum-scale=2; si está < 2, puede impedir 200% → marcamos riesgo
    risk = False
    m = re.search(r"maximum-scale\s*=\s*([0-9.]+)", low)
    if m:
        try:
            max_scale = float(m.group(1))
            if max_scale < 2.0:
                risk = True
        except Exception:
            pass
    return blocks or risk, {"content": content, "blocks": blocks, "risk": risk}

def _parse_px_value(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    m = re.match(r"([0-9.]+)\s*px", s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None

def _collect_containers(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Contenedores potencialmente problemáticos si tienen altura fija + overflow:hidden (clip al 200%).
    """
    out: List[Dict[str, Any]] = []
    for src in ("containers","cards","sections","regions","modals"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict):
                out.append(n)
    return out

# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW (heurístico):
      1) Meta viewport limita zoom (user-scalable=no o maximum-scale<2) → posible incumplimiento.
      2) Uso predominante de font-size en px/pt frente a em/rem/% → riesgo de no alcanzar 200% sin desbordes.
      3) Contenedores con height/line-height fijos en px y overflow:hidden → riesgo de recorte al 200%.
    NOTA: 1.4.4 excluye subtítulos e imágenes de texto. Verificación real de “sin pérdida de contenido/función”
    requiere RENDERED (simulación de 200%).
    """
    details: Dict[str, Any] = {}

    # 1) Viewport
    vp_block, vp_info = _viewport_blocks_zoom(ctx)

    # 2) Tamaños de fuente
    items = _get_text_items(ctx)
    text_examined = len(items)
    px_pt = 0
    rel_units = 0
    unknown_units = 0
    font_offenders: List[Dict[str, Any]] = []

    for it in items:
        unit = _font_unit_kind(it.get("computed_font_size") or it.get("font_size"))
        if unit in {"em","rem","%"}:
            rel_units += 1
        elif unit in {"px","pt"}:
            px_pt += 1
            if it.get("text"):
                font_offenders.append({
                    "source": it.get("__source"),
                    "snippet": str(it.get("text"))[:120],
                    "font_size": it.get("computed_font_size") or it.get("font_size"),
                    "reason": "Uso de tamaño absoluto (px/pt) – puede dificultar alcanzar 200% sin desbordes."
                })
        else:
            unknown_units += 1

    # 3) Contenedores con riesgo de recorte
    containers = _collect_containers(ctx)
    cont_examined = len(containers)
    fixed_height = 0
    overflow_hidden = 0
    clip_risk = 0
    cont_offenders: List[Dict[str, Any]] = []

    for c in containers:
        h = _parse_px_value(c.get("height") or c.get("css_height") or c.get("computed_height") or c.get("style_height"))
        lh = _parse_px_value(c.get("line_height") or c.get("line-height") or c.get("computed_line_height"))
        of = str(c.get("overflow") or c.get("computed_overflow") or "").lower()
        ofx = str(c.get("overflow_x") or c.get("overflow-x") or c.get("computed_overflow_x") or "").lower()
        ofy = str(c.get("overflow_y") or c.get("overflow-y") or c.get("computed_overflow_y") or "").lower()

        fh = bool(h is not None or lh is not None)
        ovh = ("hidden" in of) or ("hidden" in ofx) or ("hidden" in ofy)

        if fh:
            fixed_height += 1
        if ovh:
            overflow_hidden += 1
        if fh and ovh:
            clip_risk += 1
            cont_offenders.append({
                "id": c.get("id",""),
                "class": c.get("class", []),
                "height": c.get("height") or c.get("css_height") or c.get("computed_height") or c.get("style_height"),
                "overflow": of or ofx or ofy,
                "reason": "Altura/line-height fija en px + overflow hidden (posible recorte al 200%)."
            })

    # Heurística de cumplimiento
    # - Bloqueo de zoom → falla dura
    # - Resto: si hay clip_risk significativo frente a contenedores examinados, marcamos como falla probable
    violations = 0
    offenders = []
    if vp_block:
        violations += 1
        offenders.append({
            "type": "viewport",
            "meta_viewport": vp_info.get("content",""),
            "reason": "Meta viewport limita el zoom (<200%) – incumplimiento probable de 1.4.4."
        })
    offenders.extend(font_offenders[:10])
    offenders.extend(cont_offenders)

    ok_ratio = 1.0
    if text_examined + cont_examined > 0:
        # penaliza px/pt dominantes y riesgos de clip
        risk_count = clip_risk + (px_pt > rel_units and px_pt >= 10) * 1
        denom = max(1, (text_examined > 0) + (cont_examined > 0))
        ok_ratio = round(max(0.0, min(1.0, (denom - risk_count) / denom)), 4)

    details.update({
        "viewport_blocks_zoom": bool(vp_block),
        "viewport_info": vp_info,
        "text_examined": text_examined,
        "font_px_pt": px_pt,
        "font_relative_units": rel_units,
        "font_unknown_units": unknown_units,
        "containers_examined": cont_examined,
        "fixed_height": fixed_height,
        "overflow_hidden": overflow_hidden,
        "clip_risk": clip_risk,
        "offenders": offenders,
        "ok_ratio": ok_ratio,
        "note": (
            "RAW: 1.4.4 exige que el texto pueda redimensionarse hasta el 200% sin pérdida de contenido/funcionalidad. "
            "Se detecta meta viewport que limita zoom, uso predominante de px/pt y contenedores con altura fija + overflow hidden. "
            "La verificación definitiva requiere probar con 200% en modo RENDERED."
        )
    })
    
    # --- N/A si no hay nada que revisar (sin texto ni contenedores) y no hay bloqueo de zoom
    if text_examined == 0 and cont_examined == 0 and not bool(vp_block):
        details["na"] = True
        details["ok_ratio"] = None  
    
    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED tu extractor puede aportar una prueba a 200%:
      rctx.zoom_test = {
        "factor": 2.0,
        "horizontal_scroll": bool,           # scroll horizontal para contenido de línea única
        "clipped_text_nodes": int,           # nodos de texto recortados/ocultos
        "overlapping_nodes": int,            # solapes/encimamientos
        "hidden_controls": int,              # controles inaccesibles o fuera de viewport
        "loss_of_functionality": bool        # si alguna acción queda inaccesible
      }
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.4; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    zt = getattr(rctx, "zoom_test", None)
    if isinstance(zt, dict):
        horiz = bool(zt.get("horizontal_scroll"))
        clipped = int(zt.get("clipped_text_nodes") or 0)
        overlap = int(zt.get("overlapping_nodes") or 0)
        hidden = int(zt.get("hidden_controls") or 0)
        lof = bool(zt.get("loss_of_functionality"))

        hard = horiz or lof or hidden > 0
        if hard:
            d.setdefault("offenders", []).append({
                "type": "zoom200",
                "horizontal_scroll": horiz,
                "clipped_text_nodes": clipped,
                "overlapping_nodes": overlap,
                "hidden_controls": hidden,
                "loss_of_functionality": lof,
                "reason": "Prueba al 200% evidencia pérdida de contenido/funcionalidad."
            })
            d["zoom200_issue"] = True
            d["ok_ratio"] = 0.0
        else:
            d["zoom200_issue"] = (clipped > 0 or overlap > 0)

        d["note"] = (d.get("note","") + " | RENDERED: prueba 200% aplicada (zoom_test).").strip()

        # Si incluso con zoom_test no hay texto/containers y no hay problemas → N/A
        if (d.get("text_examined", 0) == 0 and d.get("containers_examined", 0) == 0
                and not d.get("viewport_blocks_zoom") and not d.get("zoom200_issue")):
            d["na"] = True
            d["ok_ratio"] = None
        return d
    else:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'zoom_test'.").strip()
        # Sin zoom_test y sin elementos aplicables → N/A
        if d.get("text_examined", 0) == 0 and d.get("containers_examined", 0) == 0 and not d.get("viewport_blocks_zoom"):
            d["na"] = True
            d["ok_ratio"] = None
        return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere correcciones para permitir 200%:
      - Quitar user-scalable=no y maximum-scale<2 del meta viewport.
      - Migrar font-size en px/pt a rem/em/% con escalado relativo.
      - Evitar height fijo + overflow hidden en contenedores de texto.
      - Usar layout flexible (flex/grid con wrap), min-height auto y reflow al 200%.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offenders = details.get("offenders", []) or []
    if not offenders and not details.get("viewport_blocks_zoom") and not details.get("clip_risk"):
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "viewport_blocks_zoom": details.get("viewport_blocks_zoom", False),
            "font_px_pt": details.get("font_px_pt", 0),
            "font_relative_units": details.get("font_relative_units", 0),
            "clip_risk": details.get("clip_risk", 0),
        },
        "offenders": offenders[:20],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.4 (Resize Text). "
        "Propón fixes concretos: 1) meta viewport sin 'user-scalable=no' y sin 'maximum-scale<2'; "
        "2) reemplazar 'font-size' en px/pt por rem/em/%; "
        "3) eliminar 'height' fija y 'overflow:hidden' en contenedores de texto (usar min-height/auto); "
        "4) favorecer reflow al 200% con flex/grid y 'flex-wrap: wrap'. "
        "Devuelve JSON: { suggestions: [{type, reason, css_fix?, html_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_4_4(
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
        passed = False  
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        hard = 0
        if details.get("viewport_blocks_zoom"):
            hard += 1
        if details.get("zoom200_issue"):
            hard += 1
        passed = (hard == 0)

        verdict = verdict_from_counts(details, passed)
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")
        
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Redimensionar texto"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required or (details.get("clip_risk", 0) > 0)
    )
