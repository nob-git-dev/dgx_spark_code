# Claude SDLC Skills

[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](LICENSE)
[![Commercial License Available](https://img.shields.io/badge/Commercial%20License-Available-blue.svg)](LICENSE-COMMERCIAL.md)

**Claude Code にソフトウェア開発ライフサイクル（SDLC）の規律を強制する、スキル・エージェント・フックのセット。**

AI エージェントに開発を任せる際、「仕様 → 設計 → TDD → レビュー → デプロイ」のプロセスを守らせ、
本番 DB 消失や force push などの**致命的な操作を物理的にブロック**します。

## Quick Start

```bash
# dgx_spark_code リポジトリの一部として配布されています
git clone https://github.com/nob-git-dev/dgx_spark_code.git
cd dgx_spark_code/claude-sdlc-skills
./scripts/install.sh
```

サブディレクトリだけ取得したい場合は [sparse-checkout](https://git-scm.com/docs/git-sparse-checkout) を利用できます:

```bash
git clone --no-checkout https://github.com/nob-git-dev/dgx_spark_code.git
cd dgx_spark_code
git sparse-checkout init --cone
git sparse-checkout set claude-sdlc-skills
git checkout main
cd claude-sdlc-skills
./scripts/install.sh
```

次に `~/.claude/settings.json` に以下を追加:

```json
{
  "agent": "supervisor",
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{"type": "command", "command": "/Users/YOUR_USER/.claude/hooks/guard-bash.sh", "timeout": 3}] },
      { "matcher": "Write|Edit", "hooks": [{"type": "command", "command": "/Users/YOUR_USER/.claude/hooks/guard-write.sh", "timeout": 3}] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{"type": "command", "command": "/Users/YOUR_USER/.claude/hooks/suggest-sdlc.sh", "timeout": 3}] }
    ]
  }
}
```

> `hooks/settings-snippet.json` にテンプレートがあります。`YOUR_USER` を置換してください。

これで次回 `claude` 起動時から Supervisor が常駐し、開発タスクを自動で `/sdlc` オーケストレーターに誘導します。

## 何が得られるか

### 1. プロセスの強制

ユーザーが「機能を追加したい」と言うだけで、Supervisor が:

1. タスク種別を分類（新機能 / バグ修正 / リファクタ / UI / 障害対応）
2. 危険信号（削除・本番・マイグレーション等）を検知
3. `/sdlc` オーケストレーター経由で適切なフェーズを順次実行:
   - `/spec`（仕様） → `/architect`（設計＋ADR） → `/tdd`（テスト駆動） → `/review`（品質ゲート）
4. 各フェーズ完了時にユーザー承認を求める

### 2. 致命的操作の物理ブロック

PreToolUse フックが、Claude がツール実行する**直前**に以下をブロック:

| カテゴリ | 例 |
|---|---|
| DB 破壊操作 | `DROP TABLE`, `TRUNCATE`, WHERE 句なし DELETE/UPDATE |
| 本番 DB 接続 | `psql ... *_prod` 等 |
| ファイルシステム破壊 | `rm -rf /`, `rm -rf ~`, システムディレクトリ削除 |
| 危険な Git 操作 | `main/master` への force push, `reset --hard`, `clean -f`, `branch -D` |
| 昇格 | `sudo`（Claude からの実行を禁止） |
| 機密情報露出 | `.env` / `.pem` / `.key` の書き込み、API キー混入、全環境変数ダンプ |

### 3. 学習するサブエージェント

`review`, `deploy`, `ddd` は `memory: project` 付きのサブエージェント版も提供。
プロジェクト固有のパターン・ユビキタス言語・デプロイ履歴を蓄積し、時間と共に精度が上がります。

## 構成

```
.
├── skills/         12 個のスキル（SDLC の各フェーズ）
│   ├── sdlc/       オーケストレーター
│   ├── spec/       仕様定義
│   ├── architect/  アーキテクチャ設計 + ADR
│   ├── tdd/        テスト駆動開発
│   ├── ui/         UI/UX 設計 + React
│   ├── review/     コードレビュー
│   ├── deploy/     デプロイメント
│   ├── sre/        SLO/SLI/障害対応
│   ├── observe/    オブザーバビリティ
│   ├── security/   セキュリティ（OWASP + STRIDE）
│   ├── ddd/        ドメイン駆動設計
│   └── refactor/   リファクタリング
├── agents/         4 個のサブエージェント
│   ├── supervisor.md  セッション常駐の監視役
│   ├── review.md      memory 付き拡張版
│   ├── deploy.md      memory + 権限モード付き拡張版
│   └── ddd.md         memory で用語集永続化
├── hooks/          3 個のフック
│   ├── guard-bash.sh      PreToolUse: Bash 危険操作ブロック
│   ├── guard-write.sh     PreToolUse: Write/Edit 危険操作ブロック
│   └── suggest-sdlc.sh    UserPromptSubmit: 開発タスク誘導
├── scripts/
│   └── install.sh
└── docs/
    ├── design-decisions.md     設計判断の記録
    └── pretooluse-guards.md    PreToolUse ガード仕様
```

## アーキテクチャ

```
User
  ↓ claude --agent supervisor
  ↓
Supervisor Agent (常駐、memory: project)
  ├ 意図を分類（開発か？雑談か？危険か？）
  ├ 危険信号検知（削除・本番・マイグレーション）
  └ 承認後に /sdlc を起動
        ↓
      /sdlc (オーケストレーター、メインコンテキスト)
        ├ タスク種別に応じてフローを決定
        └ Skill ツールで専門スキルを順次起動
              ↓
            /spec, /architect, /tdd, /ui, /review, ... (subagent, 隔離実行)
                  ↓
                [ツール実行前] PreToolUse Guards
                  ├ guard-bash.sh: 危険な Bash コマンドをブロック
                  └ guard-write.sh: 危険な書き込みをブロック
```

## 設計原則

1. **本質を書く** — 特定のコマンドや手順ではなく、方法論と行動原則
2. **原典に基づく** — Uncle Bob, Kent Beck, Fowler, Evans, Google SRE 等
3. **汎用** — どのプロジェクト・言語・フレームワークでも適用可能
4. **3 層防御** — Supervisor + Hooks + PreToolUse、単一の仕組みに依存しない
5. **500 行以内** — 公式推奨に従い、詳細はサポートファイルに分離可能

## なぜこれを作ったか

AI エージェントに開発を任せていたプロジェクトで、本番データベースのデータ全消失事故を**短期間に 2 回**経験しました。
`CLAUDE.md` にルールを書いても、メモリに記録しても、AI の「うっかり」は防げませんでした。

ルールではなく**構造でプロセスを強制する**必要がある — それが本リポジトリの出発点です。
詳細は [`docs/design-decisions.md`](docs/design-decisions.md) を参照してください。

## 注意事項

- **`install.sh` は既存の `~/.claude/skills/`, `~/.claude/agents/`, `~/.claude/hooks/` を上書きします**。
  実行前に `.backup-YYYYMMDD-HHMMSS/` に自動バックアップされますが、重要な独自スキルがある場合は事前確認してください。
- **PreToolUse ガードの正規表現には誤検知と見逃しの両方があります**（[`docs/pretooluse-guards.md`](docs/pretooluse-guards.md) 参照）。
  完全な保護ではなく「最終防衛線」として位置付けてください。
- **対応スタンス**: 個人プロジェクト、ベストエフォートでの保守。Issue / PR 歓迎。

## 動作確認済み環境

- macOS (Apple Silicon)
- Claude Code v2.1 以降
- bash, jq（macOS/Linux 標準）

## ライセンス

**デュアルライセンス構成**

| 利用目的 | ライセンス |
|---|---|
| 個人・研究・非営利・OSS（同ライセンスで公開） | [CC BY-NC-SA 4.0](LICENSE)（無償） |
| 営利企業での利用・商用サービスへの組み込み | [商用ライセンス](LICENSE-COMMERCIAL.md)（要申請） |

商用ライセンスのお問い合わせは [GitHub Issues](https://github.com/nob-git-dev/dgx_spark_code/issues) へ（タイトルに `[Commercial License]` を付けてください）。

## 関連ドキュメント

- [設計判断の記録](docs/design-decisions.md)
- [PreToolUse ガード仕様](docs/pretooluse-guards.md)
- 各スキル/エージェント/フックの内部 `.md` ファイル
