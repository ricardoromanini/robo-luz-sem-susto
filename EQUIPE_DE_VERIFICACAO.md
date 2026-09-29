# Equipe de verificação — como o robô evita erro, fake news e problema legal

Nenhum post é publicado sem passar por **duas camadas** de verificação.

```
            ┌────────────── CAMADA 1 — automática, ANTES de cada post (roda na nuvem) ──────────────┐
 dossiê de  │                                                                                        │
 fatos  ──► │  ✍️ Roteirista (IA "A": Gemini)                                                         │
 oficiais   │        │                                                                               │
            │        ▼                                                                               │
            │  🔎 Checador de fatos ......... código: TODO número do texto precisa existir no dossiê │
            │                                  + ressalvas obrigatórias presentes                    │
            │                                  IA "B" (outra família: gpt-oss / Llama): afirmação por│
            │                                  afirmação → suportada / sem fonte / distorcida / falsa│
            │  ⚖️ Revisor jurídico/políticas  código: termos proibidos (política/eleição, isca de   │
            │                                  engajamento, promessa, instrução perigosa, acusação)  │
            │                                  IA "B": checklist CDC, honra, eleitoral, NR-10,       │
            │                                  direitos autorais, CONAR, LGPD, regras YouTube/Meta/  │
            │                                  TikTok, rotulagem de IA                               │
            │  ✍️ Revisor de qualidade ...... código: tamanho, originalidade (x posts anteriores)   │
            │                                  IA "B": gancho, clareza, utilidade, português         │
            │        │                                                                               │
            │        ▼                                                                               │
            │  👔 Editor-chefe  →  APROVADO  /  AJUSTAR (reescreve, até 2x)  /  BLOQUEADO (veto)      │
            │                    3 pautas barradas seguidas = nada é publicado e você é avisado      │
            │        │                                                                               │
            │  🎬 QC técnico: duração, resolução, volume (-14 LUFS), a voz disse o roteiro?           │
            └────────┼───────────────────────────────────────────────────────────────────────────────┘
                     ▼
            📱 Telegram: prévia + parecer de cada membro → você aprova (ou piloto automático)
                     ▼
            ┌────────────── CAMADA 2 — agentes do Claude Code, DEPOIS (auditoria periódica) ─────────┐
            │  rs-auditor-conteudo  (semanal)  revisa os posts contra a fonte oficial na internet,   │
            │                                  corrige a base de fatos e cria regras novas           │
            │  rs-vigia-politicas   (mensal)   pesquisa mudanças nas regras das redes e nas leis     │
            │  rs-curador-pautas    (sob demanda) amplia a base de fatos, sempre com fonte primária  │
            │  rs-estrategista      (semanal)  melhora a execução com base nas métricas              │
            └────────────────────────────────────────────────────────────────────────────────────────┘
```

## Por que é difícil sair fake news
1. **A IA não inventa números.** Todo número vem do código, calculado sobre o dado oficial (ANEEL) ou de
   um fato curado com fonte em `paginas/<pagina>/pautas.yaml`. Se o texto tiver um número que não está no
   dossiê, o código barra, sem depender de IA.
2. **Quem escreve não é quem confere.** O roteiro é escrito por uma IA e verificado por outra, de outra família.
3. **Ressalvas entram pelo código.** "Sem impostos", "Fonte: ANEEL" e "procure eletricista habilitado"
   aparecem no rodapé de todas as cenas e na legenda, mesmo que a IA esqueça.
4. **Na dúvida, não publica.** Se um verificador cair (sem internet, cota estourada), o post **não** é aprovado.
5. **Você vê o parecer** de cada membro no Telegram antes de aprovar.

## Como acionar a camada 2
Abra o Claude Code na pasta `C:\projetos\redes-sociais` e peça, por exemplo:
- "use o rs-auditor-conteudo para auditar a última semana"
- "use o rs-vigia-politicas para checar mudanças nas regras deste mês"
- "use o rs-curador-pautas para criar 10 pautas novas de segurança elétrica"
- "use o rs-estrategista com o relatório desta semana"

## Onde ajustar as regras
| O quê | Arquivo |
|---|---|
| Checklists dos revisores (texto) | `motor/equipe/regras/*.md` |
| Regras fixas (termos proibidos, ressalvas, tamanho, originalidade) | `motor/equipe/regras_fixas.py` |
| Critério do editor-chefe | `motor/equipe/__init__.py` → `editor_chefe` |
| Base de fatos das pautas | `paginas/<pagina>/pautas.yaml` |
