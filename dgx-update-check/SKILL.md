---
name: dgx-update-check
description: DGX Spark（GX10）のアップデートをブラウザ・ダッシュボードのボタンで実行する「前」に、今なにが来ているのかを副作用ゼロ・read-onlyで覗き見るスキル。DGX OTA世代の大型更新と Ubuntu標準apt更新（noble-updates/noble-security）の両方を取得し、容量・メモリ見込みとネット調査要約（出典つき）を提示する。ユーザーが「DGXのアップデート何が来てる」「更新前に確認したい」「apt update 相当を覗きたい」「OTA来てる？」と言ったら起動する。
---

# dgx-update-check — アップデート事前調査スキル

DGX Spark（GX10）のアップデートは普段ブラウザのダッシュボードのボタンから実行するが、押すと
「何が・どれだけ・どんなリスクで」入るのか分からないまま更新が始まる。過去にはダッシュボードの
アップデートで約 10GB が一気に DL され統合メモリ（大型の常駐プロセス等と共有）が圧迫されてプロセス強制終了の
事故も起きた。このスキルは **ボタンを押す前に「何が来ているか」を副作用ゼロで覗く** ための道具である。

あなた（判断層）は、決定的データ層スクリプト `scripts/collect.sh` が吐く JSON を **唯一の事実の入力** とし、
ネット調査（WebFetch / WebSearch・読取のみ）で意味づけを足し、レポート A〜F を **チャットに直接提示** する。

> アーキテクチャ（二層分離）: 事実の取得＝スクリプト（副作用コマンドを物理的に持たない）／
> 意味づけ・要約・所見＝あなた。**OTA 有無・apt の中身・サイズの「事実」は必ず JSON 側を正とし、
> Web は補足に留める**（独自推測で OTA 有無を断定しない）。

---

## 手順

### 1. データ層を1回だけ実行して JSON を取得する
```
bash ~/.claude/skills/dgx-update-check/scripts/collect.sh
```
- これは read-only・sudo なし・副作用ゼロ（`apt update` も DL もサービス操作もしない）。
- 出力は単一 JSON。**あなたはこの JSON を唯一の事実として読む。** 自分で apt や OTA コマンドを直接叩かないこと
  （叩く必要があるのは collect.sh のみ。判断層がコマンドを散らかすと安全境界が崩れる）。

### 2. preflight を確認する（AC1）
- `.preflight.ok == false` なら、**それ以上進まず**「環境前提を満たさないため中止（理由：`.preflight.reason`）」とだけ報告する。
  collect.sh はこの場合 非0終了し apt 層を埋めない（fail-fast）。
- `.preflight.ok == true` なら続行。`.preflight` の arch / codename / ota_tool をレポート冒頭に出す。

### 3. JSON から事実を読む
- 第1層 OTA：`.ota.is_available`（available / name / description / releaseNotesUrl / releaseDate）、
  `.ota.installed_name`、`.ota.torn`（torn=0 が完全適用）。available=true のときは `.ota.ota_versions` に入るパッケージ群。
- 第2層 apt：`.apt.packages[]`（name / ver_from→ver_to / repos / is_security / action / size_bytes / description）、
  `.apt.counts`、`.apt.phasing_deferred`、`.apt.autoremove_candidates`、原文照合用の `.apt.upgradable_raw`。
  - action: `install`＝実際に入る / `phasing`＝更新可能だが段階展開で保留中 / `remove`＝削除。
- 容量・メモリ：`.estimate.download_bytes_total` / `download_human` / `size_partial_unknown` /
  `mem_available_bytes` / `mem_available_human`。
- 鮮度：`.freshness.apt_index_mtime` / `apt_index_file`。
- 安全材料：`.safety.apt_lists_snapshot` / `.safety.dashboard_services`。
- 取得失敗：`.errors[]`（空でなければ該当項目を「取得できなかった」と明示する。隠さない）。

### 4. ネット調査（読取のみ・出典必須・security 優先）
- **必ず**：`.ota.is_available.releaseNotesUrl` を **WebFetch** してリリースノートを要約（レポート D）。出典 URL を併記。
- **必ず**：`.apt.packages[] | select(.is_security == true)` の各パッケージ（例 `liblzma5` / `xz-utils`）を、
  `名前 + ver_to + CVE` で **WebSearch** し、意味・既知のリスク（CVE 等）を要約。各要約に参照 URL を併記。
  - security 由来が 0 件なら「security 由来の更新は今回なし」と明記すれば合格（AC7）。
- 任意：その他の主要パッケージ（phasing 中の大物等）も必要に応じて WebSearch。大規模クロール・自動リンク巡回はしない。
- **推測と事実を分離する**：JSON にある値は「事実」、Web 由来は「調査（出典つき）」として書き分ける。

### 5. レポート A〜F をチャットに提示する（ファイル書き出しはしない）

---

## レポート様式（A〜F）

**A. サマリ**
- 新 OTA 世代：来ている / 来ていない（`.ota.is_available.available`）。来ていない場合は第2層 apt を主役に。
- apt 更新件数：install `.apt.counts.install` / phasing 保留 `.apt.counts.phasing` / 削除 `.apt.counts.remove`。
- 総 DL サイズ目安：`.estimate.download_human`（`size_partial_unknown` が true なら「一部サイズ不明・判明分のみ」と添える）。

**B. 第1層 DGX OTA の詳細**（AC2/AC3）
- 世代名・説明・公開日・リリースノート URL（`.ota.is_available` の 5 項目）。
- 現在の適用状態：一致世代名 `.ota.installed_name.name` と torn `.ota.torn.torn`（0=完全適用、数値が大きいほど未適用が多い）。
- available=true のときのみ：`.ota.ota_versions` の「これから入るパッケージ群」。

**C. 第2層 apt の詳細**（AC4/AC5）
- `.apt.packages[]` を action 別に提示。各 install パッケージは
  「名前・ver_from→ver_to・リポジトリ（updates / security）・サイズ（size_bytes を MB/KB で）・一言説明」。
- phasing 保留分（`.apt.phasing_deferred`）と autoremove 候補（`.apt.autoremove_candidates`、多ければ件数＋代表例）を区別して記載。
- `.apt.upgradable_raw` と突き合わせ、upgradable の全パッケージが漏れていないことを確認（AC4）。

**D. ネット調査の要約**（AC6/AC7・出典 URL 必須）
- リリースノート要約（出典：releaseNotesUrl）。
- security パッケージの意味・リスク（CVE 等）要約（各出典 URL）。security 0 件なら「今回なし」と明記。

**E. 容量・メモリ見込み**（AC8）
- 「総ダウンロードサイズ目安：`.estimate.download_human`」
- 「現在のメモリ空き：`.estimate.mem_available_human`」
- 所見：押したら足りるか（例：DL は数百KB〜MB 規模でメモリ余力 約 X Gi に対し問題なし／大型 OTA が来ている場合は
  過去の +10GB 事故を踏まえ余力を確認するよう促す）。**size_partial_unknown が true なら「合算は判明分のみ」と明示。**

**F. 安全性の明示**（必須・AC9/AC10/AC11）
- **副作用ゼロ宣言**（必ず）：
  > このスキルは `apt update`・パッケージのダウンロード・サービスの起動/停止/再起動の **いずれも行っていません**。
  > 取得はすべて read-only（sudo なし）で、apt のローカルインデックスもダッシュボード機構も変更していません。
  - 根拠として `.safety.apt_lists_snapshot`（apt インデックスの最新 mtime）と
    `.safety.dashboard_services`（2 サービスが active のまま）を提示。
- **情報の基準日時**（AC10）：
  > 情報の基準日時：`.freshness.apt_index_mtime`（apt ローカルインデックス最終更新）。
  > これより新しい更新は反映されていない可能性があります。最新化したい場合は **ダッシュボードのアップデート** で行ってください
  > （このスキルは鮮度を表示するだけで `apt update` はしません）。
- **参考：実際に更新したい場合のユーザー手動コマンド**（スキルは実行しない・テキスト提示のみ・AC11）：
  > 以下はあなた（ユーザー）がターミナルで手動実行する場合の参考です。**このスキルは実行しません。**
  > 通常は GX10 のダッシュボードのアップデートボタンで更新するのが正規ルートです（過去の +10GB 事故を踏まえ、
  > 大型 OTA のときは統合メモリの空きを確認してから実行してください）。
  > ```
  > # （参考・手動）最新インデックス取得 → 内容確認 → 適用。実行はユーザー判断で。
  > sudo apt update
  > apt list --upgradable
  > sudo apt full-upgrade
  > ```

---

## 安全規律（あなたが守ること）

- collect.sh 以外で apt / OTA を **直接叩かない**。事実取得はデータ層に一本化されている（ADR-1）。
- `sudo`・`apt update`・`apt upgrade|full-upgrade`・ダウンロード・サービス操作を **実行しない**
  （F の手動コマンドは「テキストでの参考提示」のみ。実行は絶対にしない）。
- ダッシュボード機構（`dgx-dashboard.service` / `dgx-dashboard-admin.service`）は **観測（is-active）まで**。停止・再起動・設定変更をしない（F2）。
- ネット調査は WebFetch / WebSearch の **読取のみ**。要約には必ず出典 URL を付け、推測と事実を区別する（F6）。
- JSON が壊れていた・`.errors[]` が空でない場合は、取れた範囲で報告し、取れなかった項目を「取得できなかった」と正直に明示する。

> なぜ collect.sh に一本化するか：副作用コマンドをスクリプトに **物理的に存在させない** ことで、
> 「うっかり危険コマンドを実行する」経路自体を消している（許可コマンド allowlist は `scripts/config.sh` に明記）。
