"""Acesso às IAs de texto com troca automática de provedor.

Provedores: gemini (Google AI Studio), groq, openrouter, ollama (local).
Se um provedor falhar (sem chave, cota estourada, erro), tenta o próximo da lista
definida em config/global.yaml (llm.redator / llm.verificador).
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

from .config import carregar_global, env
from .registro import obter

log = obter("llm")

# Permite forçar um provedor (ex.: LLM_FORCAR=ollama no PC para testes sem chave)
_FORCAR = os.environ.get("LLM_FORCAR", "").strip()


class SemProvedor(RuntimeError):
    pass


def _limpar_json(texto: str):
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.S)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        ini = min([i for i in (texto.find("{"), texto.find("[")) if i >= 0], default=-1)
        fim = max(texto.rfind("}"), texto.rfind("]"))
        if ini >= 0 and fim > ini:
            return json.loads(texto[ini : fim + 1])
        raise


def _gemini(modelo, sistema, usuario, temperatura, json_saida):
    chave = env("GEMINI_API_KEY")
    if not chave:
        raise SemProvedor("GEMINI_API_KEY ausente")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    if modelo.startswith("gemma"):  # Gemma não aceita instrução de sistema nem modo JSON: vai tudo no texto
        corpo = {"contents": [{"role": "user", "parts": [{"text": f"{sistema}\n\n---\n\n{usuario}"}]}],
                 "generationConfig": {"temperature": temperatura}}
    else:
        corpo = {
            "systemInstruction": {"parts": [{"text": sistema}]},
            "contents": [{"role": "user", "parts": [{"text": usuario}]}],
            "generationConfig": {"temperature": temperatura},
        }
        if json_saida:
            corpo["generationConfig"]["responseMimeType"] = "application/json"
    r = requests.post(url, params={"key": chave}, json=corpo, timeout=180)
    r.raise_for_status()
    partes = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in partes if not p.get("thought"))


def _openai_compat(base, chave_env, modelo, sistema, usuario, temperatura, json_saida, extra_headers=None):
    chave = env(chave_env)
    if not chave:
        raise SemProvedor(f"{chave_env} ausente")
    corpo = {
        "model": modelo,
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        "temperature": temperatura,
    }
    if json_saida:
        corpo["response_format"] = {"type": "json_object"}
    h = {"Authorization": f"Bearer {chave}"}
    h.update(extra_headers or {})
    r = requests.post(f"{base}/chat/completions", json=corpo, headers=h, timeout=180)
    if r.status_code == 400 and "json_validate_failed" in r.text and json_saida:
        corpo.pop("response_format", None)  # o modelo errou o formato: tenta de novo e extraímos o JSON do texto
        r = requests.post(f"{base}/chat/completions", json=corpo, headers=h, timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _ollama(modelo, sistema, usuario, temperatura, json_saida):
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    corpo = {
        "model": modelo,
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        "stream": False,
        "think": False,
        "options": {"temperature": temperatura, "num_ctx": 16384},
    }
    if json_saida:
        corpo["format"] = "json"
    try:
        r = requests.post(f"{base}/api/chat", json=corpo, timeout=900)
    except requests.ConnectionError as e:
        raise SemProvedor("Ollama não está rodando") from e
    r.raise_for_status()
    return r.json()["message"]["content"]


def _chamar(provedor, modelo, sistema, usuario, temperatura, json_saida):
    if provedor == "gemini":
        return _gemini(modelo, sistema, usuario, temperatura, json_saida)
    if provedor == "groq":
        return _openai_compat("https://api.groq.com/openai/v1", "GROQ_API_KEY", modelo, sistema, usuario, temperatura, json_saida)
    if provedor == "openrouter":
        return _openai_compat(
            "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", modelo, sistema, usuario, temperatura, json_saida,
            {"X-Title": "motor-redes-sociais"},
        )
    if provedor == "ollama":
        return _ollama(modelo, sistema, usuario, temperatura, json_saida)
    raise SemProvedor(f"provedor desconhecido: {provedor}")


def perguntar(papel: str, sistema: str, usuario: str, json_saida: bool = True, temperatura: float | None = None,
              evitar: str | None = None):
    """papel = 'redator' ou 'verificador'. Retorna dict (json_saida) ou str."""
    cfg = carregar_global()["llm"]
    cadeia = cfg[papel]
    forcar = os.environ.get(f"LLM_FORCAR_{papel.upper()}", "").strip() or _FORCAR
    if forcar:
        forcado = [c for c in cadeia if c["provedor"] == forcar]
        cadeia = forcado or [{"provedor": forcar, "modelo": os.environ.get("LLM_MODELO", "qwen3:14b")}]
    if temperatura is None:
        temperatura = cfg.get(f"temperatura_{papel}", 0.5)
    if evitar:  # ex.: o verificador nunca é o mesmo modelo que escreveu o roteiro
        filtrada = [c for c in cadeia if f"{c['provedor']}/{c['modelo']}" != evitar]
        cadeia = filtrada or cadeia
    erros = []
    for n, op in enumerate(cadeia):
        if f"{op['provedor']}/{op['modelo']}" in ESGOTADOS:
            erros.append(f"{op['provedor']}/{op['modelo']}: cota esgotada nesta execução")
            continue
        for tentativa in range(2):
            try:
                t0 = time.time()
                txt = _chamar(op["provedor"], op["modelo"], sistema, usuario, temperatura, json_saida)
                log.info("%s via %s/%s em %.0fs", papel, op["provedor"], op["modelo"], time.time() - t0)
                if n > 0:
                    log.warning("%s usou RESERVA %s/%s (falhas antes: %s)", papel, op["provedor"], op["modelo"], " | ".join(erros))
                ULTIMO_USO[papel] = f"{op['provedor']}/{op['modelo']}"
                return _limpar_json(txt) if json_saida else txt
            except SemProvedor as e:
                erros.append(f"{op['provedor']}/{op['modelo']}: {e}")
                break
            except requests.HTTPError as e:
                cod = e.response.status_code if e.response is not None else 0
                erros.append(f"{op['provedor']}/{op['modelo']}: HTTP {cod}")
                if cod == 429 and tentativa == 1:
                    # cota esgotada (2º 429 seguido): pula este modelo pelo resto da execução
                    ESGOTADOS.add(f"{op['provedor']}/{op['modelo']}")
                if cod in (429, 500, 503) and tentativa == 0:
                    time.sleep(20)
                    continue
                break
            except (json.JSONDecodeError, KeyError, IndexError, requests.RequestException) as e:
                erros.append(f"{op['provedor']}/{op['modelo']}: {type(e).__name__}")
                if tentativa == 0:
                    continue
                break
    raise SemProvedor("Nenhuma IA respondeu: " + " | ".join(erros))


ULTIMO_USO: dict[str, str] = {}  # papel -> "provedor/modelo" da última resposta (vai para o registro do post)
ESGOTADOS: set[str] = set()  # modelos com cota esgotada nesta execução
