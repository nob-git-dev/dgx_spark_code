# gemma-jev — Gemma 4 を Jev のように使う（判断専用 API）

[Jev](https://docs.typesafe.ai/)（TypeSafe の「System One」モデル）は文章を生成せず、**選択肢ごとの確率だけを返す**判断専用の AI です。
`choice`（どれか）・`score`（どの程度か）・`noul`（Yes の確率）の 3 種類の質問に答えます。

このディレクトリは、GX10 の Ollama で動く **Gemma 4** を同じ API（`POST /v1/systemone`、llama.cpp / Ollama が採用する
TypeSafe 互換形式）で使えるようにするサーバーです。きしだなおき氏の発表「[GemmaをJevのように使ってみる](https://speakerdeck.com/kishida/use-gemma-like-jev)」と同じ考え方で、
Gemma 4 に**ラベル 1 文字だけで答えさせ、先頭トークンの確率分布（logprobs）を読む**ことで確率を得ます。学習は不要、依存パッケージもなし（Python 3.9+ 標準ライブラリのみ）。

素の読み出しの上に、オープンな決定モデル（llama.cpp の lev 型、Kev など）が「ヘッドの後」でやっている処理を足しています。

- **2 順序平均**: choice は選択肢を正順と逆順の 2 回見せて平均する。「とりあえず A」のような位置の癖が打ち消される。
- **ラベル事前分布の除算**: `calibrate.py` が選択肢を巡回させて推定した A/B/C… への偏りで割る（PriDe 方式）。
- **較正温度**: `calibrate.py` がラベル付きデータで質問型ごとに合わせた温度で確率を較正する。
- **判断ログと訂正**: 判断を記録し、人手の正解を `POST /v1/feedback` で付けられる。将来の微調整（Jev-tuning）の学習データになる。

```
Claude / アプリ ──POST /v1/systemone──▶ gemma-jev (server.py) ──/api/chat (logprobs, 1 トークン × 順序数)──▶ Ollama + Gemma 4
                 ◀── {"choice": "billing", "probabilities": {...}, "confidence": 0.97} ──
```

| 部品 | 役割 |
|---|---|
| `server.py` | `POST /v1/systemone`（choice / score / noul）、`POST /v1/feedback`、`GET /health`、`GET /v1/models` |
| `calibrate.py` | ラベル付きデータで温度とラベル事前分布を推定し、順序への感度を測って `runtime/calibration.json` を書く |
| `bench.py` | 正答率・較正（NLL / Brier / ECE）・順序への感度・レイテンシを測る |
| `jev.py` | コマンドラインから質問する（`choice` / `score` / `noul` / `ask` / `feedback` / `check`） |
| `feedback_export.py` | 判断ログと訂正を学習データ（リクエスト＋正解の JSONL）にまとめる |
| `data/sample.json` | 内蔵ベンチデータ 50 問（[kishida/jev-bench](https://huggingface.co/datasets/kishida/jev-bench) と同じ形式＋順序尺度） |
| `Dockerfile` / `compose.yaml` | Ollama コンテナの隣で動かす。`runtime/` を共有して較正ファイルとログを置く |
| `ollama/` | GX10 で Ollama + Gemma 4 を Docker 起動する compose と setup.sh |
| `tests/` | 偽 Ollama を立てたユニットテスト（`python3 -m unittest discover -s tests`） |

## 仕組み

1. 質問を「STATE / QUESTION / 選択肢ラベル」のプロンプトに組み立て、システムプロンプトで「ラベル以外を出力しない」よう指示する。
   ラベルは `choice` が `A, B, C…`、`score` が `0〜9`（低い方が 0）、`noul` が `Yes` / `No`。
2. Ollama に `num_predict: 1`、`logprobs: true`、`top_logprobs: 20`、`think: false` で 1 トークンだけ生成させる。
   サンプラーのフィルタ（top_k / top_p / min_p）は無効化し、素の softmax 分布を読む。生成されたトークン自体は使わない。
3. 先頭トークン候補のうちラベルに一致するもの（`A`、` a`、`**A**` などの表記揺れはまとめる）を拾う。
   top-20 に現れなかった選択肢には、残りの確率質量と最小候補を上限とする小さな値を割り当てる。
4. choice は選択肢を逆順にしたプロンプトでも同じことをし（`JEV_VARIANTS=2`）、それぞれの分布から
   較正ファイルのラベル事前分布を割り（`JEV_DEBIAS=1`）、質問型ごとの温度で割ってから正規化し、2 つの分布を平均する。
5. `confidence` を計算する。`choice` は `(最大確率 − 1/n) / (1 − 1/n)`（全選択肢が等確率なら 0）、
   `score` は「最尤レベルからの期待距離」を一様分布の広がりで割って 1 から引いた値（Ollama の System One 実装と同じ式）。
   どちらも公式ドキュメントの例（0.9997 / 0.673）を再現します。

較正ファイルがなければ温度 1.0・事前分布なしで動きます（素の読み出し＋2 順序平均）。較正ファイルはサーバを止めずに差し替えられます。
Jev 本体の仕組みとオープン実装の読解、ここから先（微調整）の計画は `docs/jev-research.md` にまとめてあります（motocross-analysis リポジトリ側）。

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

### 3. 較正する（推奨。学習なし、数分）

```bash
python3 calibrate.py                       # 内蔵 50 問で推定 → runtime/calibration.json（サーバが自動で読む）
python3 calibrate.py --data ./jev-bench --limit 200   # 手元のラベル付きデータで（jev-bench 形式、ファイルかディレクトリ）
```

Docker で動かしているときも、ホストの `python3 calibrate.py` がそのまま使えます（`runtime/` がコンテナと共有されています）。
ホストに Python がなければ `docker exec gemma-jev python3 calibrate.py` でも同じです。詳しくは「較正」の節。

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
  "usage": {"input_tokens": 1224, "output_tokens": 0}
}
```

（数値はイメージです。実際の値はモデルと較正で変わります。）

- `state`: 文字列でも JSON（オブジェクト / 配列）でも可。JSON はそのままテキストとしてモデルに見せます。
- `questions`: 質問 ID → 質問。`type` は `choice` / `score` / `noul`。`instructions` は質問文（JSON も可）。
- `criteria`: `choice` は「選択肢名 → 説明（または null）」のオブジェクト（2〜52 個。配列で名前だけ渡しても可）。
  `score` は低い方から並べた 2〜10 個のレベル説明。`noul` は省略可、`{"true": "...", "false": "..."}` で意味を補える。
- `files` / `images`: 画像（llama.cpp 流の data URL でも、Ollama 流の生 base64 でも可）。Gemma 4 は画像を読めます。
- `model`: 任意。インストール済みのモデル名ならそれを使い、`jev-latest` のような未知の名前は既定モデルにフォールバック。
- `variants`: 任意。`1` でこのリクエストだけ正順のみ（レイテンシ半分）、`2` で正順＋逆順（既定は `JEV_VARIANTS`）。
- `debug: true`: 各回答に、順序ごとの先頭トークン上位 20 件・分布・被覆率、使った温度と事前分布、prefill tok/s を付けて返す。
- `usage.input_tokens` は投げたプロンプト全部の合計（choice は 2 順序分）。判断ログが有効なら応答に `id` が付く。

エラーは Jev 同様 `400`（不正なリクエスト）、`501`（画像以外のファイルなど未対応）、`502`（Ollama 側の失敗や、
モデルがラベルで答え始めなかった場合。上位候補をメッセージに含めます）。

### コマンドライン

```bash
python3 jev.py choice @ticket.txt "Which team should handle this?" "billing=Payments and refunds" shipping technical
python3 jev.py score  "サイトが1時間落ちています" "How urgent is this?" "can wait" "this week" today "right now"
python3 jev.py noul   - "Is the customer angry?" < ticket.txt
python3 jev.py --image lap.jpg noul "Race photo." "Is the rider airborne?"
python3 jev.py ask request.json                 # 生の System One リクエスト
python3 jev.py feedback <id> route=shipping angry=false    # 記録された判断に正解を付ける
python3 jev.py check                            # /health（較正ファイルの状態も出る）
```

`JEV_URL`（既定 `http://127.0.0.1:9931`）で接続先を変えられます。`--debug` で診断情報付き。

## 較正（calibrate.py）

素の読み出しには 2 つの癖があります。(1) 選択肢の並び順で答えが変わる（LLM は A のような先頭ラベルを選びがち）、
(2) 確率が過信か過小になる（70% と言っても 7 割当たらない）。`calibrate.py` は学習なしで両方を補正する値を推定します。

1. **ラベル事前分布**: 各 choice 問題を、選択肢を 1 つずつずらした巡回順序で全部聞く。どの選択肢もどのラベルに 1 回ずつ
   来るので、ラベルごとの平均確率は内容ではなく「ラベルそのものへの偏り」になる（PriDe、Zheng et al. 2024）。
   選択肢数ごとに保存し、サーバはこれで割る。
2. **温度**: 事前分布で割り 2 順序を平均した分布に対し、正解の負の対数尤度を最小にする温度を格子探索する。
   質問型（choice / noul / score）ごとの件数が 30 以上あれば型別、足りなければ共通の 1 つ。
3. **順序への感度**: 巡回順序で最尤の選択肢が変わった割合、正順と逆順の分布の距離を、補正前後で報告する。

```bash
python3 calibrate.py --data ./my-questions.json --out runtime/calibration.json
cat runtime/calibration-report.md       # 前後比較と推定値
```

書き出した `runtime/calibration.json` はサーバが次のリクエストから読みます（`GET /health` の `calibration` で確認）。
**較正に使ったデータで評価しないこと**。レポートの数値は同じデータに対するものなので楽観的です。
手元の質問に近いデータを、評価用とは別に用意してください。推定した温度を固定で使いたいときは `JEV_TEMPERATURE` に数値を入れると、
ファイルより優先されます。

## ベンチマーク

```bash
python3 bench.py                      # 内蔵 50 問（知識・常識・読解 Yes/No・モトクロス・順序尺度）
python3 bench.py --data ./jev-bench   # kishida/jev-bench を落としてきた JSON / JSONL（ディレクトリ可）
```

`./gemma-jev-bench/report.md`（日本語）と `results.json` に、出典別の正答率・当て推量との差・NLL・Brier・ECE、
noul / score の成績、**正順だけと 2 順序平均の正答率、順序を逆にして答えが変わった割合**、レイテンシと prefill tok/s、
温度スイープ（診断用。合わせるのは `calibrate.py` で）が出ます。レポート冒頭に、サーバがどの較正ファイルで動いていたかが記録されます。

`jev-bench` を使うとき: `huggingface-cli download --repo-type dataset kishida/jev-bench --local-dir ./jev-bench`
（行の形式は `id, source, question, context, choices, answer_idx, n_choices`。boolq 行は noul としても評価します）。

## 判断ログとフィードバック（将来の学習データ）

`JEV_DECISION_LOG=runtime/decisions.jsonl` で起動すると、全リクエストが 1 行ずつ記録され、応答に `id` が付きます。
間違いに気づいたら正解を送ります。

```bash
curl -s localhost:9931/v1/feedback -H 'Content-Type: application/json' \
  -d '{"id": "<応答の id>", "labels": {"route": "shipping", "angry": false, "urgency": 2}}'
# または: python3 jev.py feedback <id> route=shipping angry=false urgency=2
```

`choice` は選択肢名、`noul` は true / false、`score` はレベル番号（0 始まり）。溜まったら学習データに変換します。

```bash
python3 feedback_export.py runtime/decisions.jsonl > train.jsonl          # 訂正があった判断だけ
python3 feedback_export.py runtime/decisions.jsonl --all > train.jsonl    # 訂正のないものはモデルの答えをラベルにする（自己ラベル）
```

出力は Kev の学習スクリプトと同じ「リクエスト＋`label`」形式なので、Jev-tuning（LoRA 微調整）に進むときそのまま使えます。
数千件たまったころが微調整を検討する目安です（Kev の実例: 5,219 件で 0.80 → 0.90、400 件では誤差の範囲）。

## 環境変数

| 変数 | 既定 | 説明 |
|---|---|---|
| `JEV_HOST` / `JEV_PORT` | `127.0.0.1` / `9931` | 待ち受けアドレス（LAN 公開は `0.0.0.0`） |
| `JEV_BACKEND_URL` | `http://127.0.0.1:11434` | Ollama または OpenAI 互換サーバー |
| `JEV_MODEL` | 名前に `gemma4` を含む最初のモデル | 使うモデル |
| `JEV_API_KEY` | — | OpenAI 互換サーバー用 |
| `JEV_VARIANTS` | `2` | choice を正順＋逆順で評価して平均（`1` で正順のみ。レイテンシ半分、順序バイアスは残る） |
| `JEV_DEBIAS` | `1` | 較正ファイルにラベル事前分布があれば choice をそれで割る（`0` で無効） |
| `JEV_CALIBRATION` | `runtime/calibration.json`（スクリプトと同じ場所） | `calibrate.py` が書く較正ファイル。変更は自動で反映 |
| `JEV_TEMPERATURE` | 未設定 | 未設定なら較正ファイルの温度（なければ 1.0）。数値を入れると全質問型でそれを使う |
| `JEV_DECISION_LOG` | 未設定 | 判断ログ（JSONL）の場所。設定すると `/v1/feedback` が使える |
| `JEV_TOP_LOGPROBS` | `20` | 読む候補数（Ollama の上限は 20） |
| `JEV_MAX_CTX` | `65536` | Ollama の `num_ctx` 上限（入力長から自動算出） |
| `JEV_TIMEOUT` | `300` | バックエンド 1 回あたりの秒数 |
| `JEV_PARALLEL` | `4` | 1 リクエスト内のバックエンド呼び出しを同時に投げる数 |
| `JEV_DECIMALS` | `4` | 返す確率の小数桁（Jev と同じ 4） |
| `JEV_THINK` | `0` | `0` で思考モードをオフにして送る。`unset` で何も送らない |

## 制限と注意

- **決定モデルではなく、無学習の読み出し**: 文献では無調整の Gemma 4 31B で Jev と 0.5 pt 差（OpenDecisions）、26B-A4B で
  MMLU＋ARC 88.6% という報告がありますが、ここでやっているのは「1 トークン生成して分布を読む」だけです。
  2 順序平均・事前分布除算・温度較正は、その読み出しの後処理です。精度を本当に上げるには微調整（判断ログを学習データに）が必要です。
- **top-20 の壁**: Ollama は 1 位置あたり 20 候補までしか返さないため、選択肢が 20 個を超えると下位の選択肢は推定値になります。
  実用上は 2〜10 個程度が適しています。
- **レイテンシ**: `JEV_VARIANTS=2` は choice のバックエンド呼び出しを 2 回にします。同じ `state` に複数の質問をするときは、
  Ollama のプロンプトキャッシュが効くよう `JEV_PARALLEL=1` にすると 2 問目以降が速くなることがあります（並列だと別スロットに散ることがある）。
- **思考モード**: Gemma 4 は既定で考えてから答えるため、`think: false` を送ります（対応しないモデルでは自動で外します）。
  `debug` の `coverage`（先頭トークンがラベルだった確率）が低い、または 502 で「did not start its answer with a label」が出るときは、
  モデルがラベル以外を言い始めています。`JEV_THINK` と Ollama のバージョンを確認してください。
- **較正の有効範囲**: 温度と事前分布は較正に使ったデータの分布に対するものです。質問の種類が変わったら
  `calibrate.py` をやり直してください。較正ファイルがどのモデルで作られたかは `generated_at` / `model` に残ります。
- **「分からない」は言えない**: Jev と同じく選択肢の中から必ず選びます。棄権させたいときは選択肢に `"other": "None of the above"` を加えてください。
- **Ollama 本体の `/v1/systemone`**: Ollama 0.35 以降は Nimble / Clef などの**ネイティブ決定モデル**を同じ API で直接動かせます
  （`ollama pull nimble` → `curl localhost:11434/v1/systemone`）。Gemma 4 のような普通の LLM は拒否されるので、そこをこのサーバーが埋めます。
  リクエスト形式は同じなので、クライアントは URL を差し替えるだけで両者を行き来できます。
