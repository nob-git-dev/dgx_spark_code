#!/usr/bin/env python3
"""Measure how well the Jev-style server decides: accuracy, calibration, latency.

  python3 bench.py                              # built-in data/sample.json against http://127.0.0.1:9931
  python3 bench.py --data ./jev-bench           # kishida/jev-bench style files (JSON / JSONL, or a directory)
  python3 bench.py --limit 30 --out ./gemma-jev-bench

Rows follow the kishida/jev-bench schema: id, source, question, context, choices, answer_idx,
n_choices. Every such row is asked as a `choice` question (the context, if any, is the state).
Rows whose source is boolq (yes/no) are also asked as `noul`. Rows with `levels` instead of
`choices` (ordinal, e.g. 1-5 stars) are asked as `score`.

The server is asked with debug=true, so the raw first-token candidates come back and the
temperature sweep can recompute every answer offline for several JEV_TEMPERATURE values.
Writes report.md (Japanese) and results.json into --out. Stdlib only.
"""
import argparse
import glob
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server as jev  # noqa: E402  (label matching + temperature math, same code as the server)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
YES = {"yes", "true", "はい"}
SWEEP = [0.5, 0.7, 1.0, 1.5, 2.0, 3.0]


# ----------------------------------------------------------------------------- data


def load_rows(path):
    paths = [path]
    if os.path.isdir(path):
        paths = sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)
                       + glob.glob(os.path.join(path, "**", "*.jsonl"), recursive=True))
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            if p.endswith(".jsonl"):
                rows += [json.loads(line) for line in f if line.strip()]
            else:
                data = json.load(f)
                if isinstance(data, dict):  # {"rows": [...]} / {"data": [...]} / {"train": [...]}
                    data = next((v for k in ("rows", "data", "train") for v in [data.get(k)] if v), [])
                rows += data
    if not rows:
        sys.exit(f"no rows found in {path}")
    return rows


def post(url, body, timeout):
    req = urllib.request.Request(url.rstrip("/") + "/v1/systemone",
                                 data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=timeout) as r:
        return json.load(r)


def candidates(answer):
    """debug.top_tokens [[token, prob], ...] -> [(token, logprob), ...]."""
    return [(t, math.log(max(p, 1e-12))) for t, p in answer["debug"]["top_tokens"]]


# ----------------------------------------------------------------------------- one row


def ask_choice(url, row, timeout):
    choices = [str(c) for c in row["choices"]]
    unique = len(set(choices)) == len(choices)
    names = choices if unique else [f"option {i + 1}" for i in range(len(choices))]
    criteria = {n: (None if unique else c) for n, c in zip(names, choices)}
    body = {"state": row.get("context") or "", "debug": True,
            "questions": {"q": {"type": "choice", "instructions": row["question"], "criteria": criteria}}}
    t0 = time.time()
    resp = post(url, body, timeout)
    a = resp["answers"]["q"]
    probs = [a["probabilities"][n] for n in names]
    correct = int(row["answer_idx"])
    pred = max(range(len(probs)), key=probs.__getitem__)
    return {"id": row.get("id"), "source": row.get("source", "?"), "kind": "choice",
            "n": len(choices), "correct": correct, "pred": pred, "ok": pred == correct,
            "p_correct": probs[correct], "p_max": probs[pred], "probs": probs,
            "nll": -math.log(max(probs[correct], 1e-6)),
            "brier": sum((p - (1.0 if i == correct else 0.0)) ** 2 for i, p in enumerate(probs)),
            "seconds": round(time.time() - t0, 3), "input_tokens": resp["usage"]["input_tokens"],
            "prefill_tps": a["debug"].get("prefill_tps"), "coverage": a["debug"]["coverage"],
            "candidates": candidates(a), "model": resp["model"]}


def ask_noul(url, row, timeout):
    choices = [str(c) for c in row["choices"]]
    yes_idx = next((i for i, c in enumerate(choices) if c.strip().lower() in YES), 1)
    truth = int(row["answer_idx"]) == yes_idx
    body = {"state": row.get("context") or "", "debug": True,
            "questions": {"q": {"type": "noul", "instructions": row["question"]}}}
    t0 = time.time()
    resp = post(url, body, timeout)
    a = resp["answers"]["q"]
    p = a["noul"]
    return {"id": row.get("id"), "source": row.get("source", "?"), "kind": "noul", "n": 2,
            "correct": int(truth), "pred": int(p >= 0.5), "ok": (p >= 0.5) == truth,
            "p_correct": p if truth else 1 - p, "p_max": max(p, 1 - p), "probs": [p, 1 - p],
            "nll": -math.log(max(p if truth else 1 - p, 1e-6)),
            "brier": (p - (1.0 if truth else 0.0)) ** 2,
            "seconds": round(time.time() - t0, 3), "input_tokens": resp["usage"]["input_tokens"],
            "prefill_tps": a["debug"].get("prefill_tps"), "coverage": a["debug"]["coverage"],
            "candidates": candidates(a), "model": resp["model"]}


def ask_score(url, row, timeout):
    levels = [str(l) for l in row["levels"]]
    body = {"state": row.get("context") or "", "debug": True,
            "questions": {"q": {"type": "score", "instructions": row["question"], "criteria": levels}}}
    t0 = time.time()
    resp = post(url, body, timeout)
    a = resp["answers"]["q"]
    probs = [a["probabilities"][str(i)] for i in range(len(levels))]
    correct = int(row["answer_idx"])
    nearest = int(round(a["score"]))
    pred = max(range(len(probs)), key=probs.__getitem__)
    return {"id": row.get("id"), "source": row.get("source", "?"), "kind": "score",
            "n": len(levels), "correct": correct, "pred": pred, "ok": nearest == correct,
            "score": a["score"], "mae": abs(a["score"] - correct),
            "p_correct": probs[correct], "p_max": probs[pred], "probs": probs,
            "nll": -math.log(max(probs[correct], 1e-6)),
            "brier": sum((p - (1.0 if i == correct else 0.0)) ** 2 for i, p in enumerate(probs)),
            "seconds": round(time.time() - t0, 3), "input_tokens": resp["usage"]["input_tokens"],
            "prefill_tps": a["debug"].get("prefill_tps"), "coverage": a["debug"]["coverage"],
            "candidates": candidates(a), "model": resp["model"]}


# ----------------------------------------------------------------------------- metrics


def ece(results, bins=10):
    """Expected calibration error of the top probability (equal-width bins)."""
    if not results:
        return None
    total, n = 0.0, len(results)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        group = [r for r in results if lo < r["p_max"] <= hi or (b == 0 and r["p_max"] <= lo)]
        if group:
            acc = sum(r["ok"] for r in group) / len(group)
            conf = sum(r["p_max"] for r in group) / len(group)
            total += len(group) / n * abs(acc - conf)
    return total


def summary(results):
    if not results:
        return None
    s = {"n": len(results),
         "accuracy": sum(r["ok"] for r in results) / len(results),
         "chance": sum(1.0 / r["n"] for r in results) / len(results),
         "nll": statistics.mean(r["nll"] for r in results),
         "brier": statistics.mean(r["brier"] for r in results),
         "ece": ece(results),
         "median_seconds": statistics.median(r["seconds"] for r in results),
         "coverage": statistics.mean(r["coverage"] for r in results)}
    if all("mae" in r for r in results):
        s["mae"] = statistics.mean(r["mae"] for r in results)
    return s


def sweep(results):
    """Recompute every answer offline for several temperatures, from the raw candidates."""
    out = []
    for t in SWEEP:
        rows = []
        for r in results:
            n = r["n"]
            if r["kind"] == "choice":
                labels, match = list(jev.CHOICE_LABELS[:n]), jev.choice_matcher(n)
            elif r["kind"] == "score":
                labels, match = list(jev.SCORE_LABELS[:n]), jev.score_matcher(n)
            else:
                labels, match = list(jev.NOUL_LABELS), jev.noul_matcher
            try:
                probs, _ = jev.label_distribution(r["candidates"], labels, match, t)
            except jev.BackendError:
                continue
            if r["kind"] == "noul":
                probs = [probs[0], probs[1]]  # [yes, no]; correct index 0 means "yes is true"
                correct = 0 if r["correct"] == 1 else 1
            else:
                correct = r["correct"]
            pred = max(range(len(probs)), key=probs.__getitem__)
            rows.append({"ok": pred == correct, "p_max": probs[pred], "n": n,
                         "nll": -math.log(max(probs[correct], 1e-6)),
                         "brier": sum((p - (1.0 if i == correct else 0.0)) ** 2 for i, p in enumerate(probs))})
        if rows:
            out.append({"temperature": t, "accuracy": sum(x["ok"] for x in rows) / len(rows),
                        "nll": statistics.mean(x["nll"] for x in rows),
                        "brier": statistics.mean(x["brier"] for x in rows), "ece": ece(rows)})
    return out


# ----------------------------------------------------------------------------- report


def fmt(x, d=3):
    return "-" if x is None else f"{x:.{d}f}"


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def report_md(meta, groups, results, sw):
    L = ["# gemma-jev ベンチマーク", "",
         f"{meta['generated_at']} — {meta['url']} — モデル `{meta['model']}` — データ `{meta['data']}`"
         f"（{meta['rows']} 行、質問 {len(results)} 件）", ""]
    ch = [r for r in results if r["kind"] == "choice"]
    if ch:
        L += ["## choice（多肢選択）", "",
              "| 出典 | 件数 | 正答率 | 当て推量 | NLL | Brier | ECE | 中央値レイテンシ |", "|---|---|---|---|---|---|---|---|"]
        for src in sorted({r["source"] for r in ch}):
            s = summary([r for r in ch if r["source"] == src])
            L.append(f"| {src} | {s['n']} | {pct(s['accuracy'])} | {pct(s['chance'])} | {fmt(s['nll'])} | "
                     f"{fmt(s['brier'])} | {fmt(s['ece'])} | {s['median_seconds']:.2f}s |")
        s = summary(ch)
        L.append(f"| **全体** | {s['n']} | **{pct(s['accuracy'])}** | {pct(s['chance'])} | {fmt(s['nll'])} | "
                 f"{fmt(s['brier'])} | {fmt(s['ece'])} | {s['median_seconds']:.2f}s |")
        L.append("")
    no = [r for r in results if r["kind"] == "noul"]
    if no:
        s = summary(no)
        L += ["## noul（Yes の確率）", "", "| 件数 | 正答率（閾値 0.5） | NLL | Brier | ECE | 中央値レイテンシ |",
              "|---|---|---|---|---|---|",
              f"| {s['n']} | {pct(s['accuracy'])} | {fmt(s['nll'])} | {fmt(s['brier'])} | {fmt(s['ece'])} | {s['median_seconds']:.2f}s |", ""]
    sc = [r for r in results if r["kind"] == "score"]
    if sc:
        s = summary(sc)
        L += ["## score（順序尺度）", "", "| 件数 | 最近傍レベル一致 | MAE（レベル） | NLL | Brier | 中央値レイテンシ |",
              "|---|---|---|---|---|---|",
              f"| {s['n']} | {pct(s['accuracy'])} | {fmt(s['mae'], 2)} | {fmt(s['nll'])} | {fmt(s['brier'])} | {s['median_seconds']:.2f}s |", ""]
    secs = [r["seconds"] for r in results]
    tps = [r["prefill_tps"] for r in results if r.get("prefill_tps")]
    toks = [r["input_tokens"] for r in results]
    L += ["## 速度", "",
          f"- レイテンシ: 中央値 {statistics.median(secs):.2f}s、p90 {sorted(secs)[int(0.9 * (len(secs) - 1))]:.2f}s",
          f"- 入力トークン: 中央値 {int(statistics.median(toks))}、合計 {sum(toks)}",
          f"- 入力読み込み（prefill）: 中央値 {statistics.median(tps):.0f} tok/s" if tps else "- prefill tok/s: 取得できず（OpenAI 互換バックエンド）",
          f"- ラベル被覆率（先頭トークンがラベルだった確率の平均）: {statistics.mean(r['coverage'] for r in results):.2f}"
          " — 低いときはモデルがラベル以外を言い始めている（プロンプトか think 設定を疑う）", ""]
    if sw:
        best = min(sw, key=lambda x: x["nll"])
        L += ["## 温度スイープ（`JEV_TEMPERATURE` の目安）", "",
              "同じ先頭トークン分布から温度だけ変えて再計算。NLL が最小の値を目安にする。", "",
              "| 温度 | 正答率 | NLL | Brier | ECE |", "|---|---|---|---|---|"]
        for x in sw:
            mark = " ←" if x is best else ""
            L.append(f"| {x['temperature']} | {pct(x['accuracy'])} | {fmt(x['nll'])} | {fmt(x['brier'])} | {fmt(x['ece'])}{mark} |")
        L += ["", f"推奨: `JEV_TEMPERATURE={best['temperature']}`（現在のサーバ設定での結果が上の表）", ""]
    fails = [r for r in results if not r["ok"]]
    if fails:
        L += ["## 誤答（最大 15 件）", "", "| id | 種別 | 正解 | 予測 | 正解の確率 |", "|---|---|---|---|---|"]
        for r in sorted(fails, key=lambda r: r["p_correct"])[:15]:
            L.append(f"| {r['id']} | {r['kind']} | {r['correct']} | {r['pred']} | {r['p_correct']:.3f} |")
        L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("JEV_URL", "http://127.0.0.1:9931"))
    ap.add_argument("--data", default=os.path.join(HERE, "data", "sample.json"),
                    help="JSON/JSONL file or directory in the jev-bench schema")
    ap.add_argument("--limit", type=int, default=0, help="only the first N rows")
    ap.add_argument("--out", default="./gemma-jev-bench")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--no-noul", action="store_true", help="do not re-ask boolq rows as noul")
    args = ap.parse_args(argv)

    rows = load_rows(args.data)
    if args.limit:
        rows = rows[:args.limit]
    results, errors = [], []
    for i, row in enumerate(rows):
        asks = [ask_score] if "levels" in row else [ask_choice]
        if "choices" in row and row.get("source") == "boolq" and not args.no_noul:
            asks.append(ask_noul)
        for ask in asks:
            try:
                r = ask(args.url, row, args.timeout)
            except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
                msg = getattr(e, "read", lambda: b"")()[:200].decode(errors="replace") if hasattr(e, "read") else str(e)
                errors.append({"id": row.get("id"), "kind": ask.__name__[4:], "error": f"{type(e).__name__}: {msg}"})
                print(f"  {i + 1:4}/{len(rows)} {str(row.get('id')):12} {ask.__name__[4:]:6} ERROR {msg[:80]}", flush=True)
                continue
            results.append(r)
            print(f"  {i + 1:4}/{len(rows)} {str(row.get('id')):12} {r['kind']:6} {'OK  ' if r['ok'] else 'MISS'} "
                  f"p={r['p_correct']:.2f} {r['seconds']:.2f}s", flush=True)
    if not results:
        sys.exit(f"no answers; first error: {errors[0] if errors else '?'}")

    meta = {"generated_at": time.strftime("%Y-%m-%d %H:%M"), "url": args.url, "data": args.data,
            "rows": len(rows), "model": results[0]["model"]}
    groups = {k: summary([r for r in results if r["kind"] == k]) for k in ("choice", "noul", "score")}
    sw = sweep(results)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": groups, "sweep": sw, "errors": errors,
                   "results": [{k: v for k, v in r.items() if k != "candidates"} for r in results]},
                  f, ensure_ascii=False, indent=1)
    md = report_md(meta, groups, results, sw)
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print("\n" + md)
    if errors:
        print(f"{len(errors)} question(s) failed, see results.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
