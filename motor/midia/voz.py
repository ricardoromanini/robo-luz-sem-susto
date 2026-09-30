"""Voz (TTS): Google Cloud Text-to-Speech (Chirp 3 HD) na nuvem; Piper local de reserva.

Cada cena vira um arquivo de áudio separado — assim sabemos a duração exata de
cada cena para sincronizar imagem e legenda.
"""
from __future__ import annotations

import base64
import difflib
import re
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

import requests

from ..config import RAIZ, Pagina, env
from ..registro import obter

log = obter("voz")

_UNIDADES = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove"]


def _reais(inteiro: str, cent: str) -> str:
    i = int(inteiro.replace(".", ""))
    c = int(cent) if cent else 0
    txt_i = f"{i} {'real' if i == 1 else 'reais'}" if i else ""
    txt_c = f"{c} {'centavo' if c == 1 else 'centavos'}" if c else ""
    if txt_i and txt_c:
        return f"{txt_i} e {txt_c}"
    return txt_i or txt_c or "zero real"


def normalizar_fala(t: str) -> str:
    """Troca símbolos e siglas pelo jeito certo de falar (o texto da tela continua igual)."""
    t = re.sub(r"\s*\((?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\)", "", t)
    # R$ 0,892 -> cerca de 89 centavos ; R$ 1,061 -> cerca de 1 real e 6 centavos
    t = re.sub(r"R\$\s?(\d+),(\d)(\d)(\d)\b", lambda m: "cerca de " + _reais(m.group(1), str(round(int(m.group(2) + m.group(3) + m.group(4)) / 10)).zfill(2)), t)
    t = re.sub(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\b", lambda m: _reais(m.group(1), m.group(2)), t)
    t = re.sub(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+)\b", lambda m: _reais(m.group(1), ""), t)
    t = re.sub(r"\b1\s?h\b", "1 hora", t)
    t = re.sub(r"\b(\d+)\s?h\b", r"\1 horas", t)
    t = re.sub(r"\b(\d+)\s?min\b", r"\1 minutos", t)
    t = re.sub(r"/(dia|semana|mês|mes|ano|noite)\b", r" por \1", t)
    t = re.sub(r"(\d+),(\d+)\s?%", r"\1 vírgula \2 por cento", t)
    t = re.sub(r"(\d+)\s?%", r"\1 por cento", t)
    trocas = [
        (r"\b(por|cada|o|um) kWh\b", r"\1 quilowatt-hora"), (r"(?<![\d,.])1 kWh\b", "1 quilowatt-hora"), (r"\bkWh\b", "quilowatts-hora"), (r"\bMWh\b", "megawatts-hora"), (r"\bkW\b", "quilowatts"),
        (r"(\d)\s?W\b", r"\1 watts"), (r"\bBTUs?\b", "BTUs"), (r"\bnº\s?", "número "),
        (r"\bTUSD\b", "tê u ésse dê"), (r"\bTE\b", "tê é"), (r"\bANEEL\b", "Aneel"), (r"\bNBR\b", "NBR"),
        (r"\bDR\b", "dê érre"), (r"\bDPS\b", "dê pê ésse"), (r"\bICMS\b", "ICMS"), (r"PIS/Cofins", "PIS e Cofins"),
        (r"\bART\b", "A érre tê"), (r"\bmA\b", "miliampères"), (r"\s/\s", " e "),
    ]
    for a, b in trocas:
        t = re.sub(a, b, t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _duracao_wav(arq: Path) -> float:
    with wave.open(str(arq), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _google(texto: str, voz: str, velocidade: float, destino: Path) -> None:
    chave = env("GOOGLE_TTS_API_KEY")
    if not chave:
        raise RuntimeError("GOOGLE_TTS_API_KEY ausente")
    # com marcações de pausa, a Chirp 3 HD usa o campo "markup" (pausas naturais)
    entrada = {"markup": texto} if "[pause" in texto else {"text": texto}
    corpo = {
        "input": entrada,
        "voice": {"languageCode": "pt-BR", "name": voz},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000, "speakingRate": velocidade},
    }
    r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize", params={"key": chave}, json=corpo, timeout=120)
    r.raise_for_status()
    destino.write_bytes(base64.b64decode(r.json()["audioContent"]))


def _azure(texto: str, voz: str, velocidade: float, destino: Path) -> None:
    """Microsoft Azure Speech (vozes neurais pt-BR; plano grátis F0 = 500 mil caracteres/mês)."""
    chave, regiao = env("AZURE_SPEECH_KEY"), env("AZURE_SPEECH_REGION") or "brazilsouth"
    if not chave:
        raise RuntimeError("AZURE_SPEECH_KEY ausente")
    from xml.sax.saxutils import escape

    corpo = re.sub(r"\[pause[^\]]*\]", '<break time="300ms"/>', escape(texto))
    ssml = (f'<speak version="1.0" xml:lang="pt-BR" xmlns="http://www.w3.org/2001/10/synthesis">'
            f'<voice name="{voz}"><prosody rate="{(velocidade - 1) * 100:+.0f}%">{corpo}</prosody></voice></speak>')
    r = requests.post(f"https://{regiao}.tts.speech.microsoft.com/cognitiveservices/v1", timeout=120,
                      headers={"Ocp-Apim-Subscription-Key": chave, "Content-Type": "application/ssml+xml",
                               "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm", "User-Agent": "robo-luz-sem-susto"},
                      data=ssml.encode("utf-8"))
    r.raise_for_status()
    destino.write_bytes(r.content)


def adicionar_pausas(t: str) -> str:
    """Pausas naturais (ritmo de apresentador): depois de pergunta, nas reticências e antes do número principal."""
    t = re.sub(r"\s*(\.\.\.|…)\s*", " [pause short] ", t)
    t = re.sub(r"\?\s+", "? [pause short] ", t)
    t = re.sub(r"\b(cerca de|custa|chega a|passa a|sobe para|cai para)\s+(\d)", r"\1 [pause short] \2", t, count=1)
    return re.sub(r"\s{2,}", " ", t).strip()


def _piper(texto: str, velocidade: float, destino: Path, modelo: str) -> None:
    texto = re.sub(r"\[pause[^\]]*\]", ",", texto)
    mod = Path(modelo)
    if not mod.is_absolute():
        mod = RAIZ / mod
    if not mod.exists():
        raise RuntimeError(f"modelo Piper não encontrado: {mod}")
    subprocess.run([sys.executable, "-m", "piper", "-m", str(mod), "-f", str(destino), "--length-scale", f"{1 / velocidade:.2f}"],
                   input=texto.encode("utf-8"), check=True, capture_output=True)


def escolher_voz(pagina: Pagina, indice_post: int) -> dict:
    """Combinação de voz do post (rodízio). {"atuada": {voz, estilo} | None, "google": nome Chirp3}."""
    atuadas = pagina.cfg.get("vozes_atuadas") or []
    google = pagina.cfg.get("vozes_google") or ["pt-BR-Chirp3-HD-Charon"]
    azure = pagina.cfg.get("vozes_azure") or ["pt-BR-AntonioNeural"]
    return {"atuada": atuadas[indice_post % len(atuadas)] if atuadas else None,
            "google": google[indice_post % len(google)], "azure": azure[indice_post % len(azure)]}


def _preparar(pagina: Pagina, fala: str, com_pausas: bool = True) -> str:
    txt = normalizar_fala(fala)
    if com_pausas:
        txt = adicionar_pausas(txt)
    for escrito, falado in (pagina.cfg.get("pronuncia") or {}).items():
        txt = re.sub(rf"\b{re.escape(escrito)}\b", falado, txt)
    return txt


# ------------------------------------------------------------------ voz atuada (Gemini-TTS)

def _gemini_tts(texto: str, voz: str, estilo: str, modelo: str, destino: Path) -> None:
    chave = env("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY ausente")
    corpo = {
        "contents": [{"parts": [{"text": f"{estilo}\n\nLeia EXATAMENTE o texto abaixo, sem acrescentar nem tirar palavras "
                                          f"(português do Brasil):\n{texto}"}]}],
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}},
    }
    for tentativa in range(5):
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                          headers={"x-goog-api-key": chave}, json=corpo, timeout=300)
        if r.status_code in (429, 500, 503) and tentativa < 4:
            time.sleep(25 * (tentativa + 1))
            continue
        r.raise_for_status()
        break
    pcm = base64.b64decode(r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)


def _palavras(t: str) -> list[str]:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z]+|\d+", t)


def _fronteiras(pagina: Pagina, audio: Path, falas_prep: list[str], total: float) -> list[float]:
    """Instante em que cada cena começa, achado pela transcrição (com reserva proporcional)."""
    from . import legendas

    palavras = legendas.palavras_com_tempo(pagina, audio)
    esperadas: list[tuple[str, int]] = []
    for i, f in enumerate(falas_prep):
        esperadas += [(p, i) for p in _palavras(re.sub(r"\[pause[^\]]*\]", " ", f))]
    inicios = [0.0] * len(falas_prep)
    if palavras:
        ouvidas = [(_palavras(w) or [""])[0] for w, _, _ in palavras]
        sm = difflib.SequenceMatcher(None, [p for p, _ in esperadas], ouvidas, autojunk=False)
        mapa: dict[int, int] = {}
        for bloco in sm.get_matching_blocks():
            for k in range(bloco.size):
                mapa[bloco.a + k] = bloco.b + k
        achou = [False] * len(falas_prep)
        for idx, (_, cena) in enumerate(esperadas):
            if idx in mapa and not achou[cena]:
                inicios[cena] = max(0.0, palavras[mapa[idx]][1] - 0.08)
                achou[cena] = True
        if all(achou[1:]) and all(a < b for a, b in zip(inicios, inicios[1:])):
            inicios[0] = 0.0
            return inicios
        log.warning("alinhamento incompleto; usando divisão proporcional")
    tamanhos = [max(1, len(f)) for f in falas_prep]
    soma, acc = sum(tamanhos), 0.0
    for i, t in enumerate(tamanhos):
        inicios[i] = total * acc / soma
        acc += t
    return inicios


def _cortar(origem: Path, inicio: float, fim: float, destino: Path) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(origem), "-ss", f"{inicio:.3f}", "-to", f"{fim:.3f}",
                    "-ar", "24000", "-ac", "1", str(destino)], check=True)


def _atuada(pagina: Pagina, falas: list[str], pasta: Path, combo: dict) -> tuple[list[Path], list[float]]:
    """Grava o roteiro INTEIRO numa tomada só (entonação natural) e depois divide por cena."""
    estilos = pagina.cfg.get("estilos_voz", {})
    estilo = estilos.get(combo["estilo"], combo["estilo"])
    modelo = pagina.glob.get("voz", {}).get("modelo_atuada", "gemini-2.5-flash-preview-tts")
    prep = [_preparar(pagina, f, com_pausas=False) for f in falas]
    completo = pasta / "voz_tomada.wav"
    _gemini_tts("\n".join(prep), combo["voz"], estilo, modelo, completo)
    total = _duracao_wav(completo)
    inicios = _fronteiras(pagina, completo, prep, total)
    arquivos, duracoes = [], []
    for i, ini in enumerate(inicios):
        fim = inicios[i + 1] if i + 1 < len(inicios) else total
        dest = pasta / f"voz_{i:02d}.wav"
        _cortar(completo, ini, fim, dest)
        arquivos.append(dest)
        duracoes.append(_duracao_wav(dest))
    return arquivos, duracoes


class VozIndisponivel(RuntimeError):
    """Nenhuma voz de qualidade aceitável respondeu: o vídeo é adiado em vez de sair com voz robótica."""


def sintetizar_cenas(pagina: Pagina, falas: list[str], pasta: Path, combo: dict) -> tuple[list[Path], list[float], str]:
    """Gera um .wav por cena. Retorna (arquivos, durações, descrição da voz usada)."""
    cfg_voz = pagina.glob.get("voz", {})
    velocidade = float(pagina.cfg.get("velocidade_voz", 1.0))
    ultimo_erro = None
    aceitas = pagina.cfg.get("midia", {}).get("vozes_aceitas")  # ex.: [gemini, google] = nunca publicar com Piper
    for prov in cfg_voz.get("provedores", ["gemini", "google", "piper"]):
        if aceitas and prov not in aceitas:
            continue
        try:
            if prov == "gemini":
                if not combo.get("atuada"):
                    continue
                arquivos, duracoes = _atuada(pagina, falas, pasta, combo["atuada"])
                desc = f"{combo['atuada']['voz']} ({combo['atuada']['estilo']})"
            else:
                arquivos, duracoes = [], []
                for i, fala in enumerate(falas):
                    dest = pasta / f"voz_{i:02d}.wav"
                    txt = _preparar(pagina, fala)
                    if prov == "google":
                        _google(txt, combo["google"], velocidade, dest)
                    elif prov == "azure":
                        _azure(txt, combo["azure"], velocidade, dest)
                    else:
                        _piper(txt, velocidade, dest, cfg_voz.get("piper_modelo", ""))
                    arquivos.append(dest)
                    duracoes.append(_duracao_wav(dest))
                desc = combo.get(prov) or "piper"
            log.info("voz: %s (%d cenas, %.1fs)", desc, len(falas), sum(duracoes))
            return arquivos, duracoes, desc
        except Exception as e:  # noqa: BLE001
            ultimo_erro = e
            log.warning("voz %s falhou: %s", prov, e)
    raise VozIndisponivel(f"nenhuma voz aceita respondeu ({ultimo_erro})")
