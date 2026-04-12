#!/bin/bash
# UserPromptSubmit hook: ユーザー発言から開発タスクを検出し、/sdlc への誘導を提案
#
# 目的: Supervisor エージェントが起動していない場合のバックアップ
# 動作: 開発関連キーワードを検出したら system-reminder を追加
#
# 入出力:
#   stdin: { "prompt": "...", ... } の JSON
#   stdout: system-reminder を追加（Claude のコンテキストに注入）
#   exit 0: 正常

set -eu

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null || echo "")

if [ -z "$PROMPT" ]; then
  exit 0
fi

# 既に /sdlc や /tdd 等を明示的に呼んでいる場合はスキップ
if echo "$PROMPT" | grep -E '^/(sdlc|tdd|spec|architect|review|deploy|sre|observe|security|ddd|refactor|ui)\b' > /dev/null; then
  exit 0
fi

# 開発タスクを示唆するキーワード
DEV_KEYWORDS='(実装|追加|修正|バグ|デプロイ|リファクタ|機能|エラー|テーブル|カラム|スキーマ|画面|コンポーネント|API|エンドポイント)'

# 危険信号（Supervisor でも扱うが、万が一のため警告）
# 日本語動詞の活用に対応: 消す/消し/消え, 削除, 破壊など
DANGER_KEYWORDS='(削除|消(す|し|え|そ|さ)|壊す|壊し|drop|truncate|本番|production|マイグレーション|force[ -]push|reset[ -]-hard)'

HAS_DEV=false
HAS_DANGER=false

if echo "$PROMPT" | grep -iE "$DEV_KEYWORDS" > /dev/null; then
  HAS_DEV=true
fi

if echo "$PROMPT" | grep -iE "$DANGER_KEYWORDS" > /dev/null; then
  HAS_DANGER=true
fi

# どちらも該当しなければ何も出力しない
if [ "$HAS_DEV" = "false" ] && [ "$HAS_DANGER" = "false" ]; then
  exit 0
fi

# system-reminder を stdout に出力
# Claude Code は stdout をプロンプトに追加する仕様
echo ""
echo "<system-reminder>"

if [ "$HAS_DANGER" = "true" ]; then
  echo "⚠️ 危険信号を含む可能性のあるプロンプトを検出しました。"
  echo ""
  echo "以下の方法で安全に進めることを推奨します:"
  echo "1. Supervisor エージェントが有効なら、自動で適切なスキル経由に誘導されます"
  echo "2. Supervisor が無効なら、/sdlc [タスク内容] で明示的にオーケストレーターを起動してください"
  echo "3. 不可逆操作は PreToolUse ガードで自動ブロックされます（最終防衛線）"
elif [ "$HAS_DEV" = "true" ]; then
  echo "開発タスクの可能性を検出しました。"
  echo ""
  echo "推奨される進め方:"
  echo "- Supervisor エージェント（claude --agent supervisor）経由で自動判断"
  echo "- または /sdlc [タスク内容] で直接オーケストレーター起動"
fi

echo ""
echo "このリマインダーは ~/.claude/hooks/suggest-sdlc.sh によるものです。"
echo "</system-reminder>"

exit 0
