"""Bot do Telegram: prévias com botões (Aprovar / Refazer / Descartar), alertas e comandos.

Comandos que você pode mandar para o bot:
  /status            situação da fila de cada página
  /pausar            pausa todas as publicações
  /retomar           retoma as publicações
  /piloto_on         liga o piloto automático (publica sem esperar seu toque)
  /piloto_off        volta para aprovação manual
  /ajuda             lista os comandos
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .config import env

API = "https://api.telegram.org/bot{token}/{metodo}"


def _ativo() -> bool:
    return bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"))


def _chamar(metodo: str, dados: dict | None = None, arquivos: dict | None = None, timeout: int = 120) -> dict:
    url = API.format(token=env("TELEGRAM_BOT_TOKEN"), metodo=metodo)
    r = requests.post(url, data=dados or {}, files=arquivos, timeout=timeout)
    r.raise_for_status()
    return r.json()


def enviar_texto(texto: str, botoes: list[list[dict]] | None = None) -> dict | None:
    if not _ativo():
        return None
    dados = {"chat_id": env("TELEGRAM_CHAT_ID"), "text": texto[:4000], "disable_web_page_preview": "true"}
    if botoes:
        dados["reply_markup"] = json.dumps({"inline_keyboard": botoes})
    return _chamar("sendMessage", dados)


def enviar_video(video: Path, legenda: str, botoes: list[list[dict]] | None = None) -> dict | None:
    if not _ativo():
        return None
    dados = {"chat_id": env("TELEGRAM_CHAT_ID"), "caption": legenda[:1000], "supports_streaming": "true"}
    if botoes:
        dados["reply_markup"] = json.dumps({"inline_keyboard": botoes})
    with open(video, "rb") as f:
        return _chamar("sendVideo", dados, {"video": (video.name, f, "video/mp4")}, timeout=600)


def botoes_aprovacao(pagina_id: str, post_id: str) -> list[list[dict]]:
    base = f"{pagina_id}|{post_id}"
    return [[
        {"text": "✅ Aprovar", "callback_data": f"ap|{base}"[:64]},
        {"text": "🔁 Refazer", "callback_data": f"rf|{base}"[:64]},
        {"text": "🗑 Descartar", "callback_data": f"dc|{base}"[:64]},
    ]]


def ler_atualizacoes(offset: int) -> list[dict]:
    if not _ativo():
        return []
    r = _chamar("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message", "callback_query"])})
    return r.get("result", [])


def responder_botao(callback_id: str, texto: str) -> None:
    try:
        _chamar("answerCallbackQuery", {"callback_query_id": callback_id, "text": texto[:190]})
    except requests.RequestException:
        # botão tocado há mais tempo (ex.: enquanto a geração rodava) não aceita resposta rápida: avisa por mensagem
        try:
            enviar_texto(texto)
        except requests.RequestException:
            pass


def do_dono(update: dict) -> bool:
    """Só aceita comandos vindos do SEU chat (segurança)."""
    chat = (update.get("message") or update.get("callback_query", {}).get("message") or {}).get("chat", {})
    return str(chat.get("id")) == str(env("TELEGRAM_CHAT_ID"))
