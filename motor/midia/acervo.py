"""Acervo visual brasileiro: fotos reais de referência para os objetos que a IA de imagem desenha no padrão
errado (tomada, plugue, chuveiro elétrico...). Ver paginas/<pagina>/acervo/acervo.yaml."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import PASTA_PAGINAS, Pagina


@lru_cache(maxsize=8)
def _ler(pagina_id: str) -> dict:
    arq = PASTA_PAGINAS / pagina_id / "acervo" / "acervo.yaml"
    return (yaml.safe_load(arq.read_text(encoding="utf-8")) or {}) if arq.exists() else {}


def _bate(padroes: list[str], texto: str) -> bool:
    return any(re.search(p, texto, re.I) for p in padroes or [])


def casar(pagina: Pagina, texto: str) -> dict | None:
    """Objeto do acervo citado no texto da cena (fala + descrição), já com o caminho da foto de referência."""
    for obj in _ler(pagina.id).get("objetos", []):
        ref = pagina.pasta / "acervo" / obj["referencia"]
        if ref.exists() and _bate(obj.get("gatilhos"), texto):
            return {**obj, "arquivo": Path(ref)}
    return None


def sem_referencia(pagina: Pagina, texto: str) -> bool:
    """True se a cena pede um objeto que a IA desenha errado e que ainda não tem foto de referência."""
    return _bate(_ler(pagina.id).get("sem_referencia"), texto)


def regra_geral(pagina: Pagina) -> str:
    return (_ler(pagina.id).get("regra_geral") or "").strip()
