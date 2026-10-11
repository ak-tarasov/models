#!/usr/bin/env python3
"""Deploy the viewer worker to Cloudflare and manage model links.

Usage:
  cf.py deploy                 upload worker/worker.js, bind KV and the Autodesk key
  cf.py add <urn> <name>       create a link for a model, print it
  cf.py view <id> <json>       opening view of a link: {"dir": [x, y, z], "zoom": 1.1}
  cf.py list                   existing links
  cf.py remove <id>            revoke a link
"""
import json
import os
import secrets
import sys
import urllib.parse
import uuid

import aps

API = "https://api.cloudflare.com/client/v4"
SCRIPT = "models"
KV_TITLE = "njd-models"
SUBDOMAIN = "nj-design"


def cf(method, path, body=None, headers=None, raw=False):
    r = aps.call(method, API + path, os.environ["CF_API_TOKEN"], body, headers, raw=raw)
    return r if raw else r.get("result")


def account():
    return cf("GET", "/accounts")[0]["id"]


def kv_namespace(acc, create=False):
    for ns in cf("GET", f"/accounts/{acc}/storage/kv/namespaces?per_page=100"):
        if ns["title"] == KV_TITLE:
            return ns["id"]
    if not create:
        raise SystemExit("KV namespace is missing: run cf.py deploy first")
    return cf("POST", f"/accounts/{acc}/storage/kv/namespaces", {"title": KV_TITLE})["id"]


def base_url(acc):
    return f"https://{SCRIPT}.{cf('GET', f'/accounts/{acc}/workers/subdomain')['subdomain']}.workers.dev"


def deploy():
    acc = account()
    ns = kv_namespace(acc, create=True)
    metadata = {
        "main_module": "worker.js",
        "compatibility_date": "2026-01-01",
        "bindings": [
            {"type": "kv_namespace", "name": "MODELS", "namespace_id": ns},
            {"type": "secret_text", "name": "APS_CLIENT_ID", "text": os.environ["APS_CLIENT_ID"]},
            {"type": "secret_text", "name": "APS_CLIENT_SECRET", "text": os.environ["APS_CLIENT_SECRET"]},
        ],
    }
    boundary = uuid.uuid4().hex
    code = (aps.ROOT / "worker" / "worker.js").read_bytes()
    parts = [
        (b'name="metadata"; filename="metadata.json"', b"application/json", json.dumps(metadata).encode()),
        (b'name="worker.js"; filename="worker.js"', b"application/javascript+module", code),
    ]
    body = b"".join(b"--" + boundary.encode() + b"\r\nContent-Disposition: form-data; " + disp +
                    b"\r\nContent-Type: " + ctype + b"\r\n\r\n" + data + b"\r\n"
                    for disp, ctype, data in parts) + b"--" + boundary.encode() + b"--\r\n"
    cf("PUT", f"/accounts/{acc}/workers/scripts/{SCRIPT}", body,
       {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        cf("GET", f"/accounts/{acc}/workers/subdomain")
    except SystemExit:
        cf("PUT", f"/accounts/{acc}/workers/subdomain", {"subdomain": SUBDOMAIN})
    cf("POST", f"/accounts/{acc}/workers/scripts/{SCRIPT}/subdomain", {"enabled": True})
    print(base_url(acc))


def add(urn, name):
    acc = account()
    ns = kv_namespace(acc)
    link_id = secrets.token_urlsafe(12)
    cf("PUT", f"/accounts/{acc}/storage/kv/namespaces/{ns}/values/{link_id}",
       json.dumps({"urn": urn, "name": name}, ensure_ascii=False).encode(),
       {"Content-Type": "text/plain"})
    print(f"{base_url(acc)}/m/{link_id}")


def set_view(link_id, view):
    acc = account()
    path = f"/accounts/{acc}/storage/kv/namespaces/{kv_namespace(acc)}/values/{urllib.parse.quote(link_id)}"
    model = json.loads(cf("GET", path, raw=True))
    model["view"] = json.loads(view)
    cf("PUT", path, json.dumps(model, ensure_ascii=False).encode(), {"Content-Type": "text/plain"})
    print(f"{base_url(acc)}/m/{link_id}", model["view"])


def list_links():
    acc = account()
    ns = kv_namespace(acc)
    base = base_url(acc)
    for k in cf("GET", f"/accounts/{acc}/storage/kv/namespaces/{ns}/keys?limit=1000"):
        raw = cf("GET", f"/accounts/{acc}/storage/kv/namespaces/{ns}/values/{urllib.parse.quote(k['name'])}", raw=True)
        print(f"{base}/m/{k['name']}", json.loads(raw).get("name"))


def remove(link_id):
    acc = account()
    cf("DELETE", f"/accounts/{acc}/storage/kv/namespaces/{kv_namespace(acc)}/values/{urllib.parse.quote(link_id)}")
    print("removed", link_id)


if __name__ == "__main__":
    aps.load_env()
    a = sys.argv[1:]
    if a == ["deploy"]:
        deploy()
    elif len(a) == 3 and a[0] == "add":
        add(a[1], a[2])
    elif len(a) == 3 and a[0] == "view":
        set_view(a[1], a[2])
    elif a == ["list"]:
        list_links()
    elif len(a) == 2 and a[0] == "remove":
        remove(a[1])
    else:
        raise SystemExit(__doc__)
