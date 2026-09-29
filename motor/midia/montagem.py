"""Montagem final com FFmpeg: cenas (com leve movimento) + voz + legendas queimadas.

Saídas: 9:16 (Shorts/Reels/TikTok) e, para vídeo longo, 16:9.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..registro import obter

log = obter("montagem")
FPS = 30
PAUSA = 0.18  # respiro entre cenas (s)


def _ff(args: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr[-1500:]}")


def sondar(arq: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(arq)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def montar(pasta: Path, cenas: list[dict], audios: list[Path], duracoes: list[float], ass: Path,
           w: int, h: int, destino: Path) -> Path:
    """Gera o vídeo final.

    cenas[i] = {"fundo_tipo": "video"|"imagem", "fundo": Path, "camada": Path (PNG transparente), "zoom": bool}
    duracoes[i] = duração da fala da cena (sem a pausa).
    """
    tmp = pasta / "tmp"
    tmp.mkdir(exist_ok=True)
    clipes = []
    for i, (c, dur) in enumerate(zip(cenas, duracoes)):
        d = dur + PAUSA
        frames = max(int(round(d * FPS)), 1)
        saida = tmp / f"cena_{i:02d}.mp4"
        if c["fundo_tipo"] == "video":
            # vídeo de banco: preenche a tela, repete se for curto, sem áudio; camada de texto por cima
            fc = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1[b];"
                  f"[b][1:v]overlay=0:0,format=yuv420p[v]")
            _ff(["-stream_loop", "-1", "-i", str(c["fundo"]), "-loop", "1", "-i", str(c["camada"]),
                 "-filter_complex", fc, "-map", "[v]", "-an", "-frames:v", str(frames),
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", str(saida)])
        else:
            # foto/cartão: zoom lento alternando entrada/saída (movimento sem distrair); camada parada por cima
            if c.get("zoom", True):
                z = f"1+0.08*on/{frames}" if i % 2 == 0 else f"1.08-0.08*on/{frames}"
                mov = (f"scale={int(w * 1.25) // 2 * 2}:{int(h * 1.25) // 2 * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={FPS}")
            else:
                mov = f"scale={w}:{h},fps={FPS}"
            fc = f"[0:v]{mov},setsar=1[b];[b][1:v]overlay=0:0,format=yuv420p[v]"
            _ff(["-loop", "1", "-framerate", str(FPS), "-i", str(c["fundo"]), "-loop", "1", "-i", str(c["camada"]),
                 "-filter_complex", fc, "-map", "[v]", "-frames:v", str(frames),
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", str(saida)])
        clipes.append(saida)
    # vídeo contínuo
    lista = tmp / "lista.txt"
    lista.write_text("".join(f"file '{c.name}'\n" for c in clipes), encoding="utf-8")
    _ff(["-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "video.mp4"], cwd=tmp)
    # áudio contínuo (cada fala + pausa)
    entradas, filtros = [], []
    for i, a in enumerate(audios):
        entradas += ["-i", str(a)]
        filtros.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=mono,apad=pad_dur={PAUSA}[a{i}]")
    filtros.append("".join(f"[a{i}]" for i in range(len(audios))) + f"concat=n={len(audios)}:v=0:a=1[aout]")
    _ff([*entradas, "-filter_complex", ";".join(filtros), "-map", "[aout]", str(tmp / "voz.wav")])
    # final: legendas + loudness -14 LUFS (padrão das redes)
    shutil.copy(ass, tmp / "leg.ass")
    _ff(["-i", "video.mp4", "-i", "voz.wav", "-vf", "ass=leg.ass", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", "final.mp4"], cwd=tmp)
    shutil.move(str(tmp / "final.mp4"), destino)
    shutil.copy(tmp / "voz.wav", pasta / "voz_completa.wav")
    shutil.rmtree(tmp, ignore_errors=True)
    log.info("vídeo pronto: %s", destino.name)
    return destino
