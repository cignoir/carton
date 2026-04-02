# Carton

Maya 用ローカルファーストのパッケージマネージャ。ツールの配布・管理・更新をローカルレジストリで一元管理する。

[English version](README.md)

## 特徴

- **ローカルファースト** — AWS やクラウドサービス不要。ローカルディレクトリだけで動作
- **複数レジストリ** — チーム別・プロジェクト別にレジストリを追加可能
- **ワンクリックインストール** — `.py` を Maya にドラッグ＆ドロップ
- **ローカルスクリプト登録** — 単一ファイルやフォルダを UI から登録。参照方式で編集が即反映
- **Publish** — ローカル登録したスクリプトをレジストリに書き出して共有
- **自動更新** — Carton 本体は GitHub Releases から自動更新
- **絵文字アイコン** — パッケージアイコンに絵文字を指定可能
- **VCS 非依存** — レジストリは Git / SVN / ネットワークドライブ、何でも OK

## 動作環境

- Maya 2024 / 2025 / 2026 / 2027
- PySide2 (Maya < 2025) / PySide6 (Maya >= 2025)

## クイックスタート

### インストール

1. [Releases](https://github.com/cignoir/carton/releases) から `install_carton.py` をダウンロード
2. Maya を開き、ビューポートにドラッグ＆ドロップ
3. Maya を再起動
4. メニューバーの「Carton」→「Open Carton」

### レジストリを追加

1. Carton → Settings (⚙) → + Add
2. チームや個人の `registry.json` のパスを指定

### ツールをインストール

1. Carton を開く → レジストリのパッケージ一覧が表示
2. Install ボタン → 完了

### スクリプトを登録・共有

1. Carton → + Add → ファイルまたはフォルダを選択
2. Display Name, Icon, Run Mode を設定 → Register
3. Publish ボタン → レジストリを選択 → 共有完了

## レジストリの構成

レジストリは `registry.json` を含むディレクトリ。VCS で管理するもよし、ネットワークドライブに置くもよし。

```
my-registry/
├── registry.json
├── packages/
│   └── {uuid}/{version}/
│       └── {name}-{version}.zip
└── icons/
    └── {name}.png  (任意)
```

### registry.json

```json
{
  "schema_version": "2.0",
  "packages": {
    "uuid-here": {
      "name": "my_tool",
      "display_name": "My Tool",
      "type": "python_package",
      "icon": "🔧",
      "description": "ツールの説明",
      "author": "your_name",
      "latest_version": "1.0.0",
      "versions": {
        "1.0.0": {
          "download_url": "packages/uuid-here/1.0.0/my_tool-1.0.0.zip",
          "sha256": "...",
          "size_bytes": 12345,
          "maya_versions": ["2024", "2025", "2026", "2027"],
          "released_at": "2026-04-03T00:00:00Z"
        }
      }
    }
  }
}
```

`download_url` は registry.json の親ディレクトリからの相対パス。絶対パスや URL も可。

## package.json

各ツールに配置するメタデータ。

```json
{
  "name": "my_tool",
  "display_name": "My Tool",
  "version": "1.0.0",
  "type": "python_package",
  "description": "ツールの説明",
  "author": "your_name",
  "maya_versions": ["2024", "2025", "2026", "2027"],
  "entry_point": {
    "type": "python",
    "module": "my_tool",
    "function": "show"
  },
  "icon": "🔧"
}
```

`icon` には絵文字 (`"📷"`) または画像パス (`"resources/icon.png"`) が指定可能。

## 開発

### テスト

```bash
cd carton
python -m pytest tests/ -v
```

### Maya での開発リロード

```python
exec(open(r"path/to/carton/scripts/dev_reload.py", encoding="utf-8").read())
```

## アーキテクチャ

```
carton/
├── carton/                      # パッケージマネージャ本体
│   ├── core/
│   │   ├── config.py            # 複数レジストリ設定
│   │   ├── registry_client.py   # 複数レジストリ読み込み + マージ
│   │   ├── publisher.py         # レジストリに直接書き出し
│   │   ├── downloader.py        # ローカルコピー / URL DL
│   │   ├── installer.py         # インストール / アンインストール
│   │   ├── updater.py           # バージョン比較
│   │   ├── self_updater.py      # GitHub Releases 自動更新
│   │   ├── script_manager.py    # ローカルスクリプト登録
│   │   ├── env_manager.py       # Maya 環境変数管理
│   │   └── handlers/            # パッケージタイプ別 Handler
│   ├── models/
│   └── ui/
│       ├── main_window.py       # レジストリグルーピング
│       ├── settings_dialog.py   # レジストリ管理 UI
│       ├── add_dialog.py        # ローカル登録 (ファイル / フォルダ)
│       └── edit_dialog.py       # メタ情報編集
├── bootstrap/
├── installer/
├── .github/workflows/
│   └── release.yml              # GitHub Releases にインストーラ添付
└── tests/
```

## ライセンス

MIT
