# 設計判断の記録

このドキュメントは、本リポジトリの SDLC スキル群・Supervisor エージェント・PreToolUse ガードの
設計判断を、背景と意図を含めて記録するものです。

---

## 1. 背景

### 1.1 発端となった事故

ある自社プロダクトの開発中、AI エージェント（Claude Code）を用いた作業中に、
本番データベースのデータ全消失事故が**短期間に 2 回**発生した。

| 回 | 原因の要旨 | 被害 |
|---|---|---|
| 1 回目 | pytest の conftest が本番 DB に接続し、WHERE 句なしの `DELETE FROM <table>` を実行 | 主要テーブルのデータ全消失 |
| 2 回目 | Docker コンテナ内でのインラインテスト (`python -c`) 実行時、DB 接続先をテスト環境に切り替え忘れ | 数千件の主要データ全消失 |

### 1.2 対策の変遷と限界

事故後、段階的に対策を重ねたが、いずれも限界があった:

| 対策 | 効果 |
|---|---|
| conftest.py にガード追加 | pytest 経由でのみ有効。インラインスクリプトは防げず |
| AI のメモリに「テスト DB 分離必須」と記録 | 記憶に頼る運用。時間が経つと忘れて再発 |
| `CLAUDE.md` にルール追記 | 読んで守るかは実行者次第 |
| DB 接続層の SafeConnection ガード | 本番 DB の全件 DELETE を物理ブロック。**最終防衛線として有効** |

### 1.3 根本原因

ルールを書いても守れなかった。メモリに記録しても忘れた。構造的な問題として:

1. **プロセスが AI の記憶と判断に依存していた**
2. **各フェーズの専門家がいなかった** — TDD の規律を問う仕組みがなかった
3. **オーケストレーターがいなかった** — どのフェーズでどの専門家を呼ぶかの判断が不在

---

## 2. 解決アプローチ

**行動そのものをスキル／エージェント／フックとして定義し、プロセスを強制する仕組みを構築する。**

### 2.1 3 層構造

```
Layer 1: Supervisor Agent (セッション常駐)
  ↓ ユーザー意図の分類・危険信号検知
Layer 2: /sdlc Orchestrator (開発プロセス統制)
  ↓ タスク種別に応じた専門スキルの順次起動
Layer 3: 専門スキル (各フェーズの規律)
  ↓ 隔離コンテキストで専門的作業を実行

[終端]: PreToolUse Guards (危険操作の物理ブロック)
```

### 2.2 役割分担

- **Supervisor**: 「これは開発案件か？どこに振るか？」= 受付・交通整理
- **/sdlc**: 「どのフェーズで、どのスキルを、どの順で？」= 現場監督
- **専門スキル**: 「このフェーズで何をするか」= 各専門家

---

## 3. 重要な設計判断

### 3.1 Skills か Subagents か

**判断**: 専門スキルは Skill、Supervisor は Subagent

| 役割 | 選択 | 理由 |
|---|---|---|
| /sdlc | Skill (`context: fork` なし) | メインコンテキストで動き、他スキルを順次起動する必要がある |
| 専門スキル | Skill (`context: fork` あり) | 隔離実行で結果のサマリーだけメインに戻す |
| Supervisor | Subagent | `memory`, `initialPrompt`, `hooks` などの追加機能が必要 |

### 3.2 オーケストレーターは `context: fork` を付けない

**原則**: `/sdlc` はメインコンテキストで動作し、Skill ツールで専門スキルを呼ぶ。
**根拠**: Claude Code 公式ドキュメント「サブエージェントは他のサブエージェントを生成できない」。
`/sdlc` を fork subagent にすると、専門スキル（同じく fork）を呼べなくなる。

### 3.3 Supervisor の必要性

**問題**: 開発経験が限られるユーザーには「いつ `/sdlc` を起動すべきか」が判断できない。
**解決**: セッション開始時から常駐する Supervisor が、ユーザー発言を分類して自動起動判断。
**効果**: ユーザーが「普通に話す」だけで、必要なスキルが適切なタイミングで起動する。

### 3.4 Agent Teams を採用しない理由

**検討結果**: 現時点では採用しない。

- SDLC フローは**逐次的**で、並行実行のメリットが小さい
- 専門家同士が**議論する必要がない**（オーケストレーター経由で受け渡す）
- Agent Teams は**実験的機能**でトークンコストが高い

**将来検討**: `/review` の多観点並行レビュー、`/sre` の障害調査など。

### 3.5 memory 付き Subagent 版の用意

`/review`, `/deploy`, `/ddd` については、**スキル版とサブエージェント版の両方**を提供している:

- **スキル版** (`skills/review/SKILL.md` 等): 軽量・単発用途
- **サブエージェント版** (`agents/review.md` 等): `memory: project` で学習を永続化

用途に応じて使い分け、プロジェクトの成熟と共に subagent 版の価値が増す設計。

---

## 4. 3 層防御

事故の再発を防ぐため、**単一の仕組みに依存しない多重防御**を設計:

```
Layer 1: Supervisor エージェント
   - 意図分類、危険信号検知、スキル起動判断
Layer 2: Hooks (UserPromptSubmit)
   - Supervisor が見逃した場合の自動トリガー
Layer 3: PreToolUse ガード
   - 危険操作を物理的にブロック（SafeConnection ガードパターンの汎用化）
```

この設計により、Supervisor の判断ミスがあっても、Hooks がバックアップし、
最終的に PreToolUse ガードで物理的に危険操作が止まる。

---

## 5. 参考文献

### 方法論
- Robert C. Martin "Clean Architecture", "Three Laws of TDD"
- Kent Beck "Test Driven Development: By Example"
- Martin Fowler "Refactoring"
- Eric Evans "Domain-Driven Design"
- Jez Humble & David Farley "Continuous Delivery"
- Google "Site Reliability Engineering"
- Charity Majors "Observability Engineering"
- Adam Shostack "Threat Modeling"
- OWASP Top 10, NIST SSDF

### エージェント設計
- Addy Osmani "Conductors to Orchestrators"
- Anthropic "Claude Code Skills" 公式ドキュメント
- Anthropic "Subagents" 公式ドキュメント
- Anthropic "Agent Teams" 公式ドキュメント
- InfoQ "Agentic AI Patterns"

### UI/UX
- Nielsen Norman Group "10 Usability Heuristics"
- WCAG 2.1 (W3C)
- Kent C. Dodds "Testing Library Principles"
