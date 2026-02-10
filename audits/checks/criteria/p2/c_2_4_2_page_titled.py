# audits/checks/criteria/p2/c_2_4_2_page_titled.py
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

CODE = "2.4.2"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

_PLACEHOLDER_PATTERNS = [
    r"^\s*(untitled|sin\s*t[ií]tulo|new\s*page|page\s*title|document|index|home|inicio|start|default|react\s*app|my\s*app|application)\s*$",
    r"^\s*home\s*\|\s*home\s*$",
]
PLACEHOLDER_RE = re.compile("|".join(_PLACEHOLDER_PATTERNS), re.I)

SEPARATORS = (" — ", " – ", " | ", " · ", " :: ", " - ")

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

def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", _s(s)).strip()

def _get_meta(soup, name: str = "", prop: str = "") -> Optional[str]:
    if soup is None:
        return None
    try:
        if name:
            t = soup.find("meta", attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)})
            if t:
                v = t.get("content")
                return _clean_text(v) if isinstance(v, str) else None
        if prop:
            t = soup.find("meta", attrs={"property": re.compile(rf"^{re.escape(prop)}$", re.I)})
            if t:
                v = t.get("content")
                return _clean_text(v) if isinstance(v, str) else None
    except Exception:
        return None
    return None

def _extract_title_candidates(ctx: PageContext) -> Dict[str, Any]:
    """
    Recolecta posibles fuentes de título:
      - <title>
      - meta og:title / twitter:title
      - heading principal (h1)
      - site_name (og:site_name / application-name)
    """
    soup = getattr(ctx, "soup", None)
    title_tag = None
    try:
        if soup is not None and soup.title and soup.title.string:
            title_tag = _clean_text(soup.title.string)
    except Exception:
        # fallback al texto del nodo <title>
        try:
            title_tag = _clean_text(soup.title.text) if soup and soup.title else None
        except Exception:
            title_tag = None

    title_ctx = _clean_text(getattr(ctx, "title_text", "") or "") or None
    og_title = _get_meta(soup, prop="og:title")
    tw_title = _get_meta(soup, name="twitter:title")
    site_name = _get_meta(soup, prop="og:site_name") or _get_meta(soup, name="application-name")

    # Heading principal
    h1_text = None
    try:
        for h in _as_list(getattr(ctx, "heading_tags", [])):
            # h puede ser dict o Tag
            txt = ""
            if isinstance(h, dict):
                t = h.get("text") or h.get("label") or h.get("inner_text")
                if isinstance(t, str):
                    txt = t
                else:
                    # si trae 'level' y 'content'
                    t2 = h.get("content")
                    if isinstance(t2, str):
                        txt = t2
            else:
                if hasattr(h, "name") and _lower(getattr(h, "name", "")) in ("h1",):
                    try:
                        txt = h.get_text()  # type: ignore[attr-defined]
                    except Exception:
                        txt = ""
            txt = _clean_text(txt)
            if txt:
                # preferimos el primer H1 no vacío
                if isinstance(h, dict):
                    lvl = _lower(_s(h.get("level") or h.get("tag")))
                    if "h1" in lvl or h.get("level") == 1:
                        h1_text = txt
                        break
                else:
                    # ya comprobamos tag h1 arriba
                    h1_text = txt
                    break
    except Exception:
        h1_text = None

    # documento. title preferencia: rendered > ctx > tag > og/twitter
    # (en renderizado, podríamos tener ctx.document_title)
    doc_title = _clean_text(getattr(ctx, "document_title", "") or "") or None

    candidates = {
        "document_title": doc_title,
        "ctx_title": title_ctx,
        "title_tag": title_tag,
        "og_title": og_title,
        "tw_title": tw_title,
        "h1_text": _clean_text(h1_text or ""),
        "site_name": _clean_text(site_name or ""),
    }
    return candidates

def _pick_best_title(c: Dict[str, Any]) -> Optional[str]:
    for k in ("document_title", "ctx_title", "title_tag", "og_title", "tw_title"):
        t = c.get(k)
        if isinstance(t, str) and t.strip():
            return t.strip()
    return None

def _is_placeholder(title: str) -> bool:
    return bool(PLACEHOLDER_RE.match(title))

def _is_meaningful(title: str) -> bool:
    t = title.strip()
    if not t:
        return False
    if _is_placeholder(t):
        return False
    # señales mínimas: al menos 3 letras o 1 palabra “larga”
    letters = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{1}", t)
    if len(letters) < 3 and len(t) < 5:
        return False
    return True

def _length_warnings(title: str) -> Tuple[bool, bool]:
    """
    (too_short, too_long) — heurísticas (no normativas).
    """
    n = len(title)
    return (n < 4, n > 120)

def _split_parts(title: str, site_name: str) -> Dict[str, Any]:
    parts = [title]
    for sep in SEPARATORS:
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            break
    return {
        "parts": parts,
        "includes_site": any(site_name and site_name.lower() in p.lower() for p in parts) if site_name else False
    }

# -------------------------------------------------------------------
# Evaluación RAW
# -------------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.2: Cada página tiene un título que describe su tema o propósito.
    Este check comprueba:
      - existencia de título no vacío;
      - que no sea un placeholder genérico (‘Home’, ‘Untitled’, ‘React App’…);
      - advertencias suaves de longitud muy corta o extremadamente larga;
      - pista de relevancia con H1 (similaridad simple, informativa).
    """
    cands = _extract_title_candidates(ctx)
    best = _pick_best_title(cands)
    h1 = cands.get("h1_text") or ""
    site_name = cands.get("site_name") or ""

    has_title = bool(best and best.strip())
    is_meaningful = _is_meaningful(best or "")
    too_short, too_long = _length_warnings(best or "")
    placeholder = _is_placeholder(best or "") if has_title else False

    # Similaridad muy simple con H1 (Jaccard de tokens) — informativa, no decisoria
    sim = None
    if best and h1:
        bt = set(re.findall(r"[a-z0-9áéíóúñ]+", _lower(best)))
        ht = set(re.findall(r"[a-z0-9áéíóúñ]+", _lower(h1)))
        union = len(bt | ht) or 1
        sim = round(len(bt & ht) / union, 4)

    # Partes y presencia de site_name
    parts_info = _split_parts(best or "", site_name)

    offenders: List[Dict[str, Any]] = []
    if not has_title:
        offenders.append({"reason": "Falta <title> o está vacío."})
    elif placeholder:
        offenders.append({"reason": "El título parece genérico/placeholder.", "title": best})
    elif too_short:
        offenders.append({"reason": "El título es muy corto (heurística).", "title": best})
    elif not is_meaningful:
        offenders.append({"reason": "El título no parece describir tema/propósito.", "title": best})

    details: Dict[str, Any] = {
        "has_title": has_title,
        "title": best,
        "h1_text": h1 or None,
        "similarity_h1_jaccard": sim,
        "placeholder": placeholder,
        "too_short": too_short,
        "too_long": too_long,
        "includes_site_name": parts_info.get("includes_site", False),
        "parts": parts_info.get("parts", []),
        "candidates": cands,
        "ok_ratio": 1.0 if has_title and is_meaningful and not placeholder else 0.0,
        "offenders": offenders,
        "note": (
            "RAW: 2.4.2 requiere título de página que describa el tema o propósito. "
            "Se verifica existencia y se evita placeholder genérico; longitud y similaridad con H1 son informativas."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer:
      rctx.document_title = document.title tras carga completa.
    Se prioriza document_title sobre <title> inicial.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.2; no se pudo evaluar en modo renderizado."}
    # Usa el mismo flujo RAW pero con document_title presente en el contexto renderizado.
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: se prioriza 'document.title' observado.").strip()
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Si falta título o parece placeholder, la IA sugiere un mejor título
    basado en H1 y/o site_name.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (not details.get("has_title")) or bool(details.get("placeholder")) or bool(details.get("too_short"))
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "current_title": details.get("title"),
        "h1_text": details.get("h1_text"),
        "site_name": (details.get("candidates") or {}).get("site_name"),
        "hints": {
            "separators": list(SEPARATORS),
            "style": "Descriptivo + marca (opcional). Máx ~60-65 caracteres recomendado; evitar placeholders."
        }
    }
    prompt = (
        "Eres auditor WCAG 2.4.2 (Page Titled). "
        "Sugiére 3 alternativas de título concisas y descriptivas, opcionalmente incluyendo el nombre del sitio. "
        "Devuelve JSON: { suggestions: [\"...\",\"...\",\"...\"], pick?: string, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_4_2(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None  # sin uso aquí; mantenemos firma homogénea
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
        ai_info = _ai_review(details)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = bool(ai_info.get("manual_required", False))

    # 3) passed / verdict / score
    has_title = bool(details.get("has_title"))
    placeholder = bool(details.get("placeholder"))
    is_meaningful = not placeholder and bool(details.get("title")) and _is_meaningful(details.get("title") or "")

    passed = has_title and is_meaningful

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
        title=meta.get("title", "Títulos de página"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
