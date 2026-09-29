"""Relatório semanal: relatorios/<pagina>/semana_AAAA-SS.md + resumo no Telegram."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import estado, metricas, telegram
from .config import PASTA_RELATORIOS, Pagina
from .registro import obter

log = obter("relatorio")


def _fmt(n) -> str:
    return f"{int(n):,}".replace(",", ".") if isinstance(n, (int, float)) else "-"


def semanal(p: Pagina) -> str:
    conta = metricas.coletar(p)
    ajustes = metricas.ajustar(p)
    metricas.checar_monetizacao(p, conta)
    agora = p.agora()
    inicio = agora - timedelta(days=7)
    hist = estado.historico(p)
    semana = [h for h in hist if h.get("publicado_em") and datetime.fromisoformat(h["publicado_em"]) >= inicio]
    com_m = sorted([h for h in hist if h.get("metricas")][-30:], key=lambda h: h["metricas"]["views_total"], reverse=True)
    serie = estado.ler(p, "metricas_conta", [])
    anterior = next((s for s in reversed(serie) if s.get("data", "") <= (agora - timedelta(days=7)).date().isoformat()), {})

    def seg(c: dict) -> dict:
        return {"YouTube (inscritos)": (c.get("youtube") or {}).get("inscritos"),
                "Instagram (seguidores)": (c.get("meta") or {}).get("instagram"),
                "Facebook (seguidores)": (c.get("meta") or {}).get("facebook")}

    atual_s, ant_s = seg(conta), seg(anterior)
    bloqueios = [b for b in estado.ler(p, "bloqueios", []) if b.get("em", "") >= inicio.isoformat()]
    fila = estado.fila(p)
    ano, sem, _ = agora.isocalendar()
    linhas = [f"# {p.nome} — Relatório da semana {sem:02d}/{ano}", "",
              f"Período: {inicio:%d/%m/%Y} a {agora:%d/%m/%Y} · gerado automaticamente", "",
              "## Crescimento", "", "| Rede | Agora | Semana passada | Variação |", "|---|---|---|---|"]
    for k, v in atual_s.items():
        a = ant_s.get(k)
        var = f"{(v or 0) - (a or 0):+d}" if isinstance(v, int) and isinstance(a, int) else "-"
        linhas.append(f"| {k} | {_fmt(v)} | {_fmt(a)} | {var} |")
    yt = conta.get("youtube") or {}
    linhas += ["", f"Horas assistidas no YouTube (365 dias): **{yt.get('horas_365d', '-')}** · "
               f"meta do nível de entrada: 500 inscritos + 3.000 h; programa completo: 1.000 + 4.000 h (8.000 h a partir de 01/02/2027).",
               "", "## Receita", "",
               "Ainda não monetizada. (Quando houver, a receita do YouTube entra aqui via YouTube Analytics; afiliados, pelo relatório de cada programa.)",
               "", f"## Posts publicados na semana ({len(semana)})", ""]
    for h in semana:
        v = (h.get("metricas") or {}).get("views_total", "-")
        links = " · ".join(f"[{k}]({x.get('url')})" for k, x in (h.get("publicacoes") or {}).items())
        linhas.append(f"- **{h['titulo']}** ({h['categoria']}, {h.get('horario')}) — {_fmt(v)} views — {links}")
    linhas += ["", "## 3 melhores (últimos 30 posts)", ""]
    linhas += [f"{i}. {h['titulo']} — {_fmt(h['metricas']['views_total'])} views ({h['categoria']})" for i, h in enumerate(com_m[:3], 1)] or ["(sem dados)"]
    linhas += ["", "## 3 piores (últimos 30 posts)", ""]
    linhas += [f"{i}. {h['titulo']} — {_fmt(h['metricas']['views_total'])} views ({h['categoria']})"
               for i, h in enumerate(list(reversed(com_m))[:3], 1)] or ["(sem dados)"]
    linhas += ["", "## Ajustes aplicados automaticamente", ""] + [f"- {a}" for a in ajustes]
    linhas += ["", "## Equipe de verificação", "",
               f"- Pautas barradas na semana: {len(bloqueios)}"] + [f"  - {b['tema']} ({b['decisao']})" for b in bloqueios[:10]]
    alertas = [a for i in fila for a in (i.get("equipe", {}).get("alertas_dossie") or [])]
    if alertas:
        linhas += ["- ⚠️ Alertas sobre a base de fatos (revisar pautas.yaml):"] + [f"  - {a}" for a in alertas[:10]]
    cont = {}
    for i in fila:
        cont[i["status"]] = cont.get(i["status"], 0) + 1
    linhas += ["", f"Fila atual: {cont}", ""]
    texto = "\n".join(linhas)
    pasta = PASTA_RELATORIOS / p.id
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"semana_{ano}-{sem:02d}.md"
    arq.write_text(texto, encoding="utf-8")
    resumo = (f"📊 {p.nome} — semana {sem:02d}\n"
              + "\n".join(f"{k}: {_fmt(v)}" for k, v in atual_s.items())
              + f"\nPosts na semana: {len(semana)} · barrados pela equipe: {len(bloqueios)}\n"
              + (f"🏆 Melhor: {com_m[0]['titulo']} ({_fmt(com_m[0]['metricas']['views_total'])} views)\n" if com_m else "")
              + "Ajustes: " + "; ".join(ajustes))
    telegram.enviar_texto(resumo)
    log.info("relatório salvo em %s", arq)
    return str(arq)
