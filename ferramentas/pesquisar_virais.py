"""Pesquisa os vídeos curtos MAIS VISTOS do nicho no YouTube (API oficial, só leitura) e gera um relatório
com os padrões (temas, ganchos, duração). Não copia conteúdo: serve para aprender o que o público procura.

Uso:  python ferramentas/pesquisar_virais.py            → relatorios/virais_<data>.md
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import motor  # noqa: E402,F401
import requests  # noqa: E402
from motor.config import carregar_env, env  # noqa: E402

BUSCAS = [
    "conta de luz", "economizar energia", "conta de luz cara", "chuveiro elétrico gasta", "choque elétrico em casa",
    "eletricista dicas", "tomada esquentando", "disjuntor desarmando", "energia solar vale a pena", "bandeira tarifária",
    "ar condicionado gasta muito", "aparelhos que mais gastam energia",
]


def _token() -> str:
    return requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": env("YOUTUBE_CLIENT_ID"), "client_secret": env("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": env("YOUTUBE_REFRESH_TOKEN_ENERGIA_EM_CASA"), "grant_type": "refresh_token"}).json()["access_token"]


def _dur(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def main() -> None:
    carregar_env()
    h = {"Authorization": "Bearer " + _token()}
    desde = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    vistos: dict[str, dict] = {}
    for q in BUSCAS:
        r = requests.get("https://www.googleapis.com/youtube/v3/search", headers=h, timeout=30, params={
            "part": "snippet", "q": q, "type": "video", "videoDuration": "short", "order": "viewCount",
            "regionCode": "BR", "relevanceLanguage": "pt", "publishedAfter": desde, "maxResults": 15}).json()
        for it in r.get("items", []):
            vistos.setdefault(it["id"]["videoId"], {"busca": q})
    ids = list(vistos)
    for i in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", headers=h, timeout=30, params={
            "part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50])}).json()
        for v in r.get("items", []):
            vistos[v["id"]].update({
                "titulo": v["snippet"]["title"], "canal": v["snippet"]["channelTitle"],
                "views": int(v["statistics"].get("viewCount", 0)), "likes": int(v["statistics"].get("likeCount", 0)),
                "comentarios": int(v["statistics"].get("commentCount", 0)), "dur": _dur(v["contentDetails"]["duration"]),
                "publicado": v["snippet"]["publishedAt"][:10]})
    lista = sorted([v for v in vistos.values() if "views" in v and v["dur"] <= 180], key=lambda v: -v["views"])
    linhas = [f"# Vídeos curtos mais vistos do nicho — YouTube Brasil (últimos 12 meses) — {date.today():%d/%m/%Y}", "",
              f"{len(lista)} vídeos analisados. Buscas: {', '.join(BUSCAS)}.", "",
              "| # | Visualizações | Curtidas | Duração | Título | Canal | Busca |", "|---|---|---|---|---|---|---|"]
    for n, v in enumerate(lista[:60], 1):
        linhas.append(f"| {n} | {v['views']:,} | {v['likes']:,} | {v['dur']} s | {v['titulo'][:90]} | {v['canal'][:30]} | {v['busca']} |".replace(",", "."))
    top = lista[:40]
    if top:
        durs = sorted(v["dur"] for v in top)
        linhas += ["", "## Números", f"- Duração mediana dos 40 mais vistos: {durs[len(durs) // 2]} s",
                   f"- Títulos com pergunta (?): {sum('?' in v['titulo'] for v in top)} de {len(top)}",
                   f"- Títulos com número: {sum(bool(re.search(r'\\d', v['titulo'])) for v in top)} de {len(top)}"]
    saida = RAIZ / "relatorios" / f"virais_{date.today():%Y-%m-%d}.md"
    saida.parent.mkdir(exist_ok=True)
    saida.write_text("\n".join(linhas), encoding="utf-8")
    print(saida)


if __name__ == "__main__":
    main()
