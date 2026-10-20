"""Tests for gemma-jev against a fake Ollama / fake OpenAI-compatible server.

    python3 -m unittest discover -s tests -v
"""
import json
import math
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as jev  # noqa: E402

ln = math.log
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def default_script(payload):
    """First-token candidates chosen from what the prompt asks for."""
    user = payload["messages"][-1]["content"]
    if isinstance(user, list):  # OpenAI content parts
        user = " ".join(p.get("text", "") for p in user)
    if "OPTIONS:" in user:
        return [("A", ln(0.6)), (" a", ln(0.2)), ("B", ln(0.1)), ("**", ln(0.05)), ("C", ln(0.03))]
    if "LEVELS" in user:  # the llama.cpp README example distribution
        return [("2", ln(0.6753)), ("3", ln(0.2064)), ("1", ln(0.116)), ("0", ln(0.0023))]
    return [("Yes", ln(0.6)), ("No", ln(0.3)), ("yes.", ln(0.05)), ("Maybe", ln(0.05))]


class FakeBackend:
    """Fake Ollama (kind='ollama') or fake OpenAI-compatible server (kind='openai')."""

    def __init__(self, kind="ollama"):
        self.kind = kind
        self.requests = []
        self.script = default_script
        self.reject_think = False
        self.models = ["gemma4:26b", "deepseek-r1:70b"]
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version" and fake.kind == "ollama":
                    return self._send(200, {"version": "0.20.0"})
                if self.path == "/api/tags" and fake.kind == "ollama":
                    return self._send(200, {"models": [{"name": m} for m in fake.models]})
                if self.path == "/v1/models" and fake.kind == "openai":
                    return self._send(200, {"data": [{"id": m} for m in fake.models]})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(payload)
                if fake.kind == "ollama" and self.path == "/api/chat":
                    if fake.reject_think and "think" in payload:
                        return self._send(400, {"error": f"{payload['model']} does not support thinking"})
                    c = fake.script(payload)
                    return self._send(200, {
                        "model": payload["model"], "done": True, "done_reason": "length",
                        "message": {"role": "assistant", "content": c[0][0]},
                        "prompt_eval_count": 123, "prompt_eval_duration": 100_000_000, "eval_count": 1,
                        "logprobs": [{"token": c[0][0], "logprob": c[0][1],
                                      "top_logprobs": [{"token": t, "logprob": lp} for t, lp in c]}]})
                if fake.kind == "openai" and self.path == "/v1/chat/completions":
                    if fake.reject_think and "chat_template_kwargs" in payload:
                        return self._send(400, {"error": {"message": "unknown field chat_template_kwargs"}})
                    c = fake.script(payload)
                    return self._send(200, {
                        "model": payload["model"], "usage": {"prompt_tokens": 77, "completion_tokens": 1},
                        "choices": [{"index": 0, "finish_reason": "length",
                                     "message": {"role": "assistant", "content": c[0][0]},
                                     "logprobs": {"content": [{"token": c[0][0], "logprob": c[0][1],
                                                               "top_logprobs": [{"token": t, "logprob": lp} for t, lp in c]}]}}]})
                self._send(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def start_jev(backend_url, **kw):
    backend = jev.Backend(backend_url, timeout=10, **kw)
    decider = jev.Decider(backend, parallel=2)
    httpd = jev.make_server("127.0.0.1", 0, decider)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def call(url, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


STATE = "Customer message: I was charged twice for my order last week and nobody has replied."
ROUTE = {"type": "choice", "instructions": "Which team should handle this?",
         "criteria": {"billing": None, "shipping": None, "technical": None}}
URGENCY = {"type": "score", "instructions": "How urgent is this?",
           "criteria": ["can wait", "this week", "today", "right now"]}
ANGRY = {"type": "noul", "instructions": "Is the customer angry?"}


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeBackend()
        cls.httpd, cls.url = start_jev(cls.fake.url)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.fake.close()

    def setUp(self):
        self.fake.requests.clear()
        self.fake.script = default_script
        self.fake.reject_think = False

    def ask(self, body):
        return call(self.url, "/v1/systemone", body)

    def test_choice_merges_token_variants_and_normalises(self):
        status, r = self.ask({"state": STATE, "questions": {"route": ROUTE}})
        self.assertEqual(status, 200)
        a = r["answers"]["route"]
        # A = 0.6 + 0.2 (" a" is the same label), B = 0.1, C = 0.03, renormalised over the labels
        self.assertEqual(a["type"], "choice")
        self.assertEqual(a["choice"], "billing")
        self.assertEqual(a["probabilities"], {"billing": 0.8602, "shipping": 0.1075, "technical": 0.0323})
        self.assertAlmostEqual(sum(a["probabilities"].values()), 1.0, places=3)
        self.assertEqual(a["confidence"], round((0.8 / 0.93 - 1 / 3) / (1 - 1 / 3), 4))
        self.assertEqual(r["usage"], {"input_tokens": 123, "output_tokens": 0})
        self.assertEqual(r["model"], "gemma4:26b")
        self.assertNotIn("debug", a)

    def test_choice_options_missing_from_top_k_get_a_floor(self):
        q = dict(ROUTE, criteria={"a": None, "b": None, "c": None, "d": None, "e": None})
        status, r = self.ask({"state": STATE, "questions": {"q": q}, "debug": True})
        self.assertEqual(status, 200)
        a = r["answers"]["q"]
        # listed mass 0.98 -> residual 0.02 shared by d and e (0.01 each, below the 0.03 minimum)
        total = 0.8 + 0.1 + 0.03 + 0.01 + 0.01
        self.assertEqual(a["probabilities"]["d"], round(0.01 / total, 4))
        self.assertEqual(a["probabilities"]["a"], round(0.8 / total, 4))
        self.assertEqual(a["debug"]["missing_labels"], ["D", "E"])
        self.assertEqual(a["debug"]["labels"]["A"], "a")
        self.assertEqual(a["debug"]["coverage"], 0.93)
        self.assertEqual(a["debug"]["prompt_tokens"], 123)
        self.assertEqual(a["debug"]["prefill_tps"], 1230.0)

    def test_score_matches_the_systemone_reference_example(self):
        status, r = self.ask({"state": STATE, "questions": {"urgency": URGENCY}})
        self.assertEqual(status, 200)
        a = r["answers"]["urgency"]
        self.assertEqual(a["type"], "score")
        self.assertEqual(a["legend"], {"0": "can wait", "1": "this week", "2": "today", "3": "right now"})
        self.assertEqual(a["probabilities"], {"0": 0.0023, "1": 0.116, "2": 0.6753, "3": 0.2064})
        self.assertEqual(a["score"], 2.0858)
        self.assertEqual(a["confidence"], 0.673)

    def test_noul(self):
        status, r = self.ask({"state": STATE, "questions": {"angry": ANGRY}})
        self.assertEqual(status, 200)
        a = r["answers"]["angry"]
        self.assertEqual(a, {"type": "noul", "noul": round(0.65 / 0.95, 4)})  # "yes." counts as Yes

    def test_three_questions_in_one_request(self):
        status, r = self.ask({"state": STATE, "questions": {"route": ROUTE, "angry": ANGRY, "urgency": URGENCY}})
        self.assertEqual(status, 200)
        self.assertEqual(list(r["answers"]), ["route", "angry", "urgency"])
        self.assertEqual(r["usage"]["input_tokens"], 3 * 123)
        self.assertEqual(len(self.fake.requests), 3)

    def test_backend_payload(self):
        self.ask({"state": {"ticket": 42, "text": "hello"}, "questions": {"route": ROUTE}})
        p = self.fake.requests[-1]
        self.assertEqual(p["model"], "gemma4:26b")
        self.assertIs(p["stream"], False)
        self.assertIs(p["logprobs"], True)
        self.assertEqual(p["top_logprobs"], 20)
        self.assertIs(p["think"], False)
        self.assertEqual(p["options"]["num_predict"], 1)
        self.assertEqual(p["options"]["top_k"], 0)
        self.assertEqual(p["options"]["temperature"], 1.0)
        self.assertGreaterEqual(p["options"]["num_ctx"], 4096)
        self.assertEqual(p["messages"][0], {"role": "system", "content": jev.SYSTEM_PROMPT})
        user = p["messages"][1]["content"]
        self.assertIn('"ticket": 42', user)  # non-string state is shown as JSON
        self.assertIn("QUESTION: Which team should handle this?", user)
        self.assertIn("A: billing\nB: shipping\nC: technical", user)
        self.assertTrue(user.endswith("Reply with only the letter of the best option."))

    def test_think_flag_is_dropped_when_the_model_rejects_it(self):
        self.fake.reject_think = True
        status, _ = self.ask({"state": STATE, "questions": {"route": ROUTE}})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.fake.requests), 2)  # rejected once, retried without think
        self.assertNotIn("think", self.fake.requests[-1])
        self.ask({"state": STATE, "questions": {"route": ROUTE}})
        self.assertEqual(len(self.fake.requests), 3)  # remembered: no second rejection
        self.assertNotIn("think", self.fake.requests[-1])
        self.fake.reject_think = False
        jev_backend = self.httpd.RequestHandlerClass.decider.backend
        jev_backend._no_think.clear()

    def test_no_label_token_is_a_502(self):
        self.fake.script = lambda payload: [("Hello", ln(0.9)), ("Hi", ln(0.1))]
        status, r = self.ask({"state": STATE, "questions": {"route": ROUTE}})
        self.assertEqual(status, 502)
        self.assertIn("did not start its answer with a label", r["error"]["message"])
        self.assertIn("'Hello'", r["error"]["message"])

    def test_validation_errors(self):
        bad = [
            ({"state": STATE}, "questions"),
            ({"state": STATE, "questions": {}}, "questions"),
            ({"state": STATE, "questions": {"q": {"type": "rank", "instructions": "x"}}}, "type"),
            ({"state": STATE, "questions": {"q": {"type": "choice", "criteria": {"a": None, "b": None}}}}, "instructions"),
            ({"state": STATE, "questions": {"q": {"type": "choice", "instructions": "x", "criteria": {"only": None}}}}, "at least 2"),
            ({"state": STATE, "questions": {"q": {"type": "score", "instructions": "x", "criteria": list("abcdefghijk")}}}, "2 to 10"),
            ({"state": STATE, "questions": {"q": {"type": "noul", "instructions": "x", "criteria": ["yes"]}}}, "noul criteria"),
            ({"state": STATE, "questions": {"q": ANGRY}, "files": ["http://example.com/a.png"]}, "data URL"),
            ([1, 2], "JSON object"),
        ]
        for body, needle in bad:
            status, r = self.ask(body)
            self.assertEqual(status, 400, body)
            self.assertIn(needle, r["error"]["message"])
            self.assertEqual(r["error"]["type"], "invalid_request_error")
        req = urllib.request.Request(self.url + "/v1/systemone", data=b"{not json",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            OPENER.open(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(len(self.fake.requests), 0)  # nothing reached the backend

    def test_audio_is_501(self):
        status, r = self.ask({"state": STATE, "questions": {"q": ANGRY}, "files": ["data:audio/wav;base64,UklGRg=="]})
        self.assertEqual(status, 501)
        self.assertIn("image", r["error"]["message"])

    def test_images_are_forwarded_as_base64(self):
        status, r = self.ask({"state": "A photo.", "questions": {"q": ANGRY},
                              "images": ["data:image/png;base64,iVBORw0KGgo="]})
        self.assertEqual(status, 200)
        msg = self.fake.requests[-1]["messages"][1]
        self.assertEqual(msg["images"], ["iVBORw0KGgo="])
        self.assertIn("1 image(s) above are part of the STATE", msg["content"])
        # Ollama's own /v1/systemone takes raw base64 in `images`; accept that too.
        status, r = self.ask({"state": "A photo.", "questions": {"q": ANGRY}, "files": ["/9j/4AAQSkZJRg=="]})
        self.assertEqual(status, 200)
        self.assertEqual(self.fake.requests[-1]["messages"][1]["images"], ["/9j/4AAQSkZJRg=="])
        status, r = self.ask({"state": "x", "questions": {"q": ANGRY}, "files": ["AAAAAAAA"]})
        self.assertEqual(status, 501)  # valid base64 but not a known image format
        status, r = self.ask({"state": "x", "questions": {"q": ANGRY}, "files": ["not base64!!"]})
        self.assertEqual(status, 400)

    def test_list_criteria_and_descriptions(self):
        q = {"type": "choice", "instructions": "x", "criteria": ["billing", "shipping"]}
        status, r = self.ask({"state": STATE, "questions": {"q": q}})
        self.assertEqual(status, 200)
        self.assertEqual(list(r["answers"]["q"]["probabilities"]), ["billing", "shipping"])
        q = {"type": "choice", "instructions": "x", "criteria": {"billing": "Payments and refunds", "shipping": None}}
        self.ask({"state": STATE, "questions": {"q": q}})
        self.assertIn("A: billing — Payments and refunds\nB: shipping", self.fake.requests[-1]["messages"][1]["content"])
        q = {"type": "noul", "instructions": "x", "criteria": {"true": "the customer is upset", "false": "calm"}}
        self.ask({"state": STATE, "questions": {"q": q}})
        self.assertIn("Yes means: the customer is upset\nNo means: calm", self.fake.requests[-1]["messages"][1]["content"])

    def test_model_resolution(self):
        _, r = self.ask({"state": STATE, "model": "jev-latest", "questions": {"q": ANGRY}})
        self.assertEqual(r["model"], "gemma4:26b")  # unknown Jev model ids fall back to the default
        _, r = self.ask({"state": STATE, "model": "deepseek-r1:70b", "questions": {"q": ANGRY}})
        self.assertEqual(r["model"], "deepseek-r1:70b")  # installed models are honoured
        self.assertEqual(self.fake.requests[-1]["model"], "deepseek-r1:70b")

    def test_health_and_models(self):
        status, r = call(self.url, "/health")
        self.assertEqual(status, 200)
        self.assertEqual(r["model"], "gemma4:26b")
        self.assertEqual(r["backend_kind"], "ollama")
        status, r = call(self.url, "/v1/models")
        self.assertEqual(status, 200)
        self.assertIn("decisions", r["data"][0]["architecture"]["output_modalities"])
        status, r = call(self.url, "/nope")
        self.assertEqual(status, 404)
        status, r = call(self.url, "/v1/chat/completions", {"x": 1})
        self.assertEqual(status, 404)


class OpenAIBackendTests(unittest.TestCase):
    def test_openai_compatible_backend(self):
        fake = FakeBackend(kind="openai")
        fake.models = ["gemma-4-26b-it"]
        fake.reject_think = True
        httpd, url = start_jev(fake.url)
        try:
            status, r = call(url, "/v1/systemone", {"state": STATE, "questions": {"route": ROUTE, "angry": ANGRY}})
            self.assertEqual(status, 200)
            self.assertEqual(r["model"], "gemma-4-26b-it")
            self.assertEqual(r["answers"]["route"]["choice"], "billing")
            self.assertEqual(r["answers"]["angry"]["noul"], round(0.65 / 0.95, 4))
            self.assertEqual(r["usage"]["input_tokens"], 2 * 77)
            p = fake.requests[-1]
            self.assertEqual(p["max_tokens"], 1)
            self.assertIs(p["logprobs"], True)
            self.assertEqual(p["top_logprobs"], 20)
            self.assertNotIn("chat_template_kwargs", p)  # dropped after the 400
        finally:
            httpd.shutdown()
            httpd.server_close()
            fake.close()

    def test_unreachable_backend_is_a_502_and_health_503(self):
        httpd, url = start_jev("http://127.0.0.1:9")  # nothing listens on the discard port
        try:
            status, r = call(url, "/v1/systemone", {"state": STATE, "questions": {"q": ANGRY}})
            self.assertEqual(status, 502)
            self.assertEqual(r["error"]["type"], "backend_error")
            status, r = call(url, "/health")
            self.assertEqual(status, 503)
        finally:
            httpd.shutdown()
            httpd.server_close()


class MathTests(unittest.TestCase):
    def test_confidence_formulas_reproduce_the_reference_values(self):
        self.assertAlmostEqual(jev.choice_confidence([0.9998, 0.0001, 0.0001]), 0.9997, places=4)
        self.assertAlmostEqual(jev.score_confidence([0.0023, 0.116, 0.6753, 0.2064]), 0.673, places=4)
        self.assertEqual(jev.choice_confidence([0.25, 0.25, 0.25, 0.25]), 0.0)
        self.assertEqual(jev.score_confidence([0.0, 1.0, 0.0]), 1.0)
        self.assertEqual(jev.score_confidence([0.5, 0.0, 0.5]), 0.0)  # clamped, never negative
        self.assertAlmostEqual(jev.score_confidence([0.9, 0.1]), 0.8)  # 1 - 0.1 / 0.5
        self.assertEqual(jev.score_confidence([1 / 3, 1 / 3, 1 / 3]), 0.0)  # uniform: no confidence
        self.assertAlmostEqual(jev.score_confidence([0.0, 0.0, 0.0, 0.0, 1.0]), 1.0)

    def test_label_distribution_temperature(self):
        cands = [("A", ln(0.6)), ("B", ln(0.3)), ("C", ln(0.1))]
        labels, match = ["A", "B", "C"], jev.choice_matcher(3)
        p1, meta = jev.label_distribution(cands, labels, match, 1.0)
        self.assertAlmostEqual(p1[0], 0.6, places=6)
        self.assertEqual(meta["missing"], [])
        p_sharp, _ = jev.label_distribution(cands, labels, match, 0.5)
        p_flat, _ = jev.label_distribution(cands, labels, match, 2.0)
        self.assertGreater(p_sharp[0], p1[0])
        self.assertLess(p_flat[0], p1[0])
        self.assertAlmostEqual(sum(p_flat), 1.0, places=9)

    def test_token_matching(self):
        m = jev.choice_matcher(3)
        for tok in ("A", " a", "**A**", "(b)", "Ｃ", "C."):
            self.assertIsNotNone(m(tok), tok)
        for tok in ("D", "AB", "", " ", "1", "Yes"):
            self.assertIsNone(m(tok), tok)
        m52 = jev.choice_matcher(30)
        self.assertEqual(m52("a"), "a")  # lower-case labels are distinct once more than 26 options exist
        self.assertEqual(m52("A"), "A")
        self.assertIsNone(m52("e"))  # only A-Z and a-d are in use
        s = jev.score_matcher(4)
        self.assertEqual(s(" 3"), "3")
        self.assertIsNone(s("4"))
        self.assertIsNone(s("10"))
        self.assertEqual(jev.noul_matcher("YES"), "Yes")
        self.assertEqual(jev.noul_matcher(" no."), "No")
        self.assertEqual(jev.noul_matcher("はい"), "Yes")
        self.assertIsNone(jev.noul_matcher("Maybe"))

    def test_parse_image(self):
        self.assertEqual(jev.parse_image("data:image/jpeg;base64,/9j/4AAQ"),
                         ("image/jpeg", "/9j/4AAQ", "data:image/jpeg;base64,/9j/4AAQ"))
        self.assertEqual(jev.parse_image("iVBORw0KGgoAAAANSUhEUg==")[0], "image/png")
        self.assertEqual(jev.parse_image("UklGRhgAAABXRUJQ")[2], "data:image/webp;base64,UklGRhgAAABXRUJQ")
        with self.assertRaises(jev.BadRequest):
            jev.parse_image("https://example.com/x.jpg")
        with self.assertRaises(jev.BadRequest):
            jev.parse_image("data:image/png;base64")  # data: prefix but not a data URL
        with self.assertRaises(jev.NotSupported):
            jev.parse_image("data:audio/mpeg;base64,AAAA")


if __name__ == "__main__":
    unittest.main()
