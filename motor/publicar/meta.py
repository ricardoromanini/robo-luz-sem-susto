"""Instagram (Reels) e Facebook (Reels da Página) via Graph API oficial da Meta.

Upload "resumable" (o arquivo vai direto do robô para a Meta — não precisa de link público).
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import Pagina, env


def _v() -> str:
    return env("META_GRAPH_VERSION") or "v23.0"


def _tok(pagina: Pagina) -> str:
    return env("META_PAGE_TOKEN", pagina.id, obrigatorio=True)


def ig_configurado(pagina: Pagina) -> bool:
    return bool(env("META_PAGE_TOKEN", pagina.id) and env("IG_USER_ID", pagina.id))


def fb_configurado(pagina: Pagina) -> bool:
    return bool(env("META_PAGE_TOKEN", pagina.id) and env("FB_PAGE_ID", pagina.id))


def _erro(r: requests.Response) -> None:
    if r.status_code >= 400:
        raise RuntimeError(f"Meta API {r.status_code}: {r.text[:500]}")


def _ig_esperar(g: str, cont: str, tok: str, limite_s: int) -> str:
    """Espera o Instagram processar o contêiner. Devolve "" se ficou pronto, ou o motivo de não ter ficado."""
    fim = time.time() + limite_s
    while time.time() < fim:
        s = requests.get(f"{g}/{cont}", params={"fields": "status_code,status", "access_token": tok}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            return ""
        if s.get("status_code") == "ERROR":
            return f"recusou o vídeo: {s.get('status')}"
        time.sleep(10)
    return "não terminou de processar o vídeo a tempo"


def publicar_instagram(pagina: Pagina, video: Path, legenda: str, url_publica: str = "") -> dict:
    """Publica um Reel. 1º tenta o envio direto do arquivo ("resumable"); se a Meta não processar, tenta pelo
    endereço público do vídeo (url_publica), que é o método clássico da API."""
    tok, ig = _tok(pagina), env("IG_USER_ID", pagina.id, obrigatorio=True)
    g = f"https://graph.facebook.com/{_v()}"
    base = {"media_type": "REELS", "caption": legenda, "share_to_feed": "true", "access_token": tok}
    r = requests.post(f"{g}/{ig}/media", data={**base, "upload_type": "resumable"}, timeout=60)
    _erro(r)
    cont = r.json()["id"]
    # usa o endereço de envio que a própria Meta devolve (a versão dele pode ser mais nova que a configurada)
    destino = r.json().get("uri") or f"https://rupload.facebook.com/ig-api-upload/{_v()}/{cont}"
    dados = video.read_bytes()
    up = requests.post(destino, headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(dados))},
                       data=dados, timeout=1800)
    # A resposta do envio não é confiável (a Meta às vezes responde 400 e processa mesmo assim; às vezes responde e
    # não processa). Quem decide é o status do contêiner. Com erro no envio, espera pouco e parte para o plano B.
    erro_envio = f"Meta API {up.status_code}: {up.text[:200]}" if up.status_code >= 400 else ""
    motivo = _ig_esperar(g, cont, tok, 120 if (erro_envio and url_publica) else 480 if url_publica else 600)
    if motivo and url_publica:
        r = requests.post(f"{g}/{ig}/media", data={**base, "video_url": url_publica}, timeout=60)
        _erro(r)
        cont = r.json()["id"]
        motivo = _ig_esperar(g, cont, tok, 600)
    if motivo:
        raise RuntimeError(f"Instagram {motivo} {erro_envio}".strip())
    pub = requests.post(f"{g}/{ig}/media_publish", data={"creation_id": cont, "access_token": tok}, timeout=60)
    _erro(pub)
    mid = pub.json()["id"]
    link = requests.get(f"{g}/{mid}", params={"fields": "permalink", "access_token": tok}, timeout=30).json().get("permalink", "")
    return {"id": mid, "url": link}


def publicar_facebook(pagina: Pagina, video: Path, legenda: str) -> dict:
    tok, page = _tok(pagina), env("FB_PAGE_ID", pagina.id, obrigatorio=True)
    g = f"https://graph.facebook.com/{_v()}"
    ini = requests.post(f"{g}/{page}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60)
    _erro(ini)
    vid = ini.json()["video_id"]
    tam = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(f"https://rupload.facebook.com/video-upload/{_v()}/{vid}",
                           headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(tam)}, data=f, timeout=1800)
    _erro(up)
    fim = requests.post(f"{g}/{page}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                         "description": legenda, "access_token": tok}, timeout=60)
    _erro(fim)
    return {"id": vid, "url": f"https://www.facebook.com/reel/{vid}"}


def metricas_instagram(pagina: Pagina, media_id: str) -> dict:
    tok = _tok(pagina)
    r = requests.get(f"https://graph.facebook.com/{_v()}/{media_id}/insights",
                     params={"metric": "views,reach,likes,comments,shares,saved", "access_token": tok}, timeout=30)
    _erro(r)
    return {m["name"]: (m.get("values") or [{}])[0].get("value", m.get("total_value", {}).get("value", 0)) for m in r.json().get("data", [])}


def metricas_facebook(pagina: Pagina, video_id: str) -> dict:
    tok = _tok(pagina)
    r = requests.get(f"https://graph.facebook.com/{_v()}/{video_id}/video_insights", params={"access_token": tok}, timeout=30)
    _erro(r)
    saida = {}
    for m in r.json().get("data", []):
        val = (m.get("values") or [{}])[0].get("value", 0)
        if isinstance(val, (int, float)):
            saida[m["name"]] = val
    return {"views": saida.get("blue_reels_play_count", saida.get("fb_reels_total_plays", 0)), **saida}


def seguidores(pagina: Pagina) -> dict:
    tok, out = _tok(pagina), {}
    g = f"https://graph.facebook.com/{_v()}"
    try:
        out["instagram"] = requests.get(f"{g}/{env('IG_USER_ID', pagina.id)}", params={"fields": "followers_count", "access_token": tok},
                                        timeout=30).json().get("followers_count")
    except requests.RequestException:
        pass
    try:
        out["facebook"] = requests.get(f"{g}/{env('FB_PAGE_ID', pagina.id)}", params={"fields": "followers_count", "access_token": tok},
                                       timeout=30).json().get("followers_count")
    except requests.RequestException:
        pass
    return out


def validade_token(pagina: Pagina) -> int | None:
    """Dias até o token da Página vencer (None = não vence / não foi possível saber)."""
    tok = _tok(pagina)
    try:
        d = requests.get(f"https://graph.facebook.com/{_v()}/debug_token", params={"input_token": tok, "access_token": tok},
                         timeout=30).json().get("data", {})
        exp = d.get("data_access_expires_at") or d.get("expires_at")
        if not exp:
            return None
        return int((exp - time.time()) / 86400)
    except requests.RequestException:
        return None
