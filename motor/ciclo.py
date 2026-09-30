"""CICLO (roda a cada ~20 min na nuvem):
  1. lê os botões/comandos do Telegram;
  2. refaz posts pedidos;
  3. publica o que está aprovado e chegou a hora;
  4. confere validade dos tokens (1x por dia).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import armazenamento, estado, pipeline, telegram
from .config import PASTA_ESTADO, Pagina, carregar_pagina, listar_paginas
from .publicar import meta, youtube
from .registro import alertar_erro, obter

log = obter("ciclo")
_ARQ_TG = PASTA_ESTADO / "_telegram.json"
MAX_TENTATIVAS = 3


def _tg_estado() -> dict:
    return json.loads(_ARQ_TG.read_text(encoding="utf-8")) if _ARQ_TG.exists() else {"offset": 0}


def _tg_salvar(d: dict) -> None:
    PASTA_ESTADO.mkdir(exist_ok=True)
    _ARQ_TG.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- Telegram

def _status_texto() -> str:
    linhas = []
    for p in listar_paginas():
        ctl = pipeline.controle(p)
        fila = estado.fila(p)
        cont = {}
        for i in fila:
            cont[i["status"]] = cont.get(i["status"], 0) + 1
        linhas.append(f"📄 {p.nome}: {'⏸ PAUSADA' if ctl['pausado'] else '▶️ ativa'} · "
                      f"{'🤖 piloto automático' if ctl['piloto'] else '👆 aprovação manual'} · "
                      f"aprovações seguidas: {ctl['aprovacoes_seguidas']}\n   fila: {cont or 'vazia'}")
        prox = sorted((i for i in fila if i["status"] == "aprovado"), key=lambda x: x["horario_publicacao"])
        if prox:
            linhas.append(f"   próximo: {prox[0]['titulo']} às {prox[0]['horario_publicacao'][11:16]} de {prox[0]['horario_publicacao'][8:10]}/{prox[0]['horario_publicacao'][5:7]}")
    return "\n".join(linhas) or "Nenhuma página ativa."


def _comando(texto: str, tg: dict) -> None:
    cmd = texto.strip().split()[0].lower()
    paginas = listar_paginas()
    if cmd in ("/pausar", "/retomar", "/piloto_on", "/piloto_off"):
        for p in paginas:
            ctl = pipeline.controle(p)
            if cmd == "/pausar":
                ctl["pausado"] = True
            elif cmd == "/retomar":
                ctl["pausado"] = False
            elif cmd == "/piloto_on":
                ctl["piloto"] = True
            else:
                ctl["piloto"] = False
            estado.gravar(p, "controle", ctl)
        msg = {"/pausar": "⏸ Publicações pausadas.", "/retomar": "▶️ Publicações retomadas.",
               "/piloto_on": "🤖 Piloto automático LIGADO. A equipe de verificação continua podendo barrar posts.",
               "/piloto_off": "👆 Aprovação manual ligada."}[cmd]
        telegram.enviar_texto(msg)
    elif cmd == "/status":
        telegram.enviar_texto(_status_texto())
    elif cmd in ("/ajuda", "/start", "/help"):
        telegram.enviar_texto("Comandos: /status /pausar /retomar /piloto_on /piloto_off\n"
                              "Depois de tocar em 🔁 Refazer, você pode mandar uma mensagem dizendo o que mudar (até 20 min).")
    elif tg.get("aguardando_obs"):
        pid, post = tg.pop("aguardando_obs")
        p = carregar_pagina(pid)
        estado.atualizar_item(p, post, observacao_humana=texto.strip()[:800])
        telegram.enviar_texto("📝 Anotado. Vou refazer com essa orientação.")


def _botao(cb: dict, tg: dict, pendente: bool = False) -> bool:
    """Trata um botão. Devolve False se o post ainda não foi salvo (a geração da noite ainda está rodando)."""
    responder = (lambda _id, txt: telegram.enviar_texto(txt)) if pendente else telegram.responder_botao
    try:
        acao, pid, post = cb["data"].split("|", 2)
        p = carregar_pagina(pid)
    except (ValueError, FileNotFoundError):
        responder(cb["id"], "Botão inválido.")
        return True
    item = next((i for i in estado.fila(p) if i["id"].startswith(post)), None)
    if not item:
        if not pendente:
            telegram.responder_botao(cb["id"], "⏳ Recebido! O robô ainda está terminando os outros posts; "
                                               "registro este botão assim que ele salvar tudo.")
        return False
    if item["status"] not in ("aguardando_aprovacao",):
        responder(cb["id"], f"Este post já está: {item['status']}.")
        return True
    ctl = pipeline.controle(p)
    if acao == "ap":
        novo_horario = item["horario_publicacao"]
        if datetime.fromisoformat(novo_horario) <= p.agora():
            novo_horario = pipeline.proximo_horario(p, item["formato"])
        estado.atualizar_item(p, item["id"], status="aprovado", horario_publicacao=novo_horario, aprovado_por="dono")
        ctl["aprovacoes_seguidas"] += 1
        responder(cb["id"], f"✅ Aprovado! Sai em {novo_horario[8:10]}/{novo_horario[5:7]} às {novo_horario[11:16]}.")
        lim = int(p.cfg.get("aprovacao", {}).get("sugerir_piloto_apos", 15))
        if not ctl["piloto"] and ctl["aprovacoes_seguidas"] == lim:
            telegram.enviar_texto(f"🎉 {lim} aprovações seguidas sem ajuste. Se quiser, mande /piloto_on para o robô publicar "
                                  "sozinho (a equipe de verificação continua barrando o que tiver problema).")
    elif acao == "rf":
        estado.atualizar_item(p, item["id"], status="refazer", refazer_desde=p.agora().isoformat())
        ctl["aprovacoes_seguidas"] = 0
        tg["aguardando_obs"] = [p.id, item["id"]]
        responder(cb["id"], "🔁 Vou refazer.")
        telegram.enviar_texto("🔁 Vou refazer este post. Se quiser, responda com o que mudar (ex.: \"gancho mais forte\", "
                              "\"fale de outra distribuidora\"). Sem resposta em 20 min, refaço com outro ângulo.")
    elif acao == "dc":
        estado.atualizar_item(p, item["id"], status="descartado")
        armazenamento.apagar(item["video"])
        ctl["aprovacoes_seguidas"] = 0
        responder(cb["id"], "🗑 Descartado.")
    estado.gravar(p, "controle", ctl)
    return True


def processar_telegram() -> None:
    tg = _tg_estado()
    # botões tocados enquanto a geração ainda rodava: tenta de novo (desiste depois de 24 h)
    ainda = []
    for cb in tg.pop("pendentes", []):
        try:
            if not _botao(cb, tg, pendente=True) and time.time() - cb["em"] < 86400:
                ainda.append(cb)
        except Exception as e:  # noqa: BLE001
            alertar_erro("processando botão pendente do Telegram", e)
    if ainda:
        tg["pendentes"] = ainda
    for up in telegram.ler_atualizacoes(tg.get("offset", 0)):
        tg["offset"] = up["update_id"] + 1
        if not telegram.do_dono(up):
            continue
        try:
            if "callback_query" in up:
                cb = up["callback_query"]
                if not _botao(cb, tg):
                    tg.setdefault("pendentes", []).append({"data": cb["data"], "id": cb["id"], "em": time.time()})
            elif up.get("message", {}).get("text"):
                _comando(up["message"]["text"], tg)
        except Exception as e:  # noqa: BLE001
            alertar_erro("processando mensagem do Telegram", e)
    _tg_salvar(tg)


# --------------------------------------------------------------------------- refazer / expirar

def refazer_pendentes(p: Pagina) -> None:
    for item in estado.fila(p):
        if item["status"] != "refazer":
            continue
        desde = datetime.fromisoformat(item.get("refazer_desde", item["criado_em"]))
        obs = item.get("observacao_humana", "")
        if not obs and p.agora() - desde < timedelta(minutes=20):
            continue
        estado.atualizar_item(p, item["id"], status="substituido")
        armazenamento.apagar(item["video"])
        pedido = f"O DONO DA PÁGINA pediu para refazer o post \"{item['titulo']}\". " + (f"Orientação dele: {obs}" if obs else
                                                                                         "Mude o ângulo, o gancho e a estrutura.")
        try:
            pipeline.gerar_post(p, item["formato"], observacao_humana=pedido)
        except Exception as e:  # noqa: BLE001
            alertar_erro(f"refazendo post de {p.nome}", e)


def expirar_antigos(p: Pagina) -> None:
    """Prévia sem resposta por 3 dias é descartada (notícia velha não serve)."""
    for item in estado.fila(p):
        if item["status"] == "aguardando_aprovacao" and p.agora() - datetime.fromisoformat(item["criado_em"]) > timedelta(days=3):
            estado.atualizar_item(p, item["id"], status="expirado")
            armazenamento.apagar(item["video"])


# --------------------------------------------------------------------------- publicação

def _publicar_item(p: Pagina, item: dict) -> None:
    pasta = p.pasta_saida / item["id"]
    video = armazenamento.recuperar(item["video"], pasta)
    pubs = dict(item.get("publicacoes") or {})
    erros = []
    leg = item["legenda"]
    tags = [w for w in leg["social"].split() if w.startswith("#")]
    alvos = []
    if p.plataforma_ativa("youtube") and youtube.configurado(p):
        alvos.append(("youtube", lambda: youtube.publicar(p, video, item["titulo"], leg["youtube"], tags, item["rotulo_ia"], item.get("capa"))))
    if item["formato"] == "short":
        if p.plataforma_ativa("instagram") and meta.ig_configurado(p):
            alvos.append(("instagram", lambda: meta.publicar_instagram(p, video, leg["social"])))
        if p.plataforma_ativa("facebook") and meta.fb_configurado(p):
            alvos.append(("facebook", lambda: meta.publicar_facebook(p, video, leg["social"])))
    if not alvos:
        raise RuntimeError("nenhuma plataforma configurada (faltam tokens — veja SETUP_CONTAS.md)")
    for nome, fn in alvos:
        if nome in pubs:
            continue
        try:
            pubs[nome] = fn()
            log.info("%s publicado: %s", nome, pubs[nome].get("url"))
        except Exception as e:  # noqa: BLE001
            erros.append(f"{nome}: {e}")
    tentativas = item.get("tentativas", 0) + (1 if erros else 0)
    concluido = not erros
    status = "publicado" if concluido else ("erro" if tentativas >= MAX_TENTATIVAS else "aprovado")
    estado.atualizar_item(p, item["id"], publicacoes=pubs, tentativas=tentativas, status=status,
                          publicado_em=p.agora().isoformat() if concluido else None)
    if pubs and (concluido or status == "erro"):
        estado.adicionar_historico(p, {"id": item["id"], "chave": item["chave"], "categoria": item["categoria"],
                                       "titulo": item["titulo"], "texto_falado": item["texto_falado"],
                                       "formato": item["formato"], "horario": item["horario_publicacao"][11:16],
                                       "publicado_em": p.agora().isoformat(), "publicacoes": pubs})
        for parte in item.get("partes", []):
            estado.adicionar_historico(p, {"id": item["id"] + ":" + parte, "chave": parte, "categoria": "parte_longo",
                                           "titulo": "", "texto_falado": ""})
    links = "\n".join(f"• {k}: {v.get('url')}" for k, v in pubs.items())
    msg = f"✅ Publicado — {item['titulo']}\n{links}" if pubs else ""
    if pubs.get("youtube", {}).get("privado"):
        msg += ("\n\n⚠️ YouTube: o vídeo ficou PRIVADO porque o app ainda não passou na auditoria do Google. "
                "Abra o app YouTube Studio > Conteúdo > este vídeo > Visibilidade > Público.")
    if concluido and item["formato"] == "short" and p.cfg.get("plataformas", {}).get("tiktok", {}).get("ativa"):
        msg += ("\n\n📲 TikTok (manual): poste o vídeo da prévia com a legenda abaixo e ATIVE a opção "
                "\"Conteúdo gerado por IA\" nas configurações do post.")
    if msg:
        telegram.enviar_texto(msg)
        if concluido and item["formato"] == "short":
            legenda_tt = item["legenda"]["social"]
            arroba_tt = p.cfg.get("plataformas", {}).get("tiktok", {}).get("arroba")
            if arroba_tt and p.cfg.get("arroba"):  # no TikTok o @ da página pode ser outro
                legenda_tt = legenda_tt.replace(p.cfg["arroba"], arroba_tt)
            telegram.enviar_texto(legenda_tt)
    if erros:
        alertar_erro(f"publicando \"{item['titulo']}\" (tentativa {tentativas}/{MAX_TENTATIVAS})\n" + "\n".join(erros))
    if concluido:
        armazenamento.apagar(item["video"])


def publicar_vencidos(p: Pagina) -> None:
    if pipeline.controle(p)["pausado"]:
        return
    alguma_conta = (youtube.configurado(p) or meta.ig_configurado(p) or meta.fb_configurado(p))
    for item in sorted(estado.fila(p), key=lambda x: x["horario_publicacao"]):
        if item["status"] == "aprovado" and datetime.fromisoformat(item["horario_publicacao"]) <= p.agora() and not alguma_conta:
            estado.atualizar_item(p, item["id"], status="aguardando_contas")
            telegram.enviar_texto(f"📦 \"{item['titulo']}\" foi aprovado, mas as contas do YouTube/Instagram/Facebook ainda "
                                  "não estão ligadas ao robô. O vídeo fica guardado; você pode postar à mão o vídeo da prévia.")
            continue
        if item["status"] == "aprovado" and datetime.fromisoformat(item["horario_publicacao"]) <= p.agora():
            try:
                _publicar_item(p, item)
            except Exception as e:  # noqa: BLE001
                alertar_erro(f"publicando {item['id']}", e)
            break  # no máximo 1 publicação por página por ciclo (ritmo humano)


def conferir_tokens(p: Pagina) -> None:
    ctl = pipeline.controle(p)
    hoje = p.agora().date().isoformat()
    if ctl.get("tokens_conferidos_em") == hoje:
        return
    ctl["tokens_conferidos_em"] = hoje
    estado.gravar(p, "controle", ctl)
    avisos = []
    if meta.ig_configurado(p) or meta.fb_configurado(p):
        dias = meta.validade_token(p)
        if dias is not None and dias <= 10:
            avisos.append(f"Token da Meta vence em {dias} dia(s). Rode: python main.py token-meta --pagina {p.id}")
    if youtube.configurado(p):
        try:
            youtube.token_acesso(p)
        except Exception as e:  # noqa: BLE001
            avisos.append(str(e))
    if avisos:
        telegram.enviar_texto(f"🔑 {p.nome}:\n" + "\n".join(avisos))


def rodar() -> None:
    processar_telegram()
    for p in listar_paginas():
        try:
            refazer_pendentes(p)
            expirar_antigos(p)
            publicar_vencidos(p)
            conferir_tokens(p)
        except Exception as e:  # noqa: BLE001
            alertar_erro(f"ciclo da página {p.nome}", e)
