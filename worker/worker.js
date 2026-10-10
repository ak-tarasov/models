// Model viewer behind a proxy: the Autodesk token stays on the server,
// each link id opens only the model it is mapped to.
//   /m/<id>        viewer page
//   /p/<id>/...    proxied Autodesk derivative requests, limited to that model's urn

const APS = "https://developer.api.autodesk.com";
const VIEWER = `${APS}/modelderivative/v2/viewers/7.*`;

let cached = { token: null, exp: 0 };

async function getToken(env) {
  if (cached.token && Date.now() < cached.exp) return cached.token;
  const r = await fetch(`${APS}/authentication/v2/token`, {
    method: "POST",
    headers: {
      Authorization: "Basic " + btoa(`${env.APS_CLIENT_ID}:${env.APS_CLIENT_SECRET}`),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials&scope=viewables%3Aread",
  });
  if (!r.ok) throw new Error(`token ${r.status}`);
  const j = await r.json();
  cached = { token: j.access_token, exp: Date.now() + (j.expires_in - 300) * 1000 };
  return cached.token;
}

async function getModel(env, id) {
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(id)) return null;
  const raw = await env.MODELS.get(id);
  return raw ? JSON.parse(raw) : null;
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function page(id, model) {
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<meta name="robots" content="noindex">
<title>${esc(model.name || "Модель")} · NJ Design</title>
<link rel="stylesheet" href="${VIEWER}/style.min.css">
<script src="${VIEWER}/viewer3D.min.js"></script>
<style>html,body,#v{margin:0;width:100%;height:100%;overflow:hidden}#msg{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;font:16px sans-serif;color:#444}</style>
</head>
<body>
<div id="v"></div><div id="msg">Загрузка модели…</div>
<script>
const msg = t => document.getElementById('msg').textContent = t;
Autodesk.Viewing.Initializer({ env: 'AutodeskProduction', api: 'derivativeV2', shouldInitializeAuth: false, language: 'ru' }, () => {
  Autodesk.Viewing.endpoint.setEndpointAndApi(location.origin + '/p/${id}', 'derivativeV2');
  const viewer = new Autodesk.Viewing.GuiViewer3D(document.getElementById('v'));
  viewer.start();
  Autodesk.Viewing.Document.load('urn:${model.urn}', doc => {
    viewer.loadDocumentNode(doc, doc.getRoot().getDefaultGeometry()).then(() => {
      document.getElementById('msg').remove();
      viewer.loadExtension('Autodesk.DocumentBrowser');
      window.__loaded = true;
    });
  }, code => msg('Модель не открылась (код ' + code + ')'));
});
</script>
</body>
</html>`;
}

async function proxy(request, env, id, rest, search) {
  if (request.method !== "GET") return new Response("method not allowed", { status: 405 });
  const model = await getModel(env, id);
  if (!model) return new Response("not found", { status: 404 });
  let decoded;
  try {
    decoded = decodeURIComponent(rest);
  } catch {
    return new Response("bad request", { status: 400 });
  }
  // only derivative data of this link's own model may pass
  if (!/^\/(derivativeservice|modelderivative)\/v2\//.test(decoded) || decoded.includes("..") ||
      !decoded.includes(model.urn)) {
    return new Response("forbidden", { status: 403 });
  }
  const upstream = await fetch(APS + rest + search, {
    headers: { Authorization: `Bearer ${await getToken(env)}` },
  });
  const headers = new Headers();
  for (const h of ["content-type", "content-encoding", "cache-control", "etag", "last-modified"]) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let m;
    try {
      if ((m = url.pathname.match(/^\/m\/([^/]+)\/?$/))) {
        const model = await getModel(env, m[1]);
        if (!model) return new Response("Модель не найдена", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
        return new Response(page(m[1], model), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
      }
      if ((m = url.pathname.match(/^\/p\/([^/]+)(\/.*)$/))) {
        return await proxy(request, env, m[1], m[2], url.search);
      }
    } catch (e) {
      return new Response("upstream error", { status: 502 });
    }
    return new Response("NJ Design", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
