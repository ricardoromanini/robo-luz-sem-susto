"""Verificações DETERMINÍSTICAS (sem IA) — rápidas, gratuitas e que não "alucinam".

Rodam antes dos revisores de IA:
  - todo número do texto precisa existir no dossiê;
  - ressalvas obrigatórias presentes;
  - termos proibidos (política/eleição, isca de engajamento, promessas, instruções perigosas);
  - originalidade (semelhança com posts anteriores).
"""
from __future__ import annotations

import re
import unicodedata

_RE_NUM = re.compile(r"(?<![\w/])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?![\w])")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def numeros(texto: str) -> list[tuple[str, float]]:
    out = []
    for m in _RE_NUM.finditer(texto):
        bruto = m.group(1)
        try:
            out.append((bruto, float(bruto.replace(".", "").replace(",", "."))))
        except ValueError:
            pass
    return out


def _bate(v: float, permitidos: set[float]) -> bool:
    for p in permitidos:
        if abs(v - p) <= max(0.011, abs(p) * 0.01):
            return True
        if v == round(p) or v == round(p, 1) or v == round(p, 2):
            return True
        if abs(v - p * 100) <= 0.6 and p < 10:  # 0,903 R$/kWh -> "90 centavos"
            return True
    return False


def checar_numeros(texto_publico: str, pauta: dict) -> list[dict]:
    base = " ".join([pauta["tema"]] + [f"{f['texto']} {f.get('fonte', '')}" for f in pauta["fatos"]]
                    + list(pauta.get("ressalvas") or []))
    permitidos = {v for _, v in numeros(base.replace("/", " "))}  # "14.300/2022" -> 14.300 e 2022
    permitidos |= {float(i) for i in range(0, 11)}  # contagens simples ("3 dicas", "2 segundos")
    permitidos |= {p / 1000 for p in permitidos} | {p * 1000 for p in permitidos}  # 5.500 W = 5,5 kW
    problemas = []
    for bruto, v in numeros(texto_publico):
        if not _bate(v, permitidos):
            problemas.append({"trecho": bruto, "motivo": f"o número {bruto} não está no dossiê",
                              "correcao": "remova ou troque por um número que esteja no dossiê"})
    # dedup
    vistos, unicos = set(), []
    for p in problemas:
        if p["trecho"] not in vistos:
            vistos.add(p["trecho"])
            unicos.append(p)
    return unicos


_RESSALVA_CHAVES = [("imposto", ["imposto"]), ("aneel", ["aneel"]), ("eletricista", ["eletricista", "profissional habilitado"]),
                    ("exemplo", ["exemplo", "varia"]), ("bandeira", ["bandeira"])]


def checar_ressalvas(texto_publico: str, pauta: dict) -> list[dict]:
    t = _sem_acento(texto_publico)
    problemas = []
    for r in pauta.get("ressalvas") or []:
        rs = _sem_acento(r)
        for chave, exigidas in _RESSALVA_CHAVES:
            if chave in rs and not any(_sem_acento(e) in t for e in exigidas):
                problemas.append({"trecho": "(ausente)", "motivo": f"falta a ressalva obrigatória: “{r}”",
                                  "correcao": f"inclua na fala ou na tela: {r}"})
                break
    return problemas


_PROIBIDOS = [
    (r"\b(lula|bolsonaro|tarcisio|haddad|candidat\w*|eleic\w*|eleitor\w*|partido\w*|votar|voto\b|governador\w*|prefeit\w*|deputad\w*|senador\w*|ministr[oa]\w*|presidente da republica)\b",
     "política/eleição (proibido — conteúdo deve ser técnico e neutro)"),
    (r"\b(comente|comenta|digite|escreva)\s+[\"“']?(sim|eu quero|quero|eu|aqui|\w+)[\"”']?\s+(se|para|pra|nos)\b", "isca de engajamento (Meta pune)"),
    (r"\bmarque\s+(\d+|um|uma|dois|tres|seus|suas|aquele|aquela)\b", "isca de engajamento (marque amigos)"),
    (r"\b(curta|compartilhe)\s+se\b", "isca de engajamento (curta/compartilhe se)"),
    (r"\b(zer\w+ (a|sua) conta|conta zerada|economia garantida|garantimos|garantido que)\b", "promessa de resultado (CDC art. 37)"),
    (r"\b(sem desligar o disjuntor|com a energia ligada|energizad[oa] mesmo|voce mesmo pode trocar|faca voce mesmo a instalacao)\b",
     "instrução perigosa (NR-10)"),
    (r"\b(gato de energia|burlar o medidor|desviar energia)\b", "menção a furto de energia"),
    (r"\b(roub\w+|ladr\w+|golpe\w*|fraud\w+|mafia)\b", "acusação/termo ofensivo (risco de difamação)"),
]


def checar_proibidos(texto_publico: str) -> list[dict]:
    t = _sem_acento(texto_publico)
    problemas = []
    for padrao, motivo in _PROIBIDOS:
        m = re.search(padrao, t)
        if m:
            problemas.append({"trecho": m.group(0), "motivo": motivo, "correcao": "remova ou reescreva este trecho"})
    return problemas


def _ngramas(texto: str, n: int = 3) -> set[tuple]:
    pal = re.findall(r"\w+", _sem_acento(texto))
    return {tuple(pal[i : i + n]) for i in range(len(pal) - n + 1)}


def similaridade(a: str, b: str) -> float:
    ga, gb = _ngramas(a), _ngramas(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def checar_originalidade(texto_falado: str, titulo: str, historico: list[dict], limite: float = 0.30) -> list[dict]:
    problemas = []
    for h in historico[-40:]:
        s = similaridade(texto_falado, h.get("texto_falado", ""))
        st = similaridade(titulo, h.get("titulo", ""))
        if s >= limite or st >= 0.6:
            problemas.append({"trecho": h.get("titulo", ""), "motivo": f"muito parecido com um post anterior (semelhança {s:.0%})",
                              "correcao": "mude a estrutura, o gancho e o ângulo; traga outro aspecto do dossiê"})
    return problemas[:2]


def checar_tamanho(texto_falado: str, formato: str = "short") -> list[dict]:
    n = len(re.findall(r"\w+", texto_falado))
    minimo, maximo = (650, 1200) if formato == "longo" else (55, 150)
    if n < minimo:
        return [{"trecho": f"{n} palavras", "motivo": f"texto curto demais para o formato ({n} palavras; mínimo {minimo})",
                 "correcao": "desenvolva mais: explique o dado, dê contexto e uma dica prática usando o dossiê"}]
    if n > maximo:
        return [{"trecho": f"{n} palavras", "motivo": f"texto longo demais para o formato ({n} palavras; máximo {maximo})",
                 "correcao": "corte frases redundantes"}]
    return []
