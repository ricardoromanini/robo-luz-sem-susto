"""Envia ao painel do TikTok (Cloudflare Worker) as chaves que ele precisa, lendo do .env.
Cria a LINK_SECRET (chave que assina os links do Telegram) se ainda não existir. Os valores nunca aparecem na tela.

Uso (na pasta do projeto):  python ferramentas/segredos_painel.py
"""
from __future__ import annotations

import re
import secrets
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENV = RAIZ / ".env"


def ler_env() -> dict:
    d = {}
    for linha in ENV.read_text(encoding="utf-8-sig").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def main() -> None:
    env = ler_env()
    if not env.get("TIKTOK_LINK_SECRET"):
        env["TIKTOK_LINK_SECRET"] = secrets.token_urlsafe(32)
        texto = ENV.read_text(encoding="utf-8-sig")
        texto = (re.sub(r"^TIKTOK_LINK_SECRET=.*$", f"TIKTOK_LINK_SECRET={env['TIKTOK_LINK_SECRET']}", texto, flags=re.M)
                 if "TIKTOK_LINK_SECRET=" in texto else texto.rstrip("\n") + f"\nTIKTOK_LINK_SECRET={env['TIKTOK_LINK_SECRET']}\n")
        ENV.write_text(texto, encoding="utf-8")
        print("Criada a TIKTOK_LINK_SECRET no .env")
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    for nome_worker, nome_env in (("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_KEY"), ("TIKTOK_CLIENT_SECRET", "TIKTOK_CLIENT_SECRET"),
                                  ("LINK_SECRET", "TIKTOK_LINK_SECRET")):
        valor = env.get(nome_env, "")
        if not valor:
            print(f"❌ {nome_env} vazio no .env")
            continue
        r = subprocess.run([npx, "wrangler", "secret", "put", nome_worker], cwd=RAIZ / "painel-tiktok", input=valor, encoding="utf-8", errors="replace",
                           capture_output=True, text=True, shell=False)
        print(("✅ " if r.returncode == 0 else "❌ ") + nome_worker + ("" if r.returncode == 0 else f": {r.stderr[-300:]}"))


if __name__ == "__main__":
    main()
