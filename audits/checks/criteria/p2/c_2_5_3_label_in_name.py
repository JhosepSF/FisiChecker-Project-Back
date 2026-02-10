# audits/checks/criteria/p2/c_2_5_3_label_in_name.py
from typing import Dict, Any, List, Optional, Tuple
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.5.3"

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

def _norm_accents(s: str) -> str:
    s2 = unicodedata.normalize("NFKD", s or "")
    s2 = s2.encode("ascii", "ignore").decode("ascii")
    return s2

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

def _tokens(s: str) -> List[str]:
    # minúsculas, sin acentos; solo alfanumérico (palabras)
    norm = _lower(_norm_accents(s))
    return TOKEN_RE.findall(norm)

def _subsequence_in_order(needle: List[str], hay: List[str]) -> bool:
    """
    ¿Los tokens de 'needle' aparecen en el mismo orden dentro de 'hay'?
    Se permite que 'hay' tenga tokens adicionales (p. ej., "buscar" ⊂ "buscar en el sitio").
    """
    if not needle:
        return True
    i = 0
    for h in hay:
        if h == needle[i]:
            i += 1
            if i == len(needle):
                return True
    return False

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
        # orden preferente para “texto visible”
        for k in ("visible_label","text","label","inner_text"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # botones / enlaces con iconos: quizá extractor trae 'img_alt'
        for k in ("img_alt","alt","aria-label","title"):
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

def _resolve_ids_text(soup, ids_text: str) -> str:
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
                        out.append(txt.strip())
                except Exception:
                    continue
    except Exception:
        return ""
    return " ".join(out).strip()

def _accessible_name_for_control(ctx: PageContext, ctrl: Dict[str, Any]) -> str:
    """
    Nombre accesible programático aproximado:
      - label for= (ctx.labels_for)
      - aria-label
      - aria-labelledby (resuelto)
      - title
      - placeholder (solo si no hay nada anterior; para inputs)
      - 'accessible_name' si el extractor ya lo calculó
    """
    # 0) si el extractor ya dio 'accessible_name' úsalo
    an = _s(ctrl.get("accessible_name"))
    if an.strip():
        return an.strip()

    soup = getattr(ctx, "soup", None)
    labels_for = getattr(ctx, "labels_for", {}) or {}
    cid = _s(ctrl.get("id"))

    # 1) label for
    if cid and cid in labels_for and _s(labels_for[cid]).strip():
        return _s(labels_for[cid]).strip()

    # 2) aria-label
    al = _s(ctrl.get("aria-label"))
    if al.strip():
        return al.strip()

    # 3) aria-labelledby (resolver)
    alb = _s(ctrl.get("aria-labelledby"))
    if alb.strip():
        return _resolve_ids_text(soup, alb)

    # 4) title
    ti = _s(ctrl.get("title"))
    if ti.strip():
        return ti.strip()

    # 5) placeholder como último recurso para inputs
    ph = _s(ctrl.get("placeholder"))
    if ph.strip():
        return ph.strip()

    # 6) para enlaces/botones con <img alt> interno, el extractor podría haber puesto 'img_alt'
    ia = _s(ctrl.get("img_alt"))
    if ia.strip():
        return ia.strip()

    return ""

def _visible_label_for_node(ctx: PageContext, node: Any) -> str:
    """
    “Etiqueta mostrada” visible al usuario:
      - para inputs: label_text (o texto cercano del extractor)
      - para botones/enlaces: texto visible dentro del control
    """
    if isinstance(node, dict):
        # inputs
        label_text = _s(node.get("label_text"))
        if label_text.strip():
            return label_text.strip()
        # botones/enlaces o iconos
        vt = _get_text(node)
        if vt.strip():
            return vt.strip()
        # fallback: name/id expuestos
        nm = _s(node.get("name") or node.get("id"))
        return nm.strip()
    # Tag
    return _get_text(node)

def _is_applicable_role(ctrl: Dict[str, Any]) -> bool:
    """
    Aplica para componentes “con etiqueta textual visible”:
      - botones, enlaces, inputs/select/textarea (no-hidden)
      - roles equivalentes
    """
    tag = _lower(ctrl.get("tag"))
    t = _lower(ctrl.get("type"))
    role = _lower(ctrl.get("role"))
    if tag in {"button","a","input","select","textarea"}:
        if tag == "input" and t in {"hidden","image"}:
            return False
        return True
    if role in {"button","link","textbox","combobox","listbox","switch","slider","tab","menuitem"}:
        return True
    return False

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.5.3 (AA): Cuando un componente tiene una etiqueta textual visible, el nombre accesible debe
    contener esas mismas palabras y en el mismo orden.
    """
    controls = _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or [])
    # añadimos botones/enlaces si el extractor los provee
    controls += [n for n in _as_list(getattr(ctx, "buttons", [])) if isinstance(n, dict)]
    controls += [n for n in _as_list(getattr(ctx, "anchors", [])) if isinstance(n, dict)]

    applicable = 0
    ok = 0
    missing_name = 0
    mismatch = 0
    offenders: List[Dict[str, Any]] = []

    soup = getattr(ctx, "soup", None)  # por si necesitamos resolver aria-labelledby

    for c in controls:
        if not isinstance(c, dict) or not _is_applicable_role(c):
            continue

        visible = _visible_label_for_node(ctx, c)
        visible_tokens = _tokens(visible)
        # visible vacío → no aplicable (no hay “etiqueta textual visible”)
        if not visible_tokens:
            continue

        applicable += 1
        accname = _accessible_name_for_control(ctx, c)
        acc_tokens = _tokens(accname)

        if not acc_tokens:
            missing_name += 1
            offenders.append({
                "id": c.get("id"), "name": c.get("name"), "role": c.get("role"), "tag": c.get("tag"),
                "visible_label": visible[:140],
                "reason": "Componente con etiqueta visible pero sin nombre accesible programático."
            })
            continue

        if _subsequence_in_order(visible_tokens, acc_tokens):
            ok += 1
        else:
            mismatch += 1
            offenders.append({
                "id": c.get("id"), "name": c.get("name"), "role": c.get("role"), "tag": c.get("tag"),
                "visible_label": visible[:140], "accessible_name": accname[:140],
                "reason": "Las palabras de la etiqueta visible no aparecen en el mismo orden dentro del nombre accesible."
            })

    violations = missing_name + mismatch
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, ok / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "applicable": applicable,
        "ok": ok,
        "missing_name": missing_name,
        "mismatch": mismatch,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.5.3 exige que el nombre accesible contenga la etiqueta visible en el mismo orden. "
            "Se evalúa sobre controles y enlaces/botones con etiqueta textual visible."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, usar datos del runtime si están disponibles:
      rctx.label_in_name_test = [
        { "selector": str, "visible_label": str, "accessible_name": str }
      ]
      o bien rctx.form_accnames [{selector, name, visible_label}]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.5.3; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "label_in_name_test", []))
    if not data:
        # intentar con form_accnames
        fan = _as_list(getattr(rctx, "form_accnames", []))
        for it in fan:
            if isinstance(it, dict):
                data.append({
                    "selector": _s(it.get("selector") or it.get("id") or it.get("name")),
                    "visible_label": _s(it.get("visible_label") or it.get("placeholder") or it.get("group_label")),
                    "accessible_name": _s(it.get("name"))
                })

    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin datos runtime, se reutiliza RAW.").strip()
        return d

    applicable = 0
    ok = 0
    missing_name = 0
    mismatch = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict):
            continue
        vis = _s(it.get("visible_label"))
        acc = _s(it.get("accessible_name"))
        vis_tokens = _tokens(vis)
        if not vis_tokens:
            continue
        applicable += 1
        acc_tokens = _tokens(acc)
        if not acc_tokens:
            missing_name += 1
            offenders.append({"selector": _s(it.get("selector")), "visible_label": vis[:140], "reason": "Sin nombre accesible (runtime)."})
            continue
        if _subsequence_in_order(vis_tokens, acc_tokens):
            ok += 1
        else:
            mismatch += 1
            offenders.append({"selector": _s(it.get("selector")), "visible_label": vis[:140],
                              "accessible_name": acc[:140], "reason": "Etiqueta visible no está contenida en el mismo orden (runtime)."})

    violations = missing_name + mismatch
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, ok / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "rendered": True,
        "applicable": applicable,
        "ok": ok,
        "missing_name": missing_name,
        "mismatch": mismatch,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación con nombres accesibles calculados por el runtime."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}
    needs = (details.get("missing_name", 0) or 0) > 0 or (details.get("mismatch", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "patterns": [
            "Hacer que aria-label comience con la etiqueta visible (p. ej. 'Buscar en el sitio').",
            "Usar aria-labelledby apuntando al nodo que contiene la etiqueta visible.",
            "Para iconos-only, añadir <span class='sr-only'>Etiqueta visible</span> dentro del control."
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.5.3 (Label in Name, AA). "
        "Ajusta los nombres accesibles para que contengan la etiqueta visible en el mismo orden. "
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

def run_2_5_3(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

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

    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = bool(ai_info.get("manual_review", False))

    applicable = int(details.get("applicable", 0) or 0)
    violations = int(details.get("missing_name", 0) or 0) + int(details.get("mismatch", 0) or 0)
    
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
        title=meta.get("title", "La etiqueta en el nombre"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
