"""YouTube Data API v3 — upload com rótulo de conteúdo sintético.

Atenção: enquanto o projeto do Google Cloud não passar pela auditoria da API,
o YouTube deixa os vídeos enviados por API como PRIVADOS (regra do YouTube).
Nesse período o bot avisa e você muda para "Público" no app (1 toque).
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from ..config import Pagina, env

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
           "https://www.googleapis.com/auth/yt-analytics.readonly"]


def configurado(pagina: Pagina) -> bool:
    return bool(env("YOUTUBE_CLIENT_ID") and env("YOUTUBE_CLIENT_SECRET") and env("YOUTUBE_REFRESH_TOKEN", pagina.id))


def token_acesso(pagina: Pagina) -> str:
    r = requests.post(TOKEN_URL, data={
        "client_id": env("YOUTUBE_CLIENT_ID", obrigatorio=True),
        "client_secret": env("YOUTUBE_CLIENT_SECRET", obrigatorio=True),
        "refresh_token": env("YOUTUBE_REFRESH_TOKEN", pagina.id, obrigatorio=True),
        "grant_type": "refresh_token",
    }, timeout=30)
    if r.status_code == 400 and "invalid_grant" in r.text:
        raise RuntimeError("Token do YouTube vencido/revogado. Rode: python main.py token-youtube --pagina " + pagina.id)
    r.raise_for_status()
    return r.json()["access_token"]


def publicar(pagina: Pagina, video: Path, titulo: str, descricao: str, tags: list[str], rotulo_ia: bool,
             capa: str | None = None) -> dict:
    tok = token_acesso(pagina)
    cfg = pagina.cfg.get("plataformas", {}).get("youtube", {})
    meta = {
        "snippet": {"title": titulo[:100], "description": descricao[:4900], "tags": [t.lstrip("#") for t in tags][:15],
                    "categoryId": str(cfg.get("categoria_id", "27")), "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR"},
        "status": {"privacyStatus": cfg.get("privacidade", "public"), "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": bool(rotulo_ia and cfg.get("rotulo_ia", True)), "embeddable": True},
    }
    tam = video.stat().st_size
    ini = requests.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                                 "X-Upload-Content-Length": str(tam), "X-Upload-Content-Type": "video/mp4"},
                        data=json.dumps(meta), timeout=60)
    ini.raise_for_status()
    with open(video, "rb") as f:
        up = requests.put(ini.headers["Location"], headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"},
                          data=f, timeout=1800)
    up.raise_for_status()
    dados = up.json()
    vid = dados["id"]
    if capa:
        try:
            with open(capa, "rb") as f:
                requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": vid},
                              headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"}, data=f, timeout=120)
        except requests.RequestException:
            pass  # miniatura personalizada exige canal verificado; não é crítico
    privado = dados.get("status", {}).get("privacyStatus") == "private"
    return {"id": vid, "url": f"https://youtu.be/{vid}", "privado": privado}


def estatisticas_videos(pagina: Pagina, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    tok = token_acesso(pagina)
    saida = {}
    for i in range(0, len(ids), 50):
        r = requests.get(f"{API}/videos", params={"part": "statistics", "id": ",".join(ids[i:i + 50])},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        r.raise_for_status()
        for it in r.json().get("items", []):
            s = it["statistics"]
            saida[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                               "comentarios": int(s.get("commentCount", 0))}
    return saida


def estatisticas_canal(pagina: Pagina) -> dict:
    tok = token_acesso(pagina)
    r = requests.get(f"{API}/channels", params={"part": "statistics,snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    r.raise_for_status()
    it = (r.json().get("items") or [{}])[0]
    s = it.get("statistics", {})
    return {"inscritos": int(s.get("subscriberCount", 0)), "views_total": int(s.get("viewCount", 0)),
            "videos": int(s.get("videoCount", 0)), "canal_id": it.get("id")}


def horas_assistidas_365d(pagina: Pagina, canal_id: str) -> float | None:
    """Horas de exibição de vídeos (YouTube Analytics). Pode falhar se o escopo não foi autorizado."""
    from datetime import date, timedelta
    try:
        tok = token_acesso(pagina)
        r = requests.get("https://youtubeanalytics.googleapis.com/v2/reports", headers={"Authorization": f"Bearer {tok}"},
                         params={"ids": "channel==MINE", "startDate": (date.today() - timedelta(days=365)).isoformat(),
                                 "endDate": date.today().isoformat(), "metrics": "estimatedMinutesWatched"}, timeout=30)
        r.raise_for_status()
        linhas = r.json().get("rows") or [[0]]
        return round(linhas[0][0] / 60, 1)
    except (requests.RequestException, KeyError, IndexError):
        return None
