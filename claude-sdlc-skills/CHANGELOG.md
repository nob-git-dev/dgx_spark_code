# Changelog

本リポジトリの変更履歴。[Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) 形式、[Semantic Versioning](https://semver.org/lang/ja/) 準拠。

## [0.1.0] - 2026-04-12

初回公開リリース。

### Added

#### Skills (12)
- `sdlc/` — SDLC オーケストレーター
- `spec/` — 仕様定義
- `architect/` — クリーンアーキテクチャ + ADR 記録
- `tdd/` — Uncle Bob の三法則 + Red-Green-Refactor
- `ui/` — UI/UX 設計 + React コンポーネント
- `review/` — コードレビュー（OWASP + Google 実践）
- `deploy/` — 継続的デリバリー
- `sre/` — SLO/SLI/エラーバジェット
- `observe/` — ログ・メトリクス・トレース三本柱
- `security/` — Shift-Left + STRIDE 脅威モデリング
- `ddd/` — ユビキタス言語・境界づけられたコンテキスト
- `refactor/` — Fowler のカタログ + Feathers のレガシーコード手法

#### Subagents (4)
- `supervisor.md` — セッション常駐の監視役。意図分類・危険信号検知・スキル起動判断
- `review.md` — memory 付きコードレビュー拡張版
- `deploy.md` — memory + `permissionMode: default` 付きデプロイ拡張版
- `ddd.md` — memory でユビキタス言語を永続化

#### Hooks (3)
- `guard-bash.sh` — PreToolUse: 破壊的 Bash コマンドをブロック
- `guard-write.sh` — PreToolUse: 危険な Write/Edit をブロック
- `suggest-sdlc.sh` — UserPromptSubmit: 開発タスクで `/sdlc` を推奨

#### Scripts & Docs
- `scripts/install.sh` — バックアップ付きインストールスクリプト
- `hooks/settings-snippet.json` — `settings.json` 統合テンプレート
- `docs/design-decisions.md` — 設計判断の記録
- `docs/pretooluse-guards.md` — ガード仕様と誤検知対応

### Security

- シークレット（API キー、パスワード、トークン）の埋め込みなし
- ハードコードされた IP アドレス・ホスト名なし
- プロジェクト固有識別子は匿名化済み（`myapp_prod` / `myapp_test` 等のプレースホルダ）
