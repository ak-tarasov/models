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
<style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff}body{display:flex;align-items:center;justify-content:center}#v{position:relative;width:min(100vw,100vh);height:min(100vw,100vh);width:min(100vw,100dvh);height:min(100vw,100dvh);box-sizing:border-box;border:1px solid #c8ccd0;overflow:hidden}#msg{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;font:16px sans-serif;color:#444}</style>
</head>
<body>
<div id="v"></div><div id="msg">Загрузка модели…</div>
<script>
const msg = t => document.getElementById('msg').textContent = t;
const VIEW = ${JSON.stringify(model.view || {}).replace(/</g, '\\u003c')};
Autodesk.Viewing.Initializer({ env: 'AutodeskProduction', api: 'derivativeV2', shouldInitializeAuth: false, language: 'ru' }, () => {
  Autodesk.Viewing.endpoint.setEndpointAndApi(location.origin + '/p/${id}', 'derivativeV2');
  const viewer = new Autodesk.Viewing.GuiViewer3D(document.getElementById('v'));
  viewer.start();
  addEventListener('resize', () => viewer.resize());
  // frame where the detail is: the middle 96% of solid fragment centres per axis,
  // so slabs, long walls and stray lines around the model do not shrink it
  viewer.addEventListener(Autodesk.Viewing.GEOMETRY_LOADED_EVENT, () => {
    if (!viewer.model.is3d()) return;
    const frags = viewer.model.getFragmentList(), b = new THREE.Box3(), xs = [], ys = [], zs = [];
    for (let i = 0; i < frags.getCount(); i++) {
      const g = frags.getGeometry(i);
      if (!g || g.isLines || g.isWideLines || g.isPoints) continue;
      frags.getWorldBounds(i, b);
      xs.push((b.min.x + b.max.x) / 2); ys.push((b.min.y + b.max.y) / 2); zs.push((b.min.z + b.max.z) / 2);
    }
    if (!xs.length) return;
    const span = a => { a.sort((p, q) => p - q); return [a[Math.floor(a.length * 0.02)], a[Math.ceil(a.length * 0.98) - 1]]; };
    const [x, y, z] = [span(xs), span(ys), span(zs)];
    const box = new THREE.Box3(new THREE.Vector3(x[0], y[0], z[0]), new THREE.Vector3(x[1], y[1], z[1]));
    const nav = viewer.navigation, c = box.getCenter(new THREE.Vector3());
    if (VIEW.dir) nav.setView(new THREE.Vector3().fromArray(VIEW.dir).add(c), c);
    nav.fitBounds(true, box);
    const t = nav.getTarget(), p = nav.getPosition();
    nav.setView(p.sub(t).multiplyScalar(VIEW.zoom || 1).add(t), t);
    window.__framed = true;
  });
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
