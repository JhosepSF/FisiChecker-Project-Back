# audits/checks/criteria/p1/c_1_3_4_orientation.py
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

CODE = "1.3.4"

# -------------------------
# Utilidades
# -------------------------

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _as_list(x) -> List[Dict[str, Any]]:
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

# Heurísticos de texto para “gira tu dispositivo”
_ROTATE_PATTERNS = [
    re.compile(r"\b(gira|gire|girar|rotar|rote|rotación|rotacion)\b.*\b(dispositivo|pantalla|tel[eé]fono|m[óo]vil)\b", re.I),
    re.compile(r"\b(rotate|rotation|please rotate|landscape only|portrait only)\b", re.I),
    re.compile(r"\b(solo\s+en\s+(modo|orientaci[oó]n)\s+(horizontal|vertical|paisaje|retrato))\b", re.I),
]

# Detección de APIs JS de bloqueo de orientación
_LOCK_JS_PATTERNS = [
    re.compile(r"\bscreen\.orientation\.lock\s*\(", re.I),
    re.compile(r"\blockOrientation\s*\(", re.I),           # legacy/vendor
    re.compile(r"\bmozLockOrientation\s*\(", re.I),
    re.compile(r"\bmsLockOrientation\s*\(", re.I),
]

# Detección de clases comunes/atributos para overlays de orientación
_OVERLAY_CLASS_HINTS = {"rotate", "rotation", "landscape-only", "portrait-only", "orientation-lock", "rotate-device", "only-landscape", "only-portrait"}

def _find_rotate_texts(ctx: PageContext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # Toma textos de headings, párrafos, bloques, regiones, tooltips, etc.
    for src_name in ("headings", "paragraphs", "text_blocks", "live_regions", "notes", "labels", "banners"):
        for n in _as_list(getattr(ctx, src_name, []) or []):
            txt = (n.get("text") or n.get("inner_text") or n.get("label") or "").strip()
            if not txt:
                continue
            if any(p.search(txt) for p in _ROTATE_PATTERNS):
                out.append({"source": src_name, "snippet": txt[:220]})
    # También texto plano si lo expones
    for n in _as_list(getattr(ctx, "text_nodes", []) or []):
        txt = (n.get("text") or "").strip()
        if txt and any(p.search(txt) for p in _ROTATE_PATTERNS):
            out.append({"source": "textnode", "snippet": txt[:220]})
    return out

def _find_lock_scripts(ctx: PageContext) -> List[str]:
    hits: List[str] = []
    for scr in _as_list(getattr(ctx, "scripts_text", []) or []):
        code = str(scr.get("code") or scr.get("text") or scr or "")
        if any(p.search(code) for p in _LOCK_JS_PATTERNS):
            # devolvemos una muestra
            hits.append(code[:220])
    return hits

def _find_orientation_media_queries(ctx: PageContext) -> List[str]:
    """
    Busca @media (orientation: landscape|portrait) en reglas CSS expuestas por el extractor.
    Marca solo si hay evidencias de BLOQUEO (p.ej., display:none del contenedor principal en una orientación).
    """
    findings: List[str] = []
    css_rules = _as_list(getattr(ctx, "css_rules", []) or getattr(ctx, "stylesheets", []) or [])
    for r in css_rules:
        media = str(r.get("media") or "").lower()
        if "orientation" in media and ("landscape" in media or "portrait" in media):
            # Señales de bloqueo (si el extractor trae un resumen de props)
            body_hide = bool(r.get("hides_main") or r.get("display_none_main") or r.get("blocks_root"))
            if body_hide:
                findings.append(media[:180])
    return findings

def _find_overlay_nodes(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Overlays explícitos que impiden usar una orientación: divs fijos con z-index alto,
    visibilidad alta y textos/pictogramas de rotación.
    """
    overlays: List[Dict[str, Any]] = []
    for n in _as_list(getattr(ctx, "overlays", []) or getattr(ctx, "modals", []) or []):
        cls = {c.lower() for c in (n.get("class") or [])}
        idv = (n.get("id") or "").lower()
        name_hit = bool(cls.intersection(_OVERLAY_CLASS_HINTS) or any(k in idv for k in _OVERLAY_CLASS_HINTS))
        position_fixed = (str(n.get("css_position") or "").lower() == "fixed")
        z_high = int(n.get("z_index") or 0) >= 1000
        blocks = bool(n.get("blocks_interaction") or n.get("covers_viewport"))
        if name_hit or (position_fixed and z_high and blocks):
            overlays.append({
                "id": n.get("id", ""),
                "class": n.get("class", []),
                "z_index": n.get("z_index"),
                "position": n.get("css_position"),
                "reason": "Overlay potencial de orientación (bloquea interacción/visualización)."
            })
    return overlays

# -------------------------
# Núcleo del criterio
# -------------------------
def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    Heurísticas RAW:
      - JS que intenta bloquear orientación (screen.orientation.lock, etc.)
      - CSS con @media (orientation: ...) que oculta el contenido principal en una orientación
      - Overlays/patrones de “gira tu dispositivo”
      - Textos que exigen una orientación específica
    *Excepciones (no automatizables): funciones esenciales (p.ej., teclado musical). Se requiere revisión manual.
    """
    rotate_msgs = _find_rotate_texts(ctx)              # textos “gira/rotate…”
    lock_snippets = _find_lock_scripts(ctx)            # llamadas a orientation.lock/lockOrientation
    css_blocks = _find_orientation_media_queries(ctx)  # media queries que esconden main/root
    overlays = _find_overlay_nodes(ctx)                # overlays de bloqueo

    violations = 0
    offenders: List[Dict[str, Any]] = []

    if lock_snippets:
        violations += 1
        offenders.append({"type": "js_lock", "samples": lock_snippets[:3], "reason": "Uso de APIs para bloquear la orientación."})
    if css_blocks:
        violations += 1
        offenders.append({"type": "css_block", "media_samples": css_blocks[:3], "reason": "CSS oculta el contenido en una orientación."})
    if overlays:
        violations += 1
        offenders.extend([{"type": "overlay", **o} for o in overlays])
    if rotate_msgs:
        # Mensajes por sí solos no siempre son violación; si hay otros indicios, elevan severidad.
        offenders.append({"type": "rotate_messages", "count": len(rotate_msgs), "samples": [m["snippet"] for m in rotate_msgs[:3]],
                          "reason": "Instrucciones que condicionan el uso a una orientación específica."})

    ok_ratio = 1.0 if (not lock_snippets and not css_blocks and not overlays) else 0.0

    details: Dict[str, Any] = {
        "orientation_lock_scripts": len(lock_snippets),
        "orientation_css_blocks": len(css_blocks),
        "orientation_overlays": len(overlays),
        "rotation_messages": len(rotate_msgs),
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.3.4 exige que el contenido no esté restringido a una sola orientación "
            "(retrato/paisaje) salvo que sea esencial. Se detectan: "
            "1) JS de bloqueo de orientación; 2) CSS que oculta el contenido principal por orientación; "
            "3) overlays que bloquean el uso hasta rotar; 4) mensajes de 'gira tu dispositivo'. "
            "Las excepciones esenciales requieren revisión manual."
        )
    }

    # N/A si no hay nada que revisar (todos los contadores en 0)
    if (
        details["orientation_lock_scripts"] == 0
        and details["orientation_css_blocks"] == 0
        and details["orientation_overlays"] == 0
        and details["rotation_messages"] == 0
    ):
        details["na"] = True

    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED puedes:
      - Exponer rctx.orientation = 'portrait'|'landscape' y flags de visibilidad de 'main'
      - Señalar overlays visibles que impiden interacción (covers_viewport=True)
      - Probar si el contenido principal queda inaccesible en una orientación
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.3.4; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    # Señales opcionales que puede aportar tu extractor (Playwright):
    # - rctx.orientation_visible = {'portrait': {'main_visible': bool, 'overlay_blocking': bool}, 'landscape': {...}}
    ov = getattr(rctx, "orientation_visible", None)
    if isinstance(ov, dict):
        portrait_block = bool((ov.get("portrait") or {}).get("overlay_blocking")) or not bool((ov.get("portrait") or {}).get("main_visible", True))
        landscape_block = bool((ov.get("landscape") or {}).get("overlay_blocking")) or not bool((ov.get("landscape") or {}).get("main_visible", True))
        # Si alguna orientación queda bloqueada/inutilizable → violación dura
        if portrait_block or landscape_block:
            d["orientation_render_block"] = {"portrait_blocked": portrait_block, "landscape_blocked": landscape_block}
            d["note"] = (d.get("note", "") + " | RENDERED: orientación bloqueada (main oculto u overlay).").strip()
            # Ajusta ok_ratio a 0 si se confirma bloqueo
            d["ok_ratio"] = 0.0

    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si hay indicios de bloqueo, la IA sugiere:
      - Sustituir screen.orientation.lock por diseño responsive (CSS grid/flex)
      - Quitar display:none del main en @media (orientation: …) y ofrecer layouts alternos
      - Cambiar overlays forzados por hints no bloqueantes
      - Documentar si aplica 'esencial' y cómo ofrecer alternativa (si no es esencial)
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    issues = (
        (details.get("orientation_lock_scripts", 0) or 0)
        + (details.get("orientation_css_blocks", 0) or 0)
        + (details.get("orientation_overlays", 0) or 0)
    )
    if issues == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "lock_scripts": details.get("orientation_lock_scripts", 0),
            "css_blocks": details.get("orientation_css_blocks", 0),
            "overlays": details.get("orientation_overlays", 0),
            "rotation_messages": details.get("rotation_messages", 0),
        },
        "offenders": details.get("offenders", [])[:12],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Actúa como auditor WCAG 1.3.4 (Orientación). "
        "Propón correcciones específicas: "
        "1) Reemplazar orientation.lock por layout responsive; "
        "2) Quitar 'display:none' del main en @media por reflujo adecuado; "
        "3) Convertir overlays obligatorios en mensajes no bloqueantes; "
        "4) Si alegan 'esencial', justificarlo y ofrecer equivalentes. "
        "Devuelve JSON: { suggestions: [{type, reason, fix_css?, fix_js?, fix_copy?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": True}  # casi siempre requiere revisión
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": True}

# -------------------------
# Orquestación
# -------------------------

def run_1_3_4(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
    hard_flags = 0
    soft_flags = 0
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
        manual_required = ai_info.get("manual_required", False)

    # 3) passed / verdict / score
    if details.get("na") is True:
        verdict = "na"
        score0 = score_from_verdict(verdict)
        score_hint = None
        passed = passed = (hard_flags == 0)
    else:
        hard_flags = (
            (details.get("orientation_lock_scripts", 0) or 0)
            + (details.get("orientation_css_blocks", 0) or 0)
            + (details.get("orientation_overlays", 0) or 0)
        )
        # Mensajes de “gira” solos no fallan, pero disparan revisión.
        passed = (hard_flags == 0)

        verdict = verdict_from_counts(details, passed)
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")

    # Mensajes de “gira” solos no fallan, pero disparan revisión.
    passed = (hard_flags == 0)

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
        title=meta.get("title", "Orientación"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required or (details.get("rotation_messages", 0) > 0)
    )
