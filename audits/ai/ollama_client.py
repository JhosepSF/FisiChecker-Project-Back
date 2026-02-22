# audits/ai/ollama_client.py
import os
import json
import re
import requests
from typing import Optional, Dict, Any, List, Union, Tuple
from django.conf import settings
import logging

logger = logging.getLogger('audits.ai')
logger.error('Mensaje de error o traceback')

# === Config basado en settings o entorno ===
OLLAMA_HOST = getattr(settings, "OLLAMA_HOST", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
DEFAULT_MODEL = getattr(settings, "OLLAMA_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1:latest"))


class OllamaClientError(Exception):
    pass


def _build_options(temperature: float, max_tokens: int, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Construye el objeto 'options' seguro para Ollama."""
    opts: Dict[str, Any] = {
        "temperature": float(temperature),
        "num_predict": int(max_tokens),
    }
    if isinstance(options, dict):
        opts.update(options)
    return opts


def ollama_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 800,
    options: Optional[Dict[str, Any]] = None,
    timeout: int = 300,
) -> str:
    """
    Llama a /api/chat con una lista de mensajes:
    [{"role":"system"/"user"/"assistant","content":"..."}].
    Retorna el contenido final del asistente como string (NUNCA None).
    """
    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload: Dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
        "options": _build_options(temperature, max_tokens, options),
    }

    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {}) if isinstance(data, dict) else {}
        content = msg.get("content") if isinstance(msg, dict) else ""
        return (content or "").strip()
    except Exception as e:
        import traceback
        logger.error("Ollama chat error: %s\n%s", str(e), traceback.format_exc())
        raise OllamaClientError(f"Ollama chat error: {e}")


def ollama_generate(
    prompt: str,
    model: Optional[str] = None,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 800,
    json_mode: bool = False,
    options: Optional[Dict[str, Any]] = None,
    timeout: int = 300,
) -> str:
    """
    Intento de /api/generate (single prompt).
    Si el servidor responde 404 (endpoint no soportado), se usa /api/chat como fallback.
    Retorna texto (string), nunca None.
    """
    url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    base_prompt = prompt
    if json_mode:
        base_prompt += "\n\nResponde SOLO en JSON válido, sin comentarios ni texto adicional."

    payload: Dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "prompt": base_prompt,
        "stream": False,
        "options": _build_options(temperature, max_tokens, options),
    }

    # 'system' no está formalmente soportado en /api/generate → lo inyectamos en el prompt.
    if system:
        payload["prompt"] = f"SISTEMA:\n{system.strip()}\n\nUSUARIO:\n{payload['prompt']}"

    try:
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code == 404:
            # fallback limpio a chat
            messages: List[Dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            u_prompt = base_prompt
            if json_mode:
                u_prompt += "\n\nResponde SOLO en JSON válido."
            messages.append({"role": "user", "content": u_prompt})
            return ollama_chat(
                messages=messages,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                options=options,
                timeout=timeout,
            )
        r.raise_for_status()
        data = r.json()
        content = data.get("response") if isinstance(data, dict) else ""
        return (content or "").strip()
    except requests.exceptions.HTTPError as he:
        import traceback
        logger.error("Ollama generate HTTP error: %s\n%s", str(he), traceback.format_exc())
        if he.response is not None and he.response.status_code == 404:
            messages2: List[Dict[str, str]] = []
            if system:
                messages2.append({"role": "system", "content": system})
            u_prompt = base_prompt
            if json_mode:
                u_prompt += "\n\nResponde SOLO en JSON válido."
            messages2.append({"role": "user", "content": u_prompt})
            return ollama_chat(
                messages=messages2,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                options=options,
                timeout=timeout,
            )
        raise OllamaClientError(f"Ollama generate HTTP error: {he}") from he
    except Exception as e:
        import traceback
        logger.error("Ollama generate error: %s\n%s", str(e), traceback.format_exc())
        raise OllamaClientError(f"Ollama generate error: {e}")


# =========================
# Normalización de respuestas
# =========================

def _strip_code_fences(text: str) -> str:
    """Quita ```...``` o ```json ...``` para facilitar el parseo."""
    if not text:
        return ""
    # elimina fences de bloque
    text = re.sub(r"^\s*```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```\s*$", "", text, flags=re.I)
    return text.strip()


def _try_json_variants(txt: str) -> Tuple[bool, Union[Dict[str, Any], List[Any], None], Optional[str]]:
    """
    Intenta parsear JSON en varias formas:
      - texto completo
      - primer objeto {...}
      - primer array [...]
    Devuelve (ok, obj, error_msg)
    """
    if not txt:
        return False, None, "empty"

    s = _strip_code_fences(txt)

    # 1) Intento directo
    try:
        obj = json.loads(s)
        return True, obj, None
    except Exception as e1:
        err1 = str(e1)

    # 2) Extraer primer objeto { ... }
    try:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            obj = json.loads(m.group(0))
            return True, obj, None
    except Exception as e2:
        err2 = str(e2)
    else:
        err2 = None

    # 3) Extraer primer array [ ... ]
    try:
        m = re.search(r"\[.*\]", s, re.S)
        if m:
            obj = json.loads(m.group(0))
            return True, obj, None
    except Exception as e3:
        err3 = str(e3)
    else:
        err3 = None

    # Join errores informativos
    joined_errs = "; ".join([e for e in (err1, err2, err3) if e])
    return False, None, joined_errs or "json parse failed"


def _coerce_to_dict(obj: Any) -> Dict[str, Any]:
    """
    Garantiza dict:
      - dict → dict
      - list → {"data": list}
      - str  → {"text": str}
      - None → {"text": ""}
      - otro → {"data": obj}
    """
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        return {"data": obj}
    if isinstance(obj, (bytes, bytearray)):
        try:
            return {"text": obj.decode("utf-8", "ignore")}
        except Exception:
            return {"data": obj}
    if isinstance(obj, str):
        return {"text": obj}
    if obj is None:
        return {"text": ""}
    return {"data": obj}


# =========================
# API de alto nivel (SIEMPRE dict)
# =========================

def ask_json(
    prompt: str,
    context: str = "",
    system: str = "",
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 800,
    timeout: int = 300,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    Pide explícitamente JSON usando /api/chat (y/o generate como alternativa si adaptas).
    GARANTIZA devolver Dict[str, Any] para que el resto del código pueda usar .get(...) sin romper.
    """
    # Construimos un mensaje único (chat-like) para robustez.
    user_prompt = prompt
    if context:
        user_prompt += f"\n\nContexto (JSON/Texto):\n{context[:8000]}"
    user_prompt += "\n\nResponde SOLO en JSON válido (sin backticks ni comentarios)."

    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_prompt})

    last_text = ""
    for attempt in range(max_retries + 1):
        try:
            txt = ollama_chat(
                messages=messages,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            last_text = txt or ""
            ok, obj, err = _try_json_variants(last_text)
            if ok:
                # Asegurar dict
                return _coerce_to_dict(obj)
        except Exception as e:
            import traceback
            logger.error("ask_json error: %s\n%s", str(e), traceback.format_exc())
            last_text = f"LLM error: {e}"

        # Reintento: reforzar instrucción
        if attempt < max_retries:
            messages[-1]["content"] += "\n\nATENCIÓN: Responde SOLO en JSON plano (objeto o arreglo) sin ``` ni explicaciones."
            continue

    # Fallback si falla todo → SIEMPRE dict
    return {
        "text": last_text,
        "parse_error": True,
        "message": "No fue posible parsear la respuesta del modelo como JSON válido.",
    }
