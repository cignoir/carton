# Carton

Maya 用ローカルファーストのパッケージマネージャ。

[English version](README.md)

## Carton とは？

Carton は Maya ツールの**配布・インストール・更新**をクラウド不要で行えるパッケージマネージャです。共有ドライブやローカルディレクトリだけで運用できます。

```
 あなた                       チーム
 ┌──────────┐    公開     ┌──────────────────────────┐   インストール  ┌──────────┐
 │ My Tools │ ─────────>  │  レジストリ（共有ドライブ）│  <──────────── │ アーティ │
 │ - Rigger │             │  registry.json            │               │ スト Maya│
 │ - Shader │             │  packages/                │               └──────────┘
 └──────────┘             │  icons/                   │               ┌──────────┐
                          │  icons.zip                │  <──────────── │ アーティ │
                          └──────────────────────────┘   インストール  │ スト Maya│
                                                                      └──────────┘
```

**レジストリ** = `registry.json` とパッケージ群を含む共有フォルダ。
アクセス権があれば誰でもツールをインストールできます。

## 基本コンセプト

```
┌─────────────────────────────────────────────────────────────────────┐
│  Carton（Maya 内）                                                   │
│                                                                     │
│  ┌─── My Tools ───────────────┐  ┌─── レジストリ A ─────────────┐  │
│  │                             │  │                               │  │
│  │  ローカルのスクリプト/フォルダ │  │  チーム共有のパッケージ群      │  │
│  │  参照方式で登録              │  │  registry.json からインストール│  │
│  │                             │  │                               │  │
│  │  [公開] ────────────────────│──│─> レジストリに追加             │  │
│  │                             │  │                               │  │
│  └─────────────────────────────┘  └───────────────────────────────┘  │
│                                   ┌─── レジストリ B ─────────────┐  │
│                                   │  別チーム / 別プロジェクト     │  │
│                                   └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

- **My Tools** — ローカル登録したスクリプト。参照方式なので、元ファイルの編集が即反映されます。
- **レジストリ** — パッケージをまとめた共有ディレクトリ。ローカルフォルダ、ネットワークドライブ、Git リポジトリ、リモート URL に対応。
- **公開（Publish）** — ローカルツールをパッケージ化してレジストリに追加。チームメンバーがインストール可能になります。

## 動作環境

- Maya 2024 / 2025 / 2026 / 2027

## クイックスタート

### Carton のインストール

1. [Releases](https://github.com/cignoir/carton/releases) からインストーラをダウンロード
2. Maya のビューポートに `.py` ファイルをドラッグ＆ドロップ
3. Maya を再起動
4. メニュー: **Carton > Open Carton**

### レジストリを使う

```
Settings（⚙）> Add > registry.json を選択
```

3 つのソースに対応:
- **ローカルファイル** — `registry.json` のパスを指定
- **GitHub リポジトリ** — `owner/repo` 形式
- **リモート URL** — `registry.json` の直接 URL

### ツールをインストール

Carton を開き、パッケージを選んで **Install** をクリック。

### スクリプトを登録・共有

```
My Tools > + Add > ファイルまたはフォルダを選択
                 > 名前、アイコン、説明を設定
                 > Register

カード > Publish > 公開先レジストリを選択
```

## レジストリの構成

```
my-registry/
├── registry.json          # パッケージ一覧
├── packages/
│   └── {uuid}/{version}/
│       └── {name}-{version}.zip
├── icons/
│   └── {name}.png         # パッケージごとのアイコン
└── icons.zip              # リモート配信用アイコン一括ファイル
```

Git で管理するもよし、ネットワークドライブに置くもよし、静的ファイルとしてホスティングするもよし。

## package.json

ツールのルートに配置するメタデータファイル:

```json
{
  "name": "my_tool",
  "display_name": "My Tool",
  "version": "1.0.0",
  "type": "python_package",
  "description": "ツールの説明",
  "author": "your_name",
  "entry_point": {
    "type": "python",
    "module": "my_tool",
    "function": "show"
  },
  "icon": "🔧"
}
```

対応タイプ: `python_package`, `mel_script`, `plugin`

## CLI

```bash
python -m carton list path/to/registry.json
python -m carton unpublish --registry path/to/registry.json --id <uuid>
```

## 開発

```bash
# インストーラのビルド
python scripts/build_installer.py

# テスト
python -m pytest tests/ -v

# Maya での開発リロード
exec(open(r"path/to/carton/scripts/dev_reload.py", encoding="utf-8").read())
```

## ライセンス

MIT
