# audits/utils/rendered_loader.py
from typing import Tuple
from bs4 import BeautifulSoup
import logging

# Playwright es opcional - solo requerido para modo RENDERED
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None

from ..wcag.context import build_context, PageContext

logger = logging.getLogger(__name__)

def rendered_context_for_url(url: str, timeout_ms: int = 60000) -> Tuple[PageContext, str]:
    """
    Abre la URL con Playwright, espera a networkidle y devuelve:
      - PageContext construido a partir del HTML renderizado
      - HTML de la página (por si quieres debug/almacenar)
    Requiere: pip install playwright && playwright install
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright no está disponible. El modo RENDERED requiere Python 3.7+ "
            "o instalar playwright manualmente. Use modo RAW o AI en su lugar."
        )
    
    logger.info(f"Iniciando Playwright para: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1366, "height": 768})
            page = context.new_page()
            logger.info(f"Navegando a {url}...")
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            html = page.content()
            logger.info(f"Pagina renderizada - HTML: {len(html)} chars")
        finally:
            browser.close()

    soup = BeautifulSoup(html, "lxml")
    ctx = build_context(soup)
    logger.info(f"Contexto construido - Imagenes: {len(ctx.imgs)}")
    return ctx, html
