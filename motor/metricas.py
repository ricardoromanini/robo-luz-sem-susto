"""MÉTRICAS: coleta o desempenho, ajusta temas/horários e acompanha os requisitos de monetização."""
from __future__ import annotations

from datetime import datetime

from . import estado, telegram
from .config import Pagina
from .publicar import meta, youtube
from .registro import obter

log = obter("metricas")

# Requisitos oficiais (conferidos em 29/09/2026 — ver pesquisa/1_plataformas.md). O agente
# "vigia de políticas" deve atualizar estes números quando as regras mudarem.
REQUISITOS_YT = {
    "entrada": {"inscritos": 500, "horas": 3000, "texto": "Nível de entrada do YouTube (assinaturas, Super Thanks, Shopping)"},
    "completo": {"inscritos": 1000, "horas": 4000, "texto": "Programa completo com anúncios (a partir de 01/02/2027: 8.000 horas)"},
}


def coletar(p: Pagina) -> dict:
    """Atualiza as métricas de cada post publicado (últimos 60) e da conta."""
    hist = estado.historico(p)
    publicados = [h for h in hist if h.get("publicacoes")][-60:]
    yt_ids = [h["publicacoes"]["youtube"]["id"] for h in publicados if "youtube" in h["publicacoes"]]
    yt = {}
    if yt_ids and youtube.configurado(p):
        try:
            yt = youtube.estatisticas_videos(p, yt_ids)
        except Exception as e:  # noqa: BLE001
            log.warning("métricas YouTube: %s", e)
    for h in publicados:
        m = {}
        pub = h["publicacoes"]
        if "youtube" in pub:
            m["youtube"] = yt.get(pub["youtube"]["id"], {})
        if "instagram" in pub:
            try:
                m["instagram"] = meta.metricas_instagram(p, pub["instagram"]["id"])
            except Exception as e:  # noqa: BLE001
                log.warning("métricas IG: %s", e)
        if "facebook" in pub:
            try:
                m["facebook"] = meta.metricas_facebook(p, pub["facebook"]["id"])
            except Exception as e:  # noqa: BLE001
                log.warning("métricas FB: %s", e)
        m["views_total"] = sum(int(v.get("views", 0) or 0) for v in m.values() if isinstance(v, dict))
        m["coletado_em"] = datetime.now().isoformat()
        h["metricas"] = m
    todos = {h["id"]: h for h in hist}
    for h in publicados:
        todos[h["id"]] = h
    estado.gravar(p, "historico", list(todos.values()))

    conta = {"data": p.agora().date().isoformat()}
    if youtube.configurado(p):
        try:
            conta["youtube"] = youtube.estatisticas_canal(p)
            conta["youtube"]["horas_365d"] = youtube.horas_assistidas_365d(p, conta["youtube"].get("canal_id"))
        except Exception as e:  # noqa: BLE001
            log.warning("canal YouTube: %s", e)
    if meta.ig_configurado(p) or meta.fb_configurado(p):
        conta["meta"] = meta.seguidores(p)
    serie = estado.ler(p, "metricas_conta", [])
    serie = [s for s in serie if s.get("data") != conta["data"]] + [conta]
    estado.gravar(p, "metricas_conta", serie[-400:])
    return conta


def ajustar(p: Pagina) -> list[str]:
    """Recalcula pesos por categoria e o melhor horário a partir do desempenho (mín. 3 posts por grupo)."""
    hist = [h for h in estado.historico(p) if h.get("metricas") and h.get("formato") == "short"][-60:]
    mudancas = []
    if len(hist) < 6:
        return ["poucos dados ainda (menos de 6 posts com métricas) — nenhum ajuste"]
    media_geral = sum(h["metricas"]["views_total"] for h in hist) / len(hist) or 1
    por_cat, por_hora = {}, {}
    for h in hist:
        por_cat.setdefault(h["categoria"], []).append(h["metricas"]["views_total"])
        por_hora.setdefault(h.get("horario", ""), []).append(h["metricas"]["views_total"])
    apr = estado.ler(p, "aprendizado", {})
    mult = apr.get("multiplicador_categoria", {})
    for cat, vals in por_cat.items():
        if len(vals) >= 3:
            novo = max(0.5, min(2.0, (sum(vals) / len(vals)) / media_geral))
            if abs(novo - mult.get(cat, 1.0)) >= 0.05:
                mudancas.append(f"peso de '{cat}': {mult.get(cat, 1.0):.2f} → {novo:.2f}")
            mult[cat] = round(novo, 2)
    horas_ok = {h: sum(v) / len(v) for h, v in por_hora.items() if h and len(v) >= 3}
    if horas_ok:
        melhor = max(horas_ok, key=horas_ok.get)
        if melhor != apr.get("melhor_horario"):
            mudancas.append(f"melhor horário: {apr.get('melhor_horario') or '-'} → {melhor}")
        apr["melhor_horario"] = melhor
    apr["multiplicador_categoria"] = mult
    apr["atualizado_em"] = datetime.now().isoformat()
    estado.gravar(p, "aprendizado", apr)
    return mudancas or ["sem mudanças relevantes"]


def checar_monetizacao(p: Pagina, conta: dict) -> list[str]:
    """Avisa (uma vez) quando a página atingir requisitos de monetização."""
    avisos = []
    ja = estado.ler(p, "avisos_monetizacao", {})
    yt = conta.get("youtube") or {}
    ins, horas = yt.get("inscritos", 0), yt.get("horas_365d") or 0
    for chave, req in REQUISITOS_YT.items():
        if ins >= req["inscritos"] and horas >= req["horas"] and not ja.get(chave):
            ja[chave] = p.agora().isoformat()
            avisos.append(f"💰 {p.nome} atingiu: {req['texto']}!\nPasso a passo: YouTube Studio > Ganhar dinheiro > "
                          "Inscrever-se > aceitar os termos > vincular/criar conta AdSense (dados fiscais e bancários). "
                          "A análise do YouTube leva cerca de 1 mês.")
    estado.gravar(p, "avisos_monetizacao", ja)
    for a in avisos:
        telegram.enviar_texto(a)
    return avisos
