#!/usr/bin/env python
from audits.utils.rendered_loader import rendered_context_for_url

url = 'https://www.agrobanco.com.pe/credito-agricola'
ctx, html = rendered_context_for_url(url, 15000)

print(f"\nTotal de imagenes detectadas: {len(ctx.imgs)}\n")
print("=" * 130)

for i, img in enumerate(ctx.imgs, 1):
    src = img.get("src", "SIN SRC")[:80]
    alt = img.get("alt", "SIN ALT")[:50]
    role = img.get("role", "")
    aria_hidden = img.get("aria-hidden", "")
    
    decorative = "[DECORATIVA]" if (not alt or role=="presentation" or aria_hidden=="true") else "[CONTENIDO]"
    print(f"{i:2}. {decorative:12} {src}")
    
print("=" * 130)
