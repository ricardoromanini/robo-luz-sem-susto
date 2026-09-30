"""Onde o vídeo pronto espera entre a geração e a publicação.

- local: fica em saida/<pagina>/<post>/ (seu PC)
- github_release: anexo de uma release do próprio repositório (nuvem). O GitHub Actions
  não guarda arquivos entre uma execução e outra, então a release funciona como "gaveta".
  Depois de publicado, o anexo é apagado.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from .config import na_nuvem
from .registro import obter

log = obter("armazenamento")
_API = "https://api.github.com"


def modo(glob: dict) -> str:
    m = glob.get("armazenamento", "auto")
    if m == "auto":
        return "github_release" if na_nuvem() else "local"
    return m


def _h() -> dict:
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}


def _repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def _release(tag: str) -> dict:
    r = requests.get(f"{_API}/repos/{_repo()}/releases/tags/{tag}", headers=_h(), timeout=30)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{_API}/repos/{_repo()}/releases", headers=_h(), timeout=30,
                      json={"tag_name": tag, "name": f"Fila de vídeos ({tag})", "body": "Gaveta automática do robô. Não apagar.",
                            "prerelease": True})
    r.raise_for_status()
    return r.json()


def guardar(glob: dict, pagina_id: str, arquivo: Path, nome: str | None = None) -> dict:
    """nome: nome único do anexo na nuvem (o GitHub recusa dois anexos com o mesmo nome)."""
    if modo(glob) == "local":
        return {"modo": "local", "caminho": str(arquivo)}
    nome = nome or arquivo.name
    rel = _release(f"fila-{pagina_id}")
    url = rel["upload_url"].split("{")[0]
    with open(arquivo, "rb") as f:
        r = requests.post(url, headers={**_h(), "Content-Type": "application/octet-stream"},
                          params={"name": nome}, data=f, timeout=600)
    r.raise_for_status()
    return {"modo": "github_release", "asset_id": r.json()["id"], "nome": nome}


def recuperar(ref: dict, destino_pasta: Path) -> Path:
    if ref["modo"] == "local":
        return Path(ref["caminho"])
    destino_pasta.mkdir(parents=True, exist_ok=True)
    dest = destino_pasta / ref["nome"]
    if dest.exists():
        return dest
    r = requests.get(f"{_API}/repos/{_repo()}/releases/assets/{ref['asset_id']}",
                     headers={**_h(), "Accept": "application/octet-stream"}, timeout=600, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for bloco in r.iter_content(1 << 20):
            f.write(bloco)
    return dest


def apagar(ref: dict) -> None:
    if ref.get("modo") != "github_release":
        return
    try:
        requests.delete(f"{_API}/repos/{_repo()}/releases/assets/{ref['asset_id']}", headers=_h(), timeout=30)
    except requests.RequestException as e:
        log.warning("não consegui apagar o anexo %s: %s", ref.get("nome"), e)
