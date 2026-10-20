# gemma-jev — Gemma 4 を Jev のように使う（判断専用 API）

[Jev](https://docs.typesafe.ai/)（TypeSafe の「System One」モデル）は文章を生成せず、**選択肢ごとの確率だけを返す**判断専用の AI です。
`choice`（どれか）・`score`（どの程度か）・`noul`（Yes の確率）の 3 種類の質問に答えます。

このディレクトリは、GX10 の Ollama で動く **Gemma 4** を同じ API（`POST /v1/systemone`、llama.cpp / Ollama が採用する
TypeSafe 互換形式）で使えるようにするサーバーです。きしだなおき氏の発表「[GemmaをJevのように使ってみる](https://speakerdeck.com/kishida/use-gemma-like-jev)」と同じ考え方で、
Gemma 4 に**ラベル 1 文字だけで答えさせ、先頭トークンの確率分布（logprobs）を読む**ことで確率を得ます。学習は一切不要、依存パッケージもなし（Python 3.9+ 標準ライブラリのみ）。

```
Claude / アプリ ──POST /v1/systemone──▶ gemma-jev (server.py) ──/api/chat (logprobs, 1 トークン)──▶ Ollama + Gemma 4
                 ◀── {"choice": "billing", "probabilities": {...}, "confidence": 0.97} ──
```

| 部品 | 役割 |
|---|---|
| `server.py` | `POST /v1/systemone`（choice / score / noul）、`GET /health`、`GET /v1/models` |
| `jev.py` | コマンドラインから質問する（`choice` / `score` / `noul` / `ask` / `check`） |
| `bench.py` | 正答率・較正（NLL / Brier / ECE）・レイテンシを測り、`JEV_TEMPERATURE` の目安を出す |
| `data/sample.json` | 内蔵ベンチデータ 50 問（[kishida/jev-bench](https://huggingface.co/datasets/kishida/jev-bench) と同じ形式＋順序尺度） |
| `Dockerfile` / `compose.yaml` | Ollama コンテナの隣で動かす |
| `ollama/` | GX10 で Ollama + Gemma 4 を Docker 起動する compose と setup.sh |
| `tests/` | 偽 Ollama を立てたユニットテスト（`python3 -m unittest discover -s tests`） |

## 仕組み

1. 質問を「STATE / QUESTION / 選択肢ラベル」のプロンプトに組み立て、システムプロンプトで「ラベル以外を出力しない」よう指示する。
   ラベルは `choice` が `A, B, C…`、`score` が `0〜9`（低い方が 0）、`noul` が `Yes` / `No`。
2. Ollama に `num_predict: 1`、`logprobs: true`、`top_logprobs: 20`、`think: false` で 1 トークンだけ生成させる。
   サンプラーのフィルタ（top_k / top_p / min_p）は無効化し、素の softmax 分布を読む。
3. 先頭トークン候補のうちラベルに一致するもの（`A`、` a`、`**A**` などの表記揺れはまとめる）を拾い、ラベル間で正規化する。
   top-20 に現れなかった選択肢には、残りの確率質量と最小候補を上限とする小さな値を割り当てる。
4. `confidence` を計算する。`choice` は `(最大確率 − 1/n) / (1 − 1/n)`（全選択肢が等確率なら 0）、
   `score` は「最尤レベルからの期待距離」を一様分布の広がりで割って 1 から引いた値（Ollama の System One 実装と同じ式）。
   どちらも公式ドキュメントの例（0.9997 / 0.673）を再現します。

結果はモデル自身の次トークン分布なので、Jev と違って**較正されている保証はありません**。`bench.py` で測り、`JEV_TEMPERATURE` で調整してください。

## セットアップ

以下のコマンドはこのディレクトリ（`cd gemma-jev`）で実行します。

### 1. GX10 で Ollama + Gemma 4 を動かす

```bash
bash ollama/setup.sh             # Docker で Ollama を起動して gemma4:26b を取得（26B-A4B。1 トークン生成なのでレイテンシ ≒ 入力の読み込み時間）
# すでに Ollama が動いているなら: ollama pull gemma4:26b
```

logprobs は Ollama 0.12.11 以降、Gemma 4 は 0.20.0 以降が必要です。

### 2. サーバーを起動する

Docker（おすすめ。ホストには何も入れない）:

```bash
docker compose up -d --build
curl -s localhost:9931/health
```

または直接:

```bash
python3 server.py                         # http://127.0.0.1:9931、バックエンドは http://127.0.0.1:11434
python3 server.py --check                 # 接続とモデルの確認だけ
JEV_BACKEND_URL=http://gx10.local:11434 python3 server.py   # 別マシンから（Ollama を LAN 公開している場合）
```

既定では名前に `gemma4` を含む最初のモデルを使います（`JEV_MODEL` で指定可）。
llama.cpp の `llama-server` や vLLM などの OpenAI 互換サーバーも `JEV_BACKEND_URL` に指定できます（`logprobs` 対応が必要）。

## 使い方

### curl（Jev / llama.cpp / Ollama と同じリクエスト形式）

```bash
curl -s localhost:9931/v1/systemone -H 'Content-Type: application/json' -d '{
  "state": "Customer message: I was charged twice for my order last week and nobody has replied.",
  "questions": {
    "route":   {"type": "choice", "instructions": "Which team should handle this?",
                "criteria": {"billing": "Payments and refunds", "shipping": null, "technical": null}},
    "angry":   {"type": "noul",   "instructions": "Is the customer angry?"},
    "urgency": {"type": "score",  "instructions": "How urgent is this?",
                "criteria": ["can wait", "this week", "today", "right now"]}
  }
}'
```

```json
{
  "model": "gemma4:26b",
  "answers": {
    "route":   {"type": "choice", "choice": "billing",
                "probabilities": {"billing": 0.9871, "shipping": 0.0042, "technical": 0.0087}, "confidence": 0.9807},
    "angry":   {"type": "noul", "noul": 0.7312},
    "urgency": {"type": "score", "score": 2.1398,
                "legend": {"0": "can wait", "1": "this week", "2": "today", "3": "right now"},
                "probabilities": {"0": 0.0031, "1": 0.1302, "2": 0.5905, "3": 0.2762}, "confidence": 0.6868}
  },
  "usage": {"input_tokens": 612, "output_tokens": 0}
}
```

（数値はイメージです。実際の値はモデルと温度設定で変わります。）

- `state`: 文字列でも JSON（オブジェクト / 配列）でも可。JSON はそのままテキストとしてモデルに見せます。
- `questions`: 質問 ID → 質問。`type` は `choice` / `score` / `noul`。`instructions` は質問文（JSON も可）。
- `criteria`: `choice` は「選択肢名 → 説明（または null）」のオブジェクト（2〜52 個。配列で名前だけ渡しても可）。
  `score` は低い方から並べた 2〜10 個のレベル説明。`noul` は省略可、`{"true": "...", "false": "..."}` で意味を補える。
- `files` / `images`: 画像（llama.cpp 流の data URL でも、Ollama 流の生 base64 でも可）。Gemma 4 は画像を読めます。
- `model`: 任意。インストール済みのモデル名ならそれを使い、`jev-latest` のような未知の名前は既定モデルにフォールバック。
- `debug: true`: 各回答に先頭トークン上位 20 件・ラベル被覆率・prefill tok/s などを付けて返す（プロンプト調整用）。

エラーは Jev 同様 `400`（不正なリクエスト）、`501`（画像以外のファイルなど未対応）、`502`（Ollama 側の失敗や、
モデルがラベルで答え始めなかった場合。上位候補をメッセージに含めます）。

### コマンドライン

```bash
python3 jev.py choice @ticket.txt "Which team should handle this?" "billing=Payments and refunds" shipping technical
python3 jev.py score  "サイトが1時間落ちています" "How urgent is this?" "can wait" "this week" today "right now"
python3 jev.py noul   - "Is the customer angry?" < ticket.txt
python3 jev.py --image lap.jpg noul "Race photo." "Is the rider airborne?"
python3 jev.py ask request.json      # 生の System One リクエスト
python3 jev.py check                 # /health
```

`JEV_URL`（既定 `http://127.0.0.1:9931`）で接続先を変えられます。`--debug` で診断情報付き。

## ベンチマークと温度の調整

```bash
python3 bench.py                      # 内蔵 50 問（知識・常識・読解 Yes/No・モトクロス・順序尺度）
python3 bench.py --data ./jev-bench   # kishida/jev-bench を落としてきた JSON / JSONL（ディレクトリ可）
```

`./gemma-jev-bench/report.md`（日本語）と `results.json` に、出典別の正答率・当て推量との差・NLL・Brier・ECE、
noul / score の成績、レイテンシと prefill tok/s、そして**温度スイープ**が出ます。
スイープは同じ先頭トークン分布から温度だけ変えて再計算するので追加の推論は不要です。NLL が最小の温度を
`JEV_TEMPERATURE` に設定すると、確率がよく較正された（70% と言ったら 7 割当たる）状態に近づきます。

`jev-bench` を使うとき: `huggingface-cli download --repo-type dataset kishida/jev-bench --local-dir ./jev-bench`
（行の形式は `id, source, question, context, choices, answer_idx, n_choices`。boolq 行は noul としても評価します）。

## 環境変数

| 変数 | 既定 | 説明 |
|---|---|---|
| `JEV_HOST` / `JEV_PORT` | `127.0.0.1` / `9931` | 待ち受けアドレス（LAN 公開は `0.0.0.0`） |
| `JEV_BACKEND_URL` | `http://127.0.0.1:11434` | Ollama または OpenAI 互換サーバー |
| `JEV_MODEL` | 名前に `gemma4` を含む最初のモデル | 使うモデル |
| `JEV_API_KEY` | — | OpenAI 互換サーバー用 |
| `JEV_TEMPERATURE` | `1.0` | ラベルの logprob をこの値で割ってから正規化。`bench.py` の推奨値を入れる |
| `JEV_TOP_LOGPROBS` | `20` | 読む候補数（Ollama の上限は 20） |
| `JEV_MAX_CTX` | `65536` | Ollama の `num_ctx` 上限（入力長から自動算出） |
| `JEV_TIMEOUT` | `300` | バックエンド 1 回あたりの秒数 |
| `JEV_PARALLEL` | `4` | 1 リクエスト内の質問を同時に投げる数 |
| `JEV_DECIMALS` | `4` | 返す確率の小数桁（Jev と同じ 4） |
| `JEV_THINK` | `0` | `0` で思考モードをオフにして送る。`unset` で何も送らない |

## 制限と注意

- **Yes/No 以外は top-20 の壁**: Ollama は 1 位置あたり 20 候補までしか返さないため、選択肢が 20 個を超えると
  下位の選択肢は推定値（残り質量の按分）になります。実用上は 2〜10 個程度が適しています。
- **思考モード**: Gemma 4 は既定で考えてから答えるため、`think: false` を送ります（対応しないモデルでは自動で外します）。
  `debug` の `coverage`（先頭トークンがラベルだった確率）が低い、または 502 で「did not start its answer with a label」が出るときは、
  モデルがラベル以外を言い始めています。`JEV_THINK` と Ollama のバージョンを確認してください。
- **較正**: Jev は較正済みモデルですが、こちらはそうではありません。確率を閾値に使う前に `bench.py` で測ってください。
- **質問は独立**: 同じ `state` の複数質問はそれぞれ別の推論です（Ollama 側でプロンプトキャッシュが効くので 2 問目以降は速い）。
- **Ollama 本体の `/v1/systemone`**: Ollama 0.35 以降は Nimble / Clef などの**ネイティブ決定モデル**を同じ API で直接動かせます
  （`ollama pull nimble` → `curl localhost:11434/v1/systemone`）。ただし Gemma 4 のような普通の LLM は
  「decision model ではない」と拒否されるので、Gemma 4 で同じことをしたい場合がこのサーバーの出番です。
  リクエスト形式は同じなので、クライアントは URL を差し替えるだけで両者を行き来できます。
