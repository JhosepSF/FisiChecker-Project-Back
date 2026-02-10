# audits/checks/criteria/p1/c_1_3_5_identify_input_purpose.py
from typing import Dict, Any, List, Optional, Tuple
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional (mismo mecanismo que 1.1.1–1.3.x)
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.3.5"

# -------------------------
# Utilidades y diccionarios
# -------------------------

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _as_list(x) -> List[Dict[str, Any]]:
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    # normaliza acentos y minúsculas
    s2 = unicodedata.normalize("NFKD", s)
    s2 = s2.encode("ascii", "ignore").decode("ascii")
    return s2.lower().strip()

# Lista (no exhaustiva) de tokens válidos (WHATWG Autofill)
_VALID_TOKENS = {
    # identidad
    "name","honorific-prefix","given-name","additional-name","family-name","honorific-suffix","nickname",
    # auth
    "username","new-password","current-password","one-time-code",
    # contacto
    "email","impp","photo","url","language",
    # telefono
    "tel","tel-country-code","tel-national","tel-area-code","tel-local","tel-local-prefix","tel-local-suffix","tel-extension",
    # organizacion
    "organization","organization-title",
    # direccion
    "street-address","address-line1","address-line2","address-line3",
    "address-level1","address-level2","address-level3","address-level4",
    "country","country-name","postal-code",
    # cumpleaños / sexo
    "bday","bday-day","bday-month","bday-year","sex",
    # tarjeta y transacciones
    "cc-name","cc-given-name","cc-additional-name","cc-family-name","cc-number","cc-exp","cc-exp-month","cc-exp-year","cc-csc","cc-type",
    "transaction-currency","transaction-amount",
}

# Equivalencias aceptables (ej.: tel vs tel-national)
_EQUIVS: Dict[str, List[str]] = {
    "tel": ["tel", "tel-national"],
    "country-name": ["country", "country-name"],  # aceptamos ambos si se usan en la wild
    "name": ["name","cc-name"],  # si el label sugiere "Nombre en tarjeta", el detector puede orientar a cc-name
}

# Heurísticos (ES/EN) → token esperado
_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # autenticacion
    (re.compile(r"\b(contrase[nñ]a actual|current password)\b"), "current-password"),
    (re.compile(r"\b(nueva|nuevo|repetir|repetida|confirmar).*(contrase[nñ]a|password)\b"), "new-password"),
    (re.compile(r"\b(contrase[nñ]a|password|pass)\b"), "current-password"),
    (re.compile(r"\b(usuario|user name|username|nombre de usuario)\b"), "username"),

    # identidad
    (re.compile(r"\b(nombre completo|full name)\b"), "name"),
    (re.compile(r"\b(nombres?|first name|given name)\b"), "given-name"),
    (re.compile(r"\b(apellidos?|last name|family name)\b"), "family-name"),
    (re.compile(r"\b(segundo nombre|middle name|additional name)\b"), "additional-name"),
    (re.compile(r"\b(tratamiento|prefijo|sr\.?|sra\.?|srta\.?|mr\.?|ms\.?|mrs\.?)\b"), "honorific-prefix"),

    # contacto
    (re.compile(r"\b(correo|e-?mail)\b"), "email"),
    (re.compile(r"\b(telefono|tel[eé]fono|celular|movil|m[oó]vil|phone)\b"), "tel"),
    (re.compile(r"\b(sitio web|pagina web|url|website)\b"), "url"),

    # organizacion
    (re.compile(r"\b(empresa|organizaci[oó]n|organizacion|company)\b"), "organization"),
    (re.compile(r"\b(cargo|puesto|title|job title)\b"), "organization-title"),

    # direccion
    (re.compile(r"\b(direccion|direcci[oó]n|address)\b"), "street-address"),
    (re.compile(r"\b(linea\s*1|line 1)\b"), "address-line1"),
    (re.compile(r"\b(linea\s*2|line 2)\b"), "address-line2"),
    (re.compile(r"\b(linea\s*3|line 3)\b"), "address-line3"),
    (re.compile(r"\b(departamento|provincia|estado|region|regi[oó]n)\b"), "address-level1"),
    (re.compile(r"\b(ciudad|municipio|localidad|city|town)\b"), "address-level2"),
    (re.compile(r"\b(distrito|barrio)\b"), "address-level3"),
    (re.compile(r"\b(pais|pa[ií]s|country)\b"), "country-name"),
    (re.compile(r"\b(c[oó]digo postal|postal code|zip)\b"), "postal-code"),

    # fecha nacimiento / sexo
    (re.compile(r"\b(fecha de nacimiento|cumplea[nñ]os|birthday|birth date)\b"), "bday"),
    (re.compile(r"\b(d[ií]a)\b"), "bday-day"),
    (re.compile(r"\b(mes)\b"), "bday-month"),
    (re.compile(r"\b(a[nñ]o|anio|year)\b"), "bday-year"),
    (re.compile(r"\b(sexo|genero|g[eé]nero|sex|gender)\b"), "sex"),

    # tarjeta
    (re.compile(r"\b(tarjeta|card)\b.*\b(nombre|name)\b"), "cc-name"),
    (re.compile(r"\b(n[uú]mero|number)\b.*\b(tarjeta|card)\b"), "cc-number"),
    (re.compile(r"\b(cvv|cvc|csc|security code)\b"), "cc-csc"),
    (re.compile(r"\b(vencimiento|expiraci[oó]n|expiry|exp)\b"), "cc-exp"),
    (re.compile(r"\b(mes)\b.*\b(venc|exp)\b"), "cc-exp-month"),
    (re.compile(r"\b(a[nñ]o|anio|year)\b.*\b(venc|exp)\b"), "cc-exp-year"),

    # transaccion
    (re.compile(r"\b(moneda|currency)\b"), "transaction-currency"),
    (re.compile(r"\b(monto|importe|amount)\b"), "transaction-amount"),

    # OTP
    (re.compile(r"\b(c[oó]digo de (verificaci[oó]n|seguridad)|otp|one[- ]time[- ]code)\b"), "one-time-code"),
]

def _infer_expected_token(ctrl: Dict[str, Any]) -> Optional[str]:
    """
    Deduce el token 'autocomplete' que debería usarse, a partir de:
    - type del input (email, tel, url, password, date...)
    - textos asociados (label, aria-label, title, placeholder, name/id)
    """
    tag = _norm(ctrl.get("tag"))
    ctrl_type = _norm(ctrl.get("type"))
    # pistas fuertes por tipo
    if tag in {"input","textarea","select"}:
        if ctrl_type == "email":
            return "email"
        if ctrl_type == "tel":
            return "tel"
        if ctrl_type == "url":
            return "url"
        if ctrl_type == "password":
            # distingamos por texto (new/current). Si no, 'current-password' por defecto
            text = " ".join([
                _norm(ctrl.get("label_text")),
                _norm(ctrl.get("aria-label")),
                _norm(ctrl.get("title")),
                _norm(ctrl.get("placeholder")),
                _norm(ctrl.get("name")),
                _norm(ctrl.get("id")),
            ])
            if re.search(r"\b(nueva|nuevo|repetir|confirmar)\b", text):
                return "new-password"
            return "current-password"

    # compón el “texto total” para heurística
    text = " ".join([
        _norm(ctrl.get("label_text")),
        _norm(ctrl.get("aria-label")),
        _norm(ctrl.get("title")),
        _norm(ctrl.get("placeholder")),
        _norm(ctrl.get("name")),
        _norm(ctrl.get("id")),
    ])

    for pat, tok in _PATTERNS:
        if pat.search(text):
            return tok

    return None  # no determinable programáticamente

def _parse_autocomplete(ac: str) -> Tuple[Optional[str], List[str], Optional[str]]:
    """
    Devuelve (base_token, modifiers, section) según la sintaxis:
      [section-*]? (shipping|billing)? (home|work|mobile|fax|pager)? <token>
    Tomamos el último token como base.
    """
    if not ac:
        return None, [], None
    parts = [p for p in re.split(r"\s+", ac.strip()) if p]
    if not parts:
        return None, [], None
    base = parts[-1].lower()
    section = None
    mods: List[str] = []
    for p in parts[:-1]:
        p = p.lower()
        if p.startswith("section-"):
            section = p
        else:
            mods.append(p)
    return base, mods, section

def _matches_expected(base: str, expected: str) -> bool:
    if base == expected:
        return True
    # equivalencias permisivas
    for k, vs in _EQUIVS.items():
        if expected == k and base in vs:
            return True
    return False

def _is_applicable_control(ctrl: Dict[str, Any]) -> bool:
    """
    Determina si el control probablemente recolecta datos propios del usuario.
    (Excluye hidden/submit/reset/button, sliders, etc.)
    """
    tag = _norm(ctrl.get("tag"))
    t = _norm(ctrl.get("type"))
    role = _norm(ctrl.get("role"))
    if tag not in {"input","select","textarea"} and role not in {"textbox","combobox","listbox"}:
        return False
    if t in {"hidden","button","submit","reset","image","file","range","color"}:
        return False
    # radiobutton/checkbox no suelen usar autocomplete de propósito (salvo sex, billing/shipping, etc.)
    if t in {"radio","checkbox"}:
        return False
    return True

# -------------------------
# Núcleo del criterio
# -------------------------

def _labelish(ctrl: Dict[str, Any]) -> str:
    for k in ("label_text", "aria-label", "title", "placeholder", "name", "id"):
        v = ctrl.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:120]
    return ""

def _get_autocomplete_value(ctrl: Dict[str, Any]) -> Optional[str]:
    """
    Obtiene el valor del atributo 'autocomplete' del control,
    tolerando variantes comunes que puedan traer los extractores.
    """
    for k in ("autocomplete", "autoComplete", "data-autocomplete"):
        v = ctrl.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None

def _is_behavior_only(ac: str) -> bool:
    # valores que solo controlan comportamiento del navegador, no identifican propósito
    return ac.lower() in {"on", "off"}

def _is_valid_token(token: Optional[str]) -> bool:
    return bool(token and token in _VALID_TOKENS)

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    1.3.5 (Identificar el propósito de la entrada): para entradas que recogen datos personales del usuario,
    se deben usar tokens estandarizados de 'autocomplete' (WHATWG) que identifiquen su propósito (email, tel, bday, etc.).
    Este check:
      - Deduce el token esperado (heurístico) por tipo y textos del control.
      - Verifica 'autocomplete' presente y válido.
      - Acepta modificadores (section-*, shipping/billing, home/work/mobile/fax/pager).
      - Señala 'on'/'off' como comportamiento (no válido para este criterio).
    """
    controls = _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or [])
    applicable = 0
    controls_examined = 0

    with_valid = 0                   # ac válido y coincide con lo esperado (o equivalente permitido)
    missing_autocomplete = 0         # se esperaba token pero no hay 'autocomplete'
    invalid_autocomplete = 0         # hay 'autocomplete' pero token base no es válido (ni on/off)
    behavior_only = 0                # 'autocomplete' == 'on'/'off'
    mismatched_autocomplete = 0      # ac válido, pero no coincide con el token esperado
    unknown_purpose = 0              # no se pudo inferir token esperado → no aplicable estricto

    offenders: List[Dict[str, Any]] = []

    for ctrl in controls:
        if not _is_applicable_control(ctrl):
            continue

        controls_examined += 1
        expected = _infer_expected_token(ctrl)

        if not expected:
            # No determinable programáticamente → no contamos como aplicable estricto
            unknown_purpose += 1
            continue

        applicable += 1
        ac_raw = _get_autocomplete_value(ctrl)

        if not ac_raw:
            missing_autocomplete += 1
            offenders.append({
                "id": ctrl.get("id", ""),
                "name": ctrl.get("name", ""),
                "tag": (ctrl.get("tag") or "").lower(),
                "type": (ctrl.get("type") or "").lower(),
                "label": _labelish(ctrl),
                "expected": expected,
                "autocomplete": None,
                "reason": "Falta atributo 'autocomplete' para un campo con propósito identificable."
            })
            continue

        if _is_behavior_only(ac_raw):
            behavior_only += 1
            offenders.append({
                "id": ctrl.get("id", ""),
                "name": ctrl.get("name", ""),
                "tag": (ctrl.get("tag") or "").lower(),
                "type": (ctrl.get("type") or "").lower(),
                "label": _labelish(ctrl),
                "expected": expected,
                "autocomplete": ac_raw,
                "reason": "Valor 'autocomplete' es 'on'/'off' (controla comportamiento, no identifica propósito)."
            })
            continue

        base, mods, section = _parse_autocomplete(ac_raw)
        
        if base is None:
            invalid_autocomplete += 1
            offenders.append({
                "id": ctrl.get("id", ""),
                "name": ctrl.get("name", ""),
                "tag": (ctrl.get("tag") or "").lower(),
                "type": (ctrl.get("type") or "").lower(),
                "label": _labelish(ctrl),
                "expected": expected,
                "autocomplete": ac_raw,
                "parsed_base": None,
                "mods": mods,
                "section": section,
                "reason": "Token base vacío tras parsear 'autocomplete'."
            })
            continue

        if not _is_valid_token(base):
            invalid_autocomplete += 1
            offenders.append({
                "id": ctrl.get("id", ""),
                "name": ctrl.get("name", ""),
                "tag": (ctrl.get("tag") or "").lower(),
                "type": (ctrl.get("type") or "").lower(),
                "label": _labelish(ctrl),
                "expected": expected,
                "autocomplete": ac_raw,
                "parsed_base": base,
                "mods": mods,
                "section": section,
                "reason": "Token base de 'autocomplete' no reconocido por el estándar."
            })
            continue

        if _matches_expected(base, expected):
            with_valid += 1
        else:
            mismatched_autocomplete += 1
            offenders.append({
                "id": ctrl.get("id", ""),
                "name": ctrl.get("name", ""),
                "tag": (ctrl.get("tag") or "").lower(),
                "type": (ctrl.get("type") or "").lower(),
                "label": _labelish(ctrl),
                "expected": expected,
                "autocomplete": ac_raw,
                "parsed_base": base,
                "mods": mods,
                "section": section,
                "reason": "El token 'autocomplete' no coincide con el propósito inferido."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, with_valid / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "controls_examined": controls_examined,
        "applicable": applicable,
        "with_valid": with_valid,
        "missing_autocomplete": missing_autocomplete,
        "invalid_autocomplete": invalid_autocomplete,
        "behavior_only": behavior_only,
        "mismatched_autocomplete": mismatched_autocomplete,
        "unknown_purpose": unknown_purpose,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.3.5 exige tokens de 'autocomplete' que identifiquen el propósito de campos de datos personales. "
            "Se comprueba presencia y validez del token base según WHATWG, aceptando modificadores y secciones. "
            "'on'/'off' no cuentan para este criterio. Los campos cuyo propósito no puede inferirse quedan como 'unknown_purpose'."
        )
    }

    # N/A si no hay controles o no hay campos con propósito inferible
    if controls_examined == 0 or applicable == 0:
        details["na"] = True

    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En modo RENDERED (Playwright) puedes mejorar:
      - Resolver 'aria-labelledby' a texto real, enriqueciendo _labelish().
      - Detectar 'autocomplete' aplicado por JS al montar el componente.
      - Confirmar propósito por iconos/ayudas visibles.
    Este stub reusa la lógica RAW sobre el contexto renderizado.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.3.5; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: nombres accesibles y 'autocomplete' dinámico detectados tras render.").strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si hay campos aplicables sin token válido, la IA sugiere el valor 'autocomplete' correcto,
    incluyendo opcionalmente modificadores (home/work, shipping/billing, section-*).
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    need_fixes = []
    for off in details.get("offenders", []):
        if off.get("reason", "").startswith("Falta") or \
           "no reconocido" in off.get("reason", "") or \
           "no coincide" in off.get("reason", "") or \
           "on'/'off" in off.get("reason", ""):
            need_fixes.append(off)

    if not need_fixes:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": need_fixes[:20],
        "html_snippet": (html_sample or "")[:2500],
        "valid_tokens": sorted(list(_VALID_TOKENS))[:60],
    }
    prompt = (
        "Eres auditor WCAG para 1.3.5 (Identificar el propósito de la entrada). "
        "Para cada offender, sugiere un valor 'autocomplete' correcto (incluyendo modificadores si aplica), "
        "basado en el 'expected' y el contexto (label/placeholder/name/id). "
        "Devuelve JSON: { suggestions: [{id, name, recommended_autocomplete, rationale}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_3_5(
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
        manual_required = ai_info.get("manual_required", False)

    # 3) passed / verdict / score
    if details.get("na") is True:
        verdict = "na"
        passed = False              # coherencia: sólo 'pass' cuando realmente pasa
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        applicable = details.get("applicable", 0)
        missing = details.get("missing_autocomplete", 0)
        invalid = details.get("invalid_autocomplete", 0)
        mismatched = details.get("mismatched_autocomplete", 0)
        behavior = details.get("behavior_only", 0)

        violations = missing + invalid + mismatched + behavior
        passed = (violations == 0)

        verdict = verdict_from_counts(details, passed)
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=(verdict == "pass"),
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Identificar el propósito de la entrada"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required
    )