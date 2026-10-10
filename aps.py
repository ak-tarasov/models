#!/usr/bin/env python3
"""Upload a model to Autodesk Platform Services and translate it for viewing.

Usage:
  aps.py upload <file> [--name <object-name>]   upload + start translation, print urn
  aps.py status <urn>                           translation progress
  aps.py list                                   objects in the bucket
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "https://developer.api.autodesk.com"
ROOT = Path(__file__).resolve().parent
SCOPES = "data:read data:write data:create bucket:read bucket:create viewables:read"


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def call(method, url, token=None, body=None, headers=None, raw=False, timeout=120):
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = body
    if isinstance(body, (dict, list)):
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            return payload if raw else (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {url.split('?')[0]} -> {e.code}: {e.read().decode(errors='replace')[:500]}")


def get_token(scopes=SCOPES):
    cid, sec = os.environ["APS_CLIENT_ID"], os.environ["APS_CLIENT_SECRET"]
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": scopes}).encode()
    r = call("POST", f"{HOST}/authentication/v2/token", body=body,
             headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    return r["access_token"]


def bucket_key():
    # bucket keys are global across all APS apps, so derive one from the client id
    return "njd-models-" + re.sub(r"[^a-z0-9]", "", os.environ["APS_CLIENT_ID"].lower())[:16]


def ensure_bucket(token):
    key = bucket_key()
    req = urllib.request.Request(f"{HOST}/oss/v2/buckets/{key}/details",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise SystemExit(f"bucket details -> {e.code}: {e.read().decode(errors='replace')[:300]}")
        call("POST", f"{HOST}/oss/v2/buckets", token, {"bucketKey": key, "policyKey": "persistent"})
    return key


def urn_of(object_id):
    return base64.urlsafe_b64encode(object_id.encode()).decode().rstrip("=")


def safe_name(name):
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "model"
    return f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}{ext.lower()}"


def upload(path, name=None):
    token = get_token()
    bucket = ensure_bucket(token)
    obj = name or safe_name(os.path.basename(path))
    base = f"{HOST}/oss/v2/buckets/{bucket}/objects/{urllib.parse.quote(obj)}/signeds3upload"
    signed = call("GET", base + "?minutesExpiration=30", token)
    data = Path(path).read_bytes()
    call("PUT", signed["urls"][0], body=data, raw=True, timeout=600,
         headers={"Content-Type": "application/octet-stream"})
    done = call("POST", base, token, {"uploadKey": signed["uploadKey"]})
    urn = urn_of(done["objectId"])
    job = call("POST", f"{HOST}/modelderivative/v2/designdata/job", token,
               {"input": {"urn": urn},
                "output": {"formats": [{"type": "svf", "views": ["2d", "3d"]}]}})
    print(json.dumps({"object": obj, "size": len(data), "urn": urn, "job": job.get("result")},
                     ensure_ascii=False))


def status(urn):
    m = call("GET", f"{HOST}/modelderivative/v2/designdata/{urn}/manifest", get_token())
    views = [c.get("name") for d in m.get("derivatives", []) for c in d.get("children", [])
             if c.get("type") == "geometry"]
    msgs = [x for d in m.get("derivatives", []) for x in d.get("messages", [])]
    print(json.dumps({"status": m.get("status"), "progress": m.get("progress"),
                      "views": views, "messages": msgs[:5]}, ensure_ascii=False))


def list_objects():
    token = get_token()
    r = call("GET", f"{HOST}/oss/v2/buckets/{bucket_key()}/objects?limit=100", token)
    for o in r.get("items", []):
        print(o["objectKey"], o["size"], urn_of(o["objectId"]))


if __name__ == "__main__":
    load_env()
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "upload":
        upload(a[1], a[3] if len(a) > 3 and a[2] == "--name" else None)
    elif len(a) == 2 and a[0] == "status":
        status(a[1])
    elif a == ["list"]:
        list_objects()
    else:
        raise SystemExit(__doc__)
