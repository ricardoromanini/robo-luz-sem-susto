"""Copia as chaves preenchidas do .env para os "Secrets" do repositório no GitHub (cofre protegido).

Uso (na pasta do projeto):  python ferramentas/enviar_segredos.py
Precisa do GitHub CLI logado (gh auth login). Os valores nunca aparecem na tela.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SO_LOCAIS = {"OLLAMA_URL", "WHISPER_MODELO", "LLM_FORCAR", "META_APP_ID", "META_APP_SECRET"}  # não vão para a nuvem


def main() -> None:
    gh = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
    env = RAIZ / ".env"
    if not env.exists():
        sys.exit("Arquivo .env não encontrado.")
    enviados, vazios = [], []
    for linha in env.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, valor = (x.strip() for x in linha.split("=", 1))
        if nome in SO_LOCAIS:
            continue
        if not valor:
            vazios.append(nome)
            continue
        r = subprocess.run([gh, "secret", "set", nome, "--body", valor], cwd=RAIZ, capture_output=True, text=True)
        if r.returncode == 0:
            enviados.append(nome)
        else:
            print(f"❌ {nome}: {r.stderr.strip()[:200]}")
    print(f"✅ {len(enviados)} chave(s) enviadas ao GitHub: {', '.join(enviados)}")
    if vazios:
        print(f"ℹ️ Ainda vazias (preencha e rode de novo quando tiver): {', '.join(vazios)}")


if __name__ == "__main__":
    main()
