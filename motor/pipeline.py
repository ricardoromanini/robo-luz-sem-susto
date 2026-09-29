"""Orquestra a criação de um post: pauta → roteiro → equipe de verificação → mídia → QC → fila."""
from __future__ import annotations

import json
import random
import re
import time
import unicodedata
from datetime import datetime, timedelta

from . import armazenamento, equipe, estado, ideias, llm, qc_tecnico, roteiro, telegram
from .config import Pagina
from .midia import ilustracoes, legendas, montagem, visuais, voz
from .registro import obter

log = obter("pipeline")
MAX_RODADAS_AJUSTE = 2


class CotaImagensEsgotada(RuntimeError):
    """Sem ilustrações hoje: o vídeo é adiado (a página prefere qualidade a quantidade)."""
MAX_PAUTAS = 3


def _slug(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40]


def _combinar(pautas: list[dict]) -> dict:
    """Para o vídeo longo: junta várias pautas num dossiê só."""
    fatos, ress = [], []
    for g, p in enumerate(pautas, 1):
        for f in p["fatos"]:
            fatos.append({**f, "id": f"G{g}{f['id']}", "texto": f"[{p['tema']}] {f['texto']}"})
        ress += [r for r in (p.get("ressalvas") or []) if r not in ress]
    return {"tema": "O que você precisa saber sobre a sua conta de luz esta semana: " + "; ".join(p["tema"] for p in pautas),
            "categoria": "resumo_semanal", "chave": "longo:" + "+".join(p["chave"] for p in pautas),
            "fatos": fatos, "ressalvas": ress, "grafico": next((p["grafico"] for p in pautas if p.get("grafico")), None),
            "partes": [p["chave"] for p in pautas]}


def controle(pagina: Pagina) -> dict:
    c = estado.ler(pagina, "controle", {})
    c.setdefault("pausado", False)
    c.setdefault("piloto", pagina.cfg.get("aprovacao", {}).get("modo") == "auto")
    c.setdefault("aprovacoes_seguidas", 0)
    return c


def proximo_horario(pagina: Pagina, formato: str) -> str:
    """Horário de publicação: melhor horário aprendido (80%) ou exploração (20%)."""
    agora = pagina.agora()
    freq = pagina.cfg.get("frequencia", {})
    if formato == "longo":
        dias = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
        alvo = dias.index(freq.get("video_longo", {}).get("dia_semana", "sabado"))
        h, m = map(int, freq.get("video_longo", {}).get("horario", "10:00").split(":"))
        dia = agora + timedelta(days=(alvo - agora.weekday()) % 7)
        quando = dia.replace(hour=h, minute=m, second=0, microsecond=0)
        if quando <= agora:
            quando += timedelta(days=7)
        return quando.isoformat()
    aprendido = estado.ler(pagina, "aprendizado", {}).get("melhor_horario")
    cands = freq.get("horarios_candidatos") or [freq.get("horario_inicial", "12:00")]
    hora = aprendido or freq.get("horario_inicial", cands[0])
    if random.random() < 0.2:
        hora = random.choice(cands)
    h, m = map(int, hora.split(":"))
    quando = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    ocupados = {i.get("horario_publicacao", "")[:13] for i in estado.fila(pagina) if i["status"] in ("aprovado", "aguardando_aprovacao")}
    while quando <= agora + timedelta(minutes=30) or quando.isoformat()[:13] in ocupados:
        quando += timedelta(days=1)
    return quando.isoformat()


def escrever_e_verificar(pagina: Pagina, formato: str, excluir: set[str] | None = None, observacao_humana: str = "") -> tuple[dict, dict, dict]:
    """Retorna (pauta, roteiro, parecer) com parecer APROVADO — ou levanta erro."""
    hist = estado.historico(pagina)
    titulos = [h.get("titulo", "") for h in hist]
    excluir = set(excluir or set())
    bloqueios = []
    for _ in range(MAX_PAUTAS):
        n = 3 if formato == "longo" else 1
        escolhidas = ideias.escolher(pagina, n, excluir)
        if not escolhidas:
            raise RuntimeError("sem pautas disponíveis — acrescente pautas em pautas.yaml")
        pauta = _combinar(escolhidas) if formato == "longo" else escolhidas[0]
        obs = observacao_humana
        for rodada in range(MAX_RODADAS_AJUSTE + 1):
            rot = roteiro.escrever(pagina, pauta, formato, obs, titulos)
            parecer = equipe.avaliar(pauta, rot, hist, roteiro.texto_completo(rot), roteiro.texto_falado(rot), formato,
                                     ultima_rodada=rodada == MAX_RODADAS_AJUSTE)
            parecer["rodadas"] = rodada + 1
            log.info("pauta '%s' rodada %d: %s", pauta["tema"][:60], rodada + 1, parecer["decisao"])
            if parecer["decisao"] in ("APROVADO", "BLOQUEADO"):
                break
            obs = (observacao_humana + "\n" if observacao_humana else "") + parecer["correcoes"]
            if parecer.get("sugestao_gancho"):
                obs += f"\n- Sugestão de gancho do revisor: {parecer['sugestao_gancho']}"
        if parecer["decisao"] == "APROVADO":
            return pauta, rot, parecer
        bloqueio = {"tema": pauta["tema"], "chave": pauta["chave"], "decisao": parecer["decisao"],
                    "correcoes": parecer["correcoes"][:1500], "em": datetime.now().isoformat()}
        bloqueios.append(bloqueio)
        registro = estado.ler(pagina, "bloqueios", [])
        estado.gravar(pagina, "bloqueios", (registro + [bloqueio])[-200:])
        excluir.add(pauta["chave"])
        for parte in pauta.get("partes", []):
            excluir.add(parte)
    raise RuntimeError(f"a equipe de verificação não aprovou nenhuma das {MAX_PAUTAS} pautas tentadas")


def produzir_midia(pagina: Pagina, pauta: dict, rot: dict, formato: str, pasta, indice_voz: int) -> dict:
    fmt_video = "16:9" if formato == "longo" else "9:16"
    w, h = visuais.FORMATOS[fmt_video]
    falas = [c["fala"] for c in rot["cenas"]]
    combo_voz = voz.escolher_voz(pagina, indice_voz)
    audios, duracoes, voz_usada = voz.sintetizar_cenas(pagina, falas, pasta, combo_voz)
    usadas: set[str] = set()
    cenas, creditos = [], []
    # o gráfico com o dado oficial é o melhor "visual" que temos: garante que ele apareça
    if pauta.get("grafico") and not any(c["visual"] == "grafico" for c in rot["cenas"]) and len(rot["cenas"]) >= 3:
        alvo = min(2, len(rot["cenas"]) - 2)
        rot["cenas"][alvo]["visual"] = "grafico"
    t_cenas = time.time()
    for i, c in enumerate(rot["cenas"]):
        cm = visuais.cena(pagina, c, pauta, fmt_video, usadas, rodape=rot.get("rodape", ""), indice=i, total=len(rot["cenas"]))
        if ilustracoes.COTA_ESGOTADA and pagina.cfg.get("midia", {}).get("exigir_ilustracoes", True):
            raise CotaImagensEsgotada("cota diária grátis de ilustrações esgotada — vídeo adiado para quando renovar")
        camada = pasta / f"cena_{i:02d}_camada.png"
        cm["camada"].save(camada)
        if cm["fundo"]["tipo"] == "video":
            fundo = cm["fundo"]["caminho"]
        else:
            fundo = pasta / f"cena_{i:02d}_fundo.jpg"
            cm["fundo"]["imagem"].save(fundo, quality=92)
        visuais.previa(cm, w, h).save(pasta / f"cena_{i:02d}.jpg", quality=85)  # quadro para conferência
        cenas.append({"fundo_tipo": cm["fundo"]["tipo"], "fundo": fundo, "camada": camada, "zoom": cm["zoom"]})
        if cm["credito"] and cm["credito"] not in creditos:
            creditos.append(cm["credito"])
    log.info("ilustrações/cenas prontas em %.0fs", time.time() - t_cenas)
    inicios, t = [], 0.0
    for d in duracoes:
        inicios.append(t)
        t += d + montagem.PAUSA
    fonte = visuais.caminho_fonte(pagina)
    nome_fonte = "Arial" if "arial" in fonte.lower() else "DejaVu Sans"
    ass = legendas.gerar_ass(pagina, falas, inicios, duracoes, w, h, pasta / "legendas.ass", nome_fonte)
    t_mont = time.time()
    video = montagem.montar(pasta, cenas, audios, duracoes, ass, w, h, pasta / "video.mp4")
    log.info("montagem em %.0fs", time.time() - t_mont)
    extra = {}
    if formato == "longo":
        extra["capa"] = str(visuais.capa(pagina, rot["titulo"], pasta / "capa.jpg"))
    qc = qc_tecnico.verificar(pagina, video, pasta / "voz_completa.wav", roteiro.texto_falado(rot), formato, (w, h))
    return {"video": video, "creditos": creditos, "voz": voz_usada, "qc": qc, **extra}


def montar_legenda(pagina: Pagina, pauta: dict, rot: dict, creditos: list[str], rotulo_ia: bool) -> dict:
    fontes = sorted({f["url"] for f in pauta["fatos"] if f.get("url")})
    base = rot["legenda"].strip()
    tags = " ".join(rot["hashtags"])
    aviso_ia = "Narração e roteiro produzidos com auxílio de IA e revisados por verificação de fatos." if rotulo_ia else ""
    cred = " · ".join(creditos)
    social = "\n\n".join(x for x in [base, aviso_ia, cred, tags] if x)
    yt_desc = "\n\n".join(x for x in [base, "Fontes:\n" + "\n".join(fontes) if fontes else "", aviso_ia, cred, tags] if x)
    return {"social": social[:2150], "youtube": yt_desc[:4900]}


def gerar_post(pagina: Pagina, formato: str = "short", enviar_telegram: bool = True, observacao_humana: str = "",
               excluir: set[str] | None = None) -> dict:
    agora = pagina.agora()
    pauta, rot, parecer = escrever_e_verificar(pagina, formato, excluir, observacao_humana)
    post_id = f"{agora:%Y%m%d-%H%M%S}-{_slug(rot['titulo'] or pauta['tema'])}"
    pasta = pagina.pasta_saida / post_id
    pasta.mkdir(parents=True, exist_ok=True)
    midia = produzir_midia(pagina, pauta, rot, formato, pasta, len(estado.historico(pagina)) + len(estado.fila(pagina)))
    legenda = montar_legenda(pagina, pauta, rot, midia["creditos"], parecer["rotulo_ia"])
    (pasta / "roteiro.json").write_text(roteiro.para_json(rot), encoding="utf-8")
    (pasta / "dossie.json").write_text(json.dumps(pauta, ensure_ascii=False, indent=2), encoding="utf-8")
    parecer_salvo = {k: v for k, v in parecer.items()}
    (pasta / "parecer_equipe.json").write_text(json.dumps(parecer_salvo, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (pasta / "legenda.txt").write_text(legenda["social"], encoding="utf-8")
    (pasta / "descricao_youtube.txt").write_text(legenda["youtube"], encoding="utf-8")
    ref = armazenamento.guardar(pagina.glob, pagina.id, midia["video"])
    item = {
        "id": post_id, "status": "aguardando_aprovacao", "criado_em": agora.isoformat(), "formato": formato,
        "horario_publicacao": proximo_horario(pagina, formato), "categoria": pauta["categoria"], "chave": pauta["chave"],
        "partes": pauta.get("partes", []), "titulo": rot["titulo"], "texto_falado": roteiro.texto_falado(rot),
        "legenda": legenda, "rotulo_ia": parecer["rotulo_ia"], "voz": midia["voz"], "video": ref,
        "capa": midia.get("capa"), "ia_redator": llm.ULTIMO_USO.get("redator"), "ia_verificador": llm.ULTIMO_USO.get("verificador"), "qc": {"ok": midia["qc"]["ok"], "problemas": midia["qc"]["problemas"], "info": midia["qc"]["info"]},
        "equipe": {"decisao": parecer["decisao"], "resumo": parecer["resumo"], "rodadas": parecer["rodadas"],
                   "alertas_dossie": parecer["alertas_dossie"]},
        "publicacoes": {},
    }
    (pasta / "item.json").write_text(json.dumps(item, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ctl = controle(pagina)
    if ctl["piloto"] and item["qc"]["ok"]:
        item["status"] = "aprovado"
    fila = estado.fila(pagina)
    fila.append(item)
    estado.salvar_fila(pagina, fila)
    if enviar_telegram:
        enviar_previa(pagina, item, midia["video"])
    return item


def enviar_previa(pagina: Pagina, item: dict, video) -> None:
    quando = datetime.fromisoformat(item["horario_publicacao"]).strftime("%d/%m %H:%M")
    qc = "✅ QC técnico ok" if item["qc"]["ok"] else "⚠️ QC técnico: " + "; ".join(item["qc"]["problemas"])
    alerta = ("\n🚩 Alerta sobre a base de fatos: " + "; ".join(item["equipe"]["alertas_dossie"])[:300]) if item["equipe"]["alertas_dossie"] else ""
    modo = "🤖 Piloto automático: sai sozinho" if item["status"] == "aprovado" else "👆 Toque em Aprovar para publicar"
    txt = (f"🎬 {pagina.nome} — {item['titulo']}\n🕒 Publicação: {quando} ({item['formato']}, {item['qc']['info'].get('duracao_s')}s)\n\n"
           f"{item['equipe']['resumo']}\n{qc}{alerta}\n\n{modo}")
    botoes = None if item["status"] == "aprovado" else telegram.botoes_aprovacao(pagina.id, item["id"])
    try:
        telegram.enviar_video(video, txt, botoes)
        telegram.enviar_texto("📝 Legenda:\n\n" + item["legenda"]["social"])
    except Exception as e:  # noqa: BLE001
        log.warning("não consegui mandar a prévia no Telegram: %s", e)
