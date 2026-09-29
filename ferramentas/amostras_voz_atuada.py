"""Gera amostras da voz "atuada" (Gemini-TTS) em vários estilos, para comparar.

Uso:  python ferramentas/amostras_voz_atuada.py
Saída: saida/amostras_voz_atuada/*.mp3
"""
from __future__ import annotations

import base64
import subprocess
import sys
import time
import wave
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from motor.config import RAIZ, carregar_env, env  # noqa: E402

carregar_env()

MODELO = "gemini-2.5-flash-preview-tts"
TEXTO = ("Sabia que o seu ferro de passar pode estar pesando na conta de luz? "
         "Na tarifa da E D P Espírito Santo, ele custa cerca de... 4 reais e 34 centavos por mês. "
         "É uma estimativa, usando uma hora por semana, sem impostos. Dados da Aneel.")

ESTILOS = {
    "tio_bem_humorado": "Narre como um tio brasileiro carismático e bem-humorado contando uma curiosidade para a família: "
                        "voz calorosa e expressiva, ritmo animado, leve sorriso na voz, surpresa na pergunta inicial.",
    "apresentador_firme": "Narre como um apresentador de TV brasileiro confiante: voz firme e grave, ritmo dinâmico, "
                          "pausa curta antes do valor, ênfase forte nos números, final decidido.",
    "curioso_animado": "Narre como um criador de conteúdo brasileiro animado revelando um fato surpreendente: energia alta, "
                       "entonação bem variada, curiosidade na pergunta, empolgação ao revelar o valor.",
    "serio_confiavel": "Narre como um especialista brasileiro sério e confiável: voz firme, calma e clara, pausas naturais, "
                       "tom de quem está protegendo a família do ouvinte.",
}
VOZES = ["Algenib", "Fenrir"]


def gerar(voz: str, estilo: str, destino: Path) -> None:
    corpo = {
        "contents": [{"parts": [{"text": f"{estilo}\n\nTexto (português do Brasil):\n{TEXTO}"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}},
        },
    }
    for tentativa in range(4):
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent",
                          headers={"x-goog-api-key": env("GEMINI_API_KEY", obrigatorio=True)}, json=corpo, timeout=180)
        if r.status_code == 429:  # cota por minuto do plano grátis
            time.sleep(25)
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError("cota esgotada")
    pcm = base64.b64decode(r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    wav = destino.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-b:a", "128k", str(destino)], check=True)
    wav.unlink()


def main() -> None:
    pasta = RAIZ / "saida" / "amostras_voz_atuada"
    pasta.mkdir(parents=True, exist_ok=True)
    for voz in VOZES:
        for nome, estilo in ESTILOS.items():
            arq = pasta / f"{voz}_{nome}.mp3"
            try:
                gerar(voz, estilo, arq)
                print("ok", arq.name)
            except Exception as e:  # noqa: BLE001
                print("ERRO", arq.name, str(e)[:300])


if __name__ == "__main__":
    main()
