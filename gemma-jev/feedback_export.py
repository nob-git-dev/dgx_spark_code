#!/usr/bin/env python3
"""Turn the decision log into training data.

  python3 feedback_export.py runtime/decisions.jsonl > train.jsonl
  python3 feedback_export.py runtime/decisions.jsonl --all > train.jsonl   # unlabelled decisions too

Reads the JSONL the server writes with JEV_DECISION_LOG (lines of type "decision" and "feedback",
joined on `id`) and writes one line per decision in the request-plus-label shape that Kev's
trainer and a Jev-tuning script read:

  {"state": ..., "questions": {"team": {"type": "choice", "instructions": ..., "criteria": ..., "label": "billing"}}}

A question gets the label from the latest feedback that names it. Without --all, questions and
decisions without feedback are dropped. With --all, an unlabelled question gets the model's own
answer as its label (choice: the chosen option, noul: true/false at 0.5, score: the nearest level);
mark such files as self-labelled. Stdlib only.
"""
import argparse
import json
import sys


def model_label(answer):
    if answer["type"] == "choice":
        return answer["choice"]
    if answer["type"] == "noul":
        return answer["noul"] >= 0.5
    return int(round(answer["score"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="decision log written by the server (JEV_DECISION_LOG)")
    ap.add_argument("--all", action="store_true", help="also export questions without feedback, labelled by the model")
    args = ap.parse_args(argv)

    decisions, feedback = {}, {}
    with open(args.log, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("type") == "decision":
                decisions[rec["id"]] = rec
            elif rec.get("type") == "feedback":
                feedback.setdefault(rec["id"], {}).update(rec.get("labels") or {})

    written = labelled = 0
    for rid, d in decisions.items():
        labels = feedback.get(rid, {})
        questions = {}
        for qid, q in (d.get("questions") or {}).items():
            if not isinstance(q, dict) or qid not in d.get("answers", {}):
                continue
            if qid in labels:
                label, source = labels[qid], "feedback"
            elif args.all:
                label, source = model_label(d["answers"][qid]), "model"
            else:
                continue
            out = {k: q[k] for k in ("type", "instructions", "criteria") if k in q}
            out["label"] = label
            out["label_source"] = source
            questions[qid] = out
            labelled += source == "feedback"
        if questions:
            sys.stdout.write(json.dumps({"state": d.get("state"), "questions": questions,
                                         "model": d.get("model"), "id": rid}, ensure_ascii=False) + "\n")
            written += 1
    print(f"{written} decisions written, {labelled} questions with human labels, "
          f"{len(decisions)} decisions and {len(feedback)} feedback records in the log", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
