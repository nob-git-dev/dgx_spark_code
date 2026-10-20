#!/usr/bin/env python3
"""Jev-style decision API on top of Gemma 4 (Ollama on the GX10).

Serves TypeSafe's System One API shape, the same one llama.cpp exposes as
`POST /v1/systemone`: a request carries a `state` and typed `questions`
(choice / score / noul) and the answer is a probability per option, never text.

Gemma 4 is a plain language model, so the trick is: ask it to answer with exactly
one label token (A/B/C..., 0-9, Yes/No), generate a single token with logprobs
enabled, and read the probability of every label from the `top_logprobs` of that
first position. Nothing is fine-tuned; the probabilities are the model's own
next-token distribution, renormalised over the labels.

Environment (every one can also be given as a command line flag):
  JEV_HOST / JEV_PORT     bind address (default 127.0.0.1:9931)
  JEV_BACKEND_URL         Ollama or OpenAI-compatible server (default http://127.0.0.1:11434)
  JEV_MODEL               model name; unset = first installed model whose name contains "gemma4"
  JEV_API_KEY             bearer token for OpenAI-compatible servers (optional)
  JEV_TEMPERATURE         divides the label logprobs before normalising (default 1.0;
                          <1 sharpens, >1 flattens; tune it with bench.py)
  JEV_TOP_LOGPROBS        candidate tokens read at the first position (default 20 = Ollama's maximum)
  JEV_MAX_CTX             upper bound for Ollama's num_ctx (default 65536)
  JEV_TIMEOUT             seconds per backend call (default 300)
  JEV_PARALLEL            questions of one request answered concurrently (default 4)
  JEV_DECIMALS            rounding of the returned probabilities (default 4, like Jev)
  JEV_THINK               "0" (default) asks the backend not to think; "unset" sends nothing
"""
import argparse
import json
import math
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0"
CHOICE_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
SCORE_LABELS = "0123456789"
NOUL_LABELS = ("Yes", "No")
YES_WORDS = {"yes", "y", "true", "はい"}
NO_WORDS = {"no", "n", "false", "いいえ"}
# Characters a model likes to wrap a label in ("**A**", "(B)", "3.", "Yes.").
_LABEL_TRIM = " \t\r\n*_\"'`()[]{}<>.:,;!?-"

SYSTEM_PROMPT = (
    "You are a decision engine, not a chat assistant. You will be shown a STATE and one "
    "QUESTION about it, together with the allowed answer labels. Decide, then output exactly "
    "one label and nothing else: no words, no punctuation, no explanation, no formatting.")


def env(name, default=None):
    return os.environ.get(name, default)


class BadRequest(ValueError):
    """Client error, answered with 400."""


class NotSupported(RuntimeError):
    """Valid request this server cannot serve, answered with 501."""


class BackendError(RuntimeError):
    """The model server failed, answered with 502."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------------------- backend


class Backend:
    """Talks to Ollama's native API, or to any OpenAI-compatible chat server."""

    def __init__(self, url, model=None, api_key=None, timeout=300, top_logprobs=20,
                 max_ctx=65536, think="0"):
        self.url = url.rstrip("/")
        self.requested_model = model or None
        self.api_key = api_key
        self.timeout = timeout
        self.top_logprobs = max(1, int(top_logprobs))
        self.max_ctx = int(max_ctx)
        self.think = think
        self._kind = None
        self._model = None
        self._models_cache = (0.0, [])
        self._no_think = set()  # models that rejected the think flag
        self._lock = threading.Lock()
        # The model server is local; never send it through an HTTP(S) proxy.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # -- plumbing

    def _request(self, path, payload=None, timeout=None):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers=headers)
        try:
            with self._opener.open(req, timeout=timeout or self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode(errors="replace")
            raise BackendError(f"{path}: HTTP {e.code} {body}", status=e.code)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise BackendError(f"{self.url}{path}: {e}")

    def kind(self):
        """'ollama' when the server speaks Ollama's native API, else 'openai'."""
        if self._kind is None:
            try:
                self._request("/api/version", timeout=5)
                self._kind = "ollama"
            except BackendError as e:
                if e.status is None:
                    raise  # unreachable: do not cache a guess
                self._kind = "openai"
        return self._kind

    def models(self):
        with self._lock:
            ts, cached = self._models_cache
            if time.time() - ts < 60:
                return cached
        if self.kind() == "ollama":
            names = [m["name"] for m in self._request("/api/tags", timeout=10).get("models", [])]
        else:
            names = [m["id"] for m in self._request("/v1/models", timeout=10).get("data", [])]
        with self._lock:
            self._models_cache = (time.time(), names)
        return names

    def default_model(self):
        if self.requested_model:
            return self.requested_model
        if self._model is None:
            names = self.models()
            if not names:
                raise BackendError("the backend has no models; pull one first (e.g. ollama pull gemma4:26b)")
            self._model = next((m for m in names if "gemma4" in m.lower() or "gemma-4" in m.lower()),
                               names[0])
        return self._model

    def resolve_model(self, requested):
        """Honour `model` only when it is installed; Jev clients send names like jev-latest."""
        default = self.default_model()
        if not requested or requested == default:
            return default
        try:
            if requested in self.models():
                return requested
        except BackendError:
            pass
        return default

    # -- the one call that matters

    def first_token(self, user, model, images=()):
        """Distribution of the first generated token.

        Returns dict(candidates=[(token, logprob), ...], prompt_tokens, seconds, prefill_tps).
        `images` are parse_image() triples; they go to the model when it is multimodal.
        """
        t0 = time.time()
        if self.kind() == "ollama":
            r = self._ollama_chat(user, model, images)
            entries = r.get("logprobs") or []
            if not entries:
                raise BackendError("the backend returned no logprobs (Ollama >= 0.12.11 is needed, "
                                   "and the model must emit at least one token)")
            first = entries[0]
            cands = [(c["token"], float(c["logprob"])) for c in first.get("top_logprobs") or []]
            if first.get("token") is not None and all(first["token"] != t for t, _ in cands):
                cands.append((first["token"], float(first["logprob"])))
            pt = r.get("prompt_eval_count", 0)
            pd = r.get("prompt_eval_duration", 0) / 1e9
            tps = pt / pd if pd else None
        else:
            r = self._openai_chat(user, model, images)
            choice = r["choices"][0]
            content = (choice.get("logprobs") or {}).get("content") or []
            if not content:
                raise BackendError("the backend returned no logprobs; it must support "
                                   "`logprobs`/`top_logprobs` on /v1/chat/completions")
            first = content[0]
            cands = [(c["token"], float(c["logprob"])) for c in first.get("top_logprobs") or []]
            if first.get("token") is not None and all(first["token"] != t for t, _ in cands):
                cands.append((first["token"], float(first["logprob"])))
            pt = r.get("usage", {}).get("prompt_tokens", 0)
            tps = None
        return {"candidates": cands, "prompt_tokens": pt,
                "seconds": round(time.time() - t0, 3),
                "prefill_tps": round(tps, 1) if tps else None}

    def _ollama_chat(self, user, model, images):
        msg = {"role": "user", "content": user}
        if images:
            msg["images"] = [b64 for _, b64, _ in images]
        est = (len(SYSTEM_PROMPT) + len(user)) // 3 + 1 + 1024 * len(images)
        num_ctx = min(self.max_ctx, max(4096, 1 << (est + 64).bit_length()))
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, msg],
            "stream": False,
            "logprobs": True,
            "top_logprobs": min(self.top_logprobs, 20),  # Ollama rejects > 20
            # We only read the distribution, so disable every sampler filter: the
            # probabilities must be the model's own softmax, not a truncated one.
            "options": {"num_predict": 1, "temperature": 1.0, "top_k": 0, "top_p": 1.0,
                        "min_p": 0.0, "num_ctx": num_ctx},
        }
        if self.think == "0" and model not in self._no_think:
            payload["think"] = False
        try:
            return self._request("/api/chat", payload)
        except BackendError as e:
            if "think" in payload and e.status == 400 and "think" in str(e).lower():
                self._no_think.add(model)  # e.g. "model does not support thinking"
                del payload["think"]
                return self._request("/api/chat", payload)
            raise

    def _openai_chat(self, user, model, images):
        if images:
            content = [{"type": "text", "text": user}]
            content += [{"type": "image_url", "image_url": {"url": url}} for _, _, url in images]
        else:
            content = user
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": content}],
            "max_tokens": 1, "temperature": 1.0, "top_p": 1.0,
            "logprobs": True, "top_logprobs": self.top_logprobs,
        }
        if self.think == "0" and model not in self._no_think:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            return self._request("/v1/chat/completions", payload)
        except BackendError as e:
            if "chat_template_kwargs" in payload and e.status == 400:
                self._no_think.add(model)
                del payload["chat_template_kwargs"]
                return self._request("/v1/chat/completions", payload)
            raise


_DATA_URL = re.compile(r"^data:(?P<mime>[\w.+/-]+)(;[\w=.-]+)*;base64,(?P<data>[A-Za-z0-9+/=\s]+)$")
_IMAGE_MAGIC = (("iVBORw0KGgo", "image/png"), ("/9j/", "image/jpeg"), ("UklGR", "image/webp"),
                ("R0lGOD", "image/gif"))


def parse_image(value):
    """Accepts a data URL (llama.cpp style) or raw base64 (Ollama style).

    Returns (mime, base64 payload, data URL) or raises BadRequest / NotSupported.
    """
    if not isinstance(value, str) or not value.strip():
        raise BadRequest("files/images must be data URLs (data:image/jpeg;base64,...) "
                         "or base64-encoded image files")
    value = value.strip()
    m = _DATA_URL.match(value)
    if m:
        mime, data = m.group("mime").lower(), re.sub(r"\s+", "", m.group("data"))
        if not mime.startswith("image/"):
            raise NotSupported(f"only image input is supported, not {mime}")
        return mime, data, f"data:{mime};base64,{data}"
    data = re.sub(r"\s+", "", value)
    if value.startswith("data:") or not re.fullmatch(r"[A-Za-z0-9+/]+=*", data):
        raise BadRequest("files/images must be data URLs (data:image/jpeg;base64,...) "
                         "or base64-encoded image files")
    mime = next((mt for magic, mt in _IMAGE_MAGIC if data.startswith(magic)), None)
    if mime is None:
        raise NotSupported("only PNG, JPEG, WebP or GIF images are supported")
    return mime, data, f"data:{mime};base64,{data}"


# ----------------------------------------------------------------------------- questions


def as_text(value):
    """`state` and `instructions` may be any JSON; non-strings are shown as JSON text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=1)


def parse_question(qid, q):
    """Validate one question and return (type, instructions, options).

    options is a list of (name, description) in label order; description may be None.
    """
    if not isinstance(q, dict):
        raise BadRequest(f"question '{qid}' must be an object")
    qtype = q.get("type")
    if qtype not in ("choice", "score", "noul"):
        raise BadRequest(f"question '{qid}': type must be choice, score or noul")
    instructions = q.get("instructions")
    if instructions is None or instructions == "":
        raise BadRequest(f"question '{qid}': instructions are required")
    criteria = q.get("criteria")
    if qtype == "choice":
        if isinstance(criteria, list):  # convenience: ["a", "b"] == {"a": null, "b": null}
            criteria = {str(o): None for o in criteria}
        if not isinstance(criteria, dict) or len(criteria) < 2:
            raise BadRequest(f"question '{qid}': choice criteria must be an object that maps "
                             "at least 2 options to their descriptions (or null)")
        if len(criteria) > len(CHOICE_LABELS):
            raise BadRequest(f"question '{qid}': at most {len(CHOICE_LABELS)} options")
        options = [(str(k), None if v is None else as_text(v)) for k, v in criteria.items()]
    elif qtype == "score":
        if not isinstance(criteria, list) or not 2 <= len(criteria) <= len(SCORE_LABELS):
            raise BadRequest(f"question '{qid}': score criteria must be an array of 2 to "
                             f"{len(SCORE_LABELS)} level descriptions, lowest level first")
        options = [(str(i), as_text(d)) for i, d in enumerate(criteria)]
    else:
        if criteria is not None and not isinstance(criteria, dict):
            raise BadRequest(f"question '{qid}': noul criteria must be an object with "
                             "'true' and 'false' descriptions")
        criteria = criteria or {}
        options = [("Yes", as_text(criteria.get("true")) or None),
                   ("No", as_text(criteria.get("false")) or None)]
    return qtype, instructions, options


def build_prompt(qtype, instructions, options, state_text, n_images=0):
    lines = []
    if n_images:
        lines.append(f"The {n_images} image(s) above are part of the STATE.")
    lines += ["STATE:", "<<<", state_text if state_text.strip() else "(empty)", ">>>", "",
              "QUESTION: " + as_text(instructions).strip(), ""]
    if qtype == "choice":
        lines.append("OPTIONS:")
        for label, (name, desc) in zip(CHOICE_LABELS, options):
            lines.append(f"{label}: {name}" + (f" — {desc}" if desc else ""))
        lines += ["", "Reply with only the letter of the best option."]
    elif qtype == "score":
        lines.append(f"LEVELS, from lowest (0) to highest ({len(options) - 1}):")
        for label, (_, desc) in zip(SCORE_LABELS, options):
            lines.append(f"{label}: {desc}")
        lines += ["", "Reply with only the digit of the level that fits best."]
    else:
        for name, desc in options:
            if desc:
                lines.append(f"{name} means: {desc}")
        lines += ["", "Reply with only Yes or No."]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- probabilities


def norm_token(token):
    return unicodedata.normalize("NFKC", token).strip(_LABEL_TRIM)


def choice_matcher(n):
    def match(token):
        t = norm_token(token)
        if len(t) != 1:
            return None
        if n <= 26:  # only upper-case labels in use: "a" is the same answer as "A"
            t = t.upper()
        i = CHOICE_LABELS.find(t)
        return t if 0 <= i < n else None
    return match


def score_matcher(n):
    def match(token):
        t = norm_token(token)
        return t if len(t) == 1 and t.isdigit() and int(t) < n else None
    return match


def noul_matcher(token):
    t = norm_token(token).lower()
    if t in YES_WORDS:
        return "Yes"
    if t in NO_WORDS:
        return "No"
    return None


def _logaddexp(a, b):
    m = max(a, b)
    return m + math.log(math.exp(a - m) + math.exp(b - m))


def label_distribution(candidates, labels, match, temperature=1.0):
    """Turn first-token candidates [(token, logprob)] into a distribution over labels.

    Token variants of the same label ("A", " a", "**A") are merged. Labels missing from
    the top-k get a floor: no more than the smallest listed candidate, and no more than
    their share of the probability mass the top-k did not cover. Returns (probs, meta).
    """
    merged, listed = {}, 0.0
    for tok, lp in candidates:
        listed += math.exp(lp)
        lab = match(tok)
        if lab is not None:
            merged[lab] = lp if lab not in merged else _logaddexp(merged[lab], lp)
    if not merged:
        top = ", ".join(f"{t!r}={math.exp(lp):.3f}" for t, lp in candidates[:8])
        raise BackendError("the model did not start its answer with a label; "
                           f"first-token candidates: {top}")
    coverage = sum(math.exp(v) for v in merged.values())
    missing = [l for l in labels if l not in merged]
    if missing:
        residual = max(0.0, 1.0 - listed)
        p_min = math.exp(min(lp for _, lp in candidates))
        floor = min(p_min, residual / len(missing)) if residual > 0 else p_min / 10.0
        for l in missing:
            merged[l] = math.log(max(floor, 1e-9))
    t = max(float(temperature), 1e-3)
    scaled = [merged[l] / t for l in labels]
    m = max(scaled)
    z = sum(math.exp(v - m) for v in scaled)
    probs = [math.exp(v - m) / z for v in scaled]
    return probs, {"coverage": round(coverage, 4), "listed_mass": round(min(listed, 1.0), 4),
                   "missing": missing}


def choice_confidence(probs):
    """0 when every option is equally likely, 1 when one option takes all the mass."""
    n = len(probs)
    return (max(probs) - 1.0 / n) / (1.0 - 1.0 / n) if n > 1 else 1.0


def score_confidence(probs):
    """1 minus the expected distance from the most likely level, in units of the spread a
    uniform distribution would have (same formula as Ollama's System One answers)."""
    n = len(probs)
    mode = max(range(n), key=probs.__getitem__)
    distance = sum(p * abs(i - mode) for i, p in enumerate(probs))
    midpoint = (n - 1) / 2.0
    baseline = sum(abs(i - midpoint) for i in range(n)) / n
    return min(1.0, max(0.0, 1.0 - distance / baseline)) if baseline else 1.0


# ----------------------------------------------------------------------------- decider


class Decider:
    def __init__(self, backend, temperature=1.0, decimals=4, parallel=4, log=None):
        self.backend = backend
        self.temperature = float(temperature)
        self.decimals = int(decimals)
        self.pool = ThreadPoolExecutor(max_workers=max(1, int(parallel)))
        self.log = log or (lambda msg: None)

    def _round(self, x):
        return round(x, self.decimals)

    def answer_request(self, body):
        if not isinstance(body, dict):
            raise BadRequest("the request body must be a JSON object")
        questions = body.get("questions")
        if not isinstance(questions, dict) or not questions:
            raise BadRequest("'questions' must be a non-empty object that maps ids to questions")
        parsed = {qid: parse_question(qid, q) for qid, q in questions.items()}
        images = body.get("files")
        if images is None:
            images = body.get("images")
        images = images or []
        if not isinstance(images, list):
            raise BadRequest("files/images must be an array of data URLs or base64 image files")
        images = [parse_image(u) for u in images]  # bad input is a 400 now, not a 502 mid-way
        state_text = as_text(body.get("state"))
        model = self.backend.resolve_model(body.get("model"))
        debug = bool(body.get("debug"))

        def run(item):
            qid, (qtype, instructions, options) = item
            return qid, self.answer_question(qid, qtype, instructions, options, state_text,
                                             images, model, debug)

        answers, input_tokens = {}, 0
        for qid, (answer, meta) in self.pool.map(run, parsed.items()):
            answers[qid] = answer
            input_tokens += meta["prompt_tokens"]
        return {"model": model, "answers": answers,
                "usage": {"input_tokens": input_tokens, "output_tokens": 0}}

    def answer_question(self, qid, qtype, instructions, options, state_text, images, model,
                        debug=False):
        prompt = build_prompt(qtype, instructions, options, state_text, len(images))
        r = self.backend.first_token(prompt, model, images)
        n = len(options)
        if qtype == "choice":
            labels, match = list(CHOICE_LABELS[:n]), choice_matcher(n)
        elif qtype == "score":
            labels, match = list(SCORE_LABELS[:n]), score_matcher(n)
        else:
            labels, match = list(NOUL_LABELS), noul_matcher
        probs, meta = label_distribution(r["candidates"], labels, match, self.temperature)
        names = [name for name, _ in options]

        if qtype == "choice":
            best = max(range(n), key=probs.__getitem__)
            answer = {"type": "choice", "choice": names[best],
                      "probabilities": {name: self._round(p) for name, p in zip(names, probs)},
                      "confidence": self._round(choice_confidence(probs))}
        elif qtype == "score":
            answer = {"type": "score",
                      "score": self._round(sum(i * p for i, p in enumerate(probs))),
                      "legend": {str(i): desc for i, (_, desc) in enumerate(options)},
                      "probabilities": {str(i): self._round(p) for i, p in enumerate(probs)},
                      "confidence": self._round(score_confidence(probs))}
        else:
            answer = {"type": "noul", "noul": self._round(probs[0])}

        if debug:
            answer["debug"] = {
                "model": model, "prompt_tokens": r["prompt_tokens"], "seconds": r["seconds"],
                "prefill_tps": r["prefill_tps"], "coverage": meta["coverage"],
                "listed_mass": meta["listed_mass"], "missing_labels": meta["missing"],
                "labels": dict(zip(labels, names)),
                "top_tokens": [[t, round(math.exp(lp), 5)] for t, lp in r["candidates"]],
            }
        self.log(f"{qid} {qtype} n={n} coverage={meta['coverage']:.2f} "
                 f"in={r['prompt_tokens']}tok {r['seconds']}s {model}")
        return answer, {"prompt_tokens": r["prompt_tokens"]}


# ----------------------------------------------------------------------------- http


class Handler(BaseHTTPRequestHandler):
    decider = None  # set by make_server
    server_version = "gemma-jev/" + VERSION
    sys_version = ""

    def log_message(self, fmt, *args):  # one line per question is logged by the decider
        pass

    def _send(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, kind, message):
        self._send(status, {"error": {"code": status, "type": kind, "message": message}})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        backend = self.decider.backend
        if path in ("/", "/health"):
            info = {"status": "ok", "service": "gemma-jev", "version": VERSION,
                    "backend": backend.url}
            try:
                info["backend_kind"] = backend.kind()
                info["model"] = backend.default_model()
                info["models"] = backend.models()
            except BackendError as e:
                info["status"] = "backend unreachable"
                info["error"] = str(e)
                return self._send(503, info)
            return self._send(200, info)
        if path in ("/v1/models", "/models"):
            try:
                model = backend.default_model()
            except BackendError as e:
                return self._error(503, "backend_error", str(e))
            return self._send(200, {"object": "list", "data": [{
                "id": model, "object": "model", "owned_by": "gemma-jev",
                # Same shape as llama.cpp: clients switch to /v1/systemone on "decisions".
                "architecture": {"input_modalities": ["text", "image"],
                                 "output_modalities": ["text", "decisions"]}}]})
        self._error(404, "not_found", f"no route for GET {path}")

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in ("/v1/systemone", "/systemone"):
            return self._error(404, "not_found", f"no route for POST {path}; use /v1/systemone")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"null")
        except ValueError:
            return self._error(400, "invalid_request_error", "the body is not valid JSON")
        try:
            self._send(200, self.decider.answer_request(body))
        except BadRequest as e:
            self._error(400, "invalid_request_error", str(e))
        except NotSupported as e:
            self._error(501, "not_supported", str(e))
        except BackendError as e:
            self._error(502, "backend_error", str(e))
        except Exception as e:  # keep serving; report instead of dying
            self._error(500, "server_error", f"{type(e).__name__}: {e}")


def make_server(host, port, decider):
    handler = type("BoundHandler", (Handler,), {"decider": decider})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Jev-style /v1/systemone decision API on a local Gemma 4")
    ap.add_argument("--host", default=env("JEV_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(env("JEV_PORT", "9931")))
    ap.add_argument("--backend", default=env("JEV_BACKEND_URL", "http://127.0.0.1:11434"),
                    help="Ollama or OpenAI-compatible server")
    ap.add_argument("--model", default=env("JEV_MODEL"), help="default: first installed gemma4*")
    ap.add_argument("--temperature", type=float, default=float(env("JEV_TEMPERATURE", "1.0")))
    ap.add_argument("--top-logprobs", type=int, default=int(env("JEV_TOP_LOGPROBS", "20")))
    ap.add_argument("--max-ctx", type=int, default=int(env("JEV_MAX_CTX", "65536")))
    ap.add_argument("--timeout", type=float, default=float(env("JEV_TIMEOUT", "300")))
    ap.add_argument("--parallel", type=int, default=int(env("JEV_PARALLEL", "4")))
    ap.add_argument("--decimals", type=int, default=int(env("JEV_DECIMALS", "4")))
    ap.add_argument("--think", default=env("JEV_THINK", "0"), help='"0" or "unset"')
    ap.add_argument("--check", action="store_true", help="probe the backend and exit")
    args = ap.parse_args(argv)

    def log(msg):
        sys.stderr.write(time.strftime("%H:%M:%S ") + msg + "\n")
        sys.stderr.flush()

    backend = Backend(args.backend, model=args.model, api_key=env("JEV_API_KEY"),
                      timeout=args.timeout, top_logprobs=args.top_logprobs,
                      max_ctx=args.max_ctx, think=args.think)
    decider = Decider(backend, temperature=args.temperature, decimals=args.decimals,
                      parallel=args.parallel, log=log)
    try:
        log(f"backend {backend.url} ({backend.kind()}), model {backend.default_model()}")
    except BackendError as e:
        log(f"backend not reachable yet: {e}")
        if args.check:
            return 1
    if args.check:
        return 0
    server = make_server(args.host, args.port, decider)
    log(f"gemma-jev {VERSION} listening on http://{args.host}:{args.port}/v1/systemone")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
