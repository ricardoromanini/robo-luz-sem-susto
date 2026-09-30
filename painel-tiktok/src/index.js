// Painel de publicação no TikTok do Luz Sem Susto (Cloudflare Worker).
//
// Fluxo real de uso: o robô publica nas outras redes e manda no Telegram um link assinado para este painel.
// O dono abre o link, vê a conta do TikTok, escolhe quem pode ver, as interações e a divulgação comercial,
// e toca em "Publicar". Só então o vídeo é enviado ao TikTok (Content Posting API — Direct Post).
// Segue as regras de UX do TikTok para a postagem direta (conta exibida, privacidade sem padrão, interações
// desmarcadas, divulgação comercial, aviso de consentimento e confirmação explícita).

const TT = "https://open.tiktokapis.com/v2";
const ESCOPOS = "user.info.basic,video.upload,video.publish";

// ------------------------------------------------------------------ utilidades
const html = (corpo, status = 200) => new Response(corpo, { status, headers: { "content-type": "text/html; charset=utf-8" } });
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function hmac(segredo, texto) {
  const chave = await crypto.subtle.importKey("raw", new TextEncoder().encode(segredo), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const ass = await crypto.subtle.sign("HMAC", chave, new TextEncoder().encode(texto));
  return [...new Uint8Array(ass)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// link = ?post=<id>&exp=<unix>&sig=<hmac(post.exp)>  (gerado pelo robô com o mesmo LINK_SECRET)
async function linkValido(env, post, exp, sig) {
  if (!post || !exp || !sig || Number(exp) < Date.now() / 1000) return false;
  return (await hmac(env.LINK_SECRET, `${post}.${exp}`)) === sig;
}

// ------------------------------------------------------------------ TikTok: chaves de acesso
async function tokenPost(env, campos) {
  const r = await fetch(`${TT}/oauth/token/`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_key: env.TIKTOK_CLIENT_KEY, client_secret: env.TIKTOK_CLIENT_SECRET, ...campos }),
  });
  const d = await r.json();
  if (!d.access_token) throw new Error(d.error_description || d.error || "falha ao obter a chave do TikTok");
  await env.KV.put("tiktok:tokens", JSON.stringify({ ...d, obtido_em: Date.now() }));
  return d.access_token;
}

async function acesso(env) {
  const t = JSON.parse((await env.KV.get("tiktok:tokens")) || "null");
  if (!t) throw new Error("conta do TikTok não conectada");
  if (Date.now() < t.obtido_em + (t.expires_in - 600) * 1000) return t.access_token;
  return tokenPost(env, { grant_type: "refresh_token", refresh_token: t.refresh_token });
}

async function tt(env, caminho, corpo) {
  const r = await fetch(`${TT}${caminho}`, {
    method: "POST", body: JSON.stringify(corpo || {}),
    headers: { Authorization: `Bearer ${await acesso(env)}`, "Content-Type": "application/json; charset=UTF-8" },
  });
  const d = await r.json();
  if (d.error && d.error.code !== "ok") throw new Error(`${d.error.code}: ${d.error.message}`);
  return d.data || {};
}

// ------------------------------------------------------------------ dados do post (fila pública do robô)
async function lerPost(env, id) {
  const r = await fetch(`https://raw.githubusercontent.com/${env.REPO}/main/estado/${env.PAGINA}/fila.json`, { cf: { cacheTtl: 30 } });
  const fila = await r.json();
  const item = fila.find((i) => i.id === id);
  if (!item) return null;
  const arroba = "@luz.sem.susto";
  const legenda = (item.legenda?.social || "").replaceAll("@luzsemsusto", arroba);
  return {
    id: item.id, titulo: item.titulo, legenda, duracao: item.qc?.info?.duracao_s || 0,
    video: `https://github.com/${env.REPO}/releases/download/fila-${env.PAGINA}/${item.video?.nome}`,
  };
}

// ------------------------------------------------------------------ páginas
const ESTILO = `
  :root{--fundo:#0E1A2B;--card:#16263d;--txt:#fff;--sub:#9fb3c8;--dest:#FFC107;--rosa:#fe2c55}
  *{box-sizing:border-box} body{margin:0;background:var(--fundo);color:var(--txt);font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  main{max-width:560px;margin:0 auto;padding:16px}
  h1{font-size:1.25rem;margin:.2rem 0 1rem} .card{background:var(--card);border-radius:14px;padding:14px;margin-bottom:12px}
  .conta{display:flex;gap:10px;align-items:center} .conta img{width:44px;height:44px;border-radius:50%}
  video{width:100%;border-radius:12px;background:#000;max-height:60vh}
  label{display:block;margin:.35rem 0} textarea{width:100%;min-height:110px;border-radius:8px;padding:8px;font:inherit}
  select{width:100%;padding:10px;border-radius:8px;font:inherit}
  .sub{color:var(--sub);font-size:.88rem} .aviso{color:#ffb4b4;font-size:.9rem}
  button{width:100%;padding:14px;border:0;border-radius:10px;background:var(--rosa);color:#fff;font-weight:700;font-size:1.05rem}
  button:disabled{opacity:.45} a{color:var(--dest)} .tag{display:inline-block;background:#223a5a;border-radius:6px;padding:2px 8px;font-size:.85rem}`;

function paginaPublicar(post, q) {
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Publicar no TikTok — Luz Sem Susto</title><style>${ESTILO}</style></head><body><main>
<h1>Publicar no TikTok <span class="sub">(Post to TikTok)</span></h1>
<div class="card conta" id="conta"><span class="sub">Carregando a conta do TikTok…</span></div>
<div class="card"><video src="${esc(post.video)}" controls playsinline preload="metadata"></video>
  <p class="sub" style="margin:.4rem 0 0">${esc(post.titulo)}</p></div>
<div class="card"><label for="leg"><b>Legenda</b> <span class="sub">(caption)</span></label>
  <textarea id="leg" maxlength="2200">${esc(post.legenda)}</textarea>
  <label><input type="checkbox" id="aigc" checked disabled> Conteúdo gerado por IA <span class="sub">(AI-generated content label)</span></label></div>
<div class="card"><label for="priv"><b>Quem pode ver este vídeo</b> <span class="sub">(Who can view this video)</span></label>
  <select id="priv"><option value="" selected disabled>Escolha… (Select)</option></select>
  <p class="aviso" id="avisoPriv" hidden></p></div>
<div class="card"><b>Permitir que outras pessoas</b> <span class="sub">(Allow users to)</span>
  <label><input type="checkbox" id="com"> Comentem <span class="sub">(Comment)</span></label>
  <label><input type="checkbox" id="duet"> Façam dueto <span class="sub">(Duet)</span></label>
  <label><input type="checkbox" id="stitch"> Façam costura <span class="sub">(Stitch)</span></label></div>
<div class="card"><label><input type="checkbox" id="divulgar"> <b>Divulgar conteúdo comercial</b> <span class="sub">(Disclose video content)</span></label>
  <div id="opcoesDiv" hidden>
    <p class="sub">Seu vídeo será identificado conforme a opção marcada.</p>
    <label><input type="checkbox" id="marcaPropria"> Sua marca <span class="sub">(Your brand)</span> — rótulo “Conteúdo promocional”</label>
    <label><input type="checkbox" id="marcaTerceiro"> Conteúdo de marca <span class="sub">(Branded content)</span> — rótulo “Parceria paga”</label>
    <p class="aviso" id="avisoDiv" hidden></p></div></div>
<p class="sub" id="consent">Ao publicar, você concorda com a <a href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en" target="_blank">Confirmação de Uso de Música</a> do TikTok.</p>
<button id="pub" disabled>Publicar no TikTok</button>
<p id="res" class="sub"></p>
</main><script>
const Q=${JSON.stringify(q)}, DUR=${Number(post.duracao) || 0};
const $=(i)=>document.getElementById(i); let info=null;
async function api(c,b){const r=await fetch(c+"?"+new URLSearchParams(Q),{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(b||{})});const d=await r.json();if(!r.ok)throw new Error(d.erro||r.status);return d;}
function validar(){
  const div=$("divulgar").checked, prop=$("marcaPropria").checked, terc=$("marcaTerceiro").checked, priv=$("priv").value;
  $("opcoesDiv").hidden=!div; let ok=!!priv && !!info && info.pode_postar; let aviso="";
  if(div&&!prop&&!terc){ok=false;aviso="Marque pelo menos uma opção de divulgação.";}
  if(terc&&priv==="SELF_ONLY"){ok=false;aviso="Conteúdo de marca não pode ser publicado como privado (Somente eu).";}
  $("avisoDiv").hidden=!aviso; $("avisoDiv").textContent=aviso;
  const pol='<a href="https://www.tiktok.com/legal/page/global/bc-policy/en" target="_blank">Política de Conteúdo de Marca</a> e a ';
  $("consent").innerHTML='Ao publicar, você concorda com a '+(terc?pol:'')+'<a href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en" target="_blank">Confirmação de Uso de Música</a> do TikTok.';
  $("pub").disabled=!ok;
}
["priv","divulgar","marcaPropria","marcaTerceiro"].forEach(i=>$(i).addEventListener("change",validar));
(async()=>{try{
  info=await api("/api/criador");
  $("conta").innerHTML=(info.avatar?'<img src="'+info.avatar+'" alt="">':'')+'<div><b>'+info.nome+'</b><div class="sub">Publicando nesta conta do TikTok (posting to this account)</div></div>';
  const nomes={PUBLIC_TO_EVERYONE:"Todos (Everyone)",MUTUAL_FOLLOW_FRIENDS:"Amigos (Friends)",FOLLOWER_OF_CREATOR:"Seguidores (Followers)",SELF_ONLY:"Somente eu (Only me)"};
  info.privacidades.forEach(p=>{const o=document.createElement("option");o.value=p;o.textContent=nomes[p]||p;$("priv").appendChild(o);});
  $("com").disabled=info.comentario_off; $("duet").disabled=info.dueto_off; $("stitch").disabled=info.costura_off;
  if(DUR&&info.max_duracao&&DUR>info.max_duracao){info.pode_postar=false;$("res").textContent="Este vídeo é mais longo que o permitido para esta conta ("+info.max_duracao+" s).";}
  if(!info.pode_postar&&!$("res").textContent)$("res").textContent="Esta conta não pode publicar agora (limite do TikTok). Tente mais tarde.";
  validar();
}catch(e){$("conta").innerHTML='<span class="aviso">Não foi possível carregar a conta: '+e.message+'</span>';}})();
$("pub").onclick=async()=>{ $("pub").disabled=true; $("res").textContent="Enviando o vídeo ao TikTok…";
  try{ const d=await api("/api/publicar",{legenda:$("leg").value,privacidade:$("priv").value,comentario:$("com").checked,
        dueto:$("duet").checked,costura:$("stitch").checked,marca_propria:$("divulgar").checked&&$("marcaPropria").checked,
        marca_terceiro:$("divulgar").checked&&$("marcaTerceiro").checked});
    $("res").textContent="✅ Enviado! O TikTok pode levar alguns minutos para processar e mostrar o vídeo no perfil.";
    for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,6000));const s=await api("/api/status",{publish_id:d.publish_id});
      if(s.status==="PUBLISH_COMPLETE"){$("res").textContent="✅ Publicado no TikTok.";return;}
      if(s.status==="FAILED"){$("res").textContent="⚠️ O TikTok não publicou: "+(s.fail_reason||"motivo não informado");return;}}
  }catch(e){$("res").textContent="⚠️ "+e.message;$("pub").disabled=false;}};
</script></body></html>`;
}

const paginaSimples = (titulo, texto) => html(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(titulo)}</title><style>${ESTILO}</style></head><body><main><h1>${esc(titulo)}</h1><div class="card">${texto}</div></main></body></html>`);

// ------------------------------------------------------------------ rotas
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const q = Object.fromEntries(url.searchParams);
    try {
      if (url.pathname === "/") {
        return paginaSimples("Luz Sem Susto — painel de publicação",
          `Ferramenta interna do dono da página <a href="${env.SITE}">Luz Sem Susto</a> para publicar no TikTok os vídeos já aprovados. <p class="sub">Internal publishing tool for the Luz Sem Susto page owner.</p>`);
      }
      // Telegram → cada clique/mensagem chega aqui NA HORA (webhook); guardamos para o robô processar no ciclo
      if (url.pathname === "/telegram/webhook" && req.method === "POST") {
        if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_WEBHOOK_SECRET) return new Response("", { status: 403 });
        const up = await req.json();
        const chat = String(up.callback_query?.message?.chat?.id ?? up.message?.chat?.id ?? "");
        if (chat !== String(env.TELEGRAM_CHAT_ID)) return new Response("ok");  // só o dono
        await env.KV.put(`tg:upd:${String(up.update_id).padStart(12, "0")}`, JSON.stringify(up), { expirationTtl: 7 * 86400 });
        if (up.callback_query) {
          await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({ callback_query_id: up.callback_query.id, text: "✅ Recebido! O robô registra em até 20 minutos." }) });
        }
        return new Response("ok");
      }
      // o robô busca os cliques guardados (link assinado com post="telegram") e confirma os que processou
      if (url.pathname === "/api/telegram") {
        if (!(await linkValido(env, "telegram", q.exp, q.sig))) return json({ erro: "link inválido" }, 403);
        if (req.method === "POST") {
          const b = await req.json().catch(() => ({}));
          await Promise.all((b.processados || []).map((id) => env.KV.delete(`tg:upd:${String(id).padStart(12, "0")}`)));
          return json({ ok: true });
        }
        const lista = await env.KV.list({ prefix: "tg:upd:" });
        const ups = await Promise.all(lista.keys.map((k) => env.KV.get(k.name, "json")));
        return json({ updates: ups.filter(Boolean).sort((a, b) => a.update_id - b.update_id) });
      }
      if (url.pathname.startsWith("/tiktok") && url.pathname.endsWith(".txt")) {
        const txt = await env.KV.get("verificacao:" + url.pathname.slice(1));
        return txt ? new Response(txt, { headers: { "content-type": "text/plain" } }) : new Response("não encontrado", { status: 404 });
      }
      // Login Kit: conectar a conta do TikTok (link assinado, post "conectar")
      if (url.pathname === "/conectar") {
        if (!(await linkValido(env, "conectar", q.exp, q.sig))) return paginaSimples("Link expirado", "Peça um link novo ao robô.");
        const estado = crypto.randomUUID();
        await env.KV.put("oauth:" + estado, "1", { expirationTtl: 900 });
        const dest = "https://www.tiktok.com/v2/auth/authorize/?" + new URLSearchParams({
          client_key: env.TIKTOK_CLIENT_KEY, scope: ESCOPOS, response_type: "code", state: estado,
          redirect_uri: `${url.origin}/callback` });
        return Response.redirect(dest, 302);
      }
      if (url.pathname === "/callback") {
        if (!q.code || !(await env.KV.get("oauth:" + q.state))) return paginaSimples("Autorização não concluída", esc(q.error_description || q.error || "pedido inválido"));
        await env.KV.delete("oauth:" + q.state);
        await tokenPost(env, { code: q.code, grant_type: "authorization_code", redirect_uri: `${url.origin}/callback` });
        return paginaSimples("Conta do TikTok conectada", "✅ Pronto. O painel já pode publicar nesta conta. Pode fechar esta página.");
      }
      if (url.pathname === "/publicar") {
        if (!(await linkValido(env, q.post, q.exp, q.sig))) return paginaSimples("Link expirado ou inválido", "Peça um link novo ao robô.");
        if (await env.KV.get("publicado:" + q.post)) return paginaSimples("Já publicado", "Este vídeo já foi enviado ao TikTok.");
        const post = await lerPost(env, q.post);
        if (!post) return paginaSimples("Vídeo não encontrado", "Este vídeo não está mais na fila do robô.");
        return html(paginaPublicar(post, { post: q.post, exp: q.exp, sig: q.sig }));
      }
      if (url.pathname.startsWith("/api/")) {
        if (req.method !== "POST" || !(await linkValido(env, q.post, q.exp, q.sig))) return json({ erro: "link inválido" }, 403);
        const b = await req.json().catch(() => ({}));
        if (url.pathname === "/api/criador") {
          const c = await tt(env, "/post/publish/creator_info/query/");
          return json({ nome: c.creator_nickname || c.creator_username, avatar: c.creator_avatar_url,
            privacidades: c.privacy_level_options || [], comentario_off: !!c.comment_disabled, dueto_off: !!c.duet_disabled,
            costura_off: !!c.stitch_disabled, max_duracao: c.max_video_post_duration_sec, pode_postar: c.can_post !== false });
        }
        if (url.pathname === "/api/publicar") {
          if (!b.privacidade) return json({ erro: "escolha quem pode ver o vídeo" }, 400);
          if (b.marca_terceiro && b.privacidade === "SELF_ONLY") return json({ erro: "conteúdo de marca não pode ser privado" }, 400);
          if (await env.KV.get("publicado:" + q.post)) return json({ erro: "este vídeo já foi enviado" }, 409);
          const post = await lerPost(env, q.post);
          const video = await fetch(post.video);
          if (!video.ok) return json({ erro: "vídeo indisponível na fila" }, 410);
          const dados = await video.arrayBuffer();
          const tam = dados.byteLength;
          const ini = await tt(env, "/post/publish/video/init/", {
            post_info: { title: String(b.legenda || "").slice(0, 2200), privacy_level: b.privacidade,
              disable_comment: !b.comentario, disable_duet: !b.dueto, disable_stitch: !b.costura, is_aigc: true,
              brand_organic_toggle: !!b.marca_propria, brand_content_toggle: !!b.marca_terceiro },
            source_info: { source: "FILE_UPLOAD", video_size: tam, chunk_size: tam, total_chunk_count: 1 } });
          const up = await fetch(ini.upload_url, { method: "PUT", body: dados,
            headers: { "Content-Type": "video/mp4", "Content-Range": `bytes 0-${tam - 1}/${tam}` } });
          if (!up.ok) return json({ erro: `TikTok recusou o envio (${up.status})` }, 502);
          await env.KV.put("publicado:" + q.post, JSON.stringify({ publish_id: ini.publish_id, em: Date.now(), privacidade: b.privacidade }));
          return json({ publish_id: ini.publish_id });
        }
        if (url.pathname === "/api/status") {
          const s = await tt(env, "/post/publish/status/fetch/", { publish_id: b.publish_id });
          return json({ status: s.status, fail_reason: s.fail_reason });
        }
      }
      return new Response("não encontrado", { status: 404 });
    } catch (e) {
      return url.pathname.startsWith("/api/") ? json({ erro: e.message }, 500) : paginaSimples("Erro", esc(e.message));
    }
  },
};
