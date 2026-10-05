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
from . import acervo
from ..registro import obter

log = obter("ilustracoes")

MODELO = "@cf/black-forest-labs/flux-1-schnell"
COTA_ESGOTADA = False  # vira True quando a Cloudflare avisa que a cota grátis do dia acabou
NEGATIVO = ("no text, no letters, no words, no numbers, no captions, no watermark, no logos, no brand names, "
            "no signs with writing, appliance displays and control panels blank (no digits), no labels or stickers")


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


def fiscal_de_imagem(img: Image.Image, regras_extra: str = "") -> tuple[bool, str]:
    """Dois fiscais de modelos diferentes: o 1º confere tudo; o 2º procura só texto/números pequenos (visor, etiqueta)."""
    ok, motivo = _fiscal_principal(img, regras_extra)
    if not ok:
        return ok, motivo
    from ..config import carregar_global

    segundo = carregar_global().get("fiscal_imagem_segundo")
    if not segundo:
        return ok, motivo
    ok2, motivo2 = _fiscal_texto(img, segundo)
    return (ok2, motivo2 if not ok2 else motivo)


def _fiscal_texto(img: Image.Image, modelo: str) -> tuple[bool, str]:
    """Segundo fiscal: procura QUALQUER escrita, número, visor digital, etiqueta, adesivo ou logotipo, mesmo pequeno."""
    conta, token = env("CLOUDFLARE_ACCOUNT_ID"), env("CLOUDFLARE_API_TOKEN")
    buf = io.BytesIO()
    img.resize((1024, 1024)).save(buf, format="JPEG", quality=92)
    pergunta = ("This image will be shown on a phone screen. Is there any READABLE word, brand name, logo with letters, "
                "or readable number (for example on a display, label, sticker or package) that a viewer would notice? "
                "Ignore tiny or blurry marks, abstract icons, symbols without letters and decorative shapes. "
                'Answer ONLY JSON {"tem_escrita": true|false, "onde": "..."}.')
    try:
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/v1/chat/completions", timeout=90,
                          headers={"Authorization": f"Bearer {token}"},
                          json={"model": modelo, "temperature": 0, "messages": [{"role": "user", "content": [
                              {"type": "text", "text": pergunta},
                              {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]}]})
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        res = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        if res.get("tem_escrita"):
            return False, f"2º fiscal: escrita/números em {res.get('onde', '?')}"
        return True, ""
    except Exception as e:  # noqa: BLE001
        log.warning("2º fiscal de imagem (%s) indisponível: %s", modelo, e)
        return False, "2º fiscal indisponível"


def _fiscal_principal(img: Image.Image, regras_extra: str = "") -> tuple[bool, str]:
    """Olha a imagem pronta (Gemini, visão) e reprova se tiver texto, número, logotipo, marca, dinheiro ou
    defeito grave. Retorna (aprovada, motivo). Fiscal fora do ar = reprova (na dúvida, nada de texto na tela)."""
    chave = env("GEMINI_API_KEY")
    buf = io.BytesIO()
    img.resize((768, 768)).save(buf, format="JPEG", quality=88)
    pergunta = ("Você é o fiscal de imagens de uma página brasileira. Responda SOMENTE JSON "
                '{"aprovada": true|false, "motivo": "..."}. REPROVE se a imagem tiver QUALQUER texto legível ou '
                "pseudo-texto, letras, números, logotipo, nome de marca, cédula/dinheiro, bandeira de empresa, "
                "ou deformação grave (mãos/rostos monstruosos). Aprove se for uma ilustração limpa, sem nada escrito.")
    if regras_extra:
        pergunta += " REGRAS DO BRASIL (também obrigatórias): " + regras_extra
    corpo = {"contents": [{"parts": [{"text": pergunta},
                                     {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}]}],
             "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    from ..config import carregar_global

    dados_img = base64.b64encode(buf.getvalue()).decode()
    for modelo in carregar_global().get("fiscal_imagem", ["gemini-3.5-flash"]):
        if modelo.startswith("@cf/"):  # Cloudflare Workers AI (modelo com visão)
            conta, token = env("CLOUDFLARE_ACCOUNT_ID"), env("CLOUDFLARE_API_TOKEN")
            if not (conta and token):
                continue
            try:
                r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {token}"}, timeout=90,
                                  json={"model": modelo, "temperature": 0, "response_format": {"type": "json_object"},
                                        "messages": [{"role": "user", "content": [
                                            {"type": "text", "text": pergunta},
                                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{dados_img}"}}]}]})
                r.raise_for_status()
                txt = r.json()["choices"][0]["message"]["content"]
                res = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
                return bool(res.get("aprovada")), str(res.get("motivo", ""))
            except Exception as e:  # noqa: BLE001
                log.warning("fiscal de imagem (%s) indisponível: %s", modelo, e)
            continue
        if not chave:
            continue
        for tentativa in range(3):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                                  headers={"x-goog-api-key": chave}, json=corpo, timeout=90)
                if r.status_code in (401, 403):
                    log.warning("fiscal de imagem (%s): acesso negado pelo Google; pulando o Gemini", modelo)
                    chave = ""
                    break
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


def nota_gancho(img: Image.Image, fala: str) -> float:
    """Nota de 0 a 10 para a 1ª imagem do vídeo (o GANCHO): o espectador decide em ~1 s se continua.
    Vale: um sujeito único, grande e reconhecível na tela do celular, contraste e cor fortes, algo que desperte
    curiosidade E ligação direta com a 1ª frase (gancho sem relação com a frase é isca enganosa). -1 = juiz fora do ar."""
    conta, token = env("CLOUDFLARE_ACCOUNT_ID"), env("CLOUDFLARE_API_TOKEN")
    from ..config import carregar_global

    modelo = next((m for m in carregar_global().get("fiscal_imagem", []) if m.startswith("@cf/")), "")
    if not (conta and token and modelo):
        return -1.0
    buf = io.BytesIO()
    img.resize((768, 768)).save(buf, format="JPEG", quality=88)
    pergunta = ("Esta é a PRIMEIRA imagem de um vídeo curto vertical (Shorts/Reels/TikTok). Na tela do celular, o "
                "espectador decide em 1 segundo se continua assistindo. A narração dessa cena diz: \"" + fala[:300] + "\". "
                "Dê uma nota de 0 a 10 somando: (a) UM sujeito principal, grande e reconhecível em menos de 1 segundo; "
                "(b) contraste e cores fortes, nada escuro, lavado ou poluído; (c) desperta curiosidade, alerta ou "
                "surpresa; (d) ligação DIRETA e evidente com a frase narrada (sem ligação = nota no máximo 3). "
                'Responda SOMENTE JSON {"nota": 0-10, "motivo": "..."}.')
    try:
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {token}"}, timeout=90,
                          json={"model": modelo, "temperature": 0, "response_format": {"type": "json_object"},
                                "messages": [{"role": "user", "content": [
                                    {"type": "text", "text": pergunta},
                                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]}]})
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        res = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        log.info("gancho: nota %s — %s", res.get("nota"), str(res.get("motivo", ""))[:120])
        return float(res.get("nota", 0))
    except Exception as e:  # noqa: BLE001
        log.warning("juiz do gancho indisponível: %s", e)
        return -1.0


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
        ok, motivo = fiscal_de_imagem(img, acervo.regra_geral(pagina)) if fiscalizar else (True, "")
        if ok:
            img.save(arq, quality=94)
            return img
        log.info("fiscal reprovou ilustração (%s): %s", descricao[:40], motivo)
    return None


MODELO_REFERENCIA = "@cf/black-forest-labs/flux-2-klein-4b"  # aceita foto de referência (licença Apache-2.0)


def gerar_com_referencia(pagina: Pagina, objeto: dict, variante: int = 0, semente: int | str | None = None) -> Image.Image | None:
    """Ilustração de um objeto do ACERVO BRASILEIRO: a IA recebe a foto real de referência e desenha a cena no
    estilo da página mantendo o objeto igual (ex.: tomada NBR 14136). O fiscal confere o padrão. None = não deu."""
    if not configurado() or COTA_ESGOTADA:
        return None
    cenas = objeto.get("cenas") or []
    if not cenas:
        return None
    PASTA_CACHE.mkdir(exist_ok=True)
    regras = (objeto.get("conferir", "") + " " + acervo.regra_geral(pagina)).strip()
    url = f"https://api.cloudflare.com/client/v4/accounts/{env('CLOUDFLARE_ACCOUNT_ID')}/ai/run/{MODELO_REFERENCIA}"
    for tentativa in range(3):
        cena = cenas[(variante + tentativa) % len(cenas)]
        prompt = prompt_final(pagina, cena)
        arq = PASTA_CACHE / ("ia_ref_" + hashlib.md5(f"{prompt}|{semente}|{tentativa}".encode()).hexdigest() + ".jpg")
        if arq.exists():
            return Image.open(arq).convert("RGB")
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {env('CLOUDFLARE_API_TOKEN')}"}, timeout=300,
                              files={"prompt": (None, prompt), "width": (None, "1024"), "height": (None, "1024"),
                                     "input_image_0": ("referencia.jpg", objeto["arquivo"].read_bytes(), "image/jpeg")})
            r.raise_for_status()
            img = Image.open(io.BytesIO(base64.b64decode(r.json()["result"]["image"]))).convert("RGB")
        except (requests.RequestException, KeyError, OSError) as e:
            log.warning("ilustração com referência (%s) falhou: %s", objeto["id"], e)
            continue
        ok, motivo = fiscal_de_imagem(img, regras)
        if ok:
            img.save(arq, quality=94)
            log.info("ilustração com referência brasileira: %s", objeto["id"])
            return img
        log.info("fiscal reprovou ilustração com referência (%s): %s", objeto["id"], motivo)
    return None


def _jpg(arquivo, lado: int = 768) -> bytes:
    im = Image.open(arquivo).convert("RGB")
    im.thumbnail((lado, lado))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def gerar_com_mascote(pagina: Pagina, descricao: str, objeto: dict | None = None, variante: int = 0,
                      semente: int | str | None = None, termos_proibidos: list[str] | None = None) -> Image.Image | None:
    """Cena com o MASCOTE da página apresentando o assunto. A IA recebe a imagem oficial do mascote (1ª referência)
    e, se a cena tem objeto do acervo brasileiro, a foto real dele (2ª referência). None = não deu (usa outra cena)."""
    cfg = pagina.cfg.get("mascote", {})
    arq_masc = pagina.pasta / cfg.get("arquivo", "marca/mascote.png")
    if not configurado() or COTA_ESGOTADA or not arq_masc.exists():
        return None
    personagem = cfg.get("descricao_cena") or ("The cartoon electrician character from the first reference image (same face, same "
                                                "yellow safety helmet with a lightning bolt, same navy blue work uniform)")
    if objeto:
        acoes = objeto.get("cenas_mascote") or []
        if not acoes:
            return None
        regras = objeto.get("conferir", "")
    else:
        assunto = limpar_descricao(descricao, termos_proibidos or [])
        if not assunto:
            return None
        acoes = [f"standing in the scene and pointing at the main subject with a friendly smile. Scene: {assunto}",
                 f"presenting the scene with an open hand gesture, looking at the viewer. Scene: {assunto}"]
        regras = ""
    regras = (regras + " O personagem deve ser o mascote da página: eletricista de desenho animado com capacete amarelo e "
              "uniforme azul-marinho, um só, sem deformações. " + acervo.regra_geral(pagina)).strip()
    PASTA_CACHE.mkdir(exist_ok=True)
    url = f"https://api.cloudflare.com/client/v4/accounts/{env('CLOUDFLARE_ACCOUNT_ID')}/ai/run/{MODELO_REFERENCIA}"
    for tentativa in range(3):
        acao = acoes[(variante + tentativa) % len(acoes)]
        prompt = prompt_final(pagina, f"{personagem} {acao}. Keep the character faithful to the first reference image. "
                                      "Only one character, no exposed wires")
        arq = PASTA_CACHE / ("ia_masc_" + hashlib.md5(f"{prompt}|{semente}|{tentativa}".encode()).hexdigest() + ".jpg")
        if arq.exists():
            return Image.open(arq).convert("RGB")
        arquivos = {"prompt": (None, prompt), "width": (None, "1024"), "height": (None, "1024"),
                    "input_image_0": ("mascote.jpg", _jpg(arq_masc), "image/jpeg")}
        if objeto:
            arquivos["input_image_1"] = ("objeto.jpg", _jpg(objeto["arquivo"]), "image/jpeg")
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {env('CLOUDFLARE_API_TOKEN')}"}, timeout=300, files=arquivos)
            r.raise_for_status()
            img = Image.open(io.BytesIO(base64.b64decode(r.json()["result"]["image"]))).convert("RGB")
        except (requests.RequestException, KeyError, OSError) as e:
            log.warning("cena com mascote falhou: %s", e)
            continue
        ok, motivo = fiscal_de_imagem(img, regras)
        if ok:
            img.save(arq, quality=94)
            log.info("cena com mascote%s", f" + referência brasileira: {objeto['id']}" if objeto else "")
            return img
        log.info("fiscal reprovou cena com mascote: %s", motivo)
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


# ------------------------------------------------------------------ foto real como referência (automático)
_UA = {"User-Agent": "robo-luz-sem-susto/1.0 (https://github.com/ricardoromanini/robo-luz-sem-susto)"}
_LIVRES = re.compile(r"^(cc0|public domain|pd|cc by( |-)\d|cc by-sa|cc-by)", re.I)


def foto_referencia(busca: str) -> bytes | None:
    """Foto REAL de licença livre (Wikimedia Commons) do objeto da cena, usada só como referência para a IA desenhar
    o objeto do jeito que ele é de verdade. A foto não aparece no vídeo. Guarda em cache por busca."""
    busca = re.sub(r"[^\w\s-]", " ", busca or "").strip()
    if not busca:
        return None
    PASTA_CACHE.mkdir(exist_ok=True)
    arq = PASTA_CACHE / ("ref_" + hashlib.md5(busca.lower().encode()).hexdigest() + ".jpg")
    if arq.exists():
        return arq.read_bytes() or None
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=_UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{busca} filetype:bitmap", "gsrlimit": 10, "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 768})
        paginas = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99))
        for p in paginas:
            ii = (p.get("imageinfo") or [{}])[0]
            lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
            if ii.get("mime") == "image/jpeg" and _LIVRES.match(lic) and ii.get("width", 0) >= 600:
                dados = requests.get(ii["thumburl"], headers=_UA, timeout=60).content
                arq.write_bytes(dados)
                return dados
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("busca de foto de referência ('%s') falhou: %s", busca, e)
    arq.write_bytes(b"")  # nada encontrado: não busca de novo
    return None


def gerar_com_foto_real(pagina: Pagina, busca: str, descricao: str, semente: int | str | None = None,
                        termos_proibidos: list[str] | None = None) -> Image.Image | None:
    """Pesquisa uma foto real do objeto e redesenha a cena no estilo da página, mantendo o objeto fiel à foto."""
    if not configurado() or COTA_ESGOTADA:
        return None
    ref = foto_referencia(busca)
    if not ref:
        return None
    cena = limpar_descricao(descricao or busca, termos_proibidos or [])
    prompt = prompt_final(pagina, f"{cena}. Draw the main object exactly like the real object in the reference photo "
                                  "(same shape, parts and proportions), as a clean illustration in a Brazilian home. "
                                  "Do not copy any text, label, brand or logo from the photo")
    arq = PASTA_CACHE / ("ia_foto_" + hashlib.md5(f"{prompt}|{semente}".encode()).hexdigest() + ".jpg")
    if arq.exists():
        return Image.open(arq).convert("RGB")
    url = f"https://api.cloudflare.com/client/v4/accounts/{env('CLOUDFLARE_ACCOUNT_ID')}/ai/run/{MODELO_REFERENCIA}"
    for _ in range(2):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {env('CLOUDFLARE_API_TOKEN')}"}, timeout=300,
                              files={"prompt": (None, prompt), "width": (None, "1024"), "height": (None, "1024"),
                                     "input_image_0": ("foto.jpg", ref, "image/jpeg")})
            r.raise_for_status()
            img = Image.open(io.BytesIO(base64.b64decode(r.json()["result"]["image"]))).convert("RGB")
        except (requests.RequestException, KeyError, OSError) as e:
            log.warning("ilustração a partir de foto real falhou: %s", e)
            continue
        ok, motivo = fiscal_de_imagem(img, acervo.regra_geral(pagina))
        if ok:
            img.save(arq, quality=94)
            log.info("ilustração a partir de foto real: %s", busca)
            return img
        log.info("fiscal reprovou ilustração a partir de foto real (%s): %s", busca, motivo)
    return None
