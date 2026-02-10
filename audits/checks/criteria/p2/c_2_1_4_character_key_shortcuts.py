# audits/checks/criteria/p2/c_2_1_4_character_key_shortcuts.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.1.4"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

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

# ¿es una “single printable character”?
# Incluimos letras, dígitos y signos, y también el espacio (criterio habla de “letter (printable) character keys”).
def _is_single_char_key(k: str) -> bool:
    if not k or len(k) != 1:
        return False
    # cualquier carácter imprimible de longitud 1 (evita control chars)
    return k.isprintable()

# Mapas comunes de keyCode/which a caracteres (simplificado)
_KEYCODE_TO_CHAR = {}
# A–Z
for i in range(65, 91):
    _KEYCODE_TO_CHAR[i] = chr(i).lower()
# 0–9
for i in range(48, 58):
    _KEYCODE_TO_CHAR[i] = chr(i)
# Espacio
_KEYCODE_TO_CHAR[32] = " "

# Patrones para inferir shortcuts desde código/strings expuestos por el extractor
RE_KEY_EQ_CHAR = re.compile(r"""(?:event|e)\.key\s*===?\s*['"]([^'"]{1})['"]""", re.I)
RE_CODE_EQ = re.compile(r"""(?:event|e)\.(?:keyCode|which)\s*===?\s*(\d{1,3})""", re.I)
RE_HAS_MOD = re.compile(
    r"""(ctrlKey|metaKey|altKey|shiftKey)\s*===?\s*true|(?:event|e)\.(ctrlKey|metaKey|altKey|shiftKey)""",
    re.I
)
RE_SCOPE_FOCUS = re.compile(r"""(currentTarget|target|activeElement|:focus)""", re.I)

def _infer_from_handler_text(txt: str) -> Tuple[Optional[str], bool, bool]:
    """
    Intenta inferir:
      - char_key: 'j', 'k', ' ', '1', etc. (None si no se detecta single-char)
      - requires_modifier: True si se detectan ctrl/alt/meta
      - scoped_to_focus: True si el manejo parece restringido al foco del componente
    """
    if not txt:
        return None, False, False
    char_key: Optional[str] = None
    requires_mod = False
    scoped_focus = False

    m = RE_KEY_EQ_CHAR.search(txt)
    if m:
        candidate = m.group(1)
        if _is_single_char_key(candidate):
            char_key = candidate.lower()

    for m2 in RE_CODE_EQ.finditer(txt):
        try:
            kc = int(m2.group(1))
            if kc in _KEYCODE_TO_CHAR:
                char_key = _KEYCODE_TO_CHAR[kc]
        except Exception:
            pass

    if RE_HAS_MOD.search(txt):
        requires_mod = True
    if RE_SCOPE_FOCUS.search(txt):
        scoped_focus = True

    return char_key, requires_mod, scoped_focus

def _looks_like_shortcut_obj(o: Dict[str, Any]) -> bool:
    """
    Heurística: objeto ya identificado por el extractor como shortcut o handler relevante.
    Campos útiles (si existen): key, modifiers, active_globally, scoped_to_focus, can_disable, can_remap, handler_code.
    """
    if not isinstance(o, dict):
        return False
    if isinstance(o.get("key"), str) and o.get("key"):
        return True
    if o.get("handler_code") or o.get("listener_code") or o.get("inline_handler"):
        return True
    # metadatos explícitos
    for k in ("shortcut","keyboard_shortcut","single_key","active_globally"):
        if o.get(k) is not None:
            return True
    return False

# -------------------------------------------------------------------
# Núcleo RAW
# -------------------------------------------------------------------

def _collect_shortcut_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Fuente preferida: ctx.keyboard_shortcuts (si tu extractor la provee).
    Fallbacks: listeners globales, handlers inline característicos en ‘scripts’, o metadatos en componentes.
    """
    cands: List[Dict[str, Any]] = []

    # 1) Lista directa (ideal)
    for n in _as_list(getattr(ctx, "keyboard_shortcuts", [])):
        if isinstance(n, dict) and _looks_like_shortcut_obj(n):
            nn = dict(n); nn["__source"] = "keyboard_shortcuts"
            cands.append(nn)

    # 2) Handlers globales/listeners si el extractor los expone
    for n in _as_list(getattr(ctx, "global_event_listeners", [])):
        if isinstance(n, dict) and _looks_like_shortcut_obj(n):
            nn = dict(n); nn["__source"] = "global_event_listeners"
            cands.append(nn)

    # 3) Controles/componentes con posibles shortcuts asociados
    for src in ("buttons","links","form_controls","inputs","widgets","custom_components","menus","dialogs"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict) and _looks_like_shortcut_obj(n):
                nn = dict(n); nn["__source"] = src
                cands.append(nn)

    return cands

def _normalize_shortcut_obj(o: Dict[str, Any]) -> Dict[str, Any]:
    """
    Devuelve un dict normalizado con:
      key (posible single-char), requires_modifier, scoped_to_focus, active_globally, can_disable, can_remap
    """
    key_raw = _s(o.get("key") or o.get("char") or o.get("shortcut_key")).strip()
    handler_code = _s(o.get("handler_code") or o.get("listener_code") or o.get("inline_handler"))

    key: Optional[str] = None
    req_mod = False
    scoped = False

    if key_raw:
        # Si viene como 'j', 'k', 's', etc.
        if len(key_raw) == 1 and _is_single_char_key(key_raw):
            key = key_raw.lower()
        # Algunos extractores devuelven 'Space' o 'Spacebar'
        elif key_raw.lower() in ("space","spacebar"):
            key = " "
        # Si fuera "KeyJ", "Digit1", etc. no lo contamos como single-char aquí

    # Intenta inferir del código si no vino claro
    if key is None:
        inf_key, inf_mod, inf_scoped = _infer_from_handler_text(handler_code)
        if inf_key:
            key = inf_key
        req_mod = req_mod or inf_mod
        scoped = scoped or inf_scoped

    # Modificadores explícitos
    req_mod = req_mod or _bool(o.get("requires_ctrl")) or _bool(o.get("requires_alt")) or _bool(o.get("requires_meta"))
    scoped = scoped or _bool(o.get("scoped_to_focus"))

    active_globally = _bool(o.get("active_globally")) or _bool(o.get("global")) or _bool(o.get("document_level"))
    can_disable = _bool(o.get("can_disable")) or _bool(o.get("has_toggle_to_disable"))
    can_remap = _bool(o.get("can_remap")) or _bool(o.get("user_can_rebind"))

    return {
        "key": key,
        "requires_modifier": req_mod,
        "scoped_to_focus": scoped,
        "active_globally": active_globally and not scoped,  # si es scoped, no lo tratamos como global
        "can_disable": can_disable,
        "can_remap": can_remap,
        "source": o.get("__source") or o.get("source"),
        "id": _s(o.get("id")),
        "class": _s(o.get("class")),
        "handler_preview": handler_code[:160] if handler_code else "",
        "target": _s(o.get("target") or o.get("selector") or o.get("component")),
        "notes": _s(o.get("notes")),
    }

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.1.4 exige que los atajos de teclado basados únicamente en una tecla de carácter:
      (A) puedan desactivarse, o
      (B) puedan reasignarse (p. ej., para requerir un modificador), o
      (C) solo estén activos cuando el componente tiene el foco.

    Marcamos violación si hay atajo de “una sola tecla” que:
      - es global (activo sin foco), y
      - no requiere modificadores, y
      - no se puede desactivar ni reasignar.
    """
    cands = _collect_shortcut_candidates(ctx)
    normalized: List[Dict[str, Any]] = [_normalize_shortcut_obj(o) for o in cands]

    examined = len(normalized)
    applicable = 0
    single_char_total = 0
    with_modifiers = 0
    scoped_only = 0
    with_disable = 0
    with_remap = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for sc in normalized:
        key = sc.get("key")
        if not key:
            continue  # no es atajo de una sola tecla → fuera del alcance
        single_char_total += 1
        applicable += 1

        req_mod = bool(sc.get("requires_modifier"))
        scoped = bool(sc.get("scoped_to_focus"))
        global_active = bool(sc.get("active_globally"))
        can_disable = bool(sc.get("can_disable"))
        can_remap = bool(sc.get("can_remap"))

        if req_mod:
            with_modifiers += 1
        if scoped:
            scoped_only += 1
        if can_disable:
            with_disable += 1
        if can_remap:
            with_remap += 1

        # Violación si es single-char global sin mods y sin opciones A/B
        if (not req_mod) and global_active and (not can_disable) and (not can_remap) and (not scoped):
            violations += 1
            offenders.append({
                "key": key,
                "source": sc.get("source"),
                "id": sc.get("id"),
                "class": sc.get("class"),
                "target": sc.get("target"),
                "reason": "Atajo de una sola tecla activo globalmente sin modificadores y sin opción de desactivar o reasignar.",
                "handler_preview": sc.get("handler_preview")
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, (applicable - violations) / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "shortcuts_examined": examined,
        "applicable": applicable,
        "single_char_total": single_char_total,
        "with_modifiers": with_modifiers,     # cumplen por (B) si fuerzan combinaciones con Ctrl/Alt/Meta
        "scoped_only": scoped_only,           # cumplen por (C)
        "with_disable": with_disable,         # mecanismo (A)
        "with_remap": with_remap,             # mecanismo (B)
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.1.4 (Character Key Shortcuts). Violación si hay atajos de una sola tecla, activos globalmente, "
            "sin modificadores y sin opción de desactivar o reasignar. Se aceptan atajos que requieren Ctrl/Alt/Meta, "
            "que pueden desactivarse o reasignarse, o que están activos solo cuando el componente tiene foco."
        )
    }
    
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
        details["note"] += " | NA: no se detectaron atajos de una sola tecla."
    
    return details

# -------------------------------------------------------------------
# RENDERED (prueba real de atajos y preferencias)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, tu extractor puede exponer:
      rctx.shortcut_test = [
        {
          "key": "j",                      # tecla verificada
          "active_globally": bool,         # se dispara aunque ningún control tenga foco
          "requires_modifier": bool,       # solo funciona con Ctrl/Alt/Meta/Shift+algo
          "scoped_to_focus": bool,         # solo con foco en su componente
          "can_disable": bool,             # preferencia/setting para apagar
          "can_remap": bool,               # preferencia/setting para reasignar
          "fires_without_focus": bool,     # observación directa
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.1.4; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "shortcut_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'shortcut_test'.").strip()
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
            d["note"] += " | RENDERED→NA: sin atajos aplicables."
        return d

    applicable = 0
    violations = 0
    offenders = []

    for t in tests:
        key = _s(t.get("key"))
        if not key or len(key) != 1:
            continue
        applicable += 1
        global_active = bool(t.get("active_globally") or t.get("fires_without_focus"))
        req_mod = bool(t.get("requires_modifier"))
        scoped = bool(t.get("scoped_to_focus"))
        can_disable = bool(t.get("can_disable"))
        can_remap = bool(t.get("can_remap"))

        if (not req_mod) and global_active and (not can_disable) and (not can_remap) and (not scoped):
            violations += 1
            offenders.append({
                "key": key,
                "reason": "En ejecución: atajo de una sola tecla global sin modificadores ni opción de desactivar o reasignar.",
                "observed": {
                    "active_globally": global_active,
                    "requires_modifier": req_mod,
                    "scoped_to_focus": scoped,
                    "can_disable": can_disable,
                    "can_remap": can_remap
                }
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, (applicable - violations) / max(1, applicable))), 4)
    d.update({
        "applicable": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de alcance, modificadores y preferencias.").strip()
    })

    # ➜ NA si tras las pruebas no hubo atajos válidos a evaluar
    if applicable == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] += " | RENDERED→NA: sin atajos de una tecla verificados."
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone mitigaciones para 2.1.4:
      - Añadir preferencia para desactivar atajos de una tecla.
      - Permitir reasignar para requerir Ctrl/Alt/Meta (o combinaciones).
      - Limitar atajos a cuando el componente tiene foco (no global).
      - Evitar capturar letras sueltas a nivel de document si hay inputs/textarea presentes.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offs = details.get("offenders", []) or []
    if not offs and (details.get("violations", 0) or 0) == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "single_char_total": details.get("single_char_total", 0),
        },
        "offenders": offs[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.1.4 (Character Key Shortcuts, A). "
        "Para cada offender, propone fixes: "
        "- Opción de desactivar atajos de una tecla; "
        "- Reasignar para que requieran Ctrl/Alt/Meta; "
        "- Limitar atajo a cuando el componente tiene foco; "
        "- Evitar listeners globales que capturen letras mientras hay campos de entrada activos. "
        "Devuelve JSON: { suggestions: [{key, reason, ui_setting?, js_fix?, scope_fix?, remap_example?, notes?}], "
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

def run_2_1_4(
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
        manual_required = ai_info.get("manual_review", False)

    # 3) passed / verdict / score
    
    is_na = bool(details.get("na")) or int(details.get("applicable", 0) or 0) == 0
    if is_na:
        details["na"] = True
        if details.get("ok_ratio") == 1:
            details["ok_ratio"] = None
        details["note"] = (details.get("note","") + " | NA: sin atajos aplicables para 2.1.4.").strip()
        verdict = verdict_from_counts(details, True)  # 'passed' irrelevante para NA
        score0 = score_from_verdict(verdict)

        meta = WCAG_META.get(CODE, {})
        return CriterionOutcome(
            code=CODE,
            passed=False,  # irrelevante en NA
            verdict=verdict,
            score_0_2=score0,
            details=details,
            level=meta.get("level", "A"),
            principle=meta.get("principle", "Operable"),
            title=meta.get("title", "Atajos con una sola tecla"),
            source=src,
            score_hint=details.get("ok_ratio"),
            manual_required=False
        )

    passed = (int(details.get("violations", 0) or 0) == 0) or (int(details.get("applicable", 0) or 0) == 0)

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
        title=meta.get("title", "Atajos con una sola tecla"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
