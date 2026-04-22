# Carton 設計 FAQ

「なぜ X がないの？」「なぜ Y しないの？」という疑問に対する設計上の答えをまとめたもの。
機能の欠落ではなく **意図的な非採用** であることを明示するのが目的。

---

## はじめに — Carton の設計スコープ

Carton は **Maya 向けプラグイン/ツールの配布・バージョン管理・rollback** に特化したツール。
比喩としては **「Maya プラグインの App Store」**。npm/pip のような再利用可能ライブラリ管理とは別物。

スコープを守るための3つの原則:

1. **DCC ツールはファット配布** — 必要なものはパッケージ内に同梱する文化。依存解決は行わない。
2. **Local-first** — クラウドサービスに依存しない。GitHub / ファイルサーバー / ローカルフォルダで完結。
3. **Package-first** — `namespace/name` で一意に識別される package が一級概念。catalogue はインデックスに過ぎない。

---

## スコープ

### Q. なぜ Maya 専用？Houdini / Blender / Nuke 対応は？

- DCC ごとにパッケージ形式・ロード機構・Python 環境が大きく異なり、共通化の恩恵よりもスコープ肥大のデメリットが大きい。
- Maya に特化することで `.mll` plugin / `.mel` script / `maya_module (.mod)` のネイティブサポートが可能になる。
- 他 DCC 対応が必要になった場合は、Origin / Handler 抽象を再利用した別プロジェクト(Carton-Houdini 等)として fork するのが健全。

### Q. なぜクラウドサービスを使わないの？

- スタジオ内でのツール配布に AWS 等のクラウド依存を持ち込むと、運用コスト・認証基盤・法務確認が増える。
- 既存の社内ファイルサーバー / 既存の GitHub アカウントで完結することを優先。
- セキュアな社内ネットワーク(オフラインに近い環境)のスタジオでも使える。

### Q. なぜ GitHub Origin 専用？GitLab / Gitea / Bitbucket は？

- 実装は GitHub Releases API と GitHub Archive URL に依存しているが、`GithubOrigin` をベースに subclass を追加すれば対応可能な設計。
- 現状は優先順位の問題であり、設計上の制約ではない。必要になれば `GitlabOrigin` 等を追加する。

---

## データモデル

### Q. なぜ `package.json` / `catalogue.json` / `installed.json` の3ファイル構成？

それぞれ**関心事が違う**から分離している。

| ファイル | 関心事 | 誰が書く | 誰が読む |
|---|---|---|---|
| `package.json` | パッケージ自身のメタデータ (namespace/name/version/entry_point) | ツール開発者 | Carton がインストール時 |
| `catalogue.json` | 利用可能パッケージのインデックス | スタジオ管理者 / ツール作者 | Carton が起動時 |
| `installed.json` | このマシンで現在使っているパッケージ | Carton が自動 | Carton が起動時 |

1ファイルに集約すると、ツール開発者がスタジオ管理者権限を持たないと publish できなくなる等、責任の混線が起きる。

### Q. なぜ npm 風の `namespace/name` 形式？

- 名前空間なしだと `rigger` が誰の rigger か分からない衝突問題が発生する。
- スタジオ prefix (`mystudio/rigger`) とサードパーティ (`cignoir/rigger`) を同時購読しても衝突しない。
- `<ns>/<name>` は `@scope/name` (npm) / `org/repo` (GitHub) と見慣れた形式で学習コスト低。

### Q. dependencies フィールドはなぜ実装されてないの？

**スキーマにあるが実装空** なのは意図的。近い将来も実装する予定はない。

- DCC ツールは npm/pip と違って **再利用可能ライブラリをバラ配布する文化がない**。各ツールは自己完結のファット zip で配られる。
- 共通ライブラリ問題 (スタジオ横断の util など) は `MAYA_MODULE_PATH` / `userSetup.py` / vendoring / rez 等、**パッケージマネージャーの外側で解決されるのが業界実務**。
- Carton が依存解決を持つと「Carton で全部解決できる」という誤解を招き、本来別レイヤーで解くべき問題を抱え込む。
- schema フィールド自体も将来削除を検討中(表示専用の情報に格下げする選択肢もある)。

### Q. Cartonfile のような宣言的環境定義ファイルはないの？

**不要**。既存の3層で情報過不足なくカバーされている。

- **Profile (`~/.maya/carton/profiles/*.json`)** = 環境のブート設定(どの catalogue を見るか) → **インストーラに埋め込んで配布可能** (`scripts/build_installer.py`)
- **Catalogue** = 利用可能ツールのインベントリ → UI で検索・閲覧可能
- **installed.json** = ユーザーが選択した結果

新人への展開フローは「Profile 入り install_carton.py を D&D」で完結する。別途 YAML/TOML を書く必要がない。

### Q. プロジェクト別 install_dir はサポートしないの？

**しない**。Maya の構造と冗長化コストの両面で不適切。

- Maya は1セッション1インスタンス。plugin/sys.path はプロセス単位 global。**同時並行で2バージョンは構造的に不可能**。
- 「起動時にどちらを使うか」の切替は **Profile 切替 + pinned version** で実現できる。
- install_dir を複数持たせると以下のコストが全員に降りかかる:
  - ストレージ重複(50 packages × N projects)
  - 更新コスト N 倍
  - 「どの install_dir が active か」の認知負荷
  - 同期バグ(片方だけ fix 済み状態)
  - テストマトリクス爆発
- VFX 大規模での project archive 再現は rez の縄張り(Carton scope 外)。

### Q. 検索機能はあるの？

**ある**。

- `main_window.py:475` `_build_search_row` で QLineEdit を配置、placeholder 付き
- `main_window.py:1466` `_filter_cards` で textChanged 時フィルタ
- namespace 別フィルタも `_library_ns_filter` / `_mytools_ns_filter` で実装済

---

## UI

### Q. UI は MVVM を採用しないの？

**採用しない**。Qt/PySide + Maya 環境では過剰設計のため。

- Qt の signals/slots が既にイベント routing を担う。別途 ViewModel 層を積む利得が薄い。
- View-Service 直結でも Service 層 (`CatalogueClient`, `InstallManager`, `Publisher`) は UI 非依存なので単体テスト可能。
- 代償として UI ロジックの単体テストは薄いが、これは UI テスト (pytest-qt 等) の導入で別途対応すべき問題。

### Q. `main_window.py` が2300行超えてるの直さないの？

**直す**。ただし機能追加の副産物として割る方針。

- 全面リファクタより、install/publish/launch の flow 別に controller を抽出していく方が安全。
- 現状は 475 テストが全緑なので refactor の地盤は整っている。優先度は P1。

---

## セキュリティ / 信頼性

### Q. `pinned` / `unpinned` origin の違いは？

- **Pinned**: catalogue が事前計算した SHA256 を持つ / GitHub Release に `SHA256SUMS` asset が添付されている。配布物の改ざん検出が可能。
- **Unpinned**: GitHub 自動生成 archive や hash 事前計算なしの URL。TOFU (trust-on-first-use) で初回取得時の hash をキャッシュ。

### Q. `strict_verify` ってデフォルト ON (`config.py:130`) だけど厳しすぎない？

- 改ざんリスクを考慮しデフォルト ON。共有ドライブ catalogue を誰かが書き換えるシナリオを防ぐ。
- 信頼できる自社 catalogue だけを購読している場合は OFF にして unpinned origin を使える。
- 新規スタジオは ON のまま運用し、必要になったら明示的に OFF する方針を推奨。

---

## 運用 / 配布

### Q. `install_dir` を Profile に含めないのはなぜ？ (`profile.py:12`)

- `install_dir` はマシン固有 (OS 別のデフォルトパス / ユーザーの好みのドライブ)。
- Profile は **チーム / プロジェクトの設定** を配るためのもの。マシン固有値を埋めると配布先で不整合が出る。
- Profile に入るのは `catalogues` / `language` / `auto_check_updates` / `github_repo` / `proxy` に限定。

### Q. My Tools はなぜコピーじゃなく参照登録？

- `script_manager.py:1` に明記 → "reference-based" / "Holds references without copying"
- ツール開発者が自分の作業ツリーを **編集 → 即 Maya で反映** する workflow を優先。
- コピーセマンティクスだと「編集したのに反映されない」事故が起きる。
- 公式配布用にコピーベースで固めたい場合は publish すれば embedded catalogue に zip 化される。

### Q. publish で `gh` CLI が必須なのはなぜ？代替は？

- GitHub Release への asset upload を安定して行うために `gh` CLI を採用。
- manual fallback (zip を web UI で upload) は可能だが UI 上のガイドが手薄い。必要に応じて REST API 直接呼び出しへの移行は検討余地あり。

---

## 拡張方針

### Q. 新しいパッケージ形式 (例: USD asset) に対応したい

- `carton/core/handlers/` に `PackageHandler` サブクラスを追加
- `get_handler(type)` の registry に登録
- `schemas/package.schema.json` に新 type を追加
- 既存パターンに則れば影響範囲は局所的

### Q. 新しい配布ソース (例: GitLab) に対応したい

- `carton/core/origins/` に `Origin` サブクラスを追加 (`list_versions` / `get_artifact` / `to_dict` / `from_dict` 実装)
- `origin_from_dict` の分岐に追加 (`core/origins/base.py`)
- catalogue.schema.json にバリアント追加

---

## 未採用一覧 (サマリ)

| 項目 | 採用状況 | 理由 |
|---|---|---|
| dependencies 自動解決 | ✗ | DCC はファット配布文化。schema フィールドのみ残置 |
| Cartonfile (YAML) | ✗ | Profile + catalogue + installed.json の3層で十分 |
| プロジェクト別 install_dir | ✗ | Maya 構造上メリット薄、冗長化デメリット大 |
| クラウドサービス必須化 | ✗ | Local-first を優先 |
| 他 DCC 対応 | ✗ | スコープ肥大回避、必要なら fork |
| MVVM 層 | ✗ | Qt signals/slots で代替、過剰設計 |
| 検索機能 | ✓ | 実装済 (main_window.py:475) |
| My Tools の参照登録 | ✓ | 編集即反映を優先 (script_manager.py:1) |
| strict_verify デフォルト ON | ✓ | 改ざん検出優先、OFF 可 |

---

## この文書の扱い

- 新しい設計判断が発生するたびに追記
- 「なぜ X がないの？」に繰り返し答えることになったら、先にこの文書を更新して指し示す
- 覆す判断をした場合は Q&A を残したまま「この判断は X 時点で覆った」と追記(判断の履歴を残す)
