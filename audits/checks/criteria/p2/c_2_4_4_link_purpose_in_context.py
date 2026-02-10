# audits/checks/criteria/p2/c_2_4_4_link_purpose_in_context.py
from typing import Dict, Any, List, Optional, Tuple, Set
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.4.4"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

_GENERIC_PATTERNS = [
    r"^\s*(clic(k)?\s*aqu[ií]|haz\s*clic\s*aqu[ií]|click\s*here|here|aqui)\s*$",
    r"^\s*(m[aá]s|ver\s*m[aá]s|ver|leer\s*m[aá]s|read\s*more|more|learn\s*more|see\s*more)\s*$",
    r"^\s*(detalles?|details?|info|informaci[oó]n|saber\s*m[aá]s)\s*$",
    r"^\s*(continuar|seguir|ir|go|open|abrir|enlace|link)\s*$",
]
GENERIC_RE = re.compile("|".join(_GENERIC_PATTERNS), re.I)

HEADING_TAG_RE = re.compile(r"^h[1-6]$", re.I)

FOCUSABLE_LINK_ROLES = ("link",)  # aceptamos role="link" sin <a>

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
    """
    Texto visible aproximado. Si el enlace contiene <img alt>, usamos ese alt como parte del nombre accesible.
    """
    # dict
    if isinstance(node, dict):
        # preferir accesible name-like
        for k in ("accessible_name", "text", "label", "aria-label"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # fallback: title
        v = node.get("title")
        if isinstance(v, str) and v.strip():
            return v.strip()
        # si trae info de imágenes internas
        alt = node.get("img_alt") or node.get("alt")
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
        return ""
    # Tag
    try:
        # alt de una imagen única dentro del enlace
        if hasattr(node, "find_all"):
            imgs = node.find_all("img")
            if imgs and len(imgs) == 1:
                try:
                    alt = imgs[0].get("alt")  # type: ignore[attr-defined]
                    if isinstance(alt, str) and alt.strip():
                        return alt.strip()
                except Exception:
                    pass
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return t.strip()
        # aria-label/title
        for k in ("aria-label", "title"):
            v = _get_attr(node, k)
            if v:
                return v.strip()
    except Exception:
        pass
    return ""

def _resolve_ids_text(soup, ids_text: str) -> str:
    """
    Resuelve aria-labelledby="id1 id2" a texto concatenado.
    """
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

def _closest_heading_context(soup, a_tag) -> str:
    """
    Heurística: busca encabezado (h1..h6) cercano que provea contexto programático.
    - Revisa ancestros: primer heading interno.
    - Luego revisa hermanos anteriores inmediatos del mismo contenedor.
    """
    if not soup or not a_tag:
        return ""
    # Ancestros
    try:
        parent = getattr(a_tag, "parent", None)
        while parent is not None:
            # heading dentro del ancestro
            h = parent.find(HEADING_TAG_RE) if hasattr(parent, "find") else None
            if h is not None:
                try:
                    txt = h.get_text()  # type: ignore[attr-defined]
                    if isinstance(txt, str) and txt.strip():
                        return txt.strip()
                except Exception:
                    pass
            parent = getattr(parent, "parent", None)
    except Exception:
        pass
    # Hermanos anteriores
    try:
        if hasattr(a_tag, "parent") and hasattr(a_tag.parent, "find_all"):
            siblings = a_tag.parent.find_all(HEADING_TAG_RE, recursive=False)
            if siblings:
                # toma el último heading del contenedor
                h = siblings[-1]
                try:
                    txt = h.get_text()  # type: ignore[attr-defined]
                    if isinstance(txt, str) and txt.strip():
                        return txt.strip()
                except Exception:
                    pass
    except Exception:
        pass
    return ""

def _table_headers_context(soup, cell) -> str:
    """
    Si el link está en una celda <td> con headers="th1 th2", concatena esos TH.
    """
    if not soup or not cell:
        return ""
    try:
        hdrs = cell.get("headers") if hasattr(cell, "get") else None  # type: ignore[attr-defined]
        if isinstance(hdrs, str) and hdrs.strip():
            return _resolve_ids_text(soup, hdrs)
    except Exception:
        pass
    return ""

def _li_parent_text(a_tag) -> str:
    """
    Si el link está en un <li>, usamos el texto del <li> menos el propio texto del enlace (heurístico).
    """
    try:
        li = a_tag.find_parent("li") if hasattr(a_tag, "find_parent") else None
        if li is not None:
            li_text = li.get_text() if hasattr(li, "get_text") else ""
            a_text = a_tag.get_text() if hasattr(a_tag, "get_text") else ""
            li_text = _s(li_text).strip()
            a_text = _s(a_text).strip()
            if li_text:
                # quita ocurrencias del texto del link para quedarnos con contexto
                ctx = re.sub(re.escape(a_text), "", li_text, flags=re.I).strip()
                return ctx
    except Exception:
        pass
    return ""

def _link_text_is_generic(text: str) -> bool:
    if not text or not text.strip():
        return True
    return bool(GENERIC_RE.match(text.strip()))

def _is_applicable_link(a: Any) -> bool:
    """
    En 2.4.4 evaluamos enlaces (y role=link). Excluimos role=button sin href.
    """
    tag = _lower(_get_attr(a, "tag") or (getattr(a, "name", "") if hasattr(a, "name") else ""))
    role = _lower(_get_attr(a, "role"))
    href = _get_attr(a, "href")

    if tag == "a" and href:
        return True
    if role in FOCUSABLE_LINK_ROLES and href:
        return True
    return False

def _determinable_purpose(a: Any, soup) -> Tuple[bool, Dict[str, Any]]:
    """
    Devuelve (determinable, debug_info)
    Regla: determinable si el texto del enlace NO es genérico,
           o si es genérico pero hay CONTEXTO programáticamente determinable (aria-labelledby, heading cercano, th headers, li text).
    """
    txt = _get_text(a)
    aria_labelledby = _get_attr(a, "aria-labelledby") or ""
    labelledby_text = _resolve_ids_text(soup, aria_labelledby) if aria_labelledby else ""
    # heading contextual
    ctx_heading = _closest_heading_context(soup, a if not isinstance(a, dict) else None)
    # tabla headers
    ctx_headers = ""
    if not isinstance(a, dict) and hasattr(a, "find_parent"):
        td = a.find_parent("td")
        if td is not None:
            ctx_headers = _table_headers_context(soup, td)
    # LI padre
    ctx_li = _li_parent_text(a if not isinstance(a, dict) else None)

    # Consolidar contexto
    context_bits = [labelledby_text, ctx_heading, ctx_headers, ctx_li]
    context_text = " ".join([c for c in context_bits if c]).strip()

    txt_is_generic = _link_text_is_generic(txt)
    has_name = bool(txt or labelledby_text)  # debe existir algún nombre accesible básico

    if not has_name:
        return False, {
            "text": txt, "ctx_text": context_text, "txt_is_generic": txt_is_generic,
            "reason": "Enlace sin nombre accesible (texto/aria)."
        }

    if not txt_is_generic:
        return True, {
            "text": txt, "ctx_text": context_text, "txt_is_generic": txt_is_generic,
            "reason": "Texto del enlace es descriptivo por sí mismo."
        }

    # Si el texto es genérico, aceptamos contexto programático no vacío
    if context_text:
        return True, {
            "text": txt, "ctx_text": context_text, "txt_is_generic": txt_is_generic,
            "reason": "Texto genérico, pero el contexto programático lo desambigua."
        }

    return False, {
        "text": txt, "ctx_text": context_text, "txt_is_generic": txt_is_generic,
        "reason": "Texto genérico sin contexto programático determinable."
    }

# -------------------------------------------------------------------
# Recolección (RAW)
# -------------------------------------------------------------------

def _iter_links(ctx: PageContext) -> List[Any]:
    """
    Devuelve lista de enlaces candidatos desde ctx.anchors o, si no, desde el soup.
    """
    links = _as_list(getattr(ctx, "anchors", []))
    if links:
        return links
    soup = getattr(ctx, "soup", None)
    out: List[Any] = []
    if soup is not None:
        try:
            out = list(soup.find_all("a"))
        except Exception:
            out = []
    return out

# -------------------------------------------------------------------
# Evaluación RAW
# -------------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.4 (A): El propósito de cada enlace puede determinarse por el texto del enlace
    o por el texto del enlace junto con el contexto programáticamente determinable.
    """
    soup = getattr(ctx, "soup", None)
    links = _iter_links(ctx)

    total = 0
    applicable = 0
    determinable = 0

    missing_name = 0
    generic_no_context = 0
    duplicates_ambiguous = 0

    offenders: List[Dict[str, Any]] = []

    # Para detectar duplicados ambiguos: mismo texto → distintos href
    text_to_hrefs: Dict[str, Set[str]] = {}

    for a in links:
        try:
            if not _is_applicable_link(a):
                continue
            applicable += 1
            total += 1

            href = _get_attr(a, "href") or ""
            txt = _get_text(a).strip()
            txt_norm = _lower(txt)

            det, info = _determinable_purpose(a, soup)
            if det:
                determinable += 1
            else:
                reason = info.get("reason", "Indeterminado.")
                if "sin nombre accesible" in _lower(reason):
                    missing_name += 1
                elif "sin contexto" in _lower(reason):
                    generic_no_context += 1
                offenders.append({
                    "href": href[:200],
                    "text": info.get("text"),
                    "context": info.get("ctx_text"),
                    "reason": reason
                })

            # Populate duplicados
            if txt_norm:
                s = text_to_hrefs.get(txt_norm, set())
                s.add(href)
                text_to_hrefs[txt_norm] = s
        except Exception:
            continue

    # Duplicados ambiguos: mismo texto → ≥2 href distintos y (para ese texto) hay al menos un enlace indeterminable
    for txt_norm, hrefs in text_to_hrefs.items():
        if len([h for h in hrefs if h]) >= 2 and GENERIC_RE.match(txt_norm or ""):
            # Solo cuenta si hubo algún offender con ese texto
            if any(_lower(off.get("text") or "") == txt_norm for off in offenders):
                duplicates_ambiguous += 1

    violations = missing_name + generic_no_context + duplicates_ambiguous
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, determinable / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "links_examined": total,
        "applicable": applicable,
        "determinable": determinable,
        "missing_name": missing_name,
        "generic_no_context": generic_no_context,
        "duplicates_ambiguous": duplicates_ambiguous,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.4.4 valida que el propósito del enlace se pueda determinar por el texto o por contexto "
            "programáticamente determinable (aria-labelledby, encabezados cercanos, celdas TH/headers, etc.). "
            "Enlaces con texto genérico sin contexto o sin nombre accesible se marcan como violación. "
            "Se señalan duplicados ambiguos (mismo texto genérico hacia distintos destinos) si carecen de contexto claro."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (opcional)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED puedes obtener nombres accesibles ya resueltos por el motor (AccName),
    y confirmar aria-labelledby dinámico. Si no hay datos adicionales, reusa RAW.
    Puedes exponer:
      rctx.links_accname = [
        { "href": "...", "accessible_name": "...", "selector": "...", "context_label": "..." }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.4; no se pudo evaluar en modo renderizado."}

    # Si el extractor trae accname/labels ya resueltas, las usamos para re-evaluar determinabilidad.
    links_info = _as_list(getattr(rctx, "links_accname", []))
    if not links_info:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin accnames, se reusó RAW.").strip()
        return d

    applicable = 0
    determinable = 0
    missing_name = 0
    generic_no_context = 0
    duplicates_ambiguous = 0
    offenders: List[Dict[str, Any]] = []
    text_to_hrefs: Dict[str, Set[str]] = {}

    for li in links_info:
        if not isinstance(li, dict):
            continue
        href = _s(li.get("href"))
        acc = _s(li.get("accessible_name"))
        ctx_label = _s(li.get("context_label"))

        # Consideramos aplicable si hay href
        if not href:
            continue
        applicable += 1

        if not acc.strip():
            missing_name += 1
            offenders.append({"href": href[:200], "text": acc, "context": ctx_label, "reason": "Enlace sin nombre accesible."})
        else:
            if _link_text_is_generic(acc) and not ctx_label.strip():
                generic_no_context += 1
                offenders.append({"href": href[:200], "text": acc, "context": ctx_label, "reason": "Texto genérico sin contexto programático."})
            else:
                determinable += 1

        txt_norm = _lower(acc)
        if txt_norm:
            s = text_to_hrefs.get(txt_norm, set())
            s.add(href)
            text_to_hrefs[txt_norm] = s

    for txt_norm, hrefs in text_to_hrefs.items():
        if len([h for h in hrefs if h]) >= 2 and GENERIC_RE.match(txt_norm or ""):
            if any(_lower(off.get("text") or "") == txt_norm for off in offenders):
                duplicates_ambiguous += 1

    violations = missing_name + generic_no_context + duplicates_ambiguous
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, determinable / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "rendered": True,
        "applicable": applicable,
        "determinable": determinable,
        "missing_name": missing_name,
        "generic_no_context": generic_no_context,
        "duplicates_ambiguous": duplicates_ambiguous,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: evaluación usando nombres accesibles/etiquetas proporcionados por el runtime."
    }
    return details

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone textos de enlace más descriptivos o añadir contexto programático:
      - Reemplazar “Leer más” por “Leer más sobre {Tema}”
      - Añadir aria-labelledby con id de encabezado contiguo
      - Añadir texto oculto para lectores de pantalla (sr-only) con el contexto
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("missing_name", 0) or 0) > 0 or (details.get("generic_no_context", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "missing_name": details.get("missing_name", 0),
            "generic_no_context": details.get("generic_no_context", 0),
            "duplicates_ambiguous": details.get("duplicates_ambiguous", 0),
        },
        "sample_offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "patterns_considered_generic": [p for p in _GENERIC_PATTERNS],
        "sr_only_hint": ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0;}"
    }
    prompt = (
        "Eres auditor WCAG 2.4.4 (Link Purpose in Context, A). "
        "Sugiére textos de enlace descriptivos o añadir contexto programático. "
        "Devuelve JSON: { suggestions: [{href?, current_text?, proposed_text?, "
        "aria_labelledby_ids_to_link?, sr_only_supplement?, rationale}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_4_4(
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
    applicable = int(details.get("applicable", 0) or 0)
    violations = int(details.get("missing_name", 0) or 0) + int(details.get("generic_no_context", 0) or 0)
    # Duplicados ambiguos suman como factor informativo; si existen y además son genéricos sin contexto → ya contados.

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
        level=meta.get("level", "A"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Propósito del enlace (en contexto)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
