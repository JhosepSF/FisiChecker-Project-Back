# audits/wcag/context.py
import re
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from bs4.element import Tag
from urllib.parse import urlparse

@dataclass
class PageContext:
    soup: BeautifulSoup
    title_text: str
    lang: str
    meta_viewport: Optional[dict]
    imgs: List[Any]
    videos: List[Any]
    audios: List[Any]
    tables: List[Any]
    anchors: List[Any]
    buttons: List[Any]
    iframes: List[Any]
    inputs: List[Any]
    heading_tags: List[Any]
    labels_for: Dict[str, str]
    landmarks: Dict[str, bool]

def _attr_to_str(v: Any) -> str:
    """
    Convierte valores de atributos de BS4 (str | list | None | Unknown) a str seguro.
    Une listas con espacio; para None devuelve "".
    """
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        return " ".join(str(x) for x in v if x is not None)
    return str(v)

# Opcional 
try:
    from ftfy import fix_text as _ftfy_fix
except Exception:
    _ftfy_fix = None

try:
    import tldextract
except Exception:
    tldextract = None

# Overrides para nombres comerciales conocidos
DOMAIN_DISPLAY_OVERRIDES = {
    "bancoripley.com.pe": "Banco Ripley",
    "pichincha.pe": "Banco Pichincha",
    "banbif.com.pe": "BanBif",
    "bancognb.com.pe": "Banco GNB",
    "bancofalabella.pe": "Banco Falabella",
    "bn.com.pe": "Banco de la Nación",
    "viabcp.com": "BCP",
    "viabcp.com.pe": "BCP",
    "bancom.pe": "Banco de Comercio",
    "alfinbanco.pe": "Alfin Banco",
    "agrobanco.com.pe": "Agrobanco",
}

ACRONYM_WHITELIST = {"bcp", "gnb", "bbva", "bcr", "bn", "bif"}

def _fix_mojibake(text: str) -> str:
    if not text:
        return ""
    if _ftfy_fix:
        try:
            text = _ftfy_fix(text)
        except Exception:
            pass
    return text

def _looks_broken(text: str) -> bool:
    # señales típicas de mojibake o texto inválido
    return ("Ã" in text) or ("�" in text) or (len(text.strip()) < 3)

def _registrable_and_slug_from_url(url: str):
    host = urlparse(url).netloc.lower().split(":")[0]
    if tldextract:
        ext = tldextract.extract(url)
        registrable = f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain
        slug = ext.domain  # base para generar nombre
    else:
        # Heurística simple para .pe (com.pe, gob.pe, org.pe, edu.pe, etc.)
        parts = host.split(".")
        if len(parts) >= 3 and parts[-2] in {"com", "gob", "org", "edu", "net"} and parts[-1] == "pe":
            registrable = ".".join(parts[-3:])
            slug = parts[-3]
        else:
            registrable = ".".join(parts[-2:]) if len(parts) >= 2 else host
            slug = parts[-2] if len(parts) >= 2 else host
    return host, registrable, slug

def _friendly_from_slug(slug: str) -> str:
    # p.ej. "viabcp" -> "Via BCP" (luego se corrige con overrides a "BCP")
    slug = re.sub(r"[^a-z0-9]+", " ", slug.lower()).strip()
    words = []
    for w in slug.split():
        words.append(w.upper() if w in ACRONYM_WHITELIST else w.capitalize())
    friendly = " ".join(words).strip()
    return friendly or slug

def derive_site_name_from(url: str, soup) -> dict:
    """
    Devuelve un dict con:
      - registrable_domain: 'bancoripley.com.pe'
      - site_name_from_meta: si existe og:site_name / application-name
      - site_name_from_domain: amigable derivado del dominio (u override)
      - best_site_name: la mejor opción
    """
    host, registrable, slug = _registrable_and_slug_from_url(url)
    # 1) Overrides de branding
    domain_key = registrable
    site_name_from_domain = DOMAIN_DISPLAY_OVERRIDES.get(domain_key)
    if not site_name_from_domain:
        site_name_from_domain = _friendly_from_slug(slug)

    # 2) Meta og:site_name / application-name
    site_name_from_meta = None
    if soup:
        meta = soup.find("meta", attrs={"property": "og:site_name"})
        if not meta:
            meta = soup.find("meta", attrs={"name": "application-name"})
        if meta:
            site_name_from_meta = _fix_mojibake((meta.get("content") or "").strip())

    # 3) Selección final (meta prioritaria; si no, dominio)
    best = site_name_from_meta or site_name_from_domain

    return {
        "registrable_domain": registrable,
        "site_name_from_meta": site_name_from_meta,
        "site_name_from_domain": site_name_from_domain,
        "best_site_name": best,
    }

def choose_display_title(url: str, soup, raw_title: str) -> dict:
    """
    Elige el título a mostrar:
      - preferimos og:site_name
      - si el <title> está bien y no roto, puede usarse
      - si está roto o prefieres dominio, usamos el derivado del dominio
    """
    raw_fixed = _fix_mojibake(raw_title or "")
    domain_info = derive_site_name_from(url, soup)

    # Si el título viene roto o vacío, usamos el de dominio/meta
    if not raw_fixed or _looks_broken(raw_fixed):
        display = domain_info["best_site_name"]
        source = "domain_or_meta"
    else:
        # Si quieres forzar siempre “relacionado al dominio”, comenta estas 2 líneas:
        display = domain_info["best_site_name"]
        source = "domain_or_meta"
        # (Si prefieres dejar el <title> cuando está bien, usa:)
        # display = raw_fixed
        # source = "html_title"

    return {
        "display_title": display,
        "display_title_source": source,
        "page_title_raw_fixed": raw_fixed,
        "registrable_domain": domain_info["registrable_domain"],
    }

def _tag_to_dict(tag: Tag) -> Dict[str, Any]:
    """Convierte un Tag de BS4 a dict con atributos y propiedades útiles."""
    if not isinstance(tag, Tag):
        return {}
    d: Dict[str, Any] = dict(tag.attrs)
    d["tag"] = tag.name
    d["text"] = (tag.get_text() or "").strip()
    d["inner_html"] = str(tag.decode_contents()) if hasattr(tag, "decode_contents") else ""
    return d


def build_context(soup: BeautifulSoup) -> PageContext:
    # Título de la página
    title_text = ""
    title_tag = soup.title
    if isinstance(title_tag, Tag):
        try:
            if title_tag.string is not None:
                title_text = str(title_tag.string).strip()
            else:
                title_text = (title_tag.get_text() or "").strip()
        except Exception:
            title_text = (title_tag.get_text() or "").strip()

    # Idioma de la página
    lang = ""
    html_tag = soup.find("html")
    if isinstance(html_tag, Tag):
        lang = _attr_to_str(html_tag.get("lang")).strip().lower()

    # Meta viewport
    mv: Optional[Dict[str, str]] = None
    meta_viewport = soup.find("meta", attrs={"name": re.compile(r"viewport", re.I)})
    if isinstance(meta_viewport, Tag):
        mv = {"content": _attr_to_str(meta_viewport.get("content")).strip()}

    # Labels for inputs
    labels_for: Dict[str, str] = {}
    for lab in soup.find_all("label"):
        if not isinstance(lab, Tag):
            continue
        f = _attr_to_str(lab.get("for")).strip()
        if f:
            labels_for[f] = (lab.get_text() or "").strip()

    # Landmarks simples (solo presencia; no accedemos a atributos)
    landmarks = {
        "main": bool(soup.find(["main"]) or soup.find(attrs={"role": "main"})),
        "nav": bool(soup.find(["nav"]) or soup.find(attrs={"role": "navigation"})),
        "search": bool(soup.find(attrs={"role": "search"})),
        "contentinfo": bool(soup.find(attrs={"role": "contentinfo"})),
        "banner": bool(soup.find(attrs={"role": "banner"})),
        "complementary": bool(soup.find(attrs={"role": "complementary"})),
    }

    return PageContext(
        soup=soup,
        title_text=title_text,
        lang=lang,
        meta_viewport=mv,
        # Convertimos Tags a dicts para consistencia con los checks
        imgs=[_tag_to_dict(el) for el in soup.find_all("img") if isinstance(el, Tag)],
        videos=[_tag_to_dict(el) for el in soup.find_all("video") if isinstance(el, Tag)],
        audios=[_tag_to_dict(el) for el in soup.find_all("audio") if isinstance(el, Tag)],
        tables=[_tag_to_dict(el) for el in soup.find_all("table") if isinstance(el, Tag)],
        anchors=[_tag_to_dict(el) for el in soup.find_all("a") if isinstance(el, Tag)],
        buttons=[_tag_to_dict(el) for el in soup.find_all("button") if isinstance(el, Tag)],
        iframes=[_tag_to_dict(el) for el in soup.find_all("iframe") if isinstance(el, Tag)],
        inputs=[_tag_to_dict(el) for el in soup.find_all("input") if isinstance(el, Tag)] + [_tag_to_dict(el) for el in soup.find_all("select") if isinstance(el, Tag)] + [_tag_to_dict(el) for el in soup.find_all("textarea") if isinstance(el, Tag)],
        heading_tags=[_tag_to_dict(el) for el in soup.find_all(re.compile(r"^h[1-6]$", re.I)) if isinstance(el, Tag)],
        labels_for=labels_for,
        landmarks=landmarks,
    )
