#!/usr/bin/env python
from audits.utils.rendered_loader import rendered_context_for_url

ctx, html = rendered_context_for_url('https://www.agrobanco.com.pe/inicio', 15000)

print(f"\nTotal de imágenes detectadas: {len(ctx.imgs)}\n")
print("=" * 120)

for i, img in enumerate(ctx.imgs, 1):
    src = img.get("src", "SIN SRC")[:70]
    alt = img.get("alt", "SIN ALT")[:50]
    role = img.get("role", "")
    aria_hidden = img.get("aria-hidden", "")
    
    decorative = "[DECORATIVA]" if (not alt or role=="presentation" or aria_hidden=="true") else "[CONTENIDO]"
    print(f"{i:2}. {decorative:12} src={src}...")
    if alt:
        print(f"     alt: '{alt}'")
    if role:
        print(f"     role: {role}")
    if aria_hidden:
        print(f"     aria-hidden: {aria_hidden}")
    
print("=" * 120)
