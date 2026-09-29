"""Dados abertos da ANEEL (tarifas homologadas e bandeiras tarifárias).

Todos os números que vão para os posts são CALCULADOS AQUI, a partir do dado
oficial — a IA só redige o texto em cima deste "dossiê". A equipe de verificação
confere se cada número do texto existe no dossiê.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import requests
import yaml

from ..config import PASTA_CACHE

API = "https://dadosabertos.aneel.gov.br/api/3/action/datastore_search"
RES_TARIFAS = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"
RES_BANDEIRA_ACIONAMENTO = "0591b8f6-fe54-437b-b72b-1aa2efd46e42"
RES_BANDEIRA_ADICIONAL = "5879ca80-b3bd-45b1-a135-d9b77c1d5b36"
URL_TARIFAS = "https://dadosabertos.aneel.gov.br/dataset/tarifas-distribuidoras-energia-eletrica"
URL_BANDEIRAS = "https://dadosabertos.aneel.gov.br/dataset/bandeiras-tarifarias"

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


# --------------------------------------------------------------------------- util

def num(txt) -> float:
    return float(str(txt).replace(".", "").replace(",", "."))


def brl(v: float, casas: int = 2) -> str:
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float, casas: int = 1) -> str:
    s = brl(v, casas)
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s + "%"


def kwh_txt(rs_kwh: float) -> str:
    """'R$ 0,903 por kWh (cerca de 90 centavos por kWh)' — forma escrita e forma falada."""
    c = round(rs_kwh * 100)
    falado = f"cerca de {c} centavos" if c < 100 else f"cerca de R$ {brl(rs_kwh)}"
    return f"R$ {brl(rs_kwh, 3)} por kWh ({falado} por kWh)"


def data_br(iso: str) -> str:
    a, m, d = iso[:10].split("-")
    return f"{d}/{m}/{a}"


def mes_extenso(iso: str) -> str:
    a, m, _ = iso[:10].split("-")
    return f"{MESES[int(m) - 1]} de {a}"


def distribuidoras() -> dict:
    return yaml.safe_load((Path(__file__).parent / "distribuidoras.yaml").read_text(encoding="utf-8"))


def _cache(nome: str, horas: float, buscar):
    PASTA_CACHE.mkdir(exist_ok=True)
    arq = PASTA_CACHE / f"aneel_{nome}.json"
    if arq.exists() and time.time() - arq.stat().st_mtime < horas * 3600:
        return json.loads(arq.read_text(encoding="utf-8"))
    dados = buscar()
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return dados


def _buscar(resource_id: str, filtros: dict | None = None, campos: str | None = None, limite: int = 5000) -> list[dict]:
    params = {"resource_id": resource_id, "limit": limite}
    if filtros:
        params["filters"] = json.dumps(filtros, ensure_ascii=False)
    if campos:
        params["fields"] = campos
    for tentativa in range(3):
        try:
            r = requests.get(API, params=params, timeout=120)
            r.raise_for_status()
            return r.json()["result"]["records"]
        except requests.RequestException:
            if tentativa == 2:
                raise
            time.sleep(10)
    return []


# --------------------------------------------------------------------------- tarifas

def tarifas_residenciais() -> dict[str, list[dict]]:
    """{SigAgente: [vigências da mais nova p/ mais antiga]} — B1 residencial convencional, tarifa de aplicação."""
    def buscar():
        filtros = {
            "DscSubGrupo": "B1", "DscClasse": "Residencial", "DscSubClasse": "Residencial",
            "DscModalidadeTarifaria": "Convencional", "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscDetalhe": "Não se aplica",
        }
        regs = _buscar(RES_TARIFAS, filtros, "SigAgente,DscREH,DatInicioVigencia,DatFimVigencia,VlrTUSD,VlrTE")
        por = {}
        for r in regs:
            por.setdefault(r["SigAgente"], []).append({
                "reh": r["DscREH"], "inicio": r["DatInicioVigencia"], "fim": r["DatFimVigencia"],
                "tusd": num(r["VlrTUSD"]), "te": num(r["VlrTE"]),
                "rs_kwh": round((num(r["VlrTUSD"]) + num(r["VlrTE"])) / 1000, 4),
            })
        for v in por.values():
            v.sort(key=lambda x: x["inicio"], reverse=True)
        return por
    return _cache("tarifas_residenciais", 12, buscar)


def tarifa_branca(sig: str) -> dict:
    regs = _buscar(RES_TARIFAS, {"SigAgente": sig, "DscSubGrupo": "B1", "DscClasse": "Residencial",
                                 "DscSubClasse": "Residencial", "DscModalidadeTarifaria": "Branca",
                                 "DscBaseTarifaria": "Tarifa de Aplicação", "DscDetalhe": "Não se aplica"},
                   "DscREH,DatInicioVigencia,NomPostoTarifario,VlrTUSD,VlrTE", 200)
    if not regs:
        return {}
    ult = max(r["DatInicioVigencia"] for r in regs)
    postos = {r["NomPostoTarifario"]: round((num(r["VlrTUSD"]) + num(r["VlrTE"])) / 1000, 4)
              for r in regs if r["DatInicioVigencia"] == ult}
    reh = next(r["DscREH"] for r in regs if r["DatInicioVigencia"] == ult)
    return {"inicio": ult, "reh": reh, "postos": postos}


def _valores_distintos(vig: list[dict]) -> list[dict]:
    """Junta vigências seguidas com o MESMO valor (a ANEEL às vezes divide a vigência
    em 01/01 sem mudar a tarifa). Cada item fica com o início mais antigo do bloco."""
    blocos: list[dict] = []
    for v in vig:  # do mais novo para o mais antigo
        if blocos and abs(blocos[-1]["rs_kwh"] - v["rs_kwh"]) < 1e-6:
            blocos[-1] = {**blocos[-1], "inicio": v["inicio"]}
        else:
            blocos.append(dict(v))
    return blocos


def _vigentes(sig: str) -> list[dict]:
    """Vigências até hoje (descarta as futuras), mais nova primeiro."""
    hoje = date.today().isoformat()
    return [v for v in tarifas_residenciais().get(sig, []) if v["inicio"][:10] <= hoje]


def reajustes_recentes(dias: int = 45) -> list[dict]:
    """Distribuidoras (mapeadas) cuja tarifa MUDOU de valor nos últimos N dias."""
    hoje = date.today()
    mapa = distribuidoras()
    saida = []
    for sig in mapa:
        vig = _vigentes(sig)
        if not vig or vig[0]["fim"][:10] < hoje.isoformat():
            continue
        blocos = _valores_distintos(vig)
        if len(blocos) < 2:
            continue
        nova, ant = blocos[0], blocos[1]
        ini = date.fromisoformat(nova["inicio"][:10])
        if 0 <= (hoje - ini).days <= dias:
            saida.append({"sig": sig, "nova": nova, "anterior": ant,
                          "variacao": (nova["rs_kwh"] / ant["rs_kwh"] - 1) * 100})
    return sorted(saida, key=lambda x: x["nova"]["inicio"], reverse=True)


def tarifa_vigente(sig: str) -> dict | None:
    """Tarifa em vigor hoje; None se o dado estiver desatualizado (vigência vencida)."""
    vig = _vigentes(sig)
    if not vig or vig[0]["fim"][:10] < date.today().isoformat():
        return None
    return _valores_distintos(vig)[0]


def formatar_reh(reh: str) -> str:
    """'RESOLUÇÃO HOMOLOGATÓRIA Nº 3.603, DE 28 DE AGOSTO DE 2026' -> 'Resolução Homologatória nº 3.603, de 28 de agosto de 2026'."""
    s = reh.strip().lower()
    return s.replace("resolução homologatória", "Resolução Homologatória", 1)


# --------------------------------------------------------------------------- bandeiras

def bandeiras() -> dict:
    def buscar():
        acion = _buscar(RES_BANDEIRA_ACIONAMENTO, campos="DatCompetencia,NomBandeiraAcionada,VlrAdicionalBandeira")
        adic = _buscar(RES_BANDEIRA_ADICIONAL, campos="DscResolucao,DatVigencia,NomBandeiraAcionada,VlrAdicionalBandeiraRSMWh")
        acion.sort(key=lambda x: x["DatCompetencia"], reverse=True)
        return {"acionamentos": acion, "adicionais": adic}
    return _cache("bandeiras", 12, buscar)


def adicionais_vigentes() -> dict:
    adic = bandeiras()["adicionais"]
    ult = max(a["DatVigencia"] for a in adic)
    return {a["NomBandeiraAcionada"]: {"rs_mwh": num(a["VlrAdicionalBandeiraRSMWh"]), "resolucao": a["DscResolucao"], "vigencia": ult}
            for a in adic if a["DatVigencia"] == ult}


# --------------------------------------------------------------------------- dossiês

def _fato(fatos: list, texto: str, fonte: str, url: str) -> None:
    fatos.append({"id": f"F{len(fatos) + 1}", "texto": texto, "fonte": fonte, "url": url})


def _nome(sig: str) -> tuple[str, str]:
    d = distribuidoras()[sig]
    return d["nome"], d["uf"]


def dossie_reajuste(item: dict, consumo_kwh: int = 150) -> dict:
    sig, nova, ant = item["sig"], item["nova"], item["anterior"]
    nome, uf = _nome(sig)
    fatos: list = []
    reh = formatar_reh(nova["reh"])
    _fato(fatos, f"Distribuidora: {nome} ({uf}).", "ANEEL", URL_TARIFAS)
    _fato(fatos, f"Nova tarifa homologada pela ANEEL na {reh}, vigente desde {data_br(nova['inicio'])}.", "ANEEL", URL_TARIFAS)
    _fato(fatos, f"Tarifa residencial convencional (TUSD + TE, sem impostos e sem bandeira) ANTES: {kwh_txt(ant['rs_kwh'])} (vigência a partir de {data_br(ant['inicio'])}).", "ANEEL", URL_TARIFAS)
    _fato(fatos, f"Tarifa residencial convencional (TUSD + TE, sem impostos e sem bandeira) AGORA: {kwh_txt(nova['rs_kwh'])}.", "ANEEL", URL_TARIFAS)
    v = item["variacao"]
    _fato(fatos, f"Variação da tarifa residencial: {'alta' if v >= 0 else 'queda'} de {pct(abs(v))}.", "cálculo sobre dados ANEEL", URL_TARIFAS)
    antes, depois = ant["rs_kwh"] * consumo_kwh, nova["rs_kwh"] * consumo_kwh
    _fato(fatos, f"Exemplo: para {consumo_kwh} kWh no mês, a parte da tarifa (sem impostos) passa de R$ {brl(antes)} para R$ {brl(depois)}, diferença de R$ {brl(abs(depois - antes))} por mês.", "cálculo sobre dados ANEEL", URL_TARIFAS)
    return {"tema": f"Nova tarifa da {nome} ({uf})", "categoria": "reajuste_tarifa", "busca_base": "electricity bill", "chave": f"reajuste:{sig}:{nova['inicio'][:10]}",
            "fatos": fatos, "ressalvas": ["tarifa residencial convencional, sem impostos (ICMS, PIS/Cofins) e sem bandeira; a sua pode variar (tarifa social, Tarifa Branca)", "Fonte: ANEEL"],
            "grafico": {"tipo": "barras", "titulo": f"Tarifa residencial {nome} (R$/kWh, sem impostos)",
                        "rotulos": [data_br(ant["inicio"]), data_br(nova["inicio"])],
                        "valores": [ant["rs_kwh"], nova["rs_kwh"]], "formato": "R$ {v:.3f}"}}


def dossie_bandeira() -> dict:
    acion = bandeiras()["acionamentos"]
    atual = acion[0]
    adic = adicionais_vigentes()
    fatos: list = []
    cor = atual["NomBandeiraAcionada"]
    valor_mwh = num(atual["VlrAdicionalBandeira"]) if atual.get("VlrAdicionalBandeira") else 0.0
    _fato(fatos, f"Bandeira tarifária de {mes_extenso(atual['DatCompetencia'])}: {cor}.", "ANEEL", URL_BANDEIRAS)
    if valor_mwh:
        _fato(fatos, f"Com a bandeira {cor}, a conta tem acréscimo de R$ {brl(valor_mwh / 10)} a cada 100 kWh consumidos.", "cálculo sobre dados ANEEL", URL_BANDEIRAS)
        _fato(fatos, f"Exemplo: numa casa que consome 200 kWh no mês, a bandeira {cor} acrescenta R$ {brl(valor_mwh / 1000 * 200)} (antes de impostos).", "cálculo sobre dados ANEEL", URL_BANDEIRAS)
    else:
        _fato(fatos, "Bandeira verde: não há acréscimo na conta por causa da bandeira.", "ANEEL", URL_BANDEIRAS)
    for nome_b, d in adic.items():
        _fato(fatos, f"Valor vigente da bandeira {nome_b}: R$ {brl(d['rs_mwh'] / 10)} a cada 100 kWh ({d['resolucao']}).", "ANEEL", URL_BANDEIRAS)
    ult12 = acion[:12]
    cont: dict = {}
    for a in ult12:
        cont[a["NomBandeiraAcionada"]] = cont.get(a["NomBandeiraAcionada"], 0) + 1
    resumo = ", ".join(f"{k}: {v} {'mês' if v == 1 else 'meses'}" for k, v in cont.items())
    _fato(fatos, f"Nos últimos 12 meses com dado publicado ({mes_extenso(ult12[-1]['DatCompetencia'])} a {mes_extenso(ult12[0]['DatCompetencia'])}): {resumo}.", "ANEEL", URL_BANDEIRAS)
    _fato(fatos, "A bandeira tarifária sinaliza o custo de gerar energia: verde (sem acréscimo), amarela, vermelha patamar 1 e vermelha patamar 2.", "ANEEL", URL_BANDEIRAS)
    return {"tema": f"Bandeira de {mes_extenso(atual['DatCompetencia'])}: {cor}", "categoria": "bandeira", "busca_base": "power lines",
            "chave": f"bandeira:{atual['DatCompetencia'][:7]}", "fatos": fatos,
            "ressalvas": ["acréscimo antes de impostos", "Fonte: ANEEL"],
            "grafico": {"tipo": "barras", "titulo": "Acréscimo a cada 100 kWh (R$)",
                        "rotulos": list(adic.keys()), "valores": [round(d["rs_mwh"] / 10, 2) for d in adic.values()],
                        "formato": "R$ {v:.2f}", "destaque": list(adic.keys()).index(cor) if cor in adic else -1}}


APARELHOS = {
    # potência típica usada como EXEMPLO (o texto deve dizer que é exemplo e que varia por modelo)
    "chuveiro": {"nome": "chuveiro elétrico de 5.500 W", "kw": 5.5, "uso": "15 minutos por dia", "horas_dia": 0.25, "busca": "shower water"},
    "ar": {"nome": "ar-condicionado de 12.000 BTU (cerca de 1.100 W)", "kw": 1.1, "uso": "8 horas por noite", "horas_dia": 8, "busca": "air conditioner"},
    "ferro": {"nome": "ferro de passar de 1.200 W", "kw": 1.2, "uso": "1 hora por semana", "horas_dia": 1 / 7, "busca": "ironing clothes"},
    "airfryer": {"nome": "air fryer de 1.500 W", "kw": 1.5, "uso": "30 minutos por dia", "horas_dia": 0.5, "busca": "air fryer food"},
}


def dossie_calculadora(sig: str, aparelho: str) -> dict:
    nome, uf = _nome(sig)
    tar = tarifa_vigente(sig)
    ap = APARELHOS[aparelho]
    kwh_mes = ap["kw"] * ap["horas_dia"] * 30
    custo = kwh_mes * tar["rs_kwh"]
    fatos: list = []
    _fato(fatos, f"Distribuidora: {nome} ({uf}). Tarifa residencial convencional vigente (sem impostos e sem bandeira): {kwh_txt(tar['rs_kwh'])}, desde {data_br(tar['inicio'])}.", "ANEEL", URL_TARIFAS)
    _fato(fatos, f"Exemplo de uso: {ap['nome']}, {ap['uso']}. A potência real varia por modelo — confira na etiqueta.", "premissa do exemplo", "")
    _fato(fatos, f"Consumo estimado: {brl(kwh_mes, 1)} kWh por mês (potência × horas de uso × 30 dias).", "cálculo", "")
    _fato(fatos, f"Custo estimado só da tarifa: R$ {brl(custo)} por mês, antes de impostos e bandeira.", "cálculo sobre dados ANEEL", URL_TARIFAS)
    _fato(fatos, "Com impostos (ICMS, PIS/Cofins) e bandeira, o valor final na conta fica maior; o ICMS muda de estado para estado.", "conhecimento geral", "")
    return {"tema": f"Quanto custa o {aparelho} na tarifa da {nome}", "categoria": "calculadora", "busca_base": ap.get("busca", "home appliance"),
            "chave": f"calc:{aparelho}:{sig}", "fatos": fatos,
            "ressalvas": ["tarifa residencial convencional, sem impostos (ICMS, PIS/Cofins) e sem bandeira; a sua pode variar (tarifa social, Tarifa Branca)", "potência é exemplo; varia por modelo", "Fonte: ANEEL"],
            "grafico": {"tipo": "numero", "titulo": f"{ap['nome']} · {ap['uso']}", "valor": f"R$ {brl(custo)}/mês",
                        "sub": f"tarifa {nome} sem impostos"}}


def dossie_ranking(n: int = 5) -> dict:
    mapa = distribuidoras()
    lista = []
    for sig in mapa:
        t = tarifa_vigente(sig)
        if t:
            lista.append((sig, t))
    lista.sort(key=lambda x: x[1]["rs_kwh"], reverse=True)
    fatos: list = []
    _fato(fatos, f"Comparação entre {len(lista)} grandes distribuidoras, tarifa residencial convencional vigente (TUSD + TE, sem impostos e sem bandeira).", "cálculo sobre dados ANEEL", URL_TARIFAS)
    for i, (sig, t) in enumerate(lista[:n], 1):
        nome, uf = _nome(sig)
        _fato(fatos, f"Mais cara nº {i}: {nome} ({uf}) — {kwh_txt(t['rs_kwh'])}.", "ANEEL", URL_TARIFAS)
    for i, (sig, t) in enumerate(reversed(lista[-n:]), 1):
        nome, uf = _nome(sig)
        _fato(fatos, f"Mais barata nº {i}: {nome} ({uf}) — {kwh_txt(t['rs_kwh'])}.", "ANEEL", URL_TARIFAS)
    cara, barata = lista[0][1]["rs_kwh"], lista[-1][1]["rs_kwh"]
    _fato(fatos, f"A tarifa mais cara da lista é {pct((cara / barata - 1) * 100, 0)} maior que a mais barata.", "cálculo sobre dados ANEEL", URL_TARIFAS)
    sel = lista[:n] + lista[-n:]
    return {"tema": "Ranking das tarifas residenciais mais caras e mais baratas", "categoria": "ranking", "busca_base": "electricity meter",
            "chave": f"ranking:{date.today().isoformat()[:7]}", "fatos": fatos,
            "ressalvas": ["tarifa residencial convencional, sem impostos (ICMS, PIS/Cofins) e sem bandeira; a sua pode variar (tarifa social, Tarifa Branca)", "Fonte: ANEEL"],
            "grafico": {"tipo": "barras_h", "titulo": "Tarifa residencial (R$/kWh, sem impostos)",
                        "rotulos": [f"{_nome(s)[0]} ({_nome(s)[1]})" for s, _ in sel],
                        "valores": [t["rs_kwh"] for _, t in sel], "formato": "{v:.3f}"}}


def dossie_taxa_minima(sig: str) -> dict:
    nome, uf = _nome(sig)
    tar = tarifa_vigente(sig)
    fatos: list = []
    _fato(fatos, "Custo de disponibilidade (a 'taxa mínima'): mesmo consumindo pouco, a conta cobra no mínimo 30 kWh (monofásico), 50 kWh (bifásico) ou 100 kWh (trifásico).", "ANEEL — REN 1.000/2021", "https://www2.aneel.gov.br/cedoc/ren20211000.html")
    _fato(fatos, "É um PISO, não uma taxa extra: se o consumo do mês passar do mínimo, paga-se só o consumo; o mínimo não é somado a ele.", "ANEEL — REN 1.000/2021", "https://www2.aneel.gov.br/cedoc/ren20211000.html")
    _fato(fatos, "É uma regra nacional da ANEEL: vale para todas as distribuidoras; o que muda de uma para outra é o valor da tarifa.", "ANEEL — REN 1.000/2021", "https://www2.aneel.gov.br/cedoc/ren20211000.html")
    for fase, kwh in (("monofásico", 30), ("bifásico", 50), ("trifásico", 100)):
        _fato(fatos, f"Na {nome} ({uf}), o mínimo {fase} ({kwh} kWh) equivale a R$ {brl(kwh * tar['rs_kwh'])} por mês só de tarifa, antes de impostos.", "cálculo sobre dados ANEEL", URL_TARIFAS)
    return {"tema": f"A taxa mínima da conta de luz na {nome}", "categoria": "entenda_conta", "busca_base": "electricity meter", "chave": f"taxamin:{sig}",
            "fatos": fatos, "ressalvas": ["tarifa residencial convencional, sem impostos (ICMS, PIS/Cofins) e sem bandeira; a sua pode variar (tarifa social, Tarifa Branca)", "Fonte: ANEEL"],
            "grafico": {"tipo": "barras", "titulo": f"Mínimo por mês na {nome} (R$, sem impostos)",
                        "rotulos": ["Monofásico", "Bifásico", "Trifásico"],
                        "valores": [round(k * tar["rs_kwh"], 2) for k in (30, 50, 100)], "formato": "R$ {v:.2f}"}}
