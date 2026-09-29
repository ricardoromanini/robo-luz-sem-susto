"""Ilustrações PRÓPRIAS geradas por IA (Cloudflare Workers AI — FLUX.1 schnell, licença Apache-2.0).

Grátis dentro da cota diária da Cloudflare (dá para ~170 imagens/dia; usamos ~6 por vídeo).
Cada cena ganha uma ilustração feita para ela, no estilo visual da página, SEM texto
(assim não aparece nada em inglês nem marca de terceiros).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time

import requests
from PIL import Image

from ..config import PASTA_CACHE, Pagina, env
from ..registro import obter

log = obter("ilustracoes")

MODELO = "@cf/black-forest-labs/flux-1-schnell"
COTA_ESGOTADA = False  # vira True quando a Cloudflare avisa que a cota grátis do dia acabou
NEGATIVO = ("no text, no letters, no words, no numbers, no captions, no watermark, no logos, no brand names, "
            "no signs with writing")


def configurado() -> bool:
    return bool(env("CLOUDFLARE_API_TOKEN") and env("CLOUDFLARE_ACCOUNT_ID"))


_PROIBIDO_NO_PROMPT = re.compile(
    r"(R\$\s?[\d.,]+|\d[\d.,]*\s?(%|kwh|kw|w|reais|real|centavos)?|\b(money|cash|banknote|bill with|price tag|receipt|"
    r"invoice|logo|brand|sign|label|text|written|caption)\w*)", re.I)


# Assuntos que SEMPRE saem com texto (papel, tela, visor) → trocados por cenas equivalentes sem escrita
_TROCAS_VISUAIS = [
    (r"(electricity|energy|power|utility)?\s*bills?|invoices?|receipts?|statements?|documents?|papers?|forms?|contracts?",
     "a cozy Brazilian house at dusk with warm lights glowing in the windows"),
    (r"(smart|digital|electric(ity)?)?\s*meters?|displays?|screens?|monitors?|smartphones?|phones?|calculators?|tablets?",
     "a glowing light bulb in a modern Brazilian living room"),
    (r"charts?|graphs?|infographics?|data tables?", "golden light bulbs arranged in a row, glowing"),
]


def limpar_descricao(descricao: str, termos_proibidos: list[str]) -> str:
    """Tira da descrição tudo o que faz a IA desenhar texto: números, dinheiro, nomes de empresas, placas."""
    d = descricao
    for padrao, troca in _TROCAS_VISUAIS:
        if re.search(r"\b(?:" + padrao + r")\b", d, re.I):
            d = troca  # o assunto inteiro vira uma cena equivalente sem escrita
            break
    for t in sorted(termos_proibidos, key=len, reverse=True):
        if t:
            d = re.sub(re.escape(t), "the local power company", d, flags=re.I)
    d = _PROIBIDO_NO_PROMPT.sub("", d)
    return re.sub(r"\s{2,}", " ", d).strip(" ,.")


def prompt_final(pagina: Pagina, descricao: str) -> str:
    estilo = pagina.cfg.get("estilo_ilustracao", "")
    return f"{descricao.strip().rstrip('.')}. {estilo} {NEGATIVO}."


def _chamar(prompt: str) -> Image.Image | None:
    url = f"https://api.cloudflare.com/client/v4/accounts/{env('CLOUDFLARE_ACCOUNT_ID')}/ai/run/{MODELO}"
    for tentativa in range(3):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {env('CLOUDFLARE_API_TOKEN')}"},
                              json={"prompt": prompt, "steps": 8}, timeout=240)
            if r.status_code == 429 and ("daily free allocation" in r.text or "neurons" in r.text):
                global COTA_ESGOTADA
                COTA_ESGOTADA = True  # cota diária grátis acabou: não adianta insistir hoje
                log.warning("cota diária grátis de ilustrações da Cloudflare esgotada")
                return None
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(10 * (tentativa + 1))
                continue
            r.raise_for_status()
            return Image.open(io.BytesIO(base64.b64decode(r.json()["result"]["image"]))).convert("RGB")
        except (requests.RequestException, KeyError, OSError) as e:
            log.warning("ilustração falhou: %s", e)
            time.sleep(3)
    return None


def fiscal_de_imagem(img: Image.Image) -> tuple[bool, str]:
    """Olha a imagem pronta (Gemini, visão) e reprova se tiver texto, número, logotipo, marca, dinheiro ou
    defeito grave. Retorna (aprovada, motivo). Fiscal fora do ar = reprova (na dúvida, nada de texto na tela)."""
    chave = env("GEMINI_API_KEY")
    buf = io.BytesIO()
    img.resize((512, 512)).save(buf, format="JPEG", quality=85)
    pergunta = ("Você é o fiscal de imagens de uma página brasileira. Responda SOMENTE JSON "
                '{"aprovada": true|false, "motivo": "..."}. REPROVE se a imagem tiver QUALQUER texto legível ou '
                "pseudo-texto, letras, números, logotipo, nome de marca, cédula/dinheiro, bandeira de empresa, "
                "ou deformação grave (mãos/rostos monstruosos). Aprove se for uma ilustração limpa, sem nada escrito.")
    corpo = {"contents": [{"parts": [{"text": pergunta},
                                     {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}]}],
             "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    from ..config import carregar_global

    for modelo in (carregar_global().get("fiscal_imagem", ["gemini-3.5-flash"]) if chave else []):
        for tentativa in range(3):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                                  headers={"x-goog-api-key": chave}, json=corpo, timeout=90)
                if r.status_code in (429, 500, 503) and tentativa < 2:
                    time.sleep(15 * (tentativa + 1))
                    continue
                r.raise_for_status()
                res = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                return bool(res.get("aprovada")), str(res.get("motivo", ""))
            except requests.Timeout:
                if tentativa < 2:
                    continue
                log.warning("fiscal de imagem (%s): tempo esgotado", modelo)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("fiscal de imagem (%s) indisponível: %s", modelo, e)
                break
    # reserva: modelo com visão no Groq
    chave_groq = env("GROQ_API_KEY")
    if chave_groq:
        try:
            dados = base64.b64encode(buf.getvalue()).decode()
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {chave_groq}"}, timeout=60,
                              json={"model": "qwen/qwen3.8-27b", "temperature": 0,
                                    "response_format": {"type": "json_object"},
                                    "messages": [{"role": "user", "content": [
                                        {"type": "text", "text": pergunta},
                                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{dados}"}}]}]})
            r.raise_for_status()
            res = json.loads(r.json()["choices"][0]["message"]["content"])
            return bool(res.get("aprovada")), str(res.get("motivo", "")) + " (fiscal reserva)"
        except Exception as e:  # noqa: BLE001
            log.warning("fiscal de imagem reserva (Groq) indisponível: %s", e)
    # na dúvida, NÃO aprova (o robô usa outro fundo)
    return False, "fiscal indisponível"


def gerar(pagina: Pagina, descricao: str, semente: int | str | None = None, termos_proibidos: list[str] | None = None,
          fiscalizar: bool = True) -> Image.Image | None:
    """Gera (ou reaproveita do cache) uma ilustração 1024x1024 aprovada pelo fiscal. None = usar outro fundo."""
    if not configurado() or not descricao or COTA_ESGOTADA:
        return None
    descricao = limpar_descricao(descricao, termos_proibidos or [])
    prompt = prompt_final(pagina, descricao)
    PASTA_CACHE.mkdir(exist_ok=True)
    arq = PASTA_CACHE / ("ia_" + hashlib.md5(f"{prompt}|{semente}".encode()).hexdigest() + ".jpg")
    if arq.exists():
        return Image.open(arq).convert("RGB")
    for tentativa in range(2):
        img = _chamar(prompt if tentativa == 0 else prompt + " Absolutely no writing of any kind anywhere in the image.")
        if img is None:
            return None
        ok, motivo = fiscal_de_imagem(img) if fiscalizar else (True, "")
        if ok:
            img.save(arq, quality=94)
            return img
        log.info("fiscal reprovou ilustração (%s): %s", descricao[:40], motivo)
    return None


MASCOTE_BASE = ("A friendly Brazilian electrician mascot character, 3D animated movie style, warm smile, "
                "yellow safety helmet with a small lightning bolt symbol, navy blue work uniform, holding a "
                "glowing light bulb, giving a thumbs up, upper body portrait, centered, plain solid dark navy "
                "blue background, soft studio lighting, high detail")


def gerar_opcoes_mascote(pagina: Pagina, quantidade: int = 4) -> list[Image.Image]:
    """Gera variações do mascote (sementes diferentes) para o dono escolher uma."""
    poses = ["giving a thumbs up", "waving hello with one hand", "pointing to the viewer with a confident smile",
             "holding a glowing light bulb up, surprised happy expression", "arms crossed, friendly confident smile"]
    opcoes = []
    base = pagina.cfg.get("mascote", {}).get("descricao", MASCOTE_BASE)
    for s in range(quantidade):
        img = gerar(pagina, f"{base}, {poses[s % len(poses)]}", semente=s, fiscalizar=False)
        if img is not None:
            opcoes.append(img)
    return opcoes
