# Pedido de auditoria da API do YouTube (para os vídeos saírem públicos)

> **30/09/2026 — NÃO FOI NECESSÁRIO.** O primeiro vídeo enviado pelo robô (youtu.be/XEHMPjpwqRw) saiu **público**
> sem auditoria. Este documento fica guardado só para o caso de o YouTube passar a travar os vídeos como
> privados (o robô avisa no Telegram se isso acontecer).

Enquanto o Google não aprovar, os vídeos enviados pelo robô ficam **privados**. O robô avisa no
Telegram, e você muda para "Público" no YouTube Studio com 1 toque.

Formulário: https://support.google.com/youtube/contact/yt_api_form
(opção "YouTube API Services - Audit and Quota Extension Form")

## Respostas prontas
- **Projeto do Google Cloud:** My First Project (ID `hopeful-subject-441510-p8`)
- **Nome do cliente da API:** Robo Luz Sem Susto
- **Canal:** Luz Sem Susto — https://www.youtube.com/channel/UCIAjQCAHC583ecGiqZ6FTOw
- **Site / política de privacidade / termos:**
  - https://ricardoromanini.github.io/robo-luz-sem-susto/
  - https://ricardoromanini.github.io/robo-luz-sem-susto/privacidade.html
  - https://ricardoromanini.github.io/robo-luz-sem-susto/termos.html
- **Código-fonte (público):** https://github.com/ricardoromanini/robo-luz-sem-susto
- **Quem usa:** só o dono do canal (uso interno, 1 canal, sem usuários externos).
- **APIs usadas:** `videos.insert` (enviar Shorts próprios), `channels.list` e YouTube Analytics (ler as métricas do próprio canal).
- **Cota:** a padrão (10.000/dia) é suficiente. São no máximo 5 envios por dia.

### Descrição do uso (colar em inglês)
> Internal tool used only by the channel owner to publish original, fact-checked short videos
> about electricity bills and home electrical safety to our own channel "Luz Sem Susto".
> Every video is reviewed and approved by the owner in a private Telegram chat before the tool
> calls videos.insert. The tool also reads our own channel's statistics (YouTube Analytics API)
> to produce a weekly internal report. No third-party users, no data sharing, no data sold.
> Content is labeled as AI-assisted (containsSyntheticMedia) and follows the YouTube policies.
> Source code is public on GitHub.
