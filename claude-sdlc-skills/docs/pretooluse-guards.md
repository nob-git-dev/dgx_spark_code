# PreToolUse ガード仕様

3層防御の**最終防衛線**として、危険な操作を物理的にブロックするフック。
Supervisor や `/sdlc` が判断ミスをしても、ここで止まる。

## 配置

```
~/.claude/hooks/
├── guard-bash.sh     — Bash ツールのコマンドをチェック
└── guard-write.sh    — Write/Edit ツールの書き込み先をチェック
```

`~/.claude/settings.json` の `hooks.PreToolUse` に登録することで有効化される。

## 動作原理

1. Claude がツール呼び出しを試みる
2. Claude Code が PreToolUse hook を起動し、ツール入力を JSON で stdin に渡す
3. フックがコマンドや書き込み先を検査
4. **Exit code 2 でブロック**（stderr メッセージが Claude に伝わる）
5. **Exit code 0 で許可**

ブロック時、Claude はエラー理由を受け取り、ユーザーに報告する。

## guard-bash.sh のブロック対象

| カテゴリ | 例 | 根拠 |
|---|---|---|
| DB 破壊的操作 | `DROP TABLE`, `TRUNCATE`, `DELETE FROM x;` (WHERE なし) | 過去の本番 DB 消失事故の教訓 |
| 全件 UPDATE | `UPDATE x SET y = z` (WHERE なし) | 意図しない全件更新 |
| 本番 DB 接続 | `*_prod`, `production_db`, 本番ホスト | 本番環境への直接操作防止 |
| 致命的ファイル削除 | `rm -rf /`, `rm -rf ~`, `rm -rf /etc` 等 | 回復不能な削除防止 |
| force push | `git push --force` を main/master に | 共有ブランチの破壊防止 |
| git reset --hard | 未コミット変更を失う | 作業消失防止 |
| git clean -f | 追跡外ファイル削除 | 作業消失防止 |
| git branch -D | 未マージブランチ強制削除 | 作業消失防止 |
| sudo | すべての sudo コマンド | 権限昇格の明示化 |
| シークレットの表示 | `cat .env`, `env`, `printenv` | 機密情報漏洩防止 |

## guard-write.sh のブロック対象

| カテゴリ | 例 |
|---|---|
| シークレットファイル | `.env`, `.pem`, `.key`, `credentials.json` |
| 書き込み内容に API キー | `api_key = "abc..."`, `AKIA...` |
| `~/.claude/` 直下の設定 | `settings.json` 等（skills/agents/hooks/projects 配下は除外） |

## 設計原則

1. **安全側に倒す**: 誤検知でもブロックする。ユーザーが判断して手動実行すればよい
2. **理由を明示**: ブロック時に「なぜ危険か」を stderr に出力
3. **スキル経由の正規ルート**を示す: 「/deploy スキル経由で段階実行してください」等
4. **プロジェクト特有パターンも一部含む**: `myapp_prod` 等。汎用化したい場合は別ファイルに分離

## テスト方法

```bash
# 安全なコマンド（許可される）
echo '{"tool_input":{"command":"ls -la"}}' | ~/.claude/hooks/guard-bash.sh
# → exit 0

# WHERE なし DELETE（ブロックされる）
echo '{"tool_input":{"command":"DELETE FROM articles;"}}' | ~/.claude/hooks/guard-bash.sh
# → exit 2, stderr にブロック理由
```

## 既知の制約・今後の課題

- **正規表現ベース**のため、複雑なコマンドで誤検知・見逃しの可能性がある
- ヒアドキュメントや `eval` 等を使った難読化は検知しきれない
- プロジェクト固有のパターン（本番 DB 名等）はハードコードされている
  - 将来的には `~/.claude/hooks/patterns/project-patterns.json` のような外部ファイルに分離したい
- フックは同期実行のため、タイムアウト（3秒）に注意

## 実装中に遭遇した誤検知と対応

Phase 3 の初期実装でパターンが広すぎ、以下の誤検知が発生した:

### ケース1: コミットメッセージ内の言及で本番 DB 検知が発動
コミットメッセージに本番 DB 名を含む文字列（例: 「myapp_prod の説明」）があった時、
本番 DB 接続と誤判定されブロックされた。

**対応**: DB 名の検知を**DB クライアントコマンド（psql, mysql 等）の引数として**
使われている場合に限定した。git commit 等のメッセージ内の言及は通過する。

### ケース2: コミットメッセージ内の `rm -rf /` 言及でブロック
コミットメッセージに「rm -rf / (hooks)」のような文字列があると
rm -rf / と誤判定された。

**対応**: `rm -rf` を**コマンドの先頭または区切り文字（`&&`, `;`, `|`）の直後**に
あるものに限定。引用符内の言及は通過する。

### 教訓

- PreToolUse フックは **Bash コマンド全体**を見るため、引数内の文字列も検査対象になる
- 「コマンド内のどこかで一致」ではなく、「**実コマンドとして実行される位置**」で一致させる
- 誤検知は「安全側に倒す」原則としては正しいが、運用性を下げるので段階的に改善する

## 例外ケース: ガードを一時的に無効化したい場合

正当な理由でガードをバイパスする必要がある場合:

1. **推奨**: ユーザーが直接ターミナルでコマンドを実行（Claude 経由しない）
2. **非推奨（緊急時のみ）**: `~/.claude/settings.json` の hooks.PreToolUse を一時的にコメントアウト
   - 作業後は必ず有効化に戻すこと
