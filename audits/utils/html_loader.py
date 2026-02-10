# audits/utils/html_loader.py
import requests
from bs4 import BeautifulSoup
from typing import Tuple, Dict, Any, Optional

DEFAULT_HEADERS = {
    "User-Agent": "FisiChecker/1.0 (+ WCAG 2.1 auditor)"
}

def fetch_html(
    url: str,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
    allow_redirects: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """
    Descarga HTML desde la URL y retorna (html_texto, meta_info).

    meta_info: dict con {status_code, url_final, elapsed_ms, encoding, content_type}
    """
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)

    r = requests.get(url, headers=hdrs, timeout=timeout, allow_redirects=allow_redirects)

    content_type = r.headers.get("Content-Type", "")
    # Forzar decode correcto cuando 'requests' no identifica bien
    if not r.encoding:
        # Usa encoding aparente si no hay (chardet/charset_normalizer lo infiere)
        r.encoding = r.apparent_encoding or "utf-8"
    html = r.text

    meta = {
        "status_code": r.status_code,
        "url_final": str(r.url),
        "elapsed_ms": int(r.elapsed.total_seconds() * 1000),
        "encoding": r.encoding,
        "content_type": content_type,
    }
    return html, meta

def make_soup(html: str) -> BeautifulSoup:
    """
    Construye un BeautifulSoup robusto usando lxml (si falla, fallback a html.parser).
    """
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        # Fallback a parser estándar
        return BeautifulSoup(html, "html.parser")


def soup_from_url(
    url: str,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[BeautifulSoup, Dict[str, Any]]:
    """
    Atajo: descarga la URL y devuelve (soup, meta).
    """
    html, meta = fetch_html(url, timeout=timeout, headers=headers)
    soup = make_soup(html)
    return soup, meta
