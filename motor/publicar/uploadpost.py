"""TikTok pelo Upload-Post (upload-post.com) — serviço com integração aprovada na Content Posting API do TikTok.
Publica direto como PÚBLICO, com legenda e rótulo de conteúdo gerado por IA, sem toque no app.

Configuração: UPLOAD_POST_API_KEY no .env/Secrets e, na página, plataformas.tiktok.via: uploadpost +
plataformas.tiktok.perfil_uploadpost: <nome do perfil criado no painel do Upload-Post>.
Documentação: https://docs.upload-post.com/api/upload-video/
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import Pagina, env

API = "https://api.upload-post.com/api"


def configurado(pagina: Pagina) -> bool:
    cfg = pagina.cfg.get("plataformas", {}).get("tiktok", {})
    return bool(env("UPLOAD_POST_API_KEY") and cfg.get("via") == "uploadpost" and cfg.get("perfil_uploadpost"))


def _h() -> dict:
    return {"Authorization": f"Apikey {env('UPLOAD_POST_API_KEY')}"}


def publicar_tiktok(pagina: Pagina, video: Path, legenda: str) -> dict:
    cfg = pagina.cfg.get("plataformas", {}).get("tiktok", {})
    dados = {
        "user": cfg["perfil_uploadpost"], "platform[]": "tiktok", "title": legenda[:2200],
        "post_mode": "DIRECT_POST", "privacy_level": cfg.get("privacidade", "PUBLIC_TO_EVERYONE"),
        "is_aigc": "true",                      # rótulo obrigatório: conteúdo gerado por IA
        "disable_inbox_fallback": "true",       # nunca cair em rascunho sem avisar
        "disable_comment": "false", "disable_duet": "false", "disable_stitch": "false",
        "async_upload": "true",
    }
    with open(video, "rb") as f:
        r = requests.post(f"{API}/upload", headers=_h(), data=dados, files={"video": (video.name, f, "video/mp4")}, timeout=900)
    corpo = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"erro": r.text[:300]}
    if r.status_code >= 400 or not corpo.get("success"):
        raise RuntimeError(f"Upload-Post recusou: {r.status_code} {str(corpo)[:300]}")
    res = (corpo.get("results") or {}).get("tiktok")
    if not res and corpo.get("request_id"):  # envio em segundo plano: acompanha até terminar (até ~10 min)
        for _ in range(60):
            time.sleep(10)
            st = requests.get(f"{API}/uploadposts/status", headers=_h(), params={"request_id": corpo["request_id"]}, timeout=60).json()
            res = (st.get("results") or {}).get("tiktok") if isinstance(st.get("results"), dict) else None
            if res is None and isinstance(st.get("results"), list):
                res = next((x for x in st["results"] if x.get("platform") == "tiktok"), None)
            if res and (res.get("success") is True or res.get("url")):
                break
            if str((res or {}).get("status", "")).lower() in ("failed", "error") or str(st.get("status", "")).lower() in ("failed", "error"):
                raise RuntimeError(f"Upload-Post: falhou ({str(st)[:300]})")
        else:
            # ainda "processing" depois de 10 min: o Upload-Post continua sozinho. NÃO reenviar (reenviar duplica o vídeo).
            arroba = cfg.get("arroba", "")
            return {"id": corpo["request_id"], "modo": "uploadpost", "pendente": True,
                    "url": f"https://www.tiktok.com/{arroba}" if arroba else ""}
    if not res or res.get("success") is False:
        raise RuntimeError(f"Upload-Post não confirmou a publicação no TikTok: {str(res or corpo)[:300]}")
    arroba = cfg.get("arroba", "")
    return {"id": res.get("post_id") or corpo.get("request_id", ""), "modo": "uploadpost",
            "url": res.get("url") or (f"https://www.tiktok.com/{arroba}" if arroba else "")}
