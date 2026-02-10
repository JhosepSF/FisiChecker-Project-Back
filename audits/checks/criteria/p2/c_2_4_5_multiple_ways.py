# audits/checks/criteria/p2/c_2_4_5_multiple_ways.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.4.5"

# -------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------

_TOC_HINTS = ("table of contents", "contenido", "índice", "indice", "sumario", "contents")
_BREADCRUMB_HINTS = ("breadcrumb", "miga", "migas", "breadcrumbs")
_SITEMAP_HINTS = ("mapa del sitio", "site map", "sitemap")
_PROCESS_HINTS = ("paso", "step", "wizard", "checkout", "progreso", "progress", "stepper", "steps")

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
            return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text", "label", "aria-label", "title"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return t.strip()
        for k in ("aria-label", "title"):
            v = _get_attr(node, k)
            if v:
                return v.strip()
    except Exception:
        pass
    return ""

def _collect_links(ctx: PageContext) -> List[Any]:
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

# -------------------------------------------------------------
# Detección de “página en proceso lineal” (no aplicable)
# -------------------------------------------------------------

_STEP_RE = re.compile(r"\b(paso|step)\s*\d+(\s*(de|of)\s*\d+)?\b", re.I)

def _looks_like_process_page(ctx: PageContext) -> bool:
    """
    Si la página es parte de un proceso (asistente/checkout),
    2.4.5 puede considerarse NA. Heurísticas:
      - textos “Paso 1 de 4”, “Step 2 of 3”
      - aria-current="step" / role="progressbar" con steps
      - clases: stepper, wizard, checkout-step
    """
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            # aria-current="step"
            if soup.find(attrs={"aria-current": re.compile(r"^step$", re.I)}):
                return True
            # role="progressbar" con datos de steps
            if soup.find(attrs={"role": re.compile(r"^progressbar$", re.I)}):
                txt = soup.get_text() or ""
                if _STEP_RE.search(txt):
                    return True
            # clases típicas
            if soup.find(attrs={"class": re.compile(r"(stepper|wizard|checkout\-step|progress\-steps)", re.I)}):
                return True
            # texto “Paso X de Y”
            if _STEP_RE.search(soup.get_text() or ""):
                return True
        except Exception:
            pass

    # pistas del contexto
    title = _lower(getattr(ctx, "title_text", "") or "")
    if any(h in title for h in _PROCESS_HINTS):
        return True
    return False

# -------------------------------------------------------------
# Detección de mecanismos
# -------------------------------------------------------------

def _has_sitewide_nav(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    """
    Consideramos navegación global si hay landmark <nav> o role="navigation"
    con un número apreciable de enlaces (>=4).
    """
    soup = getattr(ctx, "soup", None)
    lm = getattr(ctx, "landmarks", {}) or {}
    has_nav_lm = bool(lm.get("nav"))
    count_links = 0
    try:
        if soup is not None:
            navs = soup.find_all(["nav"])
            if not navs:
                navs = soup.find_all(attrs={"role": re.compile(r"^navigation$", re.I)})
            for n in navs:
                try:
                    count_links += len(n.find_all("a"))
                except Exception:
                    continue
    except Exception:
        pass
    has_nav = has_nav_lm or (count_links >= 4)
    return has_nav, {"nav_links_count": count_links, "landmark_nav": has_nav_lm}

def _has_search(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    """
    Busca mecanismo de búsqueda:
      - landmark role="search"
      - <form role="search"> / input[type=search]
      - placeholder/aria-label “Buscar / Search”
    """
    soup = getattr(ctx, "soup", None)
    lm = getattr(ctx, "landmarks", {}) or {}
    has_search_lm = bool(lm.get("search"))

    found = False
    metas = {"by_role": False, "type_search": 0, "placeholders": 0}

    if soup is not None:
        try:
            # role="search"
            if soup.find(attrs={"role": re.compile(r"^search$", re.I)}):
                found = True; metas["by_role"] = True
            # input type="search"
            inputs = soup.find_all("input", attrs={"type": re.compile(r"^search$", re.I)})
            metas["type_search"] = len(inputs)
            if inputs:
                found = True
            # placeholders / aria-label
            ph = soup.find_all(attrs={"placeholder": re.compile(r"(buscar|search)", re.I)})
            al = soup.find_all(attrs={"aria-label": re.compile(r"(buscar|search)", re.I)})
            metas["placeholders"] = len(ph) + len(al)
            if ph or al:
                found = True
        except Exception:
            pass

    return (has_search_lm or found), {"landmark_search": has_search_lm, **metas}

def _has_breadcrumbs(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    """
    Detecta migas de pan:
      - <nav aria-label="breadcrumb">
      - clase 'breadcrumb'
      - microdatos schema.org BreadcrumbList
    """
    soup = getattr(ctx, "soup", None)
    meta = {"aria_breadcrumb": False, "class_breadcrumb": False, "schema_breadcrumb": False}
    found = False
    if soup is not None:
        try:
            if soup.find("nav", attrs={"aria-label": re.compile(r"breadcrumb", re.I)}):
                meta["aria_breadcrumb"] = True; found = True
            if soup.find(attrs={"class": re.compile(r"breadcrumb", re.I)}):
                meta["class_breadcrumb"] = True; found = True
            if soup.find(attrs={"itemtype": re.compile(r"BreadcrumbList", re.I)}):
                meta["schema_breadcrumb"] = True; found = True
        except Exception:
            pass
    return found, meta

def _has_toc_near_top(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    """
    Índice de contenidos cercano al inicio (ver 2.4.1).
    """
    soup = getattr(ctx, "soup", None)
    meta = {"labeled_nav": False, "heading_toc": False}
    if soup is None:
        return False, meta
    try:
        # nav/aside/section con aria-label tipo TOC
        candidates = soup.find_all(["nav","aside","section"])
        for n in candidates[:6]:
            label = _get_attr(n, "aria-label") or ""
            if any(k in _lower(label) for k in _TOC_HINTS):
                meta["labeled_nav"] = True
                return True, meta
            h = n.find(re.compile(r"^h[1-6]$", re.I))
            htxt = (h.get_text() or "") if h else ""
            if any(k in _lower(htxt) for k in _TOC_HINTS):
                meta["heading_toc"] = True
                return True, meta
    except Exception:
        pass
    return False, meta

def _has_sitemap_link(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    """
    Link a mapa del sitio: texto u href sugieren 'sitemap'.
    """
    links = _collect_links(ctx)
    found = False
    where = []
    for a in links:
        try:
            href = _get_attr(a, "href") or ""
            txt = _lower(_get_text(a))
            if any(h in txt for h in _SITEMAP_HINTS) or "sitemap" in href.lower() or href.lower().endswith("sitemap.xml"):
                found = True
                where.append({"href": href[:200], "text": (txt or "")[:120]})
        except Exception:
            continue
    return found, {"examples": where[:5]}

def _compute_mechanisms(ctx: PageContext) -> Tuple[List[str], Dict[str, Any]]:
    mech: List[str] = []
    meta_all: Dict[str, Any] = {}

    has_nav, meta_nav = _has_sitewide_nav(ctx)
    if has_nav:
        mech.append("sitewide_navigation")
    meta_all["nav"] = meta_nav

    has_search, meta_search = _has_search(ctx)
    if has_search:
        mech.append("site_search")
    meta_all["search"] = meta_search

    has_bc, meta_bc = _has_breadcrumbs(ctx)
    if has_bc:
        mech.append("breadcrumbs")
    meta_all["breadcrumbs"] = meta_bc

    has_toc, meta_toc = _has_toc_near_top(ctx)
    if has_toc:
        mech.append("table_of_contents")
    meta_all["toc"] = meta_toc

    has_map, meta_map = _has_sitemap_link(ctx)
    if has_map:
        mech.append("sitemap_link")
    meta_all["sitemap"] = meta_map

    return mech, meta_all

# -------------------------------------------------------------
# RAW
# -------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.5 (AA): Para páginas dentro de un conjunto, debe existir más de un método para localizar una página.
    Se aceptan mecanismos como: navegación global, búsqueda del sitio, migas de pan, índice/TOC, enlace a mapa del sitio.
    No aplica a páginas que son parte de un proceso (p. ej., paso de un asistente).
    """
    is_process = _looks_like_process_page(ctx)
    applicable = 0 if is_process else 1

    mechanisms, meta = _compute_mechanisms(ctx)
    distinct = sorted(set(mechanisms))
    count = len(distinct)

    passed = (applicable == 0) or (count >= 2)

    offenders: List[Dict[str, Any]] = []
    if applicable == 1 and count < 2:
        offenders.append({
            "reason": "Se detectó menos de dos vías para localizar la página.",
            "found": distinct,
            "hints": meta
        })

    details: Dict[str, Any] = {
        "applicable": applicable,
        "is_process_like": is_process,
        "mechanisms_found": distinct,
        "mechanisms_meta": meta,
        "count_mechanisms": count,
        "ok_ratio": 1.0 if (applicable == 0 or count >= 2) else 0.0,
        "offenders": offenders,
        "note": (
            "RAW: 2.4.5 requiere más de un método para localizar una página dentro de un conjunto. "
            "Se consideran navegación global, búsqueda del sitio, migas de pan, índice/TOC y enlace a mapa del sitio. "
            "Si la página es parte de un proceso lineal (asistente/checkout), el criterio no aplica."
        )
    }
    return details

# -------------------------------------------------------------
# RENDERED
# -------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer mecanismos cargados por JS:
      rctx.multiple_ways_test = {
        "has_search_runtime": bool,
        "has_breadcrumbs_runtime": bool,
        "has_nav_runtime": bool,
        "has_toc_runtime": bool,
        "has_sitemap_runtime": bool
      }
    Si no se provee, reusamos RAW sobre el contexto renderizado.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.5; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    rt = getattr(rctx, "multiple_ways_test", None)
    if not isinstance(rt, dict):
        d["note"] = (d.get("note","") + " | RENDERED: sin 'multiple_ways_test', se reusó RAW.").strip()
        return d

    # Añadimos mecanismos runtime
    runtime_mechs = []
    if rt.get("has_nav_runtime"): runtime_mechs.append("sitewide_navigation")
    if rt.get("has_search_runtime"): runtime_mechs.append("site_search")
    if rt.get("has_breadcrumbs_runtime"): runtime_mechs.append("breadcrumbs")
    if rt.get("has_toc_runtime"): runtime_mechs.append("table_of_contents")
    if rt.get("has_sitemap_runtime"): runtime_mechs.append("sitemap_link")

    existing = set(d.get("mechanisms_found", []))
    merged = sorted(existing | set(runtime_mechs))
    d["mechanisms_found"] = merged
    d["count_mechanisms"] = len(merged)

    # recomputar aprobación
    applicable = int(d.get("applicable", 0) or 0)
    d["ok_ratio"] = 1.0 if (applicable == 0 or len(merged) >= 2) else 0.0
    if applicable == 1 and len(merged) < 2:
        d["offenders"] = _as_list(d.get("offenders")) + [{
            "reason": "En ejecución también se detectó < 2 mecanismos.",
            "found": merged
        }]
    d["note"] = (d.get("note","") + " | RENDERED: mecanismos observados tras cargar JS.").strip()
    return d

# -------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere añadir al menos dos vías (p.ej. navegación global + búsqueda; migas + TOC).
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    applicable = int(details.get("applicable", 0) or 0)
    count = int(details.get("count_mechanisms", 0) or 0)
    if applicable == 0 or count >= 2:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "current_mechanisms": details.get("mechanisms_found", []),
        "hints": details.get("mechanisms_meta", {}),
        "html_snippet": (html_sample or "")[:2200],
        "suggestions_catalog": [
            "Añadir buscador del sitio con role='search' y <input type='search'>",
            "Incluir breadcrumbs (<nav aria-label='breadcrumb'>…)",
            "Exponer un enlace a ‘Mapa del sitio’ en el footer",
            "Añadir navegación global en <nav> con estructura de secciones",
            "Proveer índice (TOC) al inicio de páginas largas"
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.4.5 (Multiple Ways, AA). "
        "La página necesita al menos dos vías para localizar contenido. "
        "Sugiere dos o más mecanismos, con snippets mínimos (HTML/CSS/ARIA) y breve racional. "
        "Devuelve JSON: { suggestions: [{mechanism, snippet, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------

def run_2_4_5(
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
    count = int(details.get("count_mechanisms", 0) or 0)
    passed = (applicable == 0) or (count >= 2)

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
        title=meta.get("title", "Múltiples vías"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
