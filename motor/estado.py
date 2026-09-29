"""Estado persistente de cada página (arquivos JSON pequenos em estado/<pagina>/).

Na nuvem, o GitHub Actions faz commit desta pasta ao final de cada execução,
então o "cérebro" da página sobrevive entre uma execução e outra.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Pagina


def _arq(pagina: Pagina, nome: str) -> Path:
    return pagina.pasta_estado / f"{nome}.json"


def ler(pagina: Pagina, nome: str, padrao=None):
    a = _arq(pagina, nome)
    if not a.exists():
        return padrao if padrao is not None else {}
    return json.loads(a.read_text(encoding="utf-8"))


def gravar(pagina: Pagina, nome: str, dados) -> None:
    a = _arq(pagina, nome)
    tmp = a.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(a)


# ---- Fila de posts --------------------------------------------------------
# Cada item: {id, status, criado_em, horario_publicacao, formato, categoria, titulo,
#             legenda, arquivos:{...}, parecer:{...}, publicacoes:{...}}
# status: aguardando_aprovacao | aprovado | publicado | descartado | refazer | bloqueado | erro

def fila(pagina: Pagina) -> list[dict]:
    return ler(pagina, "fila", [])


def salvar_fila(pagina: Pagina, itens: list[dict]) -> None:
    gravar(pagina, "fila", itens)


def atualizar_item(pagina: Pagina, post_id: str, **campos) -> dict | None:
    itens = fila(pagina)
    for it in itens:
        if it["id"] == post_id:
            it.update(campos)
            salvar_fila(pagina, itens)
            return it
    return None


def historico(pagina: Pagina) -> list[dict]:
    """Tudo o que já foi gerado e aprovado/publicado (usado contra repetição)."""
    return ler(pagina, "historico", [])


def adicionar_historico(pagina: Pagina, registro: dict) -> None:
    h = historico(pagina)
    h.append(registro)
    gravar(pagina, "historico", h[-1000:])
