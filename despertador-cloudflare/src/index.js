// Despertador do robô Luz Sem Susto (Cloudflare Workers — gatilhos de relógio).
// O agendador gratuito do GitHub atrasa horas; este relógio chama o robô na hora certa, com o PC desligado.
// Ele só "aperta o botão" de rodar o workflow no GitHub. O robô continua rodando no GitHub Actions.
//
// Segredo necessário (wrangler secret put GITHUB_TOKEN): token do GitHub com permissão
// "Actions: Read and write" SOMENTE no repositório do robô.

const REPO = "ricardoromanini/robo-luz-sem-susto";

// expressão do relógio (UTC) -> workflow e entradas
const AGENDA = {
  "4,24,44 * * * *": { workflow: "ciclo.yml" },                                  // a cada 20 min: lê o Telegram e publica
  "7 1 * * *": { workflow: "diario.yml", inputs: { formato: "short" } },         // 22:07 BRT: gera os posts do dia seguinte
  "37 1 * * SAT": { workflow: "diario.yml", inputs: { formato: "longo" } },      // sexta 22:37 BRT: vídeo longo
  "13 11 * * MON": { workflow: "semanal.yml" },                                  // segunda 08:13 BRT: relatório semanal
};

async function disparar(env, alvo) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${alvo.workflow}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "despertador-luz-sem-susto",
    },
    body: JSON.stringify({ ref: "main", inputs: alvo.inputs || {} }),
  });
  if (!r.ok) throw new Error(`GitHub respondeu ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.status;
}

export default {
  async scheduled(evento, env, ctx) {
    const alvo = AGENDA[evento.cron];
    if (!alvo) return;
    ctx.waitUntil(disparar(env, alvo).then(
      (s) => console.log(`ok ${alvo.workflow} (${s})`),
      (e) => console.error(`falhou ${alvo.workflow}: ${e.message}`),
    ));
  },
  // abrir o endereço do Worker no navegador só mostra que ele está vivo (não dispara nada)
  async fetch() {
    return new Response("Despertador do Luz Sem Susto: ativo.", { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
