# Contributing

Claude SDLC Skills へのコントリビューションを歓迎します。

## スタンス

本プロジェクトは個人プロジェクトで、保守はベストエフォートです。
Issue や Pull Request の対応には時間がかかる場合があります。ご理解ください。

## Issue の報告

### バグ報告 (特に誤検知)

PreToolUse ガードの誤検知・見逃しは最優先で改善したい領域です。以下の情報を添えてください:

- 実行したコマンド（機密情報は伏せ字で）
- 期待した結果 vs 実際の結果
- `~/.claude/hooks/guard-bash.sh` のバージョン（git commit hash）
- OS / シェル / Claude Code のバージョン

### 機能提案

- 提案の動機（何が困っているか、なぜ必要か）
- 既存スキル / エージェントで実現できないか検討した結果
- 想定される副作用・衝突

## Pull Request

### 受け入れ基準

新しいスキル・エージェントを追加する場合、以下を満たしてください:

1. **500 行以内** — 公式推奨に従う
2. **原典に基づく** — 方法論書籍・論文を参考文献に明記
3. **汎用性** — 特定のプロジェクト・言語・フレームワークに依存しない
4. **既存パターンとの整合** — 既存の SKILL.md と同じ構造（原則・実行フロー・アンチパターン）
5. **description フィールドの明確さ** — Claude が自動起動判断しやすい記述

### フック改善の PR

- 誤検知を減らす場合: テストケース（before/after）を必ず添付
- 新パターン追加の場合: 実世界の例とリスクの説明

### コミットメッセージ

Conventional Commits を推奨（必須ではない）:

```
feat(skills): 新スキル foo を追加
fix(hooks): guard-bash.sh の誤検知を修正
docs(readme): Quick Start を更新
```

## 開発環境

### ローカルでの動作確認

```bash
# install.sh のドライラン（CLAUDE_DIR を変えて本番に影響を与えない）
CLAUDE_DIR=/tmp/claude-test ./scripts/install.sh

# フックの単体テスト
echo '{"tool_input":{"command":"DROP TABLE test"}}' | hooks/guard-bash.sh
echo $?  # → 2 が期待値
```

### スキル作成のガイド

1. `skills/<name>/SKILL.md` を作成
2. YAML フロントマターに `name`, `description`, `context: fork`（オーケストレーター以外）
3. 本文は 6〜8 セクション（原則・実行フロー・アンチパターン等）
4. 既存スキルを参考に

## ライセンス

コントリビューションは MIT License のもとで受け入れられます。
PR を送信することで、あなたは貢献がこのライセンスで配布されることに同意するものとします。
