#!/bin/bash
# dgx-update-check インストールスクリプト
#
# このスクリプトは dgx-update-check スキルを ~/.claude/skills/ に展開します。
# 既存の dgx-update-check は上書きされるため、事前にバックアップしてください。

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SKILL_NAME="dgx-update-check"
DST="$CLAUDE_DIR/skills/$SKILL_NAME"

echo "dgx-update-check インストーラー"
echo "================================"
echo "リポジトリ: $REPO_DIR"
echo "インストール先: $DST"
echo ""

# 動作環境チェック（スキルの前提と同じ：ARM64 / Ubuntu 24.04 / nvidia-spark-ota-check）
if [ "$(uname -m)" != "aarch64" ]; then
  echo "⚠️ 警告: アーキテクチャが aarch64 ではありません ($(uname -m))。" >&2
  echo "   このスキルは DGX Spark（GX10・ARM64）用です。インストールは続行できますが、起動時に preflight で停止します。" >&2
  echo ""
fi
if ! command -v nvidia-spark-ota-check >/dev/null 2>&1; then
  echo "⚠️ 警告: nvidia-spark-ota-check コマンドが見つかりません。" >&2
  echo "   このスキルは DGX Spark の OTA チェックツールを使用します。インストールは続行できますが、起動時に preflight で停止します。" >&2
  echo ""
fi

# バックアップ
if [ -d "$DST" ]; then
  BACKUP_DIR="$CLAUDE_DIR/.backup-$SKILL_NAME-$(date +%Y%m%d-%H%M%S)"
  echo "既存の $SKILL_NAME を $BACKUP_DIR にバックアップします..."
  mkdir -p "$BACKUP_DIR"
  cp -r "$DST" "$BACKUP_DIR/"
  echo "バックアップ完了"
  echo ""
fi

# インストール
mkdir -p "$DST"
echo "スキルファイルをコピー中..."
cp "$REPO_DIR/SKILL.md" "$DST/"
cp "$REPO_DIR/README.md" "$DST/"
cp -r "$REPO_DIR/scripts" "$DST/"
cp -r "$REPO_DIR/tests" "$DST/"
[ -f "$REPO_DIR/LICENSE" ] && cp "$REPO_DIR/LICENSE" "$DST/"
chmod +x "$DST/scripts/collect.sh" "$DST/tests/"*.sh

echo "  - SKILL.md"
echo "  - README.md"
echo "  - scripts/ (collect.sh, build_json.py, config.sh)"
echo "  - tests/ (run_all.sh, test_static.sh, test_runtime.sh, test_glob.sh, lib.sh)"
echo ""

# 動作確認のためのテスト実行（read-only・安全）
echo "動作確認のためテストを実行します（read-only・副作用ゼロ）..."
echo ""
if bash "$DST/tests/run_all.sh" >/dev/null 2>&1; then
  echo "✅ 全テスト PASS"
else
  echo "⚠️ テストに失敗があります。詳細は次のコマンドで確認できます:" >&2
  echo "   bash $DST/tests/run_all.sh" >&2
fi
echo ""

echo "================================"
echo "インストール完了"
echo ""
echo "使い方："
echo "  Claude のチャットで「DGX のアップデート何が来てる？」「更新前に確認したい」"
echo "  などと頼むと起動します。または /dgx-update-check と直接打鍵してもOK。"
echo ""
echo "データ層スクリプトを直接確認する場合（read-only・安全）："
echo "  bash $DST/scripts/collect.sh | jq ."
