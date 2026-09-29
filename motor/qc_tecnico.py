"""Controle de qualidade TÉCNICO do vídeo pronto (sem IA de texto).

Confere: duração dentro do formato, resolução, áudio presente, volume (LUFS),
e se a voz disse o roteiro (transcrição × texto, quando houver transcrição).
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import unicodedata
from pathlib import Path

from .config import Pagina
from .midia import legendas, montagem
from .midia.voz import normalizar_fala


def _palavras(t: str) -> list[str]:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z]+|\d+", t)


def loudness(arq: Path) -> float | None:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(arq), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    return float(json.loads(m.group(0))["input_i"]) if m else None


def verificar(pagina: Pagina, video: Path, audio_voz: Path, texto_falado: str, formato: str, esperado_wh: tuple[int, int]) -> dict:
    problemas, info = [], {}
    meta = montagem.sondar(video)
    dur = float(meta["format"]["duration"])
    info["duracao_s"] = round(dur, 1)
    v = next((s for s in meta["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in meta["streams"] if s["codec_type"] == "audio"), None)
    if not v or (v["width"], v["height"]) != esperado_wh:
        problemas.append(f"resolução inesperada: {v and (v['width'], v['height'])}")
    if not a:
        problemas.append("vídeo sem áudio")
    if formato == "longo":
        lim = pagina.cfg.get("duracao_longo_minutos", {})
        mn, mx = lim.get("minimo", 4) * 60, lim.get("maximo", 10) * 60
    else:
        lim = pagina.cfg.get("duracao_short_segundos", {})
        mn, mx = lim.get("minimo", 25), lim.get("maximo", 58)
    if not (mn <= dur <= mx):
        problemas.append(f"duração {dur:.0f}s fora do limite ({mn}–{mx}s)")
    lufs = loudness(video)
    info["lufs"] = lufs
    if lufs is not None and not (-17 <= lufs <= -11):
        problemas.append(f"volume fora do padrão ({lufs:.1f} LUFS; ideal -14)")
    transcricao = legendas.transcrever(pagina, audio_voz)
    if transcricao:
        esperado = _palavras(normalizar_fala(texto_falado))
        ouvido = _palavras(transcricao)
        sim = difflib.SequenceMatcher(None, esperado, ouvido).ratio()
        info["fala_confere"] = round(sim, 2)
        if sim < 0.70:
            problemas.append(f"a voz não bate com o roteiro (semelhança {sim:.0%}) — possível erro de pronúncia")
    else:
        info["fala_confere"] = "sem transcrição"
    return {"ok": not problemas, "problemas": problemas, "info": info, "transcricao": transcricao}
