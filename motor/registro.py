"""Logs em arquivo/tela e alertas de erro no Telegram."""
from __future__ import annotations

import logging
import sys
import traceback

from .config import RAIZ

_PASTA_LOGS = RAIZ / "logs"
_PASTA_LOGS.mkdir(exist_ok=True)


def obter(nome: str = "motor") -> logging.Logger:
    log = logging.getLogger(nome)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    h1 = logging.StreamHandler(sys.stdout)
    h1.setFormatter(fmt)
    h2 = logging.FileHandler(_PASTA_LOGS / "motor.log", encoding="utf-8")
    h2.setFormatter(fmt)
    log.addHandler(h1)
    log.addHandler(h2)
    return log


def alertar_erro(contexto: str, exc: BaseException | None = None) -> None:
    """Registra o erro e avisa no Telegram (se configurado). Nunca levanta exceção."""
    log = obter()
    detalhe = "".join(traceback.format_exception(exc)) if exc else ""
    log.error("%s\n%s", contexto, detalhe)
    try:
        from . import telegram

        resumo = f"⚠️ ERRO no robô\n{contexto}"
        if exc:
            resumo += f"\n\n{type(exc).__name__}: {str(exc)[:600]}"
        telegram.enviar_texto(resumo)
    except Exception:  # noqa: BLE001 — alerta nunca pode derrubar o robô
        pass
