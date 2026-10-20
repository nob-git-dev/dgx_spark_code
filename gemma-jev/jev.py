#!/usr/bin/env python3
"""Command line client for gemma-jev (or any other /v1/systemone server).

  jev.py choice STATE "Which team should handle this?" billing shipping technical
  jev.py choice @ticket.txt "Which team?" "billing=Payments and refunds" "shipping=Delivery"
  jev.py score  STATE "How urgent is this?" "can wait" "this week" today "right now"
  jev.py noul   STATE "Is the customer angry?"
  jev.py ask    request.json          # a raw System One request (- for stdin)
  jev.py check                        # GET /health

STATE is text, @path (the file's contents) or - (stdin). --image PATH attaches an image.
--url defaults to $JEV_URL or http://127.0.0.1:9931. --debug adds first-token diagnostics.
Stdlib only.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:9931"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # local server, no proxy


def http(url, body=None, timeout=600):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": {"code": e.code, "message": raw[:500]}}


def read_state(arg):
    if arg == "-":
        return sys.stdin.read()
    if arg.startswith("@"):
        with open(os.path.expanduser(arg[1:]), encoding="utf-8", errors="replace") as f:
            return f.read()
    return arg


def image_data_url(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(os.path.expanduser(path), "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def build_request(args):
    if args.command == "ask":
        src = sys.stdin if args.file == "-" else open(os.path.expanduser(args.file), encoding="utf-8")
        with src:
            return json.load(src)
    if args.command == "choice":
        criteria = {}
        for opt in args.options:
            name, _, desc = opt.partition("=")
            criteria[name] = desc or None
        q = {"type": "choice", "instructions": args.question, "criteria": criteria}
    elif args.command == "score":
        q = {"type": "score", "instructions": args.question, "criteria": args.levels}
    else:
        q = {"type": "noul", "instructions": args.question}
    body = {"state": read_state(args.state), "questions": {"q": q}}
    if args.image:
        body["files"] = [image_data_url(p) for p in args.image]
    if args.model:
        body["model"] = args.model
    return body


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("JEV_URL", DEFAULT_URL))
    ap.add_argument("--debug", action="store_true", help="include first-token diagnostics")
    ap.add_argument("--model", help="model name to send (ignored by the server if not installed)")
    ap.add_argument("--image", action="append", metavar="PATH", help="attach an image (repeatable)")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("choice", help="probability of each option")
    p.add_argument("state"); p.add_argument("question"); p.add_argument("options", nargs="+", metavar="OPTION[=DESC]")
    p = sub.add_parser("score", help="distribution over ordered levels")
    p.add_argument("state"); p.add_argument("question"); p.add_argument("levels", nargs="+", metavar="LEVEL")
    p = sub.add_parser("noul", help="probability that the answer is yes")
    p.add_argument("state"); p.add_argument("question")
    p = sub.add_parser("ask", help="send a raw System One request")
    p.add_argument("file", help="JSON file, or - for stdin")
    sub.add_parser("check", help="server and backend health")
    args = ap.parse_args(argv)

    if args.command == "check":
        status, data = http(args.url.rstrip("/") + "/health")
    else:
        body = build_request(args)
        if args.debug:
            body["debug"] = True
        status, data = http(args.url.rstrip("/") + "/v1/systemone", body)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
