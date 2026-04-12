#!/bin/bash
# PreToolUse ガード: Write/Edit ツールの危険操作を物理ブロック
#
# 目的: シークレット・設定ファイルへの不用意な書き込みを防ぐ
#
# 入出力:
#   stdin: { "tool_input": { "file_path": "..." }, ... } の JSON
#   exit 0: 許可
#   exit 2: ブロック

set -eu

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // empty' 2>/dev/null || echo "")

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

block() {
  echo "BLOCKED: $1" >&2
  echo "対象ファイル: $FILE_PATH" >&2
  echo "このブロックは ~/.claude/hooks/guard-write.sh によるものです" >&2
  exit 2
}

# ============================================================
# 1. シークレットファイルへの書き込み
# ============================================================

if echo "$FILE_PATH" | grep -iE '\.(env|pem|key|credentials)$' > /dev/null; then
  block "シークレットファイルへの書き込みはユーザーが直接行ってください"
fi

if echo "$FILE_PATH" | grep -iE '(\.env\.|credentials\.json|secrets\.)' > /dev/null; then
  block "シークレット系ファイルへの書き込みはユーザーが直接行ってください"
fi

# ============================================================
# 2. 書き込み内容にシークレットらしきもの
# ============================================================

if [ -n "$CONTENT" ]; then
  # API キーらしきパターン
  if echo "$CONTENT" | grep -iE '(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*["\x27]?[a-zA-Z0-9_\-]{20,}' > /dev/null; then
    block "書き込み内容に API キー・トークンらしきものが含まれています。環境変数を使用してください"
  fi

  # AWS 認証情報パターン
  if echo "$CONTENT" | grep -E 'AKIA[0-9A-Z]{16}' > /dev/null; then
    block "AWS Access Key ID らしきパターンを検出しました"
  fi
fi

# ============================================================
# 3. ~/.claude/ 配下の書き込み制限
# ============================================================

# settings.json は正当な用途で編集する必要があるため許可
# （ユーザーに Write の承認ダイアログが出るため、明示的な同意は得られる）
# その他の直下 .json はブロック（内部ファイルの可能性があるため）
if echo "$FILE_PATH" | grep -E '^/Users/[^/]+/\.claude/[^/]+\.json$' > /dev/null; then
  if ! echo "$FILE_PATH" | grep -E '^/Users/[^/]+/\.claude/settings\.json$' > /dev/null; then
    block "~/.claude/ 直下の .json ファイルは Claude Code 内部用の可能性があります。ユーザーが直接編集してください"
  fi
fi

exit 0
