"""EQUIPE DE VERIFICAÇÃO — roda antes de QUALQUER publicação.

Membros:
  1. Checador de fatos ........ regras fixas (números/ressalvas) + IA verificadora (afirmação por afirmação)
  2. Revisor jurídico/políticas  regras fixas (termos proibidos) + IA verificadora (checklist de leis e das redes)
  3. Revisor de qualidade ..... regras fixas (originalidade) + IA verificadora (gancho, clareza, utilidade)
  4. Editor-chefe ............. consolida: APROVADO / AJUSTAR (reescreve, até 2 vezes) / BLOQUEADO (veto)

A IA verificadora é de outra família de modelos que a redatora (config/global.yaml),
para um modelo não "confirmar" o erro do outro. Os checklists ficam em motor/equipe/regras/*.md
e podem ser melhorados sem mexer no código.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .. import llm
from ..registro import obter
from . import regras_fixas as rf

log = obter("equipe")
_REGRAS = Path(__file__).parent / "regras"

MEMBROS = {
    "fatos": "🔎 Checador de fatos",
    "juridico": "⚖️ Revisor jurídico e de políticas",
    "qualidade": "✍️ Revisor de qualidade",
}


def _regra(nome: str) -> str:
    return (_REGRAS / f"{nome}.md").read_text(encoding="utf-8")


def _ia(membro: str, arquivo_regra: str, conteudo: str) -> dict:
    hoje = date.today().strftime("%d/%m/%Y")
    try:
        r = llm.perguntar("verificador", _regra(arquivo_regra) + f"\n\nDATA DE HOJE: {hoje}.", conteudo,
                          evitar=llm.ULTIMO_USO.get("redator"))  # quem escreveu não confere
        if not isinstance(r, dict):
            raise ValueError("resposta não é objeto JSON")
        r["veredito"] = str(r.get("veredito", "AJUSTAR")).upper().strip()
        if r["veredito"] not in ("APROVAR", "AJUSTAR", "BLOQUEAR"):
            r["veredito"] = "AJUSTAR"
        r["problemas"] = [p for p in r.get("problemas", []) if isinstance(p, dict)]
        return r
    except Exception as e:  # noqa: BLE001
        # Sem verificador disponível = NÃO aprova (segurança em primeiro lugar)
        log.error("%s indisponível: %s", membro, e)
        return {"veredito": "AJUSTAR", "problemas": [{"trecho": "-", "motivo": f"verificador indisponível ({e})",
                                                     "correcao": "tentar de novo mais tarde"}], "indisponivel": True}


def avaliar(pauta: dict, rot: dict, historico: list[dict], texto_publico: str, texto_falado: str,
            formato: str = "short", ultima_rodada: bool = False) -> dict:
    dossie = "\n".join(f"[{f['id']}] {f['texto']} (fonte: {f['fonte']})" for f in pauta["fatos"])
    ress = "; ".join(pauta.get("ressalvas") or []) or "nenhuma"
    titulos = "\n".join(f"- {h.get('titulo', '')}" for h in historico[-15:]) or "(nenhum ainda)"

    # ---------- 1. Checador de fatos
    fixos_fatos = rf.checar_numeros(texto_publico, pauta) + rf.checar_ressalvas(texto_publico, pauta)
    ia_fatos = _ia("fatos", "checador_fatos",
                   f"DOSSIÊ:\n{dossie}\n\nRESSALVAS OBRIGATÓRIAS: {ress}\n\nTEXTO DO POST:\n{texto_publico}")
    # ---------- 2. Jurídico / políticas
    fixos_jur = rf.checar_proibidos(texto_publico)
    ia_jur = _ia("juridico", "revisor_juridico", f"TEXTO DO POST:\n{texto_publico}")
    # ---------- 3. Qualidade / originalidade
    fixos_qual = rf.checar_originalidade(texto_falado, rot["titulo"], historico) + rf.checar_tamanho(texto_falado, formato)
    ia_qual = _ia("qualidade", "revisor_qualidade",
                  f"FORMATO: {'vídeo longo horizontal (~6 min)' if formato == 'longo' else 'vídeo curto vertical (~40 s)'}\n\nTÍTULOS RECENTES DA PÁGINA:\n{titulos}\n\nTEXTO DO POST:\n{texto_publico}")
    if ia_qual.get("veredito") == "BLOQUEAR":
        ia_qual["veredito"] = "AJUSTAR"

    membros = {
        "fatos": {"ia": ia_fatos, "fixos": fixos_fatos},
        "juridico": {"ia": ia_jur, "fixos": fixos_jur},
        "qualidade": {"ia": ia_qual, "fixos": fixos_qual},
    }
    return editor_chefe(membros, ultima_rodada)


def _nota(ia: dict) -> float:
    try:
        return float(ia.get("nota"))
    except (TypeError, ValueError):
        return 0.0


def _relevantes(chave: str, ia: dict) -> list[dict]:
    """Apontamentos da IA que obrigam reescrita (os demais viram só observação)."""
    probs = ia.get("problemas", [])
    if chave == "fatos":  # anti fake news: tudo o que não tem fonte, distorce ou é falso
        return [p for p in probs if str(p.get("classificacao", "sem_fonte")).lower() in ("sem_fonte", "distorcida", "falsa")]
    if chave == "juridico":
        return [p for p in probs if str(p.get("gravidade", "media")).lower() in ("alta", "media", "média")]
    return probs


def editor_chefe(membros: dict, ultima_rodada: bool = False) -> dict:
    """Consolida os pareceres.

    - Fatos e jurídico: qualquer problema relevante (sem fonte / distorcido / falso; gravidade média ou alta) → AJUSTAR;
      BLOQUEAR deles é veto definitivo.
    - Qualidade: só obriga reescrita com nota < 7 ou regra fixa (tamanho/originalidade); na última rodada,
      nota ≥ 6 é aceita (gosto não barra publicação; fato e lei barram).
    - Verificador indisponível = nunca aprova.
    """
    decisao = "APROVADO"
    correcoes: list[str] = []
    observacoes: list[str] = []
    linhas: list[str] = []
    for chave, m in membros.items():
        ia, fixos = m["ia"], m["fixos"]
        relevantes = _relevantes(chave, ia)
        v = ia.get("veredito", "AJUSTAR")
        if chave == "qualidade":
            if fixos or _nota(ia) < 7:
                v = "AJUSTAR"
            else:
                v = "APROVAR"
            if ultima_rodada and not fixos and _nota(ia) >= 6:
                v = "APROVAR"
        elif v != "BLOQUEAR":
            v = "AJUSTAR" if (fixos or relevantes or ia.get("indisponivel")) else "APROVAR"
        m["veredito_final"] = v
        if v == "BLOQUEAR" and chave in ("fatos", "juridico"):
            decisao = "BLOQUEADO"
        elif v == "AJUSTAR" and decisao != "BLOQUEADO":
            decisao = "AJUSTAR"
        obrigatorios = fixos + (relevantes if chave != "qualidade" else (ia.get("problemas", []) if v == "AJUSTAR" else []))
        for p in obrigatorios:
            motivo = p.get("motivo") or p.get("regra") or p.get("classificacao") or ""
            correcoes.append(f"- [{MEMBROS[chave]}] “{p.get('trecho', '')}”: {motivo}. Correção: {p.get('correcao', '')}")
        for p in ia.get("problemas", []):
            if p not in obrigatorios:
                observacoes.append(f"- [{MEMBROS[chave]}] {p.get('motivo') or p.get('regra') or ''}")
        icone = {"APROVAR": "✅", "AJUSTAR": "✏️", "BLOQUEAR": "⛔"}[v]
        linhas.append(f"{icone} {MEMBROS[chave]}: {v} (nota {ia.get('nota', '-')}, {len(obrigatorios)} obrigatório(s), "
                      f"{len(ia.get('problemas', [])) + len(fixos) - len(obrigatorios)} observação(ões))")
    return {
        "decisao": decisao,
        "resumo": "\n".join(linhas) + f"\n👔 Editor-chefe: {decisao}",
        "correcoes": "\n".join(correcoes),
        "observacoes": "\n".join(observacoes),
        "rotulo_ia": bool(membros["juridico"]["ia"].get("precisa_rotulo_ia", True)),
        "alertas_dossie": membros["fatos"]["ia"].get("alertas_dossie", []) or [],
        "sugestao_gancho": membros["qualidade"]["ia"].get("sugestao_gancho", ""),
        "membros": membros,
    }
