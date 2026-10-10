// Local run of worker.js on Node 20+: node worker/dev.mjs [port]
// Reads the key from ../.env and the id -> model map from ../models.local.json.
import http from "node:http";
import fs from "node:fs";
import { Readable } from "node:stream";
import worker from "./worker.js";

const root = new URL("..", import.meta.url);
const env = Object.fromEntries(
  fs.readFileSync(new URL(".env", root), "utf8").split("\n").filter((l) => l.includes("=")).map((l) => {
    const i = l.indexOf("=");
    return [l.slice(0, i).trim(), l.slice(i + 1).trim()];
  }),
);
const models = JSON.parse(fs.readFileSync(new URL("models.local.json", root), "utf8"));
env.MODELS = { get: async (id) => (models[id] ? JSON.stringify(models[id]) : null) };

const port = Number(process.argv[2] || 8787);
http.createServer(async (req, res) => {
  const r = await worker.fetch(new Request(`http://127.0.0.1:${port}${req.url}`, { method: req.method }), env);
  const headers = Object.fromEntries(r.headers);
  // Node's fetch already decompressed the upstream body
  delete headers["content-encoding"];
  res.writeHead(r.status, headers);
  if (r.body) Readable.fromWeb(r.body).pipe(res);
  else res.end();
}).listen(port, "127.0.0.1", () => console.log(`http://127.0.0.1:${port}`));
