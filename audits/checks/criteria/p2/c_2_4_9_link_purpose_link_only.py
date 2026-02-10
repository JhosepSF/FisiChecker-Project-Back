# audits/checks/criteria/p2/c_2_4_9_link_purpose_link_only.py
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

CODE = "2.4.9"

# -------------------------------------------------------------------
# Utilidades compartidas
# -------------------------------------------------------------------

_GENERIC_PATTERNS = [
    r"^\s*(clic(k)?\s*aqu[ií]|haz\s*clic\s*aqu[ií]|click\s*here|here|aqui)\s*$",
    r"^\s*(m[aá]s|ver\s*m[aá]s|ver|leer\s*m[aá]s|read\s*more|more|learn\s*more|see\s*more)\s*$",
    r"^\s*(detalles?|details?|info|informaci[oó]n|saber\s*m[aá]s)\s*$",
    r"^\s*(continuar|seguir|ir|go|open|abrir|enlace|link)\s*$",
]
GENERIC_RE = re.compile("|".join(_GENERIC_PATTERNS), re.I)

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

def _get_attr(node: Any, name: str) -> Optional[str]:
    """Lectura segura de atributos desde dict o Tag."""
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

def _get_link_accname(node: Any) -> str:
    """
    Nombre accesible SOLO del enlace:
     - texto del <a> (incluye alt de <img> interno),
     - aria-label (aceptado),
     - aria-labelledby (aceptado, no miramos contexto externo; lo tomamos como nombre programático).
    NO usamos headings cercanos ni textos de contexto fuera del nombre accesible.
    """
    # dict
    if isinstance(node, dict):
        for k in ("accessible_name", "text", "aria-label", "title", "label"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # pistas de imagen enlazada
        for k in ("img_alt", "alt"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # aria-labelledby resuelto por el extractor (si existiera)
        v = node.get("aria_labelledby_text")
        if isinstance(v, str) and v.strip():
            return v.strip()
        return ""
    # Tag (BeautifulSoup)
    try:
        # un único <img> con alt cuenta como nombre
        if hasattr(node, "find_all"):
            imgs = node.find_all("img")
            if imgs and len(imgs) == 1:
                try:
                    alt = imgs[0].get("alt")  # type: ignore[attr-defined]
                    if isinstance(alt, str) and alt.strip():
                        return alt.strip()
                except Exception:
                    pass
        # aria-label sobre el propio <a>
        al = _get_attr(node, "aria-label")
        if al and al.strip():
            return al.strip()
        # texto del enlace
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return t.strip()
        # title como fallback
        ti = _get_attr(node, "title")
        if ti and ti.strip():
            return ti.strip()
    except Exception:
        pass
    return ""

def _is_applicable_link(a: Any) -> bool:
    tag = _lower(_get_attr(a, "tag") or (getattr(a, "name", "") if hasattr(a, "name") else ""))
    href = _get_attr(a, "href")
    role = _lower(_get_attr(a, "role"))
    if tag == "a" and href:
        return True
    if role == "link" and href:
        return True
    return False

def _link_text_is_generic(text: str) -> bool:
    if not text or not text.strip():
        return True
    return bool(GENERIC_RE.match(text.strip()))

def _iter_links(ctx: PageContext) -> List[Any]:
    links = _as_list(getattr(ctx, "anchors", []))
    if links:
        return links
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return list(soup.find_all("a"))
        except Exception:
            pass
    return []

# -------------------------------------------------------------------
# RAW
# -------------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.9 (AAA): El propósito de cada enlace debe poder determinarse por el
    TEXTO DEL ENLACE (nombre accesible) por sí solo, sin depender de contexto externo.
    Falla si:
      - el enlace no tiene nombre accesible,
      - el nombre es genérico ("Leer más", "Aquí", "Ver"),
      - hay múltiples enlaces con el MISMO nombre genérico apuntando a destinos distintos (ambigüedad).
    """
    links = _iter_links(ctx)
    applicable = 0
    determinable = 0
    missing_name = 0
    generic_text = 0
    duplicates_ambiguous = 0
    offenders: List[Dict[str, Any]] = []

    text_to_hrefs: Dict[str, Set[str]] = {}

    for a in links:
        try:
            if not _is_applicable_link(a):
                continue
            applicable += 1
            href = _s(_get_attr(a, "href"))
            acc = _get_link_accname(a)
            acc_norm = _lower(acc)

            if not acc_norm:
                missing_name += 1
                offenders.append({"href": href[:200], "text": acc, "reason": "Enlace sin nombre accesible."})
            elif _link_text_is_generic(acc):
                generic_text += 1
                offenders.append({"href": href[:200], "text": acc, "reason": "Nombre de enlace genérico; no describe el propósito por sí solo."})
            else:
                determinable += 1

            if acc_norm:
                s = text_to_hrefs.get(acc_norm, set())
                s.add(href)
                text_to_hrefs[acc_norm] = s
        except Exception:
            continue

    # Duplicados ambiguos: mismo accname → >=2 href distintos y ese accname es genérico
    for txt_norm, hrefs in text_to_hrefs.items():
        if len([h for h in hrefs if h]) >= 2 and GENERIC_RE.match(txt_norm or ""):
            duplicates_ambiguous += 1
            offenders.append({
                "text": txt_norm, "distinct_hrefs": min(len(hrefs), 20),
                "reason": "Mismo texto genérico enlaza a destinos distintos (ambigüedad)."
            })

    violations = missing_name + generic_text + duplicates_ambiguous
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, determinable / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "links_examined": applicable,
        "applicable": 1 if applicable > 0 else 0,
        "determinable": determinable,
        "missing_name": missing_name,
        "generic_text": generic_text,
        "duplicates_ambiguous": duplicates_ambiguous,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.4.9 exige que el propósito del enlace sea claro desde el propio nombre accesible del enlace. "
            "Se marca como violación enlaces sin nombre o con textos genéricos, y duplicados genéricos hacia destinos distintos."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED podemos usar nombres accesibles resueltos:
      rctx.links_accname = [{href, accessible_name, selector?, context_label?}, ...]
    (Ignoramos context_label para 2.4.9 a propósito).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.9; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "links_accname", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'links_accname', se reusó RAW.").strip()
        return d

    applicable = 0
    determinable = 0
    missing_name = 0
    generic_text = 0
    duplicates_ambiguous = 0
    offenders: List[Dict[str, Any]] = []
    text_to_hrefs: Dict[str, Set[str]] = {}

    for li in data:
        if not isinstance(li, dict):
            continue
        href = _s(li.get("href"))
        acc = _s(li.get("accessible_name"))
        if not href:
            continue
        applicable += 1
        if not acc.strip():
            missing_name += 1
            offenders.append({"href": href[:200], "text": acc, "reason": "Enlace sin nombre accesible (runtime)."})
        elif _link_text_is_generic(acc):
            generic_text += 1
            offenders.append({"href": href[:200], "text": acc, "reason": "Texto genérico (runtime)."})
        else:
            determinable += 1

        txt_norm = _lower(acc)
        if txt_norm:
            s = text_to_hrefs.get(txt_norm, set())
            s.add(href)
            text_to_hrefs[txt_norm] = s

    for txt_norm, hrefs in text_to_hrefs.items():
        if len([h for h in hrefs if h]) >= 2 and GENERIC_RE.match(txt_norm or ""):
            duplicates_ambiguous += 1
            offenders.append({"text": txt_norm, "distinct_hrefs": min(len(hrefs), 20),
                              "reason": "Mismo texto genérico enlaza a destinos distintos (runtime)."})

    violations = missing_name + generic_text + duplicates_ambiguous
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, determinable / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "rendered": True,
        "links_examined": applicable,
        "applicable": 1 if applicable > 0 else 0,
        "determinable": determinable,
        "missing_name": missing_name,
        "generic_text": generic_text,
        "duplicates_ambiguous": duplicates_ambiguous,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: evaluación usando nombres accesibles calculados por el runtime (AccName)."
    }
    return details

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone textos de enlace autoexplicativos o añadir texto oculto dentro del propio enlace (sr-only).
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("missing_name", 0) or 0) > 0 or (details.get("generic_text", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "missing_name": details.get("missing_name", 0),
            "generic_text": details.get("generic_text", 0),
            "duplicates_ambiguous": details.get("duplicates_ambiguous", 0),
        },
        "sample_offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "sr_only_hint": (
            ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;"
            "clip:rect(0,0,0,0);white-space:nowrap;border:0;}"
        ),
        "examples": [
            # reemplazo directo del texto del enlace
            {"current":"Leer más", "proposed":"Leer más sobre Becas 2025"},
            # suplemento sr-only dentro del <a>
            {"current":"Ver", "proposed_html":"Ver <span class='sr-only'>detalle del plan Premium</span>"}
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.4.9 (Link Purpose, Link Only, AAA). "
        "Para cada offender, propone un nombre accesible autoexplicativo (reemplazo del texto o "
        "añadir texto sr-only DENTRO del enlace). Devuelve JSON: "
        "{ suggestions: [{href?, current_text?, proposed_text?, proposed_html?, rationale}], "
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

def run_2_4_9(
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
    violations = int(details.get("missing_name", 0) or 0) + int(details.get("generic_text", 0) or 0) + int(details.get("duplicates_ambiguous", 0) or 0)
    passed = (applicable == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Propósito del enlace (solo el enlace)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
