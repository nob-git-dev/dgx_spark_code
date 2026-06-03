# dgx-update-check

> 📌 **このディレクトリは参照用コピーです**
>
> 正本（メンテナンスはこちらで行います）: **[https://github.com/nob-git-dev/claude-skills/tree/main/dgx-update-check](https://github.com/nob-git-dev/claude-skills/tree/main/dgx-update-check)**
>
> このリポジトリ（dgx_spark_code）は DGX Spark 上で動かすコードの保管庫であり、本ディレクトリは「DGX Spark 用に作ったスキル」の参照用として置いています。
> （`claude-sdlc-skills/` も同様に claude-skills/sdlc-skills/ へ移転済み・参照コピー）

DGX Spark（GX10）のシステムアップデートを、ブラウザ・ダッシュボードのアップデートボタンを押す **前に**
「今なにが来ているのか」をコマンドで覗き見るための Claude スキルです。
UNIX の `apt update` で「これから来るもの」を確認する体験を、DGX の OTA 文脈で **副作用ゼロ** に再現します。

## なにをするか

起動すると、以下を **read-only・sudo なし・副作用ゼロ** で取得し、レポート A〜F をチャットに提示します。

1. **第1層：DGX OTA 世代更新** — NVIDIA が配信する大型更新（CUDA・カーネル・FW 等）が来ているか
   （`nvidia-spark-ota-check` を読取専用で使用。OTA 有無の判定は公式ツールに委ねる）。
2. **第2層：Ubuntu 標準 apt 更新** — `noble-updates` / `noble-security` の日次パッチを個別パッケージ単位で。
3. **容量・メモリ見積り** — 「押したら何 GB 来るか・メモリは足りるか」（実体 .deb を DL せず算出）。
4. **ネット調査要約（出典つき）** — リリースノートと主要/セキュリティパッケージ（CVE 等）の意味・リスク。
5. **安全性の明示** — 「このスキルは何も変更していない」副作用ゼロ宣言と、情報の基準日時（インデックス鮮度）。

> 背景：過去にダッシュボードのアップデートで約 10GB が一気に DL され、統合メモリ（128GB を大型の常駐プロセス等と共有）が
> 圧迫されてプロセス強制終了の事故が起きました。本スキルは「押す前に中身を知る」ためのものです。

## 使い方

Claude のチャットで「DGX のアップデート何が来てる？」「更新前に確認したい」等と頼むと起動します。
レポートはチャットに直接表示されます（ファイル書き出しはしません）。

データ層スクリプトを直接確認したい場合（read-only・安全）：
```bash
bash ~/.claude/skills/dgx-update-check/scripts/collect.sh | jq .
```

## 構成

```
dgx-update-check/
├── SKILL.md            判断層（Claude）の指示書：手順・レポート様式・安全宣言・手動コマンド雛形
├── scripts/
│   ├── collect.sh      データ層の単一エントリ。read-only コマンド群 → 統合 JSON を stdout
│   ├── build_json.py   collect.sh が集めた生出力を構造化 JSON に整形（stdlib のみ・副作用なし）
│   └── config.sh       設定値の外部分離：許可コマンド allowlist・既定 URL・LC_ALL=C
├── tests/
│   ├── run_all.sh      テスト一括実行（静的＋実機）
│   ├── test_static.sh  安全性・構造の静的検証（禁止コマンドが含まれないことを grep で検証）
│   ├── test_runtime.sh collect.sh を1回実行し JSON 契約と副作用ゼロを検証（read-only）
│   ├── test_glob.sh    パッケージ名のグロブ展開・単語分割の防止検証
│   └── lib.sh          素のシェル・アサーション関数（pip / bats 不使用）
├── LICENSE             CC BY-NC-SA 4.0（個人・研究・非営利は無償／営利は要申請）
└── README.md           本ファイル
```

## 安全設計（やらないこと）

- 実体の .deb をダウンロードしない（調査・シミュレーションのみ）。
- `apt update` をしない（apt ローカルインデックスを書き換えない）。最新化はダッシュボードに委ねる。
- `apt upgrade` / `apt full-upgrade` / `apt autoremove` を実行しない。
- ダッシュボード機構（`dgx-dashboard.service` / `dgx-dashboard-admin.service`）の停止・再起動・設定変更をしない（観測のみ）。
- `sudo` を要する操作をスキルから実行しない（必要時はユーザー向け手動コマンドの提示のみ）。

これらは `scripts/config.sh` の **許可コマンド allowlist**（default-deny）で構造的に担保し、
`tests/test_static.sh` が「禁止コマンドがスクリプトに含まれないこと」を毎回 grep で機械検証します。

## テスト

```bash
bash ~/.claude/skills/dgx-update-check/tests/run_all.sh
```
依存は OS 同梱の `jq` と `python3` のみ（pip / bats 不使用）。実機テストは read-only なので安全で、
collect.sh 実行前後で apt インデックス mtime・ダッシュボード 2 サービスの状態が不変であることを自動確認します。

## 動作環境

ARM64（`aarch64`）/ Ubuntu 24.04（noble）。`nvidia-spark-ota-check` が存在する DGX Spark（GX10）。
前提を満たさない場合は理由を添えて中止します。

## ライセンス

CC BY-NC-SA 4.0（個人・研究・非営利は無償／営利は要申請）。詳細は [LICENSE](LICENSE) を参照してください。
本スキルは [claude-skills](https://github.com/nob-git-dev/claude-skills) リポジトリの一部であり、
sdlc-skills / learning-skills と同じライセンス方針です。
