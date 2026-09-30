"""Painel de comandos do robô.

  python main.py gerar                 gera os posts do dia (todas as páginas ativas) e manda a prévia no Telegram
  python main.py gerar --formato longo gera o vídeo longo da semana
  python main.py ciclo                 lê o Telegram, refaz pedidos e publica o que está aprovado e na hora
  python main.py semanal               métricas + ajustes + relatório semanal
  python main.py exemplos --quantidade 3   gera posts de EXEMPLO no seu PC, sem publicar nada
  python main.py testar                confere se as chaves/tokens estão funcionando
  python main.py token-youtube --pagina energia-em-casa   autoriza o canal do YouTube (abre o navegador)
  python main.py token-meta --pagina energia-em-casa      autoriza Instagram + Página do Facebook (abre o navegador)
  python main.py telegram-id           descobre o número do seu chat no Telegram (mande "oi" para o bot antes)
"""
from __future__ import annotations

import argparse
import http.server
import json
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

from motor.config import RAIZ, carregar_env, carregar_pagina, env, listar_paginas

carregar_env()

from motor import ciclo, estado, pipeline, relatorio  # noqa: E402
from motor.midia import voz  # noqa: E402
from motor.registro import alertar_erro, obter  # noqa: E402

log = obter("main")


def _paginas(args) -> list:
    return [carregar_pagina(args.pagina)] if getattr(args, "pagina", None) else listar_paginas()


def cmd_gerar(args) -> None:
    for p in _paginas(args):
        n = 1 if args.formato == "longo" else int(args.quantidade or p.cfg.get("frequencia", {}).get("shorts_por_dia", 1))
        pendentes = [i for i in estado.fila(p) if i["status"] in ("aguardando_aprovacao", "aprovado") and i["formato"] == args.formato]
        if args.formato == "short" and len(pendentes) >= n + 2:
            log.info("%s: já há %d posts na fila; não gero mais hoje", p.nome, len(pendentes))
            continue
        for _ in range(n):
            try:
                item = pipeline.gerar_post(p, args.formato)
                log.info("gerado: %s (%s)", item["titulo"], item["status"])
            except pipeline.CotaImagensEsgotada as e:
                from motor import telegram
                telegram.enviar_texto(f"🖼️ {p.nome}: {e}. Tento de novo na próxima rodada.")
                break
            except voz.VozIndisponivel as e:
                from motor import telegram
                telegram.enviar_texto(f"🎙️ {p.nome}: vídeo adiado — {e}. Não publico com voz robótica; "
                                      "tento de novo na próxima rodada.")
                break
            except Exception as e:  # noqa: BLE001
                alertar_erro(f"gerando post ({args.formato}) de {p.nome}", e)


def cmd_ciclo(args) -> None:
    ciclo.rodar()


def cmd_semanal(args) -> None:
    for p in _paginas(args):
        try:
            relatorio.semanal(p)
        except Exception as e:  # noqa: BLE001
            alertar_erro(f"relatório semanal de {p.nome}", e)


def cmd_exemplos(args) -> None:
    """Gera posts de exemplo localmente (sem Telegram e sem publicar) e um resumo EXEMPLOS.md."""
    for p in _paginas(args):
        itens = []
        # não repete temas de exemplos que já existem na pasta
        excluir: set[str] = {json.loads(d.read_text(encoding="utf-8")).get("chave", "") for d in p.pasta_saida.glob("*/dossie.json")}
        formatos = ["short"] * int(args.quantidade)
        if args.com_longo:
            formatos.append("longo")
        for f in formatos:
            try:
                it = pipeline.gerar_post(p, f, enviar_telegram=False, excluir=excluir)
                excluir.add(it["chave"])
                itens.append(it)
            except Exception as e:  # noqa: BLE001
                alertar_erro(f"exemplo {f}", e)
        linhas = [f"# Posts de exemplo — {p.nome}", "", "Gerados no PC, **sem publicar**. Cada pasta tem: video.mp4, roteiro.json, "
                  "dossie.json (fatos e fontes), parecer_equipe.json (verificação), legenda.txt.", ""]
        todos = [json.loads(a.read_text(encoding="utf-8")) for a in sorted(p.pasta_saida.glob("*/item.json"))]
        for it in todos:
            linhas += [f"## {it['titulo']}", "", f"- Pasta: `saida/{p.id}/{it['id']}/`",
                       f"- Formato: {it['formato']} · duração {it['qc']['info'].get('duracao_s')} s · volume {it['qc']['info'].get('lufs')} LUFS "
                       f"· voz confere com roteiro: {it['qc']['info'].get('fala_confere')}",
                       f"- QC técnico: {'ok' if it['qc']['ok'] else '; '.join(it['qc']['problemas'])}",
                       f"- IA que escreveu: {it.get('ia_redator', '?')} · IA que verificou: {it.get('ia_verificador', '?')} · voz: {it.get('voz', '?')}",
                       f"- Equipe de verificação ({it['equipe']['rodadas']} rodada(s)):", "", "```", it["equipe"]["resumo"], "```", "",
                       "Legenda:", "", "```", it["legenda"]["social"], "```", ""]
        (p.pasta_saida / "EXEMPLOS.md").write_text("\n".join(linhas), encoding="utf-8")
        # exemplos não entram na fila real
        estado.salvar_fila(p, [i for i in estado.fila(p) if i["id"] not in {x["id"] for x in itens}])
        print(f"\n✅ {len(itens)} exemplo(s) em {p.pasta_saida}")


def cmd_testar(args) -> None:
    from motor import llm, telegram
    from motor.publicar import meta, youtube

    ok = lambda b: "✅" if b else "❌"  # noqa: E731
    print("IA de texto:")
    for papel in ("redator", "verificador"):
        try:
            r = llm.perguntar(papel, "Responda em JSON.", 'Devolva {"ok": true}')
            print(f"  {ok(r.get('ok'))} {papel}")
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {papel}: {e}")
    print(f"Voz Google: {ok(bool(env('GOOGLE_TTS_API_KEY')))}  · Pexels: {ok(bool(env('PEXELS_API_KEY')))}  · Pixabay: {ok(bool(env('PIXABAY_API_KEY')))}")
    try:
        r = telegram.enviar_texto("🔌 Teste de conexão do robô: OK")
        print(f"Telegram: {ok(bool(r))}")
    except Exception as e:  # noqa: BLE001
        print(f"Telegram: ❌ {e}")
    for p in _paginas(args):
        print(f"Página {p.nome}:")
        try:
            print(f"  YouTube: {ok(youtube.configurado(p))}", youtube.estatisticas_canal(p) if youtube.configurado(p) else "")
        except Exception as e:  # noqa: BLE001
            print(f"  YouTube: ❌ {e}")
        try:
            print(f"  Instagram: {ok(meta.ig_configurado(p))}  Facebook: {ok(meta.fb_configurado(p))}",
                  meta.seguidores(p) if meta.ig_configurado(p) else "")
        except Exception as e:  # noqa: BLE001
            print(f"  Meta: ❌ {e}")


# ------------------------------------------------------------------ autorizações (rodam no seu PC)

def _receber_codigo(porta: int, url_autorizacao: str) -> str:
    codigo = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("code"):
                codigo["code"] = q["code"][0]
            if q.get("error"):
                codigo["erro"] = q["error"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Pronto! Pode fechar esta aba e voltar ao robô.</h2>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("localhost", porta), H)
    srv.timeout = 2

    def atender():
        # atende várias chamadas (o navegador às vezes pede outra coisa antes) até chegar o código ou o erro
        fim = time.time() + 900
        while time.time() < fim and not (codigo.get("code") or codigo.get("erro")):
            srv.handle_request()

    t = threading.Thread(target=atender)
    t.start()
    print("Abrindo o navegador para você autorizar... (se não abrir, copie o link abaixo)\n" + url_autorizacao, flush=True)
    webbrowser.open(url_autorizacao)
    t.join(timeout=920)
    srv.server_close()
    if not codigo.get("code"):
        raise SystemExit(f"Autorização não concluída: {codigo.get('erro') or 'tempo esgotado'}")
    return codigo["code"]


def _gravar_env(chave: str, valor: str) -> None:
    arq = RAIZ / ".env"
    linhas = arq.read_text(encoding="utf-8").splitlines() if arq.exists() else []
    linhas = [l for l in linhas if not l.startswith(chave + "=")] + [f"{chave}={valor}"]
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"✅ {chave} gravado no .env (e cadastre o mesmo valor como Secret no GitHub — veja SETUP_CONTAS.md)")


def cmd_token_youtube(args) -> None:
    from motor.publicar.youtube import ESCOPOS

    porta = 8087
    redir = f"http://localhost:{porta}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": env("YOUTUBE_CLIENT_ID", obrigatorio=True), "redirect_uri": redir, "response_type": "code",
        "scope": " ".join(ESCOPOS), "access_type": "offline", "prompt": "consent"})
    code = _receber_codigo(porta, url)
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": env("YOUTUBE_CLIENT_ID"), "client_secret": env("YOUTUBE_CLIENT_SECRET", obrigatorio=True),
        "redirect_uri": redir, "grant_type": "authorization_code"}, timeout=30)
    r.raise_for_status()
    rt = r.json().get("refresh_token")
    if not rt:
        raise SystemExit("O Google não devolveu refresh_token. Remova o acesso do app em myaccount.google.com/permissions e tente de novo.")
    _gravar_env(f"YOUTUBE_REFRESH_TOKEN_{args.pagina.upper().replace('-', '_')}", rt)


def cmd_token_meta(args) -> None:
    porta = 8085
    redir = f"http://localhost:{porta}/"
    app_id, secret = env("META_APP_ID", obrigatorio=True), env("META_APP_SECRET", obrigatorio=True)
    v = env("META_GRAPH_VERSION") or "v23.0"
    escopos = env("META_ESCOPOS") or "pages_show_list,pages_read_engagement,pages_manage_posts,business_management,instagram_basic,instagram_content_publish"
    url = f"https://www.facebook.com/{v}/dialog/oauth?" + urllib.parse.urlencode(
        {"client_id": app_id, "redirect_uri": redir, "scope": escopos, "response_type": "code"})
    code = _receber_codigo(porta, url)
    g = f"https://graph.facebook.com/{v}"
    curto = requests.get(f"{g}/oauth/access_token", params={"client_id": app_id, "client_secret": secret, "redirect_uri": redir,
                                                             "code": code}, timeout=30).json()["access_token"]
    longo = requests.get(f"{g}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": app_id,
                                                             "client_secret": secret, "fb_exchange_token": curto}, timeout=30).json()["access_token"]
    paginas = requests.get(f"{g}/me/accounts", params={"fields": "id,name,access_token,instagram_business_account",
                                                        "access_token": longo}, timeout=30).json().get("data", [])
    if not paginas:
        raise SystemExit("Nenhuma Página do Facebook encontrada nesta conta.")
    for i, pg in enumerate(paginas):
        print(f"  [{i}] {pg['name']} (id {pg['id']}) — Instagram vinculado: {bool(pg.get('instagram_business_account'))}")
    nome_marca = carregar_pagina(args.pagina).nome.lower()
    certas = [pg for pg in paginas if pg["name"].strip().lower() == nome_marca]
    if certas:
        esc = certas[0]
    elif len(paginas) == 1:
        esc = paginas[0]
    else:
        esc = paginas[int(input("Número da Página desta marca: "))]
    print(f"Página escolhida: {esc['name']}")
    suf = args.pagina.upper().replace("-", "_")
    _gravar_env(f"META_PAGE_TOKEN_{suf}", esc["access_token"])
    _gravar_env(f"FB_PAGE_ID_{suf}", esc["id"])
    if esc.get("instagram_business_account"):
        _gravar_env(f"IG_USER_ID_{suf}", esc["instagram_business_account"]["id"])
    else:
        print("⚠️ Esta Página não tem Instagram profissional vinculado. Vincule no app do Instagram e rode de novo.")


def cmd_telegram_id(args) -> None:
    """Depois de mandar qualquer mensagem para o seu bot, mostra o número do seu chat e grava no .env."""
    tok = env("TELEGRAM_BOT_TOKEN", obrigatorio=True)
    r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=30).json()
    chats = {str(u["message"]["chat"]["id"]): u["message"]["chat"].get("first_name", "") for u in r.get("result", []) if "message" in u}
    if not chats:
        raise SystemExit("Nenhuma mensagem encontrada. Abra o seu bot no Telegram, mande 'oi' e rode de novo.")
    cid = list(chats)[-1]
    print(f"Chat encontrado: {chats[cid]} ({cid})")
    _gravar_env("TELEGRAM_CHAT_ID", cid)


def main() -> None:
    ap = argparse.ArgumentParser(description="Robô de páginas em redes sociais")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gerar")
    g.add_argument("--pagina")
    g.add_argument("--formato", default="short", choices=["short", "longo"])
    g.add_argument("--quantidade", type=int)
    sub.add_parser("ciclo")
    s = sub.add_parser("semanal")
    s.add_argument("--pagina")
    e = sub.add_parser("exemplos")
    e.add_argument("--pagina", default="energia-em-casa")
    e.add_argument("--quantidade", type=int, default=3)
    e.add_argument("--com-longo", action="store_true")
    t = sub.add_parser("testar")
    t.add_argument("--pagina")
    for nome in ("token-youtube", "token-meta"):
        x = sub.add_parser(nome)
        x.add_argument("--pagina", required=True)
    sub.add_parser("telegram-id")
    args = ap.parse_args()
    {"gerar": cmd_gerar, "ciclo": cmd_ciclo, "semanal": cmd_semanal, "exemplos": cmd_exemplos, "testar": cmd_testar,
     "token-youtube": cmd_token_youtube, "token-meta": cmd_token_meta, "telegram-id": cmd_telegram_id}[args.cmd](args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        alertar_erro("falha geral: " + " ".join(sys.argv[1:]), exc)
        sys.exit(1)
