"""Legendas queimadas no vídeo (arquivo .ass) + transcrição para o controle de qualidade.

Tempo das legendas: como cada cena tem seu próprio áudio, as palavras são
distribuídas dentro da duração exata da cena (proporcional ao tamanho de cada
palavra). A transcrição (Groq Whisper ou faster-whisper) serve para o QC conferir
se a voz falou exatamente o roteiro.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import requests

from ..config import Pagina, env
from ..registro import obter

log = obter("legendas")


def _t(seg: float) -> str:
    h, r = divmod(max(seg, 0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_cor(hex_: str) -> str:
    c = hex_.lstrip("#")
    return f"&H00{c[4:6]}{c[2:4]}{c[0:2]}".upper()


def gerar_ass(pagina: Pagina, falas: list[str], inicios: list[float], duracoes: list[float], w: int, h: int,
              destino: Path, fonte_nome: str = "Arial") -> Path:
    v = pagina.cfg.get("visual", {})
    vertical = h > w
    tam = 78 if vertical else 64
    margem_v = int(h * (0.20 if vertical else 0.08))
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Leg,{fonte_nome},{tam},&H00FFFFFF,{_ass_cor(v.get('cor_destaque', '#FFC107'))},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,{margem_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    eventos = []
    for fala, ini, dur in zip(falas, inicios, duracoes):
        palavras = fala.split()
        if not palavras:
            continue
        pesos = [len(p) + 2 for p in palavras]
        total = sum(pesos)
        t = ini
        blocos, atual, peso_atual = [], [], 0
        for p, pe in zip(palavras, pesos):
            atual.append(p)
            peso_atual += pe
            if len(atual) >= 3 or re.search(r"[.,!?;:]$", p):
                blocos.append((" ".join(atual), peso_atual))
                atual, peso_atual = [], 0
        if atual:
            blocos.append((" ".join(atual), peso_atual))
        for texto, pe in blocos:
            d = dur * pe / total
            eventos.append(f"Dialogue: 0,{_t(t)},{_t(t + d)},Leg,,0,0,0,,{texto.upper()}")
            t += d
    destino.write_text(cab + "\n".join(eventos) + "\n", encoding="utf-8")
    return destino


def transcrever(pagina: Pagina, audio: Path) -> str:
    """Transcrição em português (para o QC). Retorna '' se nenhum provedor estiver disponível."""
    for prov in pagina.glob.get("legendas", {}).get("provedores", ["groq", "faster_whisper"]):
        try:
            if prov == "groq":
                chave = env("GROQ_API_KEY")
                if not chave:
                    continue
                with open(audio, "rb") as f:
                    r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                      headers={"Authorization": f"Bearer {chave}"},
                                      files={"file": (audio.name, f)},
                                      data={"model": "whisper-large-v3-turbo", "language": "pt", "response_format": "json"},
                                      timeout=300)
                r.raise_for_status()
                return r.json().get("text", "")
            if prov == "faster_whisper":
                from faster_whisper import WhisperModel

                modelo = os.environ.get("WHISPER_MODELO") or pagina.glob.get("legendas", {}).get("faster_whisper_modelo", "small")
                wm = WhisperModel(modelo, device="cpu", compute_type="int8")
                segs, _ = wm.transcribe(str(audio), language="pt", vad_filter=False)
                return " ".join(s.text.strip() for s in segs)
        except Exception as e:  # noqa: BLE001
            log.warning("transcrição via %s falhou: %s", prov, e)
    return ""


def palavras_com_tempo(pagina: Pagina, audio: Path) -> list[tuple[str, float, float]]:
    """[(palavra, início, fim)] — usado para achar onde cada cena começa numa gravação contínua."""
    for prov in pagina.glob.get("legendas", {}).get("provedores", ["groq", "faster_whisper"]):
        try:
            if prov == "groq":
                chave = env("GROQ_API_KEY")
                if not chave:
                    continue
                with open(audio, "rb") as f:
                    r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                      headers={"Authorization": f"Bearer {chave}"}, files={"file": (audio.name, f)},
                                      data={"model": "whisper-large-v3-turbo", "language": "pt", "response_format": "verbose_json",
                                            "timestamp_granularities[]": "word"}, timeout=300)
                r.raise_for_status()
                return [(w["word"].strip(), float(w["start"]), float(w["end"])) for w in r.json().get("words", [])]
            if prov == "faster_whisper":
                from faster_whisper import WhisperModel

                modelo = os.environ.get("WHISPER_MODELO") or pagina.glob.get("legendas", {}).get("faster_whisper_modelo", "small")
                wm = WhisperModel(modelo.strip(), device="cpu", compute_type="int8")
                segs, _ = wm.transcribe(str(audio), language="pt", word_timestamps=True)
                return [(w.word.strip(), w.start, w.end) for s in segs for w in (s.words or [])]
        except Exception as e:  # noqa: BLE001
            log.warning("palavras com tempo via %s falhou: %s", prov, e)
    return []
