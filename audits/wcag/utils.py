import re
from typing import Optional, Tuple
import webcolors
from .constants import BAD_LINK_TEXT

def text_ok(txt: str) -> bool:
    if not txt: return False
    s = re.sub(r"\s+", " ", txt).strip().lower()
    if not s or s in BAD_LINK_TEXT: return False
    if re.fullmatch(r"https?://\S+", s): return False
    return len(s) >= 3

def hex_to_rgb(value: str) -> Optional[Tuple[int, int, int]]:
    try:
        v = value.strip()
        if not v.startswith("#"):
            return None
        if len(v) == 4:  # #RGB
            r = int(v[1] * 2, 16)
            g = int(v[2] * 2, 16)
            b = int(v[3] * 2, 16)
            return (r, g, b)
        if len(v) == 7:  # #RRGGBB
            r = int(v[1:3], 16)
            g = int(v[3:5], 16)
            b = int(v[5:7], 16)
            return (r, g, b)
    except Exception:
        pass
    return None

def parse_css_color(s: str) -> Optional[Tuple[int,int,int]]:
    if not s: return None
    s = s.strip().lower()
    rgb = hex_to_rgb(s)
    if rgb: return rgb
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) >= 3:
            try:
                r = int(float(parts[0])); g = int(float(parts[1])); b = int(float(parts[2]))
                return (max(0,min(255,r)), max(0,min(255,g)), max(0,min(255,b)))
            except Exception:
                return None
    try:
        c = webcolors.name_to_rgb(s)
        return (c.red, c.green, c.blue)
    except Exception:
        return None

def get_inline_style(el, prop: str) -> Optional[str]:
    style = el.get("style")
    if not style: return None
    for decl in style.split(";"):
        if ":" not in decl: continue
        name, val = decl.split(":", 1)
        if name.strip().lower() == prop.lower():
            return val.strip()
    return None

def relative_luminance(rgb: Tuple[int,int,int]) -> float:
    def ch(c):
        c = c/255.0
        return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
    r,g,b = rgb
    return 0.2126*ch(r) + 0.7152*ch(g) + 0.0722*ch(b)

def contrast_ratio(rgb1: Tuple[int,int,int], rgb2: Tuple[int,int,int]) -> float:
    L1 = relative_luminance(rgb1)+0.05
    L2 = relative_luminance(rgb2)+0.05
    return max(L1,L2)/min(L1,L2)

def is_large_text(tag_name: str, text: str) -> bool:
    return tag_name in {"h1","h2","h3"} or (len(text) >= 30 and tag_name == "p")
