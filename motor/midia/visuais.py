"""Visual de cada cena em DUAS CAMADAS:

  fundo  → vídeo curto ou foto do ASSUNTO da cena (ferro, chuveiro, quadro de luz…), bem visível;
           ou gráfico/cartão quando o visual é um dado.
  camada → PNG transparente por cima: marca, texto em destaque, barra de progresso e rodapé.
           Fica parada enquanto o fundo se move (texto sempre legível).

Prioridade do fundo: 1) suas fotos (paginas/<p>/midia_propria)  2) vídeo Pexels  3) foto Pexels
4) Pixabay  5) Openverse (sem chave; só licenças CC0/domínio público/CC BY)  6) cartão da página.
"""
from __future__ import annotations

import hashlib
import io
import random
import re
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import requests  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from ..config import PASTA_CACHE, Pagina, env  # noqa: E402
from ..registro import obter  # noqa: E402

log = obter("visuais")

FORMATOS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


# ------------------------------------------------------------------ utilidades

def _fonte(pagina: Pagina, tamanho: int) -> ImageFont.FreeTypeFont:
    candidatos = [
        pagina.cfg.get("visual", {}).get("fonte", "arialbd.ttf"),
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ]
    for c in candidatos:
        try:
            return ImageFont.truetype(c, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(tamanho)


def caminho_fonte(pagina: Pagina) -> str:
    return _fonte(pagina, 20).path


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def _cobrir(img: Image.Image, w: int, h: int) -> Image.Image:
    r = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * r) + 1, int(img.height * r) + 1), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


# ------------------------------------------------------------------ busca de mídia

def _fotos_proprias(pagina: Pagina) -> list[Path]:
    pasta = pagina.pasta / "midia_propria"
    if not pasta.exists():
        return []
    return [p for p in pasta.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]


def _baixar(url: str) -> Image.Image:
    PASTA_CACHE.mkdir(exist_ok=True)
    arq = PASTA_CACHE / ("img_" + hashlib.md5(url.encode()).hexdigest() + ".jpg")
    if not arq.exists():
        r = requests.get(url, timeout=60, headers={"User-Agent": "robo-redes-sociais/1.0"})
        r.raise_for_status()
        arq.write_bytes(r.content)
    return Image.open(arq).convert("RGB")


def _baixar_arquivo(url: str, sufixo: str) -> Path:
    PASTA_CACHE.mkdir(exist_ok=True)
    arq = PASTA_CACHE / ("vid_" + hashlib.md5(url.encode()).hexdigest() + sufixo)
    if not arq.exists():
        with requests.get(url, timeout=180, stream=True) as r:
            r.raise_for_status()
            with open(arq, "wb") as f:
                for bloco in r.iter_content(1 << 20):
                    f.write(bloco)
    return arq


def _pexels_video(consulta: str, orientacao: str, usadas: set[str], w: int, h: int) -> dict | None:
    chave = env("PEXELS_API_KEY")
    if not chave or not consulta:
        return None
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": chave},
                         params={"query": consulta, "orientation": orientacao, "size": "medium", "per_page": 15}, timeout=30)
        r.raise_for_status()
        videos = [v for v in r.json().get("videos", []) if f"pv{v['id']}" not in usadas and v.get("duration", 0) >= 4]
        for v in videos[:6]:
            arqs = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
            # o menor arquivo que ainda cobre bem a tela (economiza download)
            bons = sorted([f for f in arqs if min(f["width"], f["height"]) >= min(w, h) * 0.66], key=lambda f: f["width"] * f["height"])
            if not bons:
                continue
            usadas.add(f"pv{v['id']}")
            return {"tipo": "video", "caminho": _baixar_arquivo(bons[0]["link"], ".mp4"),
                    "credito": f"Vídeo: {v['user']['name']} / Pexels"}
    except requests.RequestException as e:
        log.warning("Pexels vídeo falhou: %s", e)
    return None


def _pexels_foto(consulta: str, orientacao: str, usadas: set[str]) -> dict | None:
    chave = env("PEXELS_API_KEY")
    if not chave:
        return None
    try:
        r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": chave},
                         params={"query": consulta, "orientation": orientacao, "per_page": 15}, timeout=30)
        r.raise_for_status()
        fotos = [f for f in r.json().get("photos", []) if f["src"]["large2x"] not in usadas]
        if fotos:
            f = fotos[0] if len(fotos) < 3 else random.choice(fotos[:5])
            usadas.add(f["src"]["large2x"])
            return {"tipo": "imagem", "imagem": _baixar(f["src"]["large2x"]), "credito": f"Foto: {f['photographer']} / Pexels"}
    except requests.RequestException as e:
        log.warning("Pexels foto falhou: %s", e)
    return None


def _pixabay(consulta: str, orientacao: str, usadas: set[str]) -> dict | None:
    chave = env("PIXABAY_API_KEY")
    if not chave:
        return None
    try:
        r = requests.get("https://pixabay.com/api/", params={"key": chave, "q": consulta, "image_type": "photo",
                                                             "orientation": "vertical" if orientacao == "portrait" else "horizontal",
                                                             "safesearch": "true", "per_page": 20}, timeout=30)
        r.raise_for_status()
        hits = [h for h in r.json().get("hits", []) if h["largeImageURL"] not in usadas]
        if hits:
            h = random.choice(hits[:5])
            usadas.add(h["largeImageURL"])
            return {"tipo": "imagem", "imagem": _baixar(h["largeImageURL"]), "credito": f"Imagem: {h['user']} / Pixabay"}
    except requests.RequestException as e:
        log.warning("Pixabay falhou: %s", e)
    return None


def _openverse(consulta: str, usadas: set[str]) -> dict | None:
    """Reserva SEM chave: só licenças que permitem uso comercial e modificação sem 'compartilha igual'."""
    try:
        r = requests.get("https://api.openverse.org/v1/images/",
                         params={"q": consulta, "license": "cc0,pdm,by", "category": "photograph", "page_size": 20,
                                 "mature": "false"}, timeout=30)
        r.raise_for_status()
        res = [x for x in r.json().get("results", []) if (x.get("width") or 0) >= 900 and x["url"] not in usadas]
        for x in res[:6]:
            try:
                img = _baixar(x["url"])
            except (requests.RequestException, OSError):
                continue
            usadas.add(x["url"])
            lic = (x.get("license") or "").lower()
            lic_txt = "domínio público" if lic in ("cc0", "pdm") else f"CC {lic.upper()} {x.get('license_version', '')}".strip()
            return {"tipo": "imagem", "imagem": img,
                    "credito": f"Imagem: {x.get('creator') or 'autor desconhecido'} ({lic_txt}) via Openverse"}
    except requests.RequestException as e:
        log.warning("Openverse falhou: %s", e)
    return None


def buscar_midia(pagina: Pagina, consultas: list[str], formato: str, usadas: set[str], ilustracao: str = "",
                 fala: str = "") -> dict | None:
    """Fundo da cena: {"tipo": "video", "caminho"} | {"tipo": "imagem", "imagem"}, com "credito". None = usa cartão."""
    w, h = FORMATOS[formato]
    orient = "portrait" if h > w else "landscape"
    cfg = pagina.cfg.get("midia", {})
    proprias = [p for p in _fotos_proprias(pagina) if str(p) not in usadas]
    if proprias and random.random() < float(cfg.get("chance_foto_propria", 0.7)):
        p = random.choice(proprias)
        usadas.add(str(p))
        return {"tipo": "imagem", "imagem": Image.open(p).convert("RGB"), "credito": ""}
    consultas = [c for c in dict.fromkeys(consultas) if c]
    if not ilustracao and consultas:
        # o roteirista não descreveu a ilustração: monta a partir do assunto da cena/pauta
        ilustracao = f"{consultas[0]}, in a cozy Brazilian home"
    if ilustracao and random.random() < float(cfg.get("chance_ilustracao", 0.7)):
        from . import ilustracoes

        from ..fontes.aneel import distribuidoras

        nomes = [d["nome"] for d in distribuidoras().values()] + list(distribuidoras())
        nomes += ["Energisa", "Equatorial", "Neoenergia", "Enel", "CPFL", "Cemig", "Copel", "Celesc", "Light", "EDP", "ANEEL", "Inmetro"]
        seguras = cfg.get("ilustracoes_seguras") or ["a glowing light bulb in a cozy Brazilian living room at night"]
        # ACERVO BRASILEIRO: objeto que a IA desenha no padrão errado (tomada, plugue, chuveiro...) sai a partir da
        # foto real de referência. A fala manda (é o que o público ouve); a descrição da cena vem em seguida.
        from . import acervo

        objeto = acervo.casar(pagina, fala) or acervo.casar(pagina, ilustracao)
        if objeto:
            img = ilustracoes.gerar_com_referencia(pagina, objeto, variante=len(usadas), semente=len(usadas))
            if img is not None:
                usadas.add(f"acervo:{objeto['id']}:{len(usadas)}")
                return {"tipo": "ilustracao", "imagem": img, "credito": ""}
            ilustracao, consultas = "", []  # não conseguiu no padrão brasileiro: melhor uma cena segura do que o padrão errado
        elif acervo.sem_referencia(pagina, f"{fala} {ilustracao}"):
            ilustracao, consultas = "", []  # objeto sem referência ainda: cena segura
        if not ilustracao:
            ilustracao = seguras[len(usadas) % len(seguras)]
        # 1ª tentativa: a cena pedida · 2ª: o assunto da pauta, simples · 3ª: cena segura da página
        tentativas = [ilustracao]
        if consultas:
            tentativas.append(f"{consultas[-1]}, simple composition, one object, cozy Brazilian home")
        tentativas += seguras
        for desc in tentativas[:4]:
            if desc in usadas:
                continue
            # "semente" única por cena: mesmo que duas descrições virem a mesma cena segura, a imagem é outra
            img = ilustracoes.gerar(pagina, desc, termos_proibidos=nomes, semente=f"{ilustracao}|{len(usadas)}")
            if img is not None:
                usadas.add(desc)
                return {"tipo": "ilustracao", "imagem": img, "credito": ""}
    if not cfg.get("usar_banco_de_imagens", False):
        # sem banco de imagens: fotos/vídeos de banco podem trazer texto em inglês e cenas fora do assunto
        return None
    if random.random() < float(cfg.get("chance_video", 0.65)):
        for q in consultas:
            m = _pexels_video(q, orient, usadas, w, h)
            if m:
                return m
    for q in consultas:
        fontes = [lambda: _pexels_foto(q, orient, usadas), lambda: _pixabay(q, orient, usadas)]
        if cfg.get("usar_openverse", False):  # desligado: resultados pouco relevantes e com logos de marca
            fontes.append(lambda: _openverse(q, usadas))
        for fonte in fontes:
            m = fonte()
            if m:
                return m
    return None


# ------------------------------------------------------------------ desenho

def cartao(pagina: Pagina, w: int, h: int, variante: int = 0) -> Image.Image:
    """Fundo com a identidade da página (usado quando não há foto/vídeo e nos gráficos)."""
    v = pagina.cfg.get("visual", {})
    base = _hex(v.get("cor_fundo", "#0E1A2B"))
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    for y in range(h):
        f = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(c * (0.75 + 0.5 * f)) for c in base))
    destaque = _hex(v.get("cor_secundaria", "#4FC3F7"))
    passo = 140 if variante % 2 == 0 else 90
    for i in range(-h, w, passo):
        cor = tuple(int(c * 0.10 + b * 0.9) for c, b in zip(destaque, base))
        d.line([(i + h, 0), (i, h)] if variante % 3 == 2 else [(i, 0), (i + h, h)], fill=cor, width=3)
    brilho = Image.new("L", (w, h), 0)
    db = ImageDraw.Draw(brilho)
    cx, cy = [(0.2, 0.3), (0.8, 0.25), (0.5, 0.7), (0.15, 0.75), (0.85, 0.6)][variante % 5]
    r = int(min(w, h) * 0.6)
    db.ellipse((int(cx * w) - r, int(cy * h) - r, int(cx * w) + r, int(cy * h) + r), fill=70)
    brilho = brilho.filter(ImageFilter.GaussianBlur(r // 2))
    cor_brilho = Image.new("RGB", (w, h), destaque if variante % 2 else _hex(v.get("cor_destaque", "#FFC107")))
    return Image.composite(cor_brilho, img, brilho.point(lambda x: int(x * 0.5)))


_RE_DESTAQUE = re.compile(r"(R\$|\d|%)")


def _quebrar(d, palavras, f, largura):
    linhas, atual = [], []
    for p in palavras:
        if atual and d.textlength(" ".join(atual + [p]), font=f) > largura:
            linhas.append(atual)
            atual = [p]
        else:
            atual.append(p)
    if atual:
        linhas.append(atual)
    return linhas


def _texto_destacado(d: ImageDraw.ImageDraw, caixa, texto: str, fonte_f, cor, cor_destaque, max_tam: int,
                     min_tam: int = 40, contorno: int = 0) -> tuple[int, int]:
    """Texto centralizado; palavras com número/R$/% em amarelo. Retorna (y_topo, y_base) usados."""
    x0, y0, x1, y1 = caixa
    largura, altura = x1 - x0, y1 - y0
    palavras = texto.split()
    tam = max_tam
    while True:
        f = fonte_f(tam)
        linhas = _quebrar(d, palavras, f, largura)
        alt = int(tam * 1.18)
        if (len(linhas) * alt <= altura and all(d.textlength(" ".join(li), font=f) <= largura for li in linhas)) or tam <= min_tam:
            break
        tam -= 6
    y = y0 + (altura - len(linhas) * alt) // 2
    topo = y
    esp = d.textlength(" ", font=f)
    for li in linhas:
        x = x0 + (largura - d.textlength(" ".join(li), font=f)) / 2
        for p in li:
            c = cor_destaque if _RE_DESTAQUE.search(p) else cor
            if contorno:
                d.text((x, y), p, font=f, fill=c, stroke_width=contorno, stroke_fill=(0, 0, 0))
            else:
                d.text((x + 4, y + 4), p, font=f, fill=(0, 0, 0))
                d.text((x, y), p, font=f, fill=c)
            x += d.textlength(p, font=f) + esp
        y += alt
    return topo, y


def _texto_centralizado(d: ImageDraw.ImageDraw, caixa, texto: str, fonte_f, cor, max_tam: int,
                        min_tam: int = 40, sombra: bool = True) -> None:
    x0, y0, x1, y1 = caixa
    largura, altura = x1 - x0, y1 - y0
    tam = max_tam
    while tam >= min_tam:
        f = fonte_f(tam)
        linhas = textwrap.wrap(texto, width=max(6, int(largura / (tam * 0.55)))) or [""]
        if len(linhas) * int(tam * 1.18) <= altura and all(d.textlength(li, font=f) <= largura for li in linhas):
            break
        tam -= 6
    f = fonte_f(tam)
    alt = int(tam * 1.18)
    y = y0 + (altura - len(linhas) * alt) // 2
    for li in linhas:
        x = x0 + (largura - d.textlength(li, font=f)) / 2
        if sombra:
            d.text((x + 4, y + 4), li, font=f, fill=(0, 0, 0))
        d.text((x, y), li, font=f, fill=cor)
        y += alt


def grafico(pagina: Pagina, g: dict, w: int, h: int) -> Image.Image:
    v = pagina.cfg.get("visual", {})
    fundo, destaque, texto = v.get("cor_fundo", "#0E1A2B"), v.get("cor_destaque", "#FFC107"), v.get("cor_texto", "#FFFFFF")
    if g.get("tipo") == "numero":
        img = cartao(pagina, w, h)
        d = ImageDraw.Draw(img)
        _texto_centralizado(d, (60, int(h * 0.22), w - 60, int(h * 0.36)), g.get("titulo", ""), lambda s: _fonte(pagina, s), texto, 64)
        _texto_centralizado(d, (60, int(h * 0.38), w - 60, int(h * 0.55)), g.get("valor", ""), lambda s: _fonte(pagina, s), _hex(destaque), 170)
        _texto_centralizado(d, (60, int(h * 0.56), w - 60, int(h * 0.64)), g.get("sub", ""), lambda s: _fonte(pagina, s), texto, 48)
        return img
    dpi = 100
    fig = plt.figure(figsize=(w / dpi, h * 0.55 / dpi), dpi=dpi)
    fig.patch.set_alpha(0)
    ax = fig.add_subplot(111)
    ax.set_facecolor((0, 0, 0, 0))
    rot, val = g["rotulos"], g["valores"]
    fmt = g.get("formato", "{v}")
    alvo = g.get("destaque", len(val) - 1)
    alvo = alvo if alvo >= 0 else len(val) - 1
    cores = [destaque if i == alvo else "#4FC3F7" for i in range(len(val))]
    fs = 26 if w < h else 22
    if g.get("tipo") == "barras_h":
        cores = [destaque] * (len(val) // 2) + ["#4FC3F7"] * (len(val) - len(val) // 2)
        barras = ax.barh(range(len(val)), val, color=cores)
        ax.set_yticks(range(len(val)), rot, color=texto, fontsize=fs - 6)
        ax.invert_yaxis()
        for b, vv in zip(barras, val):
            ax.text(b.get_width(), b.get_y() + b.get_height() / 2, " " + fmt.format(v=vv).replace(".", ","),
                    va="center", color=texto, fontsize=fs - 6, fontweight="bold")
        ax.set_xticks([])
        ax.set_xlim(0, max(val) * 1.25)
    else:
        barras = ax.bar(range(len(val)), val, color=cores, width=0.6)
        ax.set_xticks(range(len(val)), rot, color=texto, fontsize=fs)
        for b, vv in zip(barras, val):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), fmt.format(v=vv).replace(".", ","),
                    ha="center", va="bottom", color=texto, fontsize=fs + 4, fontweight="bold")
        ax.set_yticks([])
        ax.set_ylim(0, max(val) * 1.2)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    graf = Image.open(buf).convert("RGBA")
    img = cartao(pagina, w, h, 1)
    d = ImageDraw.Draw(img)
    _texto_centralizado(d, (60, int(h * 0.10), w - 60, int(h * 0.20)), g.get("titulo", ""), lambda s: _fonte(pagina, s), texto, 64)
    img.paste(graf, (0, int(h * 0.20)), graf)
    return img


def _camada(pagina: Pagina, w: int, h: int, c: dict, com_midia: bool, rodape: str, indice: int, total: int,
            e_grafico: bool, layout: str = "") -> Image.Image:
    """PNG transparente com tudo o que fica POR CIMA do fundo.
    layout: "midia" (foto/vídeo tela cheia) · "moldura" (ilustração em quadro) · "cta" (mascote) · "cartao"."""
    v = pagina.cfg.get("visual", {})
    cor_txt, cor_dest = _hex(v.get("cor_texto", "#FFFFFF")), _hex(v.get("cor_destaque", "#FFC107"))
    vertical = h > w
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if layout in ("moldura", "cta"):
        d = ImageDraw.Draw(img)
        tela = c.get("tela", "").strip()
        if layout == "cta":
            tela = f"Siga {pagina.cfg.get('arroba') or pagina.nome}"
            caixa = (60, int(h * 0.55), w - 60, int(h * 0.68)) if vertical else (100, int(h * 0.68), w - 100, int(h * 0.82))
        else:
            caixa = (50, int(h * 0.635), w - 50, int(h * 0.735)) if vertical else (100, int(h * 0.80), w - 100, int(h * 0.90))
        if tela and not e_grafico:
            _texto_destacado(d, caixa, tela, lambda s: _fonte(pagina, s), cor_txt, cor_dest, 100 if layout == "cta" else 84, 40, contorno=5)
        return _comum(pagina, img, w, h, indice, total, rodape, cor_dest)
    if com_midia:
        # degradê escuro só onde há texto (topo e parte de baixo) — o meio da imagem fica limpo e chamativo
        grad = Image.new("L", (1, h))
        for y in range(h):
            f = y / h
            a = 0
            if f < 0.14:
                a = int(170 * (1 - f / 0.14))
            elif f > 0.45:
                a = int(235 * min(1.0, (f - 0.45) / 0.30))
            grad.putpixel((0, y), a)
        preto = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        preto.putalpha(grad.resize((w, h)))
        img = Image.alpha_composite(img, preto)
    d = ImageDraw.Draw(img)
    tela = c.get("tela", "").strip()
    if tela and not e_grafico:
        if com_midia:
            # texto na faixa de baixo (acima da legenda), com contorno para ler sobre qualquer imagem
            caixa = (60, int(h * 0.50), w - 60, int(h * 0.66)) if vertical else (100, int(h * 0.56), w - 100, int(h * 0.76))
            tam = 150 if c["visual"] == "numero" else 96
            _texto_destacado(d, caixa, tela, lambda s: _fonte(pagina, s), cor_txt, cor_dest, tam, 44, contorno=5)
        else:
            caixa = (70, int(h * 0.18), w - 70, int(h * 0.50)) if vertical else (120, int(h * 0.12), w - 120, int(h * 0.55))
            if c["visual"] == "numero":
                _texto_centralizado(d, caixa, tela, lambda s: _fonte(pagina, s), cor_dest, 180)
            else:
                _texto_destacado(d, caixa, tela, lambda s: _fonte(pagina, s), cor_txt, cor_dest, 110)
    return _comum(pagina, img, w, h, indice, total, rodape, cor_dest)


def _comum(pagina: Pagina, img: Image.Image, w: int, h: int, indice: int, total: int, rodape: str, cor_dest) -> Image.Image:
    """Elementos presentes em toda cena: barra de progresso, @ da página e rodapé com ressalvas."""
    d = ImageDraw.Draw(img)
    vertical = h > w
    if total > 1:  # barra de progresso (ajuda a reter até o fim)
        d.rectangle((0, 0, w, 10), fill=(40, 50, 70, 230))
        d.rectangle((0, 0, int(w * (indice + 1) / total), 10), fill=cor_dest + (255,))
    f = _fonte(pagina, 40 if vertical else 34)
    marca = pagina.cfg.get("arroba") or pagina.nome
    d.text((w / 2 - d.textlength(marca, font=f) / 2, int(h * 0.05 if vertical else h * 0.04)), marca, font=f,
           fill=cor_dest + (255,), stroke_width=3, stroke_fill=(0, 0, 0))
    if rodape:
        _texto_centralizado(d, (60, int(h * 0.915), w - 60, int(h * 0.985)), rodape, lambda s: _fonte(pagina, s),
                            (230, 230, 230, 255), 30, 20, sombra=True)
    return img


def cena(pagina: Pagina, c: dict, pauta: dict, formato: str, usadas: set[str], rodape: str = "",
         indice: int = 0, total: int = 1) -> dict:
    """Monta uma cena. Retorna {"fundo": {"tipo": "video", "caminho"} | {"tipo": "imagem", "imagem"},
    "camada": PNG RGBA, "credito": str, "zoom": bool}."""
    w, h = FORMATOS[formato]
    e_grafico = c["visual"] == "grafico" and bool(pauta.get("grafico"))
    credito = ""
    if e_grafico:
        fundo = {"tipo": "imagem", "imagem": grafico(pagina, pauta["grafico"], w, h)}
        com_midia, zoom = False, False
    else:
        consultas = [c.get("busca_imagem", ""), pauta.get("busca_base", "")]
        mascote = _mascote(pagina)
        if indice == total - 1 and total > 1 and mascote is not None:
            # cena final ("siga a página"): mascote da página + @ — nunca imagem aleatória
            fundo = {"tipo": "imagem", "imagem": _cena_mascote(pagina, mascote, w, h)}
            camada = _camada(pagina, w, h, c, False, rodape, indice, total, False, layout="cta")
            return {"fundo": fundo, "camada": camada, "credito": "", "zoom": True}
        midia = buscar_midia(pagina, consultas, formato, usadas, c.get("ilustracao", ""), fala=c.get("fala", ""))
        layout = "cartao"
        if midia:
            credito = midia.get("credito", "")
            if midia["tipo"] == "ilustracao":
                midia = {"tipo": "imagem", "imagem": _moldura(pagina, midia["imagem"], w, h)}
                layout = "moldura"
            elif midia["tipo"] == "imagem":
                midia = {"tipo": "imagem", "imagem": _cobrir(midia["imagem"], w, h)}
                layout = "midia"
            else:
                layout = "midia"
            fundo, com_midia, zoom = midia, True, True
        else:
            fundo, com_midia, zoom = {"tipo": "imagem", "imagem": cartao(pagina, w, h, indice)}, False, True
        camada = _camada(pagina, w, h, c, com_midia, rodape, indice, total, e_grafico, layout=layout)
        return {"fundo": fundo, "camada": camada, "credito": credito, "zoom": zoom}
    camada = _camada(pagina, w, h, c, com_midia, rodape, indice, total, e_grafico)
    return {"fundo": fundo, "camada": camada, "credito": credito, "zoom": zoom}


def _mascote(pagina: Pagina) -> Image.Image | None:
    arq = pagina.pasta / pagina.cfg.get("mascote", {}).get("arquivo", "marca/mascote.png")
    return Image.open(arq).convert("RGB") if arq.exists() else None


def _arredondar(img: Image.Image, raio: int) -> Image.Image:
    mascara = Image.new("L", img.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, img.width - 1, img.height - 1), raio, fill=255)
    saida = img.convert("RGBA")
    saida.putalpha(mascara)
    return saida


def _moldura(pagina: Pagina, ilustr: Image.Image, w: int, h: int) -> Image.Image:
    """Ilustração quadrada em destaque (cantos arredondados, borda na cor da página) sobre ela mesma desfocada."""
    v = pagina.cfg.get("visual", {})
    fundo = _cobrir(ilustr, w, h).filter(ImageFilter.GaussianBlur(40))
    fundo = Image.blend(fundo, Image.new("RGB", (w, h), _hex(v.get("cor_fundo", "#0E1A2B"))), 0.55)
    if h > w:
        lado = w - 80
        x, y = 40, int(h * 0.10)
    else:
        lado = int(h * 0.80)
        x, y = (w - lado) // 2, int(h * 0.06)
    quadro = _arredondar(ilustr.resize((lado, lado), Image.LANCZOS), 44)
    borda = Image.new("RGBA", (lado + 16, lado + 16), (0, 0, 0, 0))
    ImageDraw.Draw(borda).rounded_rectangle((0, 0, lado + 15, lado + 15), 52, fill=_hex(v.get("cor_destaque", "#FFC107")) + (255,))
    base = fundo.convert("RGBA")
    base.alpha_composite(borda, (x - 8, y - 8))
    base.alpha_composite(quadro, (x, y))
    return base.convert("RGB")


def _cena_mascote(pagina: Pagina, mascote: Image.Image, w: int, h: int) -> Image.Image:
    v = pagina.cfg.get("visual", {})
    base = cartao(pagina, w, h, 3).convert("RGBA")
    lado = int(min(w, h) * (0.72 if h > w else 0.55))
    m = mascote.resize((lado, lado), Image.LANCZOS)
    mascara = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(mascara).ellipse((0, 0, lado - 1, lado - 1), fill=255)
    circ = m.convert("RGBA")
    circ.putalpha(mascara)
    anel = Image.new("RGBA", (lado + 24, lado + 24), (0, 0, 0, 0))
    ImageDraw.Draw(anel).ellipse((0, 0, lado + 23, lado + 23), fill=_hex(v.get("cor_destaque", "#FFC107")) + (255,))
    x = (w - lado) // 2
    y = int(h * 0.13) if h > w else int(h * 0.08)
    base.alpha_composite(anel, (x - 12, y - 12))
    base.alpha_composite(circ, (x, y))
    return base.convert("RGB")


def previa(cena_montada: dict, w: int, h: int) -> Image.Image:
    """Quadro estático da cena (para conferência)."""
    f = cena_montada["fundo"]
    if f["tipo"] == "imagem":
        base = f["imagem"].convert("RGBA")
    else:
        import subprocess
        import tempfile

        tmp = Path(tempfile.gettempdir()) / "quadro_previa.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "1", "-i", str(f["caminho"]), "-frames:v", "1", str(tmp)], check=True)
        base = _cobrir(Image.open(tmp).convert("RGB"), w, h).convert("RGBA")
    return Image.alpha_composite(base, cena_montada["camada"]).convert("RGB")


def capa(pagina: Pagina, titulo: str, destino: Path) -> Path:
    """Miniatura 1280x720 para o YouTube (vídeo longo)."""
    img = cartao(pagina, 1280, 720)
    d = ImageDraw.Draw(img)
    v = pagina.cfg.get("visual", {})
    _texto_centralizado(d, (60, 120, 1220, 600), titulo, lambda s: _fonte(pagina, s), _hex(v.get("cor_destaque", "#FFC107")), 110)
    img.save(destino, quality=92)
    return destino
