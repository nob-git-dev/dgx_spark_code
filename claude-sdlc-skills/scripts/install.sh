#!/bin/bash
# Claude SDLC Skills インストールスクリプト
#
# このスクリプトは skills/ と agents/ を ~/.claude/ に展開します。
# 既存のスキル/エージェントは上書きされるため、事前にバックアップしてください。

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"

echo "Claude SDLC Skills インストーラー"
echo "================================"
echo "リポジトリ: $REPO_DIR"
echo "インストール先: $CLAUDE_DIR"
echo ""

# バックアップ
if [ -d "$CLAUDE_DIR/skills" ] || [ -d "$CLAUDE_DIR/agents" ] || [ -d "$CLAUDE_DIR/hooks" ]; then
  BACKUP_DIR="$CLAUDE_DIR/.backup-$(date +%Y%m%d-%H%M%S)"
  echo "既存のスキル/エージェント/フックを $BACKUP_DIR にバックアップします..."
  mkdir -p "$BACKUP_DIR"
  [ -d "$CLAUDE_DIR/skills" ] && cp -r "$CLAUDE_DIR/skills" "$BACKUP_DIR/"
  [ -d "$CLAUDE_DIR/agents" ] && cp -r "$CLAUDE_DIR/agents" "$BACKUP_DIR/"
  [ -d "$CLAUDE_DIR/hooks" ] && cp -r "$CLAUDE_DIR/hooks" "$BACKUP_DIR/"
  echo "バックアップ完了"
  echo ""
fi

# インストール
mkdir -p "$CLAUDE_DIR/skills" "$CLAUDE_DIR/agents" "$CLAUDE_DIR/hooks"

echo "スキルをインストール中..."
cp -r "$REPO_DIR/skills/"* "$CLAUDE_DIR/skills/"
for skill in "$CLAUDE_DIR/skills/"*/; do
  echo "  - $(basename "$skill")"
done

echo ""
echo "エージェントをインストール中..."
cp -r "$REPO_DIR/agents/"* "$CLAUDE_DIR/agents/"
for agent in "$CLAUDE_DIR/agents/"*.md; do
  echo "  - $(basename "$agent" .md)"
done

echo ""
echo "フック（PreToolUse ガード）をインストール中..."
cp "$REPO_DIR/hooks/guard-bash.sh" "$CLAUDE_DIR/hooks/"
cp "$REPO_DIR/hooks/guard-write.sh" "$CLAUDE_DIR/hooks/"
chmod +x "$CLAUDE_DIR/hooks/guard-bash.sh" "$CLAUDE_DIR/hooks/guard-write.sh"
echo "  - guard-bash.sh (Bash 危険操作のブロック)"
echo "  - guard-write.sh (Write/Edit 危険操作のブロック)"

echo ""
echo "================================"
echo "インストール完了"
echo ""
echo "有効化するための手動作業:"
echo ""
echo "1. Supervisor の常駐化:"
echo "   $CLAUDE_DIR/settings.json に追加:"
echo "     \"agent\": \"supervisor\""
echo ""
echo "2. PreToolUse ガードの有効化:"
echo "   $REPO_DIR/hooks/settings-snippet.json を参考に"
echo "   $CLAUDE_DIR/settings.json の hooks.PreToolUse にマージしてください"
echo "   （YOUR_USER を実際のユーザー名に置換）"
echo ""
echo "3. 起動時指定で試す場合:"
echo "   claude --agent supervisor"
echo ""
