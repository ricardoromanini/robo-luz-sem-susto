# Robô de páginas em redes sociais

Um robô que **cria, verifica e publica** vídeos curtos (e um vídeo longo por semana) em páginas "sem rosto",
usando **dados oficiais** e **só as APIs oficiais** das redes. Ele roda **na nuvem, de graça** (GitHub Actions),
sem o seu computador ligado.

Página 1: **Luz Sem Susto**, sobre conta de luz, energia solar e segurança elétrica, com dados da ANEEL.

---

## Como funciona (resumo)

```
23:00  ideia (dado oficial ANEEL ou pauta com fonte) ─► roteiro (IA) ─► EQUIPE DE VERIFICAÇÃO (4 membros)
       ─► voz (Google) ─► imagens + gráfico ─► legendas ─► vídeo 9:16 ─► QC técnico ─► prévia no seu Telegram
       [✅ Aprovar] [🔁 Refazer] [🗑 Descartar]
horário escolhido  ─► publica no YouTube, Instagram e Facebook (APIs oficiais, com rótulo de IA)
                   ─► te manda os links + o vídeo pronto para o TikTok (manual)
segunda 08:00      ─► métricas ─► ajusta temas e horários sozinho ─► relatório semanal (arquivo + Telegram)
```

Detalhes da verificação: [EQUIPE_DE_VERIFICACAO.md](EQUIPE_DE_VERIFICACAO.md)

## O seu dia a dia
- **Toda noite (~23h)** chegam no Telegram as prévias dos vídeos do dia seguinte, com o parecer da equipe. Toque em **Aprovar**. Leva uns 10 segundos.
- Se não gostar, toque em **Refazer** e, se quiser, escreva o que mudar ("gancho mais forte", "outra distribuidora").
- **Comandos do bot**: `/status`, `/pausar`, `/retomar`, `/piloto_on`, `/piloto_off`.
- Depois de 15 aprovações seguidas sem ajuste, o bot sugere ligar o **piloto automático**. Com ele ligado,
  o robô publica sozinho, e a equipe de verificação continua podendo barrar posts com problema.
- **Toda segunda** chega o resumo da semana. O relatório completo fica em `relatorios/<pagina>/`.

## Custo
**R$ 0**, dentro dos planos grátis. A voz do Google usa o cartão já cadastrado apenas como garantia, e o
consumo previsto fica abaixo de 5% da cota grátis. Um alerta de orçamento de R$ 5 avisa se algo fugir do previsto.

## Instalação no seu PC (para as autorizações e testes)
Requisitos: Python 3.12 e FFmpeg. Os dois já estão instalados no seu desktop.

1. Abra a pasta `C:\projetos\redes-sociais` no terminal.
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Copie `.env.exemplo` para `.env` e siga o [SETUP_CONTAS.md](SETUP_CONTAS.md) para preencher as chaves.
4. Confira tudo:
   ```bash
   python main.py testar
   ```
5. Gere exemplos sem publicar nada:
   ```bash
   python main.py exemplos --quantidade 3
   ```
   Os vídeos ficam em `saida/energia-em-casa/`.

### Testar sem nenhuma chave (só no PC)
Dá para usar a IA local (Ollama) e a voz local (Piper). É mais lento e a qualidade é menor, mas não depende de nada externo:
```bash
set LLM_FORCAR=ollama
python main.py exemplos --quantidade 3
```

## Na nuvem (GitHub Actions)
| Agendamento | Horário (Brasília) | O que faz |
|---|---|---|
| `diario` | todo dia 23:00 · sexta 23:30 (vídeo longo) | gera os 4 posts do dia seguinte e manda as prévias |
| `ciclo` | a cada 20 min | lê o Telegram e publica o que está aprovado e chegou a hora |
| `semanal` | segunda 08:00 | métricas, ajustes e relatório |

Para rodar na hora: aba **Actions**, escolha o workflow e clique em **Run workflow**.

O "cérebro" do robô (fila, histórico, aprendizado) fica em `estado/` e é salvo no repositório depois de
cada execução. Os vídeos esperam a aprovação numa *release* do repositório e são apagados depois de publicados.

## Mudar coisas sem mexer no código
Tudo fica em `paginas/energia-em-casa/config.yaml`: nome, @, tom de voz, cores, vozes, horários,
frequência, plataformas, modo de aprovação, pesos das categorias e frases de fechamento.
Os fatos permitidos das pautas fixas ficam em `paginas/energia-em-casa/pautas.yaml`.

## Adicionar uma nova página (2ª, 3ª…)
1. Copie a pasta `paginas/energia-em-casa` para `paginas/<nova-pagina>`.
2. Edite o `config.yaml` e o `pautas.yaml` da nova página. O Claude faz isso com você, com o agente `rs-curador-pautas`.
3. Crie as contas da nova página ([SETUP_CONTAS.md](SETUP_CONTAS.md), itens 2 a 5) e rode `token-youtube` e
   `token-meta` com `--pagina <nova-pagina>`.
4. Cadastre os Secrets com o sufixo da página (ex.: `META_PAGE_TOKEN_QUARTO_DE_MILHA`) e acrescente essas
   linhas em `.github/workflows/_preparar.yml`, nas seções `secrets` e `env`.

A página nova já entra nos agendamentos automaticamente.

> A página de energia usa dados da ANEEL. Uma página de outro nicho (ex.: Quarto de Milha) precisa de uma
> fonte de dados própria ou só das pautas com fatos curados. O Claude monta isso na hora de criar.

## Fotos próprias
Fotos em `paginas/<pagina>/midia_propria/` deixam os vídeos mais autênticos. Por padrão essa pasta **não**
vai para o GitHub, por privacidade. Para usar essas fotos na nuvem, escolha as fotos liberadas (sem cliente,
endereço ou placa) e remova a linha `paginas/*/midia_propria/*` do `.gitignore`. Lembre que o repositório é público.

## Problemas comuns
| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Bot avisa "token vencido" | autorização expirou | rode `token-youtube` ou `token-meta` e atualize o Secret |
| Vídeo do YouTube saiu privado | app ainda sem auditoria do Google | mude para Público no app (SETUP item 4.7) |
| "equipe de verificação não aprovou nenhuma pauta" | pautas fracas ou dado duvidoso | veja `estado/<pagina>/bloqueios.json`; peça ao Claude o `rs-curador-pautas` |
| "sem pautas disponíveis" | banco de pautas esgotado | `rs-curador-pautas` |
| Nada acontece na nuvem | Actions desativado (60 dias sem atividade) | aba Actions → Enable. O commit diário do estado costuma evitar isso. |

## Estrutura
```
main.py                     comandos
config/global.yaml          IAs, voz, legendas (vale para todas as páginas)
paginas/<pagina>/           config.yaml · pautas.yaml · midia_propria/
motor/                      o robô (ideias, roteiro, equipe/, midia/, publicar/, ciclo, métricas, relatório)
estado/<pagina>/            fila, histórico, aprendizado (salvo automaticamente)
relatorios/<pagina>/        relatórios semanais
.claude/agents/             equipe de agentes do Claude Code (auditoria, políticas, pautas, estratégia)
.github/workflows/          agendamentos na nuvem
```
