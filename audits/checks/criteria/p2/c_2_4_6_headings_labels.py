# audits/checks/criteria/p2/c_2_4_6_headings_labels.py
from typing import Dict, Any, List, Optional, Tuple
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.4.6"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

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

def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _norm_accents(s: str) -> str:
    if not s:
        return ""
    s2 = unicodedata.normalize("NFKD", s)
    s2 = s2.encode("ascii", "ignore").decode("ascii")
    return s2

def _get_attr(node: Any, name: str) -> Optional[str]:
    """Lectura segura de atributos desde dict o Tag de BeautifulSoup."""
    try:
        if isinstance(node, dict):
            val = node.get(name)
            return _s(val) if (val is not None) else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if (val is not None) else None
    except Exception:
        pass
    return None

def _get_text(node: Any) -> str:
    """Texto visible aproximado."""
    # dict
    if isinstance(node, dict):
        for k in ("text","label","aria-label","title","accessible_name","inner_text"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return _norm_spaces(v)
        return ""
    # Tag
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return _norm_spaces(t)
        for k in ("aria-label","title"):
            v = _get_attr(node, k)
            if v:
                return _norm_spaces(v)
    except Exception:
        pass
    return ""

def _resolve_ids_text(soup, ids_text: str) -> str:
    """Resuelve aria-labelledby="id1 id2" a texto concatenado."""
    if not soup or not ids_text:
        return ""
    out: List[str] = []
    try:
        for tok in re.split(r"[\s,]+", ids_text.strip()):
            if not tok:
                continue
            el = soup.find(id=tok)
            if el is not None:
                try:
                    txt = el.get_text()  # type: ignore[attr-defined]
                    if isinstance(txt, str) and txt.strip():
                        out.append(_norm_spaces(txt))
                except Exception:
                    continue
    except Exception:
        return ""
    return " ".join(out).strip()

# ------------------------------------------------------------
# Heurísticas de “genérico / poco descriptivo”
# ------------------------------------------------------------

# Encabezados genéricos/placeholder
_GENERIC_HEADINGS_PATTERNS = [
    r"^\s*(seccion|section|bloque|block|modulo|module|heading|encabezado|titulo|title|content|contenido)\s*\d*\s*$",
    r"^\s*(sin\s*t[ií]tulo|untitled)\s*$",
]
GEN_HEAD_RE = re.compile("|".join(_GENERIC_HEADINGS_PATTERNS), re.I)

# Etiquetas genéricas
_GENERIC_LABELS_PATTERNS = [
    r"^\s*(ok|aceptar|accept|submit|enviar|send|go|continuar|siguiente|next|apply|aplicar)\s*$",
    r"^\s*(click\s*aqui|haz\s*clic\s*aqui|click\s*here|aqui|here)\s*$",
    r"^\s*(mas|m[aá]s|info|informaci[oó]n|details?|detalles?)\s*$",
]
GEN_LABEL_RE = re.compile("|".join(_GENERIC_LABELS_PATTERNS), re.I)

HEADING_TAG_RE = re.compile(r"^h[1-6]$", re.I)

# ------------------------------------------------------------
# Determinar controles aplicables y su “etiqueta” (nombre accesible)
# ------------------------------------------------------------

def _control_is_label_relevant(ctrl: Dict[str, Any]) -> bool:
    """
    Consideramos controles que deben “describir propósito”: inputs/selects/textarea/button/role interactivos
    (excluimos hidden, presentation, etc.).
    """
    tag = _lower(ctrl.get("tag"))
    t = _lower(ctrl.get("type"))
    role = _lower(ctrl.get("role"))
    if tag not in {"input","select","textarea","button"} and role not in {
        "textbox","combobox","listbox","button","switch","slider","spinbutton","radio","checkbox"
    }:
        return False
    if t in {"hidden","image"}:
        return False
    return True

def _label_from_ctx(ctx: PageContext, ctrl: Dict[str, Any]) -> str:
    """
    Obtiene un “nombre accesible” aproximado de un control a partir de:
      - labels_for[id] (si existen),
      - aria-label,
      - aria-labelledby,
      - title,
      - placeholder,
      - texto cercano opcional (si extractor lo provee en ctrl['label_text']).
    """
    soup = getattr(ctx, "soup", None)
    # 1) label asociado por <label for>
    labels_for = getattr(ctx, "labels_for", {}) or {}
    cid = _s(ctrl.get("id"))
    if cid and cid in labels_for and _s(labels_for[cid]).strip():
        return _norm_spaces(_s(labels_for[cid]))

    # 2) aria-label
    al = _s(ctrl.get("aria-label"))
    if al.strip():
        return _norm_spaces(al)

    # 3) aria-labelledby
    alb = _s(ctrl.get("aria-labelledby"))
    if alb.strip():
        return _resolve_ids_text(soup, alb)

    # 4) title
    ti = _s(ctrl.get("title"))
    if ti.strip():
        return _norm_spaces(ti)

    # 5) placeholder (aceptado como pista, no ideal)
    ph = _s(ctrl.get("placeholder"))
    if ph.strip():
        return _norm_spaces(ph)

    # 6) label_text precalculado por extractor
    lt = _s(ctrl.get("label_text"))
    if lt.strip():
        return _norm_spaces(lt)

    # 7) fallback: nombre/id
    nm = _s(ctrl.get("name") or ctrl.get("id"))
    return _norm_spaces(nm)

def _label_is_generic(label: str) -> bool:
    if not label or not label.strip():
        return True
    s = _norm_accents(label)
    return bool(GEN_LABEL_RE.match(s.strip()))

# ------------------------------------------------------------
# Encabezados (headings)
# ------------------------------------------------------------

def _extract_headings(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Normaliza encabezados desde ctx.heading_tags (Tag o dict).
    Devuelve [{level:int|None, text:str, tag:str|None, selector?:str}]
    """
    out: List[Dict[str, Any]] = []
    for h in _as_list(getattr(ctx, "heading_tags", [])):
        try:
            if isinstance(h, dict):
                text = _get_text(h)
                level = h.get("level")
                tag = _lower(_s(h.get("tag")))
                if level is None and tag:
                    m = re.match(r"h([1-6])$", tag)
                    level = int(m.group(1)) if m else None
                out.append({"level": level if isinstance(level, int) else None,
                            "text": text, "tag": tag or None,
                            "selector": _s(h.get("selector") or h.get("id"))})
            else:
                # Tag BS4
                tagname = _lower(getattr(h, "name", ""))
                if not HEADING_TAG_RE.match(tagname or ""):
                    continue
                try:
                    text = _norm_spaces(h.get_text())  # type: ignore[attr-defined]
                except Exception:
                    text = ""
                lvl = None
                m = re.match(r"h([1-6])$", tagname) if tagname else None
                if m:
                    try:
                        lvl = int(m.group(1))
                    except Exception:
                        lvl = None
                out.append({"level": lvl, "text": text, "tag": tagname, "selector": _s(getattr(h, "id", ""))})
        except Exception:
            continue
    return out

def _heading_is_generic(text: str) -> bool:
    if not text or not text.strip():
        return True
    s = _norm_accents(text)
    return bool(GEN_HEAD_RE.match(s.strip()))

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.6 (AA): Encabezados y etiquetas describen el tema o propósito.
    Heurística:
      - Encabezados presentes no deben ser vacíos ni genéricos/placeholder.
      - Controles de formulario deben tener un nombre accesible y no ser genérico.
      - Se acepta que el “contexto de grupo” (fieldset/legend) haga la etiqueta más breve (si lo provee el extractor).
    """
    headings = _extract_headings(ctx)
    total_head = len(headings)
    empty_head = 0
    generic_head = 0
    ok_head = 0
    head_offenders: List[Dict[str, Any]] = []

    for h in headings:
        txt = _s(h.get("text"))
        if not txt.strip():
            empty_head += 1
            head_offenders.append({"selector": h.get("selector"), "text": txt, "reason": "Encabezado vacío."})
            continue
        if _heading_is_generic(txt):
            generic_head += 1
            head_offenders.append({"selector": h.get("selector"), "text": txt, "reason": "Encabezado genérico/placeholder."})
        else:
            ok_head += 1

    # Controles y etiquetas
    controls = _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or [])
    total_ctrl = 0
    missing_label = 0
    generic_label = 0
    ok_label = 0
    label_offenders: List[Dict[str, Any]] = []

    for c in controls:
        if not isinstance(c, dict):
            continue
        if not _control_is_label_relevant(c):
            continue
        total_ctrl += 1

        # Si el extractor trae info de grupo/legend, úsalo para contexto
        group_label = _s(c.get("group_label") or c.get("fieldset_legend") or c.get("parent_label"))
        label_text = _label_from_ctx(ctx, c)
        combined = _norm_spaces((group_label + " " + label_text).strip())

        if not combined.strip():
            missing_label += 1
            label_offenders.append({
                "id": c.get("id"), "name": c.get("name"), "type": c.get("type"), "reason": "Control sin nombre/etiqueta accesible."
            })
            continue

        if _label_is_generic(combined):
            generic_label += 1
            label_offenders.append({
                "id": c.get("id"), "name": c.get("name"), "type": c.get("type"),
                "label": combined[:140], "reason": "Etiqueta genérica; no describe el propósito."
            })
        else:
            ok_label += 1

    # Métricas y veredicto
    head_applicable = 1 if total_head > 0 else 0
    label_applicable = 1 if total_ctrl > 0 else 0

    violations = (empty_head + generic_head) + (missing_label + generic_label)
    ok_ratio_parts = []
    if head_applicable:
        denom_h = max(1, total_head)
        ok_ratio_parts.append(ok_head / denom_h)
    if label_applicable:
        denom_l = max(1, total_ctrl)
        ok_ratio_parts.append(ok_label / denom_l)
    ok_ratio = 1.0 if not ok_ratio_parts else round(max(0.0, min(1.0, sum(ok_ratio_parts) / len(ok_ratio_parts))), 4)

    details: Dict[str, Any] = {
        "headings_examined": total_head,
        "headings_empty": empty_head,
        "headings_generic": generic_head,
        "headings_ok": ok_head,

        "controls_examined": total_ctrl,
        "labels_missing": missing_label,
        "labels_generic": generic_label,
        "labels_ok": ok_label,

        "applicable_headings": head_applicable,
        "applicable_labels": label_applicable,
        "ok_ratio": ok_ratio,

        "offenders": {
            "headings": head_offenders,
            "labels": label_offenders,
        },
        "note": (
            "RAW: 2.4.6 verifica que los encabezados y etiquetas describan tema/propósito. "
            "Se marcan encabezados vacíos/genéricos y etiquetas ausentes o genéricas. "
            "Si el extractor provee 'group_label' (fieldset/legend), se usa como contexto para permitir etiquetas más breves."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar nombres accesibles resueltos:
      rctx.form_accnames = [
        { "selector": str, "role": str, "name": str, "placeholder": str|None, "group_label": str|None }
      ]
    Si no están, reusamos RAW.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.6; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    accs = _as_list(getattr(rctx, "form_accnames", []))
    if not accs:
        d["note"] = (d.get("note","") + " | RENDERED: sin 'form_accnames', se reusó RAW.").strip()
        return d

    total_ctrl = 0
    missing_label = 0
    generic_label = 0
    ok_label = 0
    label_offenders = []

    for a in accs:
        if not isinstance(a, dict):
            continue
        total_ctrl += 1
        group_label = _s(a.get("group_label"))
        name = _norm_spaces(_s(a.get("name")) or _s(a.get("placeholder")))
        combined = _norm_spaces((group_label + " " + name).strip())

        if not combined:
            missing_label += 1
            label_offenders.append({"selector": a.get("selector"), "reason": "Control sin nombre accesible (runtime)."})
            continue
        if _label_is_generic(combined):
            generic_label += 1
            label_offenders.append({"selector": a.get("selector"), "label": combined, "reason": "Etiqueta genérica (runtime)."})
        else:
            ok_label += 1

    # Actualizar métricas de labels (mantenemos headings desde RAW/rendered DOM)
    d["controls_examined"] = total_ctrl
    d["labels_missing"] = missing_label
    d["labels_generic"] = generic_label
    d["labels_ok"] = ok_label
    d["offenders"]["labels"] = label_offenders + _as_list(d.get("offenders", {}).get("labels", []))

    # recomputa ok_ratio (promedio de headings_ok% y labels_ok%)
    parts = []
    if int(d.get("applicable_headings", 0) or 0) == 1:
        denom_h = max(1, int(d.get("headings_examined", 0) or 0))
        parts.append((int(d.get("headings_ok", 0) or 0)) / denom_h)
    if total_ctrl > 0:
        parts.append(ok_label / max(1, total_ctrl))
        d["applicable_labels"] = 1
    d["ok_ratio"] = 1.0 if not parts else round(max(0.0, min(1.0, sum(parts) / len(parts))), 4)

    d["note"] = (d.get("note","") + " | RENDERED: evaluación de etiquetas usando nombres accesibles en ejecución.").strip()
    return d

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere reescritura de encabezados genéricos/placeholder y etiquetas más descriptivas.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    heads_need = (details.get("headings_empty", 0) or 0) > 0 or (details.get("headings_generic", 0) or 0) > 0
    labels_need = (details.get("labels_missing", 0) or 0) > 0 or (details.get("labels_generic", 0) or 0) > 0
    if not (heads_need or labels_need):
        return {"ai_used": False, "manual_required": False}

    offenders = {
        "headings": (details.get("offenders", {}).get("headings", []) or [])[:20],
        "labels": (details.get("offenders", {}).get("labels", []) or [])[:20],
    }
    ctx_json = {
        "offenders": offenders,
        "guidance": {
            "headings": "Haz los encabezados específicos y concisos; deben describir el tema de la sección.",
            "labels": "Las etiquetas deben describir el propósito del campo (p.ej., 'Correo electrónico', 'Buscar en el sitio', 'Número de tarjeta')."
        },
        "html_snippet": (html_sample or "")[:2200]
    }
    prompt = (
        "Eres auditor WCAG 2.4.6 (Headings and Labels, AA). "
        "Reescribe encabezados genéricos/placeholder y propone etiquetas más descriptivas para los campos. "
        "Devuelve JSON: { suggestions: { headings: [{old?, new, rationale?}], labels: [{selector?, current?, proposed, rationale?}] }, "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_2_4_6(
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
        manual_required = bool(ai_info.get("manual_review", False))

    # 3) passed / verdict / score
    head_app = int(details.get("applicable_headings", 0) or 0)
    lab_app = int(details.get("applicable_labels", 0) or 0)

    head_viol = int(details.get("headings_empty", 0) or 0) + int(details.get("headings_generic", 0) or 0)
    label_viol = int(details.get("labels_missing", 0) or 0) + int(details.get("labels_generic", 0) or 0)

    # Si ninguno aplica, lo consideramos “no aplicable” → pasa.
    if (head_app == 0 and lab_app == 0):
        passed = True
    else:
        # Falla si hay cualquier violación en lo que sí aplica.
        passed = ((head_app == 0) or (head_viol == 0)) and ((lab_app == 0) or (label_viol == 0))

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
        title=meta.get("title", "Encabezados y etiquetas"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
