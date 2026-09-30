"""Pesquisa na internet para o PESQUISADOR da equipe de verificação.

Fontes (só APIs oficiais):
- Wikipédia em português (API pública, sem chave): contexto sobre normas, aparelhos e conceitos;
- Tavily (opcional, TAVILY_API_KEY; plano grátis de 1.000 buscas/mês): busca na web restrita a sites
  confiáveis (governo, ANEEL, Inmetro, Procel, ABNT, Abracopel...).

O resultado é uma lista de EVIDÊNCIAS {titulo, url, trecho}. Falha de rede nunca derruba a geração:
sem evidência, o pesquisador só registra que não conseguiu conferir.
"""
from __future__ import annotations

import hashlib
import json
import re

import requests

from ..config import PASTA_CACHE, env
from ..registro import obter

log = obter("pesquisa")
_UA = {"User-Agent": "robo-luz-sem-susto/1.0 (https://github.com/ricardoromanini/robo-luz-sem-susto)"}
SITES_CONFIAVEIS = ["gov.br", "aneel.gov.br", "inmetro.gov.br", "procelinfo.com.br", "abnt.org.br", "abracopel.org",
                    "epe.gov.br", "ons.org.br", "ccee.org.br", "planalto.gov.br", "pt.wikipedia.org"]


def _wikipedia(consulta: str, limite: int = 2) -> list[dict]:
    api = "https://pt.wikipedia.org/w/api.php"
    r = requests.get(api, headers=_UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": consulta, "gsrlimit": limite,
        "prop": "extracts|info", "explaintext": 1, "exchars": 1500, "exlimit": limite, "inprop": "url"})
    r.raise_for_status()
    paginas = (r.json().get("query") or {}).get("pages") or {}
    return [{"titulo": p["title"], "url": p.get("fullurl", ""), "trecho": (p.get("extract") or "").strip()}
            for p in sorted(paginas.values(), key=lambda p: p.get("index", 0)) if p.get("extract")]


def _tavily(consulta: str, limite: int = 3) -> list[dict]:
    chave = env("TAVILY_API_KEY")
    if not chave:
        return []
    r = requests.post("https://api.tavily.com/search", timeout=45, headers={"Authorization": f"Bearer {chave}"},
                      json={"query": consulta, "max_results": limite, "include_domains": SITES_CONFIAVEIS,
                            "search_depth": "basic"})
    r.raise_for_status()
    return [{"titulo": x.get("title", ""), "url": x.get("url", ""), "trecho": (x.get("content") or "")[:1500]}
            for x in r.json().get("results", [])]


def pesquisar(consultas: list[str], max_evidencias: int = 8) -> list[dict]:
    """Evidências para as consultas (com cache em disco: a mesma pauta não pesquisa duas vezes no dia)."""
    consultas = [c.strip() for c in dict.fromkeys(consultas) if c and c.strip()][:5]
    if not consultas:
        return []
    PASTA_CACHE.mkdir(exist_ok=True)
    arq = PASTA_CACHE / ("pesquisa_" + hashlib.md5("|".join(consultas).encode()).hexdigest() + ".json")
    if arq.exists():
        return json.loads(arq.read_text(encoding="utf-8"))
    evidencias, vistos = [], set()
    for c in consultas:
        for fonte in (_tavily, _wikipedia):
            try:
                for e in fonte(c):
                    if e["url"] and e["url"] not in vistos and len(e["trecho"]) > 80:
                        vistos.add(e["url"])
                        evidencias.append(e)
            except (requests.RequestException, ValueError, KeyError) as e:
                log.warning("pesquisa %s('%s') falhou: %s", fonte.__name__, c[:40], e)
    evidencias = evidencias[:max_evidencias]
    if evidencias:
        arq.write_text(json.dumps(evidencias, ensure_ascii=False), encoding="utf-8")
    return evidencias


def normas_citadas(texto: str) -> list[str]:
    """Normas e leis citadas no texto (viram consultas de pesquisa)."""
    achados = re.findall(r"\b(?:ABNT\s+)?NBR\s?\d{3,5}\b|\bNR[- ]?\d{1,2}\b|\bLei\s+n?[ºo.]?\s?[\d.]+(?:/\d{2,4})?"
                         r"|\bResolu[çc][ãa]o\s+(?:Normativa\s+)?(?:ANEEL\s+)?n?[ºo.]?\s?[\d.]+(?:/\d{2,4})?", texto, re.I)
    return list(dict.fromkeys(a.strip() for a in achados))
