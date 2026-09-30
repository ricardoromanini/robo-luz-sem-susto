# Pedido de auditoria do TikTok (Content Posting API — Direct Post)

Preenchido em 30/09/2026 no portal developers.tiktok.com (app "Luz Sem Susto Robo", versão Production).
Demonstração gravada no Sandbox "testes" com a conta @luz.sem.susto privada (regra do TikTok para apps não auditados).

## Texto enviado (explicação dos produtos e escopos)

Luz Sem Susto Robo is an internal tool used only by the owner of the TikTok account @luz.sem.susto, an educational page about Brazilian electricity bills. We produce our own short videos; the owner reviews each one and then opens a private, signed link to our posting page (luz-sem-susto-painel.ricardoromanini9.workers.dev).
Login Kit / user.info.basic: the owner connects his TikTok account once; the posting page shows his nickname and avatar so he sees which account will receive the post.
Content Posting API / video.publish + video.upload: on the posting page the owner previews the video, edits the caption, must choose who can view it (no default, options from creator_info), sets comments/duet/stitch (off by default, disabled when not allowed), may disclose commercial content, sees the Music Usage Confirmation and taps "Post to TikTok". Only then the file is uploaded (FILE_UPLOAD, is_aigc=true) and the status is shown. Nothing is posted without this action.

## Depois da aprovação
- Trocar em paginas/energia-em-casa/config.yaml: plataformas.tiktok.modo_api de rascunho para painel.
- O robô passa a mandar no Telegram o link do painel; o dono escolhe a privacidade e toca em Publicar.
- Trocar as chaves do painel (TIKTOK_CLIENT_KEY/SECRET) pelas da versão Production e reconectar a conta (/conectar).
