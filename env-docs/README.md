# DGX Spark 環境ドキュメント テンプレート

NVIDIA DGX Spark（GB10）の環境情報を構造化して管理するためのテンプレートです。

AIエージェント（Claude Code等）がサーバーのリソースを正しく把握し、安全にアプリケーション開発・運用を行えるようにすることを目的としています。

## 対象読者

- DGX Spark / ASUS Ascent GX10 をローカルAIサーバーとして運用している個人・チーム
- Claude Code などのAIエージェントと連携して開発を行っている方

## ファイル構成

| ファイル | 内容 | 更新頻度 |
|----------|------|----------|
| `hardware.md` | ハードウェア仕様（CPU, GPU, メモリ, ストレージ） | 年単位 |
| `services.md` | 公開サービス一覧（エンドポイント, ポート, 用途） | 週〜月単位 |
| `network.md` | ネットワーク・SSH接続情報 | 月単位 |
| `policies.md` | 開発ルール・制約（Docker優先, pip禁止, ARM64必須等） | 変更時 |
| `snapshots/` | 生のシステムインベントリ（参考・検証用） | 手動取得 |
| `claude/gx10-sync-env.md` | Claude Code用スラッシュコマンド定義 | 変更時 |

## セットアップ

### 1. テンプレートをコピー

```bash
# ドキュメント用ディレクトリを作成
mkdir -p ~/projects/docs
cp -r env-docs/* ~/projects/docs/
cd ~/projects/docs && git init && git add -A && git commit -m "init: 環境ドキュメント初期化"
```

### 2. プレースホルダーを自分の環境に書き換え

各ファイル内の `{{...}}` で囲まれた箇所を、自分の環境の値に置き換えてください。

```
{{HOSTNAME}}       → 実際のホスト名（例: dgx-spark-01）
{{USERNAME}}       → ユーザー名
{{LAN_IP}}         → LAN内IPアドレス
{{VPN_IP}}         → VPN（Tailscale等）のIPアドレス
{{MODEL_NAME}}     → 導入済みモデル名
{{MODEL_PORT}}     → モデルのAPIポート番号
```

### 3. Claude Code スラッシュコマンドの設定

```bash
# Claude Codeのコマンドディレクトリにコピー
mkdir -p ~/.claude/commands
cp ~/projects/docs/claude/gx10-sync-env.md ~/.claude/commands/
```

これにより、Claude Code上で `/gx10-sync-env` と入力するだけで、自然言語で伝えた変更が自動的にドキュメントに反映されます。

### 4. スナップショットの取得（任意）

```bash
# システム情報を取得してスナップショットとして保存
~/projects/docs/snapshots/ に date, hostname, uname -a, nvidia-smi 等の出力を保存
```

## 使い方（AIエージェント向け）

1. まずこの `README.md` で全体像を把握する
2. `services.md` で利用可能なAPIとその接続先を確認する
3. `policies.md` で開発時の制約を確認する
4. 詳細が必要なら `hardware.md` や `network.md` を参照する
5. 生データが必要なら `snapshots/` を参照する

## Claude Code との連携

環境に変更を加えた際は、Claude Code上で以下のように伝えるだけでドキュメントが更新されます:

```
/gx10-sync-env Ollamaに新しいビジョンモデルを追加した
```

Claude Codeが変更内容を分析し、該当するファイルのみを編集して `git diff` を表示します。承認後にコミットされます。

## カスタマイズのヒント

- **サービスの追加:** `services.md` にセクションを追加。エンドポイント・ポート・プロトコル・Docker Network を記載する
- **モデルの追加:** Ollama/SGLang セクション内の「導入済みモデル」リストに追記
- **ポリシーの変更:** `policies.md` を更新し、CLAUDE.md にも反映する
- **メモリ安全:** 大型モデルの `num_ctx` を制限して OOM を防止する（128GB統合メモリの制約）
