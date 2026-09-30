"""Módulo de ROTEIRO: transforma o dossiê de fatos em roteiro de vídeo + legenda.

A IA redatora só pode usar os fatos do dossiê. Quem confere é a equipe de
verificação (motor/equipe), com outro modelo de IA.
"""
from __future__ import annotations

import json
from datetime import date

from . import llm
from .config import Pagina

FORMATO_SHORT = {
    "nome": "short",
    "cenas": "6 a 8 cenas; CADA fala com 12 a 20 palavras (nem mais, nem menos)",
    "palavras": "100 a 130 palavras faladas no total (cerca de 40 segundos) — conte as palavras; menos de 90 será devolvido",
}
FORMATO_LONGO = {
    "nome": "longo",
    "cenas": "20 a 35 cenas, organizadas em abertura, 3 a 5 blocos e fechamento",
    "palavras": "700 a 1.000 palavras faladas no total (cerca de 6 minutos)",
}

SISTEMA = """Você é o roteirista-chefe da página "{nome}" ({arroba}).
Nicho: {nicho}
Tom de voz: {tom}

REGRAS INEGOCIÁVEIS
1. Use SOMENTE os fatos do DOSSIÊ. Não acrescente números, datas, leis, nomes ou estatísticas que não estejam lá.
2. Todo número dito ou mostrado deve aparecer no dossiê exatamente com o mesmo valor (pode arredondar só se o dossiê já trouxer a forma arredondada).
3. As RESSALVAS obrigatórias devem aparecer (na fala ou no texto da tela).
4. Proibido: falar de política, eleições, candidatos, partidos ou governo; acusar empresa ou pessoa de crime ou má-fé;
   prometer economia garantida; ensinar a mexer em instalação energizada; alarmismo; palavrões.
5. Proibido "isca de engajamento" (ex.: "comente SIM", "marque 3 amigos", "curta se..."). O CTA deve ser natural,
   como uma pergunta real ("Qual é a sua distribuidora?") ou "Siga para entender sua conta todo mês".
6. Gancho fortíssimo nos 2 primeiros segundos: começa com o dado mais surpreendente ou uma pergunta direta. Nada de "Olá, pessoal".
   O gancho tem de ser VERDADEIRO e ser respondido pelo vídeo: não invente um problema que o dossiê não explica
   (ex.: não pergunte "por que a conta sobe com geladeira nova?" se o dossiê não diz que sobe).
7. Português do Brasil, frases curtas (até 15 palavras), fala natural para narração.
8. Na fala, escreva valores em reais do jeito que se lê em voz alta (ex.: "R$ 5,11" está ok; evite 3 casas decimais na fala — use a forma "cerca de X centavos" quando o dossiê trouxer).
9. Cite pelo menos uma vez a fonte que aparece no DOSSIÊ (campo "fonte"). Nunca cite uma fonte que não esteja lá (ex.: não diga "ANEEL" se o dossiê só cita o Inmetro).
10. Todo cálculo (consumo, custo) é ESTIMATIVA: diga "estimativa", "cerca de" ou "em média" e mencione a premissa (ex.: "usando 1 hora por semana").
12. Use o nome da distribuidora exatamente como no dossiê (ex.: "EDP Espírito Santo", nunca siglas como "EDP ES").
13. Escreva para ser FALADO com energia, como um apresentador confiante: gancho em forma de PERGUNTA ou afirmação surpreendente,
    frases curtas e variadas (algumas bem curtas, de impacto), reticências (…) logo antes do número principal para criar
    expectativa, e uma frase final firme. Nada de tom de leitura escolar.
11. Título sem clickbait: nada de "Veja como!", "Descubra!", "Você não vai acreditar". Descreva o que o vídeo mostra.
14. ESTRUTURA do vídeo curto, nesta ordem (uma ou duas cenas para cada parte):
    (a) GANCHO: pergunta ou dor direta do bolso ou da segurança de quem assiste;
    (b) DADO OFICIAL: o fato ou número principal do dossiê, dizendo de onde vem (fonte do dossiê);
    (c) EXPLICAÇÃO: como se chega nisso, em linguagem de casa (quando houver cálculo: potência, tempo de uso, kWh e o valor em reais);
    (d) DICA PRÁTICA E SEGURA: o que a pessoa pode fazer ou conferir sem risco. Só fale em eletricista quando o assunto
        envolver instalação, conserto ou fiação (aí, sempre eletricista habilitado); em tema de compra ou de hábito, não force.
    Depois vem a cena final de chamada para seguir a página, com a frase exata que for indicada.

DATA DE HOJE: {hoje}. Datas do dossiê são fatos já ocorridos ou vigentes.

Responda SOMENTE com JSON válido."""

USUARIO = """FORMATO: {fmt_nome} — {fmt_cenas}; {fmt_palavras}.

TEMA: {tema}
CATEGORIA: {categoria}

DOSSIÊ (os únicos fatos permitidos):
{fatos}

RESSALVAS OBRIGATÓRIAS: {ressalvas}
{historico}{observacoes}
Devolva JSON com esta estrutura:
{{
  "titulo": "título para YouTube, até 80 caracteres, sem caixa alta exagerada, sem clickbait enganoso",
  "cenas": [
    {{"fala": "o que a voz narra nesta cena",
      "tela": "texto curto em destaque na tela (até 7 palavras) — pode repetir o número principal",
      "visual": "numero | grafico | foto | texto",
      "ilustracao": "descrição EM INGLÊS de uma ilustração para esta cena (1 frase): o objeto/ação concreta, em ambiente de casa brasileira, sem texto, sem números, sem dinheiro, sem nomes de empresas ou marcas, e SEM papéis/contas/telas/visores/celulares — que sempre saem com letras (ex.: 'a steam iron pressing a shirt on an ironing board in a cozy Brazilian living room')",
      "busca_imagem": "2 a 4 palavras em INGLÊS descrevendo o OBJETO ou AÇÃO concreta de que a cena fala, para buscar vídeo/foto (ex.: 'ironing clothes', 'electric shower', 'electrical panel', 'power outlet plug', 'electricity bill paper', 'solar panels roof'). Nada abstrato ('economy', 'money saving')."}}
  ],
  "legenda": "texto do post para Instagram/Facebook/descrição do YouTube (3 a 6 linhas, com a fonte no final)",
  "hashtags": ["#...", "#..."],
  "fatos_usados": ["F1", "F3"]
}}
Use "visual": "grafico" em no máximo 1 cena (só se houver gráfico disponível: {tem_grafico}).
A primeira cena é o GANCHO e a última é o CTA.
A fala da ÚLTIMA cena deve ser EXATAMENTE esta frase: "{cta}"."""


def _texto_fatos(pauta: dict) -> str:
    return "\n".join(f"[{f['id']}] {f['texto']} (fonte: {f['fonte']})" for f in pauta["fatos"])


def escolher_cta(pagina: Pagina, indice: int) -> str:
    opcoes = pagina.cfg.get("cta_opcoes") or ["Siga a página para mais dados oficiais."]
    return opcoes[indice % len(opcoes)]


def escrever(pagina: Pagina, pauta: dict, formato: str = "short", observacoes: str = "",
             titulos_recentes: list[str] | None = None, cta: str = "") -> dict:
    fmt = FORMATO_LONGO if formato == "longo" else FORMATO_SHORT
    cfg = pagina.cfg
    sistema = SISTEMA.format(nome=cfg["nome"], arroba=cfg.get("arroba", ""), nicho=cfg["nicho"].strip(),
                             tom=cfg["tom_de_voz"].strip(), hoje=date.today().strftime("%d/%m/%Y"))
    hist = ""
    if titulos_recentes:
        hist = "\nTÍTULOS RECENTES DA PÁGINA (não repita estrutura, gancho nem frases deles):\n- " + "\n- ".join(titulos_recentes[-15:]) + "\n"
    obs = f"\nCORREÇÕES PEDIDAS PELA EQUIPE DE VERIFICAÇÃO (obrigatório atender):\n{observacoes}\n" if observacoes else ""
    usuario = USUARIO.format(
        fmt_nome=fmt["nome"], fmt_cenas=fmt["cenas"], fmt_palavras=fmt["palavras"], tema=pauta["tema"],
        categoria=pauta["categoria"], fatos=_texto_fatos(pauta), ressalvas="; ".join(pauta.get("ressalvas") or ["nenhuma"]),
        historico=hist, observacoes=obs, tem_grafico="sim" if pauta.get("grafico") else "não",
        cta=cta or escolher_cta(pagina, len(titulos_recentes or [])),
    )
    rot = normalizar(llm.perguntar("redator", sistema, usuario), pagina)
    return aplicar_ressalvas(rot, pauta)


def aplicar_ressalvas(rot: dict, pauta: dict) -> dict:
    """As ressalvas obrigatórias entram SEMPRE pelo código (rodapé do vídeo + legenda),
    sem depender de a IA lembrar."""
    ress = [r for r in (pauta.get("ressalvas") or []) if r]
    if not ress:
        rot["rodape"] = ""
        return rot
    texto = "; ".join(r[0].upper() + r[1:] for r in ress if not r.lower().startswith("fonte"))
    fonte = next((r for r in ress if r.lower().startswith("fonte")), "")
    rot["rodape"] = " · ".join(x for x in [texto, fonte] if x)
    linha = "⚠️ " + " ".join(x.rstrip(".") + "." for x in [texto, fonte] if x)
    if linha not in rot["legenda"]:
        rot["legenda"] = (rot["legenda"].rstrip() + "\n\n" + linha).strip()
    return rot


def normalizar(rot: dict, pagina: Pagina) -> dict:
    """Garante a estrutura mínima, independentemente do modelo que respondeu."""
    if isinstance(rot, list):
        rot = rot[0] if rot else {}
    cenas = []
    for c in rot.get("cenas", []):
        if not isinstance(c, dict) or not str(c.get("fala", "")).strip():
            continue
        vis = str(c.get("visual", "texto")).strip().lower()
        cenas.append({
            "fala": str(c["fala"]).strip(),
            "tela": str(c.get("tela", "")).strip(),
            "visual": vis if vis in ("numero", "grafico", "foto", "texto") else "texto",
            "busca_imagem": str(c.get("busca_imagem", "")).strip(),
            "ilustracao": str(c.get("ilustracao", "")).strip(),
        })
    tags = [t if str(t).startswith("#") else f"#{t}" for t in rot.get("hashtags", []) if str(t).strip()]
    for t in pagina.cfg.get("hashtags_base", []):
        if t not in tags:
            tags.append(t)
    return {
        "titulo": str(rot.get("titulo", "")).strip()[:95],
        "cenas": cenas,
        "legenda": str(rot.get("legenda", "")).strip(),
        "hashtags": [t.replace(" ", "") for t in tags][:10],
        "fatos_usados": rot.get("fatos_usados", []),
    }


def texto_falado(rot: dict) -> str:
    return " ".join(c["fala"] for c in rot["cenas"])


def texto_completo(rot: dict) -> str:
    """Tudo o que o público vai ler/ouvir (usado na verificação)."""
    partes = [rot["titulo"]] + [f"{c['fala']} [TELA: {c['tela']}]" for c in rot["cenas"]] + [rot["legenda"]]
    if rot.get("rodape"):
        partes.append(f"[RODAPÉ FIXO EM TODAS AS CENAS: {rot['rodape']}]")
    return "\n".join(partes)


def para_json(rot: dict) -> str:
    return json.dumps(rot, ensure_ascii=False, indent=2)
