"""TikTok via Content Posting API oficial (developers.tiktok.com).

Dois modos (paginas/<pagina>/config.yaml → plataformas.tiktok.modo):
- "rascunho": o vídeo vai para a caixa de entrada do app TikTok; você abre, cola a legenda e publica.
- "direto": o robô publica sozinho. Enquanto o app não passa na auditoria do TikTok, só é permitido
  publicar como PRIVADO (privacidade SELF_ONLY) — por isso o padrão é "rascunho".

Autorização: python main.py token-tiktok (gera TIKTOK_REFRESH_TOKEN_<PAGINA> no .env).
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import Pagina, env
from ..registro import obter

log = obter("tiktok")
API = "https://open.tiktokapis.com/v2"
ESCOPOS = "user.info.basic,video.upload,video.publish"
REDIRECT = "https://ricardoromanini.github.io/robo-luz-sem-susto/tiktok-callback.html"


def configurado(pagina: Pagina) -> bool:
    return bool(env("TIKTOK_CLIENT_KEY") and env("TIKTOK_CLIENT_SECRET") and env("TIKTOK_REFRESH_TOKEN", pagina.id))


def url_autorizacao(estado: str) -> str:
    from urllib.parse import urlencode

    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": env("TIKTOK_CLIENT_KEY", obrigatorio=True), "scope": ESCOPOS, "response_type": "code",
        "redirect_uri": REDIRECT, "state": estado})


def trocar_codigo(codigo: str) -> dict:
    r = requests.post(f"{API}/oauth/token/", timeout=30, headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
                            "code": codigo.strip(), "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    dados = r.json()
    if r.status_code >= 400 or "access_token" not in dados:
        raise RuntimeError(f"TikTok recusou o código: {dados.get('error_description') or dados}")
    return dados


def _acesso(pagina: Pagina) -> str:
    r = requests.post(f"{API}/oauth/token/", timeout=30, headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
                            "grant_type": "refresh_token", "refresh_token": env("TIKTOK_REFRESH_TOKEN", pagina.id)})
    dados = r.json()
    if "access_token" not in dados:
        raise RuntimeError(f"autorização do TikTok vencida ou inválida ({dados.get('error_description') or dados}); "
                           "rode: python main.py token-tiktok")
    novo = dados.get("refresh_token")
    if novo and novo != env("TIKTOK_REFRESH_TOKEN", pagina.id):
        # o TikTok trocou a chave de renovação: ela precisa ser atualizada no .env/Secrets (o robô avisa)
        log.warning("TikTok devolveu uma nova chave de renovação; atualize TIKTOK_REFRESH_TOKEN (token-tiktok)")
    return dados["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}


def _checar(r: requests.Response) -> dict:
    dados = r.json()
    erro = dados.get("error", {})
    if r.status_code >= 400 or (erro.get("code") not in (None, "ok")):
        raise RuntimeError(f"TikTok {r.status_code}: {erro.get('code')} — {erro.get('message')}")
    return dados.get("data", {})


def perfil(pagina: Pagina) -> dict:
    tok = _acesso(pagina)
    r = requests.get(f"{API}/user/info/", params={"fields": "open_id,display_name,avatar_url"}, headers=_h(tok), timeout=30)
    return _checar(r).get("user", {})


def publicar(pagina: Pagina, video: Path, legenda: str) -> dict:
    """Envia o vídeo ao TikTok (rascunho ou publicação direta, conforme a config). Devolve {"id", "url", "modo"}."""
    cfg = pagina.cfg.get("plataformas", {}).get("tiktok", {})
    modo = cfg.get("modo_api", "rascunho")
    tok = _acesso(pagina)
    tam = video.stat().st_size
    fonte = {"source": "FILE_UPLOAD", "video_size": tam, "chunk_size": tam, "total_chunk_count": 1}
    if modo == "direto":
        info = _checar(requests.post(f"{API}/post/publish/creator_info/query/", headers=_h(tok), json={}, timeout=30))
        opcoes = info.get("privacy_level_options") or ["SELF_ONLY"]
        privacidade = cfg.get("privacidade", "PUBLIC_TO_EVERYONE")
        if privacidade not in opcoes:
            privacidade = "SELF_ONLY" if "SELF_ONLY" in opcoes else opcoes[0]
        corpo = {"post_info": {"title": legenda[:2200], "privacy_level": privacidade, "is_aigc": True,
                               "disable_comment": False, "disable_duet": False, "disable_stitch": False},
                 "source_info": fonte}
        dados = _checar(requests.post(f"{API}/post/publish/video/init/", headers=_h(tok), json=corpo, timeout=60))
    else:
        dados = _checar(requests.post(f"{API}/post/publish/inbox/video/init/", headers=_h(tok),
                                      json={"source_info": fonte}, timeout=60))
    envio = requests.put(dados["upload_url"], data=video.read_bytes(), timeout=1800,
                         headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{tam - 1}/{tam}"})
    if envio.status_code >= 400:
        raise RuntimeError(f"TikTok recusou o envio do arquivo: {envio.status_code} {envio.text[:200]}")
    pid = dados["publish_id"]
    for _ in range(30):  # acompanha o processamento (até ~5 min)
        st = _checar(requests.post(f"{API}/post/publish/status/fetch/", headers=_h(tok), json={"publish_id": pid}, timeout=30))
        status = st.get("status", "")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            break
        if status == "FAILED":
            raise RuntimeError(f"TikTok não processou o vídeo: {st.get('fail_reason')}")
        time.sleep(10)
    arroba = cfg.get("arroba", "")
    return {"id": pid, "modo": modo,
            "url": (f"https://www.tiktok.com/{arroba}" if arroba else "") if modo == "direto" else "rascunho no app TikTok"}


PAINEL = "https://luz-sem-susto-painel.ricardoromanini9.workers.dev"


def link_painel(post_id: str, dias: int = 3, rota: str = "publicar") -> str:
    """Link assinado para o painel de publicação no TikTok (vale alguns dias). Usa TIKTOK_LINK_SECRET."""
    import hashlib
    import hmac
    from urllib.parse import urlencode

    segredo = env("TIKTOK_LINK_SECRET")
    if not segredo:
        return ""
    exp = int(time.time()) + dias * 86400
    sig = hmac.new(segredo.encode(), f"{post_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{PAINEL}/{rota}?" + urlencode({"post": post_id, "exp": exp, "sig": sig})
