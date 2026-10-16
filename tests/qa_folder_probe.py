"""Standalone QA probe for InfoHub/AnythingLLM folder-structure behaviour.

Checks, against a real instance, whether:
  (a) a flat upload lands in the workspace folder, and
  (b) a nested name ("Sub/probe.txt") is accepted or rejected.

Usage:
    python -m tests.qa_folder_probe --base URL --key KEY --slug SLUG

With no --key, or an unreachable server, it prints SKIPPED and exits 0.
Note: if the server has no delete endpoint the probe file remains; see output.
"""

import argparse
import json

import requests

PROBE_FLAT = "Sub__probe.txt"
PROBE_NESTED = "Sub/probe.txt"
PROBE_CONTENT = b"infohub folder probe\n"
TIMEOUT = 60


def _excerpt(text, limit=400):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


def _folder_items(payload, slug):
    folders = (payload.get("localFiles") or {}).get("items") or []
    for folder in folders:
        if isinstance(folder, dict) and folder.get("name") == slug:
            return folder.get("items") or []
    return []


def _headers(key):
    return {"Authorization": f"Bearer {key}", "accept": "application/json"}


def _upload(session, base, slug, key, name):
    url = f"{base}/api/v1/document/upload/{slug}"
    return session.post(
        url, headers=_headers(key), files={"file": (name, PROBE_CONTENT)}, timeout=TIMEOUT
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Probe InfoHub folder/flat/nested upload behaviour."
    )
    parser.add_argument("--base", default="", help="InfoHub base URL")
    parser.add_argument("--key", default="", help="InfoHub API key")
    parser.add_argument("--slug", default="", help="Workspace slug")
    args = parser.parse_args(argv)

    if not args.key.strip():
        print("SKIPPED: no --key provided")
        return 0

    session = requests.Session()
    try:
        session.get(
            f"{args.base}/api/v1/documents", headers=_headers(args.key), timeout=10
        )
    except requests.RequestException as exc:
        print(f"SKIPPED: server unreachable ({exc.__class__.__name__})")
        return 0

    print("InfoHub folder-structure probe")
    print(f"  base={args.base}  slug={args.slug}")

    # (a) flat upload
    flat = _upload(session, args.base, args.slug, args.key, PROBE_FLAT)
    print(f"(a) upload {PROBE_FLAT}: HTTP {flat.status_code} :: {_excerpt(flat.text)}")

    # (b) verify flat name appears under the slug folder in the documents listing
    flat_ok = False
    payload_excerpt = "<no response>"
    try:
        docs = session.get(
            f"{args.base}/api/v1/documents", headers=_headers(args.key), timeout=10
        )
        payload_excerpt = _excerpt(docs.text)
        data = docs.json()
        flat_ok = any(
            isinstance(item, dict) and item.get("name") == PROBE_FLAT
            for item in _folder_items(data, args.slug)
        )
    except (requests.RequestException, ValueError) as exc:
        payload_excerpt = f"<error: {exc.__class__.__name__}>"
    print(f"(b) flat_ok={flat_ok}  payload_excerpt={payload_excerpt}")

    # (c) nested name: server accepts (200/201) or rejects
    try:
        nested = _upload(session, args.base, args.slug, args.key, PROBE_NESTED)
        nested_rejected = nested.status_code not in (200, 201)
        nested_detail = f"HTTP {nested.status_code} :: {_excerpt(nested.text)}"
    except requests.RequestException as exc:
        nested_rejected = True
        nested_detail = f"<error: {exc.__class__.__name__}>"
    print(f"(c) nested_rejected={nested_rejected}  {nested_detail}")

    print("SUMMARY")
    print(f"  uploaded={PROBE_FLAT} accepted={flat.status_code in (200, 201)}")
    print(f"  flat_ok={flat_ok}")
    print(f"  nested_rejected={nested_rejected}")
    print(
        f"  RESIDUAL: {PROBE_FLAT} remains in workspace '{args.slug}' "
        "(no delete endpoint assumed) - remove manually if needed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
