"""Leitura das configurações (global + página) e das variáveis de ambiente."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

RAIZ = Path(__file__).resolve().parent.parent
PASTA_PAGINAS = RAIZ / "paginas"
PASTA_ESTADO = RAIZ / "estado"
PASTA_SAIDA = RAIZ / "saida"
PASTA_CACHE = RAIZ / "cache"
PASTA_RELATORIOS = RAIZ / "relatorios"


def carregar_env() -> None:
    """Carrega o arquivo .env (se existir) sem sobrescrever o que já está no ambiente.
    Também lê o client_secret_youtube.json (baixado do Google Cloud), se existir."""
    cs = RAIZ / "client_secret_youtube.json"
    if cs.exists():
        import json

        dados = json.loads(cs.read_text(encoding="utf-8"))
        info = dados.get("installed") or dados.get("web") or {}
        os.environ.setdefault("YOUTUBE_CLIENT_ID", info.get("client_id", ""))
        os.environ.setdefault("YOUTUBE_CLIENT_SECRET", info.get("client_secret", ""))
    arq = RAIZ / ".env"
    if not arq.exists():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip())


def env(nome: str, pagina: str | None = None, obrigatorio: bool = False) -> str:
    """Busca NOME_<PAGINA> primeiro e depois NOME."""
    candidatos = []
    if pagina:
        candidatos.append(f"{nome}_{pagina.upper().replace('-', '_')}")
    candidatos.append(nome)
    for c in candidatos:
        v = os.environ.get(c, "").strip()
        if v:
            return v
    if obrigatorio:
        raise RuntimeError(f"Variável de ambiente ausente: {' ou '.join(candidatos)}")
    return ""


def na_nuvem() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


@dataclass
class Pagina:
    id: str
    cfg: dict
    glob: dict
    pasta: Path = field(init=False)

    def __post_init__(self):
        self.pasta = PASTA_PAGINAS / self.id

    @property
    def nome(self) -> str:
        return self.cfg.get("nome", self.id)

    @property
    def pasta_estado(self) -> Path:
        p = PASTA_ESTADO / self.id
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def pasta_saida(self) -> Path:
        p = PASTA_SAIDA / self.id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def agora(self) -> datetime:
        return datetime.now(ZoneInfo(self.glob.get("fuso_horario", "America/Sao_Paulo")))

    def plataforma_ativa(self, nome: str) -> bool:
        return bool(self.cfg.get("plataformas", {}).get(nome, {}).get("ativa"))


def carregar_global() -> dict:
    return yaml.safe_load((RAIZ / "config" / "global.yaml").read_text(encoding="utf-8"))


def carregar_pagina(pagina_id: str) -> Pagina:
    arq = PASTA_PAGINAS / pagina_id / "config.yaml"
    if not arq.exists():
        raise FileNotFoundError(f"Página não encontrada: {arq}")
    cfg = yaml.safe_load(arq.read_text(encoding="utf-8"))
    return Pagina(pagina_id, cfg, carregar_global())


def listar_paginas(somente_ativas: bool = True) -> list[Pagina]:
    paginas = []
    for pasta in sorted(PASTA_PAGINAS.iterdir()):
        if (pasta / "config.yaml").exists():
            p = carregar_pagina(pasta.name)
            if p.cfg.get("ativa", True) or not somente_ativas:
                paginas.append(p)
    return paginas


def ler_yaml_pagina(pagina: Pagina, nome_arquivo: str, padrao=None):
    arq = pagina.pasta / nome_arquivo
    if not arq.exists():
        return padrao
    return yaml.safe_load(arq.read_text(encoding="utf-8"))
