"""Módulo de IDEIAS: monta as pautas candidatas e escolhe a próxima sem repetir.

Pautas vêm de duas fontes:
  1. Dados oficiais (ANEEL): reajustes recentes, bandeira do mês, calculadoras, ranking, taxa mínima.
  2. Banco de pautas atemporais da página (paginas/<p>/pautas.yaml), cada uma com seus fatos.

A escolha usa os pesos por categoria (config + aprendizado das métricas) e evita
temas já usados (histórico) — notícias têm prioridade enquanto são novidade.
"""
from __future__ import annotations

import random
from datetime import date

from . import estado
from .config import Pagina, ler_yaml_pagina
from .fontes import aneel
from .registro import obter

log = obter("ideias")


def _chaves_usadas(pagina: Pagina) -> set[str]:
    usados = {h.get("chave") for h in estado.historico(pagina)}
    usados |= {i.get("chave") for i in estado.fila(pagina) if i.get("status") not in ("descartado", "bloqueado")}
    return usados


def _pesos(pagina: Pagina) -> dict[str, float]:
    base = {k: float(v.get("peso", 1)) for k, v in pagina.cfg.get("categorias", {}).items()}
    aprendido = estado.ler(pagina, "aprendizado", {}).get("multiplicador_categoria", {})
    return {k: base[k] * float(aprendido.get(k, 1.0)) for k in base}


def candidatas(pagina: Pagina) -> list[dict]:
    """Lista de pautas possíveis agora (cada uma já com o dossiê de fatos)."""
    usadas = _chaves_usadas(pagina)
    lista: list[dict] = []

    def add(d: dict, urgente: bool = False):
        if d and d["chave"] not in usadas:
            d["urgente"] = urgente
            lista.append(d)

    # --- notícias / dados oficiais --------------------------------------------------
    try:
        for r in aneel.reajustes_recentes(dias=30):
            add(aneel.dossie_reajuste(r), urgente=True)
        b = aneel.bandeiras()["acionamentos"][0]
        if b["DatCompetencia"][:7] == date.today().isoformat()[:7] and date.today().day <= 20:  # bandeira é notícia no início do mês
            add(aneel.dossie_bandeira(), urgente=True)
        mapa = list(aneel.distribuidoras())
        random.shuffle(mapa)
        for sig in mapa[:8]:
            if aneel.tarifa_vigente(sig):
                add(aneel.dossie_calculadora(sig, random.choice(list(aneel.APARELHOS))))
                add(aneel.dossie_taxa_minima(sig))
        add(aneel.dossie_ranking())
    except Exception as e:  # noqa: BLE001 — sem ANEEL, seguimos com as pautas atemporais
        log.warning("ANEEL indisponível agora (%s); usando só pautas atemporais", e)

    # --- pautas atemporais da página ------------------------------------------------
    for p in ler_yaml_pagina(pagina, "pautas.yaml", []) or []:
        fatos = [{"id": f"F{i + 1}", "texto": f["texto"], "fonte": f.get("fonte", ""), "url": f.get("url", "")}
                 for i, f in enumerate(p["fatos"])]
        ress = [pagina.cfg.get("ressalvas", {}).get("seguranca")] if p.get("aviso_seguranca") else []
        add({"tema": p["tema"], "categoria": p["categoria"], "chave": f"pauta:{p['id']}", "fatos": fatos,
             "busca_base": p.get("busca", ""),
             "ressalvas": [r for r in ress if r], "grafico": None})
    return lista


def escolher(pagina: Pagina, n: int = 1, excluir: set[str] | None = None) -> list[dict]:
    """Escolhe N pautas: primeiro as urgentes (notícia), depois sorteio ponderado por categoria."""
    excluir = excluir or set()
    cands = [c for c in candidatas(pagina) if c["chave"] not in excluir]
    if not cands:
        return []
    pesos = _pesos(pagina)
    escolhidas: list[dict] = []
    urgentes = [c for c in cands if c.get("urgente")]
    # no máximo 1 notícia por dia para não virar página só de reajuste
    if urgentes:
        escolhidas.append(urgentes[0])
    restantes = [c for c in cands if c not in escolhidas]
    # evita repetir categoria e "assunto" (ex.: o mesmo aparelho) dos últimos posts publicados E dos que estão na fila
    na_fila = [i for i in estado.fila(pagina) if i.get("status") in ("aguardando_aprovacao", "aprovado")]
    ultimos = estado.historico(pagina)[-3:] + na_fila
    recentes = [h.get("categoria") for h in ultimos]
    assuntos_recentes = {":".join(str(h.get("chave", "")).split(":")[:2]) for h in ultimos}
    while len(escolhidas) < n and restantes:
        w = [pesos.get(c["categoria"], 1.0)
             * (0.25 if c["categoria"] in recentes else 1.0)
             * (0.05 if ":".join(c["chave"].split(":")[:2]) in assuntos_recentes else 1.0)
             for c in restantes]
        c = random.choices(restantes, weights=w, k=1)[0]
        escolhidas.append(c)
        restantes = [r for r in restantes if r["categoria"] != c["categoria"]] or [r for r in restantes if r is not c]
    return escolhidas[:n]
