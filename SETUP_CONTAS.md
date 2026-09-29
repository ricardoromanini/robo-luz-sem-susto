# Passo a passo das contas e chaves (feito UMA vez)

**Tempo total: cerca de 2h30.** Pode dividir em dias. Onde aparece 🤖, o Claude pode abrir as telas
e preencher com você; você só entra com login e senha e clica em "Permitir".

> Regra de segurança: chaves e tokens **nunca** vão no código nem em conversa. Eles ficam no arquivo `.env`
> (no seu PC) e nos **Secrets** do GitHub (na nuvem).

---

## 1. Nome da página (5 min)
O nome provisório é **Luz Sem Susto (@luzsemsusto)**. Para trocar, edite `nome` e `arroba` em
`paginas/energia-em-casa/config.yaml`. Use o **mesmo @** no YouTube, Instagram, Facebook e TikTok.

## 2. Gmail da página (10 min)
Crie um Gmail só para a página (ex.: `luzsemsusto@gmail.com`), com verificação por celular.
Assim nada se mistura com o seu e-mail pessoal nem com os outros projetos.

## 3. Canal do YouTube (10 min)
1. Com o Gmail novo, abra youtube.com → foto → **Criar um canal** → use o nome da página.
2. Em youtube.com/verify, verifique o celular. Isso libera vídeos longos e miniatura personalizada.

## 4. Google Cloud: voz + API do YouTube (25 min) 🤖
Faça login com o **Gmail da página** em console.cloud.google.com:
1. **Criar projeto** → nome `robo-luz-sem-susto`.
2. **Faturamento**: vincule a conta de faturamento que já tem cartão. A voz é grátis até 1 milhão de
   caracteres por mês, e usamos menos de 5%.
   Em seguida, em Faturamento → **Orçamentos e alertas**, crie um orçamento de **R$ 5** com alerta em 50%.
3. **APIs e serviços → Biblioteca**: ative **YouTube Data API v3**, **YouTube Analytics API** e
   **Cloud Text-to-Speech API**.
4. **Credenciais → Criar credenciais → Chave de API** → Restringir chave → só "Cloud Text-to-Speech API".
   Copie a chave: é o `GOOGLE_TTS_API_KEY`.
5. **Tela de consentimento OAuth** → Externo → nome do app, e-mail → adicione o Gmail da página como
   usuário de teste → depois clique em **Publicar app** ("Em produção").
   *Se o app ficar em "Teste", a autorização vence a cada 7 dias.*
6. **Credenciais → Criar credenciais → ID do cliente OAuth → App para computador**.
   Copie o `YOUTUBE_CLIENT_ID` e o `YOUTUBE_CLIENT_SECRET`.
7. **Auditoria da API do YouTube** (para os vídeos saírem públicos sozinhos): preencha o formulário
   "YouTube API Services – Audit and Quota Extension". O Claude prepara as respostas. A resposta leva de 2 a 6 semanas.
   Até lá, os vídeos sobem como **privados** e o bot te avisa para mudar para "Público" no app (1 toque).

## 5. Instagram + Página do Facebook (30 min) 🤖
1. No app do Instagram, crie a conta **@da página** e mude para **Conta profissional** (Criador de conteúdo → Educação).
2. No Facebook, crie a **Página** da marca (categoria: Site de educação).
3. No Instagram: Configurações → Central de Contas → **vincule a Página do Facebook**.
4. Em developers.facebook.com (a mesma conta de desenvolvedor que você já usa), **crie um app novo**
   "Robo Luz Sem Susto" (tipo Empresa), com os casos de uso "Gerenciar tudo na sua Página" e "Instagram".
   Copie o **ID do app** e a **Chave secreta** para o `.env` (`META_APP_ID`, `META_APP_SECRET`).
5. No seu PC, dentro da pasta do projeto, rode:
   ```bash
   python main.py token-meta --pagina energia-em-casa
   ```
   O navegador abre, você clica em **Permitir** e o robô grava `META_PAGE_TOKEN_...`, `FB_PAGE_ID_...` e `IG_USER_ID_...`.
   Esse token de Página não vence enquanto você não trocar a senha ou remover o app. O robô confere todo dia.

## 6. Telegram (5 min)
1. No Telegram, fale com **@BotFather** → `/newbot` → nome "Luz Sem Susto Robô" → usuário terminando em `bot`.
2. Copie o token para o `.env` como `TELEGRAM_BOT_TOKEN`.
3. Abra o seu bot, mande **oi** e rode:
   ```bash
   python main.py telegram-id
   ```

## 7. Chaves grátis de IA e imagens (20 min) 🤖
| Chave | Onde | Observação |
|---|---|---|
| `GEMINI_API_KEY` | aistudio.google.com/apikey | Roteirista. No plano grátis o Google pode usar os textos para melhorar modelos; não mandamos nada sigiloso. |
| `GROQ_API_KEY` | console.groq.com/keys | Equipe de verificação + transcrição (Whisper) |
| `OPENROUTER_API_KEY` | openrouter.ai/keys | Reserva (opcional) |
| `PEXELS_API_KEY` | pexels.com/api | Fotos (licença permite uso monetizado; o robô credita na legenda) |
| `PIXABAY_API_KEY` | pixabay.com/api/docs | Reserva de fotos |

## 8. Testar tudo no PC (5 min)
```bash
python main.py testar
```
Tudo precisa aparecer com ✅. O Telegram recebe "Teste de conexão do robô: OK".

## 9. YouTube: autorizar o canal (3 min)
```bash
python main.py token-youtube --pagina energia-em-casa
```
Faça login com o **Gmail da página**. Se aparecer "O Google não verificou este app", clique em
Avançado → Acessar (o app é seu) → **Permitir**.

## 10. GitHub: colocar o robô na nuvem (20 min) 🤖
1. Crie uma conta em github.com (se ainda não tiver).
2. Crie um repositório **público** chamado `robo-luz-sem-susto`. Público dá minutos ilimitados, e as senhas
   ficam protegidas nos Secrets.
3. O Claude envia o código para o repositório.
4. No repositório: **Settings → Secrets and variables → Actions → New repository secret**, e cadastre um
   por um (os mesmos valores do seu `.env`):
   `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_TTS_API_KEY`, `PEXELS_API_KEY`,
   `PIXABAY_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
   `YOUTUBE_REFRESH_TOKEN_ENERGIA_EM_CASA`, `META_PAGE_TOKEN_ENERGIA_EM_CASA`, `FB_PAGE_ID_ENERGIA_EM_CASA`,
   `IG_USER_ID_ENERGIA_EM_CASA`.
5. Aba **Actions** → habilite os workflows → abra **diario** → **Run workflow**. Em alguns minutos a
   primeira prévia chega no seu Telegram.

## 11. TikTok (opcional, 10 min)
Crie a conta com o mesmo @. A postagem é manual: o bot manda o vídeo pronto e a legenda. No app, ative
**"Conteúdo gerado por IA"** em cada post.

## 12. Mais tarde (mês 1–2): afiliados (30 min)
Mercado Livre Afiliados, Amazon Associados e Shopee Afiliados (CPF + dados bancários). Depois me passe os
links e eu ativo `afiliados` no config. O aviso de afiliado é automático, como exige o CONAR.

## 13. Quando o robô avisar: monetização do YouTube (20 min)
YouTube Studio → **Ganhar dinheiro** → aceitar os termos → criar/vincular o **AdSense** (dados fiscais e
bancários). O robô avisa no Telegram quando os requisitos forem atingidos.

---

### Manutenção (o robô te lembra)
| O quê | Quando | Comando |
|---|---|---|
| Token Meta | Se o bot avisar (troca de senha, app removido) | `python main.py token-meta --pagina energia-em-casa` |
| Token YouTube | Se o bot avisar "token vencido/revogado" | `python main.py token-youtube --pagina energia-em-casa` |
| Atualizar o Secret no GitHub | Sempre que rodar um dos comandos acima | Settings → Secrets → editar |
