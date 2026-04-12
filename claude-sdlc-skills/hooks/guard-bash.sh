#!/bin/bash
# PreToolUse ガード: Bash コマンドの危険操作を物理ブロック
#
# 目的: Supervisor や /sdlc の判断ミスがあっても、最終防衛線としてここで止める
# 背景: 過去の本番 DB 消失事故の再発防止のために設計
#
# 入出力:
#   stdin: { "tool_input": { "command": "..." }, ... } の JSON
#   exit 0: 許可
#   exit 2: ブロック（stderr のメッセージが Claude に伝わる）
#
# 方針:
#   - 明確な破壊的操作はブロック
#   - 曖昧なものは警告付きブロック（ユーザー判断に委ねる）
#   - 誤検知でも「安全側」に倒す

set -eu

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")

if [ -z "$COMMAND" ]; then
  exit 0
fi

block() {
  echo "BLOCKED: $1" >&2
  echo "コマンド: $COMMAND" >&2
  echo "このブロックは ~/.claude/hooks/guard-bash.sh によるものです" >&2
  exit 2
}

# ============================================================
# 1. DB 破壊的操作（最優先ガード）
# ============================================================

# DROP DATABASE / TABLE / SCHEMA
if echo "$COMMAND" | grep -iE '\bDROP\s+(DATABASE|TABLE|SCHEMA|INDEX)\b' > /dev/null; then
  block "DROP 系コマンドは /deploy スキル経由で段階実行してください"
fi

# TRUNCATE
if echo "$COMMAND" | grep -iE '\bTRUNCATE\s+(TABLE\s+)?[a-zA-Z_]+' > /dev/null; then
  block "TRUNCATE は /deploy スキル経由で実行してください"
fi

# WHERE 句なしの DELETE (最も危険: 過去の DB 消失事故の直接原因パターン)
# "DELETE FROM table;" "DELETE FROM table" のパターンを検知
if echo "$COMMAND" | grep -iE '\bDELETE\s+FROM\s+[a-zA-Z_]+\s*[;)]?\s*(["\'']|$)' > /dev/null; then
  if ! echo "$COMMAND" | grep -iE '\bDELETE\s+FROM\s+[a-zA-Z_]+\s+WHERE\b' > /dev/null; then
    block "WHERE 句なしの DELETE は全件削除です（本番データ消失のリスク）"
  fi
fi

# WHERE 句なしの UPDATE (全件更新)
if echo "$COMMAND" | grep -iE '\bUPDATE\s+[a-zA-Z_]+\s+SET\b' > /dev/null; then
  if ! echo "$COMMAND" | grep -iE '\bUPDATE\s+[a-zA-Z_]+\s+SET\s+.*\s+WHERE\b' > /dev/null; then
    block "WHERE 句なしの UPDATE は全件更新になる可能性があります"
  fi
fi

# ============================================================
# 2. 本番環境への接続
# ============================================================

# 本番 DB 名が DB クライアントコマンドの引数として使われている場合のみ検知
# （git commit メッセージ等での言及は除外）
if echo "$COMMAND" | grep -iE '\b(psql|mysql|mongosh|redis-cli|pg_dump|pg_restore)\b[^|&;]*\b(production_db|prod_db|[a-z_]+_prod)\b' > /dev/null; then
  block "本番 DB への操作は /deploy スキル経由で承認が必要です"
fi

# DB 接続環境変数・URL に本番が含まれる
if echo "$COMMAND" | grep -iE '(DATABASE_URL|DB_HOST|PGHOST)=[^|&;]*\b(prod|production)' > /dev/null; then
  block "本番環境の接続情報を設定しようとしています"
fi

# 本番っぽい接続文字列（リテラル）
if echo "$COMMAND" | grep -iE 'postgres(ql)?://[^"\s]*@[^"\s]*\.(prod|production)\.' > /dev/null; then
  block "本番環境への接続文字列を検出しました"
fi

# ============================================================
# 3. 破壊的ファイル操作
# ============================================================

# rm -rf が実コマンドとして使われている場合のみ検知
# （コマンドの先頭、または && / ; / | の直後）
# 引用符内の言及は除外
RM_PATTERN='(^|[&;|]\s*)rm\s+-[rRfF]{1,2}\s+'

# rm -rf /  rm -rf ~  rm -rf $HOME など、ホーム/ルート直下の削除
if echo "$COMMAND" | grep -E "${RM_PATTERN}(/\s*$|/\s+[^\"'\`]|~\s*$|~/\s*$|\\\$HOME\s*$)" > /dev/null; then
  block "ホームディレクトリまたはルート直下の rm -rf は致命的です"
fi

# rm -rf でシステムディレクトリ
if echo "$COMMAND" | grep -E "${RM_PATTERN}(/etc|/usr|/var|/bin|/sbin|/System|/Applications)(/|\s|$)" > /dev/null; then
  block "システムディレクトリの削除を検出しました"
fi

# ============================================================
# 4. 危険な Git 操作
# ============================================================

# main/master への force push（パターン2種類）
if echo "$COMMAND" | grep -iE 'git\s+push\s+[^\|&;]*(-f|--force|--force-with-lease)\s+[^\|&;]*\b(main|master)\b' > /dev/null; then
  block "main/master への force push は明示的な承認が必要です"
fi
if echo "$COMMAND" | grep -iE 'git\s+push\s+[^\|&;]*\b(main|master)\b\s+[^\|&;]*(-f|--force)' > /dev/null; then
  block "main/master への force push は明示的な承認が必要です"
fi

# git reset --hard
if echo "$COMMAND" | grep -iE 'git\s+reset\s+--hard' > /dev/null; then
  block "git reset --hard は未コミットの変更を失います。git stash を検討してください"
fi

# git clean -f (untracked ファイル削除)
if echo "$COMMAND" | grep -iE 'git\s+clean\s+-[fd]{1,2}' > /dev/null; then
  block "git clean -f は追跡されていないファイルを削除します。対象を確認してください"
fi

# git branch -D (強制ブランチ削除)
if echo "$COMMAND" | grep -iE 'git\s+branch\s+-D\b' > /dev/null; then
  block "git branch -D は未マージのブランチを強制削除します"
fi

# ============================================================
# 5. sudo 使用（原則ブロック）
# ============================================================

if echo "$COMMAND" | grep -E '(^|[;&|]\s*)sudo\s' > /dev/null; then
  block "sudo 使用はユーザーが直接実行してください（Claude からの実行は禁止）"
fi

# ============================================================
# 6. 認証情報の露出
# ============================================================

# シークレットファイルの cat / less
if echo "$COMMAND" | grep -iE '(cat|less|head|tail)\s+[^\|&;]*\.(env|pem|key|credentials)' > /dev/null; then
  block "シークレットファイルの内容表示はブロックされます。必要なら環境変数名のみ参照してください"
fi

# 全環境変数のダンプ
if echo "$COMMAND" | grep -E '^(env|printenv)\s*$' > /dev/null; then
  block "全環境変数のダンプはシークレット露出のリスクがあります。特定の変数を名指ししてください"
fi

exit 0
