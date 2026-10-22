#!/usr/bin/env python3
"""Fit the calibration file the server loads: a temperature per question type and a label prior
per option count, from labelled questions. Also measures how much the answers depend on the
option order. No training, only inference against the running server.

  python3 calibrate.py                                # built-in data/sample.json -> runtime/calibration.json
  python3 calibrate.py --data ./jev-bench --limit 200 # kishida/jev-bench style files or a directory
  python3 calibrate.py --out ~/.config/gemma-jev/calibration.json   # if the server reads it from there

How it works:
  * label prior (PriDe, Zheng et al. 2024): every choice question is asked once per cyclic
    rotation of its options. Each option visits each label (A, B, C...) exactly once, so the mean
    probability of a label over all rotations is the model's bias for that label, not for any
    content. The server divides it out of every choice distribution (JEV_DEBIAS=1).
  * temperature: with the prior applied and the forward/reverse variants averaged (the server's
    pipeline), the temperature that minimises the negative log-likelihood of the correct answers is
    searched on a grid, per question type when that type has enough questions, else one shared value.
  * order sensitivity: how often the most likely option changes with the rotation, and the mean
    distance between the forward and the reversed distribution, raw and debiased.

Fit on data you will not evaluate on and that looks like your questions; the in-sample numbers in
the report are optimistic. The server picks the new file up on its next request. Stdlib only.
"""
import argparse
import json
import math
import os
import statistics
import sys
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench  # noqa: E402
import server as jev  # noqa: E402

GRID = [round(0.3 * (5.0 / 0.3) ** (i / 59), 4) for i in range(60)]  # 0.3 .. 5.0, geometric


def rotate(seq, r):
    return seq[r:] + seq[:r]


# ----------------------------------------------------------------------------- collect


def collect(url, rows, max_rotations, timeout, no_noul):
    """Ask every question; returns records with the raw first-token candidates of every prompt.

    choice: runs = [forward, reversed] (the server's variants), prior_runs = all cyclic rotations.
    noul / score: runs = [the one prompt].
    """
    records = []
    for i, row in enumerate(rows):
        try:
            if "levels" in row:
                r = bench.ask_score(url, row, timeout)
                records.append(_record(row, "score", r, [r["variants"][0]]))
            else:
                n = len(row["choices"])
                r = bench.ask_choice(url, row, timeout, variants=2)
                rec = _record(row, "choice", r, r["variants"][:2])
                rec["prior_runs"] = [r["variants"][0]]
                for k in range(1, min(n, max_rotations)):
                    order = rotate(list(range(n)), k)
                    body, _ = bench.choice_body(row, order, variants=1)
                    resp = bench.post(url, body, timeout)
                    v = resp["answers"]["q"]["debug"]["variants"][0]
                    rec["prior_runs"].append({"order": order, "candidates": bench.candidates(v)})
                records.append(rec)
                if row.get("source") == "boolq" and not no_noul:
                    r = bench.ask_noul(url, row, timeout)
                    records.append(_record(row, "noul", r, [r["variants"][0]]))
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            msg = e.read()[:200].decode(errors="replace") if hasattr(e, "read") else str(e)
            print(f"  {i + 1:4}/{len(rows)} {str(row.get('id')):12} ERROR {msg[:80]}", flush=True)
            continue
        print(f"  {i + 1:4}/{len(rows)} {str(row.get('id')):12} ok", flush=True)
    return records


def _record(row, kind, r, runs):
    return {"id": row.get("id"), "source": row.get("source", "?"), "kind": kind, "n": r["n"],
            "correct": r["correct"], "runs": [{"order": v["order"], "candidates": v["candidates"]} for v in runs],
            "server_probs": r["probs"], "model": r["model"]}


# ----------------------------------------------------------------------------- estimates


def label_priors(records, min_runs=10):
    """Mean label probability over all rotations of all choice questions, per option count."""
    sums, counts = {}, {}
    for rec in records:
        if rec["kind"] != "choice":
            continue
        n = rec["n"]
        labels, match = jev.labels_for("choice", n)
        for run in rec.get("prior_runs", []):
            try:
                p, _ = jev.label_distribution(run["candidates"], labels, match, 1.0)
            except jev.BackendError:
                continue
            acc = sums.setdefault(n, [0.0] * n)
            for j in range(n):
                acc[j] += p[j]
            counts[n] = counts.get(n, 0) + 1
    out = {}
    for n, acc in sums.items():
        if counts[n] >= min_runs:
            out[str(n)] = [round(x / counts[n], 5) for x in acc]
    return out, counts


def pipeline(rec, temperature, priors, use_prior=True, n_variants=2):
    """The server's answer, offline: prior, temperature, forward/reverse average."""
    labels, match = jev.labels_for(rec["kind"], rec["n"])
    prior = priors.get(str(rec["n"])) if (use_prior and rec["kind"] == "choice") else None
    dists = []
    for run in rec["runs"][:n_variants]:
        p, _ = jev.label_distribution(run["candidates"], labels, match, temperature, prior)
        dists.append(jev.to_original_order(p, run["order"]))
    return jev.average(dists)


def metrics(records, temperature, priors, use_prior=True, n_variants=2):
    """Accuracy, NLL, Brier and ECE of the offline pipeline; `temperature` is a number or a
    per-type dict like the calibration file's ({"default": t, "choice": t, ...})."""
    rows = []
    for rec in records:
        t = temperature if isinstance(temperature, (int, float)) else \
            temperature.get(rec["kind"], temperature.get("default", 1.0))
        try:
            probs = pipeline(rec, t, priors, use_prior, n_variants)
        except jev.BackendError:
            continue
        c = rec["correct"]
        pred = max(range(len(probs)), key=probs.__getitem__)
        rows.append({"ok": pred == c, "p_max": probs[pred], "n": rec["n"],
                     "nll": -math.log(max(probs[c], 1e-6)),
                     "brier": sum((p - (1.0 if i == c else 0.0)) ** 2 for i, p in enumerate(probs))})
    if not rows:
        return None
    return {"n": len(rows), "accuracy": sum(r["ok"] for r in rows) / len(rows),
            "nll": statistics.mean(r["nll"] for r in rows), "brier": statistics.mean(r["brier"] for r in rows),
            "ece": bench.ece(rows)}


def fit_temperature(records, priors):
    """Grid search of the temperature that minimises the mean NLL of the server's pipeline."""
    best, best_nll = 1.0, float("inf")
    for t in GRID:
        m = metrics(records, t, priors)
        if m and m["nll"] < best_nll:
            best, best_nll = t, m["nll"]
    return best


def order_sensitivity(records, priors):
    """How much the choice answers depend on the option order, raw and debiased."""
    out = {}
    for name, use_prior in (("raw", False), ("debiased", True)):
        flips, tvs = [], []
        for rec in records:
            if rec["kind"] != "choice" or len(rec["runs"]) < 2:
                continue
            labels, match = jev.labels_for("choice", rec["n"])
            prior = priors.get(str(rec["n"])) if use_prior else None
            try:
                dists = [jev.to_original_order(jev.label_distribution(run["candidates"], labels, match, 1.0, prior)[0], run["order"])
                         for run in rec.get("prior_runs") or rec["runs"]]
                fwd, rev = (jev.to_original_order(jev.label_distribution(run["candidates"], labels, match, 1.0, prior)[0], run["order"])
                            for run in rec["runs"][:2])
            except jev.BackendError:
                continue
            tops = {max(range(rec["n"]), key=d.__getitem__) for d in dists}
            flips.append(len(tops) > 1)
            tvs.append(0.5 * sum(abs(a - b) for a, b in zip(fwd, rev)))
        if flips:
            out[name] = {"questions": len(flips), "flip_rate": sum(flips) / len(flips),
                         "mean_tv_forward_reverse": statistics.mean(tvs)}
    return out


# ----------------------------------------------------------------------------- report


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def fmt(x, d=3):
    return "-" if x is None else f"{x:.{d}f}"


def report_md(cal, before, after, forward_only, sens, counts):
    L = ["# gemma-jev 較正レポート", "",
         f"{cal['generated_at']} — {cal['server']} — モデル `{cal['model']}` — データ `{cal['fit_on']}`"
         f"（choice {cal['questions'].get('choice', 0)}、noul {cal['questions'].get('noul', 0)}、score {cal['questions'].get('score', 0)} 件）", "",
         "## 推定したもの", "",
         "| 項目 | 値 |", "|---|---|"]
    for k, v in cal["temperature"].items():
        L.append(f"| 温度 `{k}` | {v} |")
    for n, p in sorted(cal["label_prior"].get("choice", {}).items(), key=lambda kv: int(kv[0])):
        L.append(f"| ラベル事前分布（{n} 択、{counts.get(int(n), 0)} プロンプト） | {', '.join(f'{x:.3f}' for x in p)} |")
    L += ["", "一様なら各ラベルは 1/n。先頭（A）が大きいほど「とりあえず A」の癖が強い。", "",
          "## 同じ質問での前後比較（in-sample、楽観的）", "",
          "| 設定 | 正答率 | NLL | Brier | ECE |", "|---|---|---|---|---|"]
    for name, m in (("正順のみ・温度 1・補正なし（素の読み出し）", forward_only),
                    ("2 順序平均・温度 1・補正なし", before),
                    ("2 順序平均・事前分布除算・推定温度（サーバの新設定）", after)):
        if m:
            L.append(f"| {name} | {pct(m['accuracy'])} | {fmt(m['nll'])} | {fmt(m['brier'])} | {fmt(m['ece'])} |")
    L.append("")
    if sens:
        L += ["## 選択肢順序への感度", "", "| 分布 | 質問数 | 順序で最尤が変わる割合 | 正順と逆順の距離（全変動） |", "|---|---|---|---|"]
        for name, s in sens.items():
            L.append(f"| {name} | {s['questions']} | {pct(s['flip_rate'])} | {fmt(s['mean_tv_forward_reverse'])} |")
        L.append("")
    L += ["## 使い方", "",
          f"サーバは `{cal['written_to']}` を次のリクエストから自動で読む（`JEV_CALIBRATION` で場所を変更可）。",
          "評価は較正に使っていないデータで `bench.py` を回して確認すること。", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("JEV_URL", "http://127.0.0.1:9931"))
    ap.add_argument("--data", default=os.path.join(HERE, "data", "sample.json"),
                    help="labelled questions in the jev-bench schema (file or directory)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N rows")
    ap.add_argument("--out", default=jev.DEFAULT_CALIBRATION, help="calibration file to write")
    ap.add_argument("--max-rotations", type=int, default=8,
                    help="cyclic rotations per choice question for the label prior (<= option count)")
    ap.add_argument("--min-prior-runs", type=int, default=10,
                    help="prompts needed before a prior is stored for an option count")
    ap.add_argument("--min-type-questions", type=int, default=30,
                    help="questions needed before a question type gets its own temperature")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--no-noul", action="store_true", help="do not re-ask boolq rows as noul")
    args = ap.parse_args(argv)

    rows = bench.load_rows(args.data)
    if args.limit:
        rows = rows[:args.limit]
    try:
        health = bench.get(args.url, "/health")
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit(f"server not reachable at {args.url}: {e}")
    print(f"asking {len(rows)} rows (choice questions also in up to {args.max_rotations} rotations)...", flush=True)
    records = collect(args.url, rows, args.max_rotations, args.timeout, args.no_noul)
    if not records:
        sys.exit("no answers collected")

    priors, counts = label_priors(records, args.min_prior_runs)
    temps = {"default": fit_temperature(records, priors)}
    for kind in ("choice", "noul", "score"):
        subset = [r for r in records if r["kind"] == kind]
        if len(subset) >= args.min_type_questions:
            temps[kind] = fit_temperature(subset, priors)
    by_type = {k: len([r for r in records if r["kind"] == k]) for k in ("choice", "noul", "score")}

    forward_only = metrics(records, 1.0, priors, use_prior=False, n_variants=1)
    before = metrics(records, 1.0, priors, use_prior=False, n_variants=2)
    after = metrics(records, temps, priors, use_prior=True, n_variants=2)
    sens = order_sensitivity(records, priors)

    cal = {"generated_at": time.strftime("%Y-%m-%d %H:%M"), "server": args.url, "model": records[0]["model"],
           "fit_on": args.data, "questions": by_type, "temperature": temps,
           "label_prior": {"choice": priors} if priors else {},
           "order_sensitivity": sens,
           "in_sample": {"forward_only_raw": forward_only, "averaged_raw": before, "calibrated": after},
           "note": "fitted by calibrate.py; the temperatures and priors are in-sample estimates on fit_on",
           "written_to": os.path.abspath(os.path.expanduser(args.out))}
    out = os.path.expanduser(args.out)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=1)
    md = report_md(cal, before, after, forward_only, sens, counts)
    with open(os.path.splitext(out)[0] + "-report.md", "w", encoding="utf-8") as f:
        f.write(md)
    print("\n" + md)
    print(f"wrote {out}", file=sys.stderr)
    if health.get("calibration", {}).get("path") and os.path.abspath(os.path.expanduser(health["calibration"]["path"])) != cal["written_to"]:
        print(f"note: the server reads {health['calibration']['path']}; copy the file there or set JEV_CALIBRATION",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
