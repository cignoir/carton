"""Internationalization (i18n) for Carton UI."""

_current_lang = "ja"

_STRINGS = {
    "en": {
        # Common
        "cancel": "Cancel",
        "close": "Close",
        "save": "Save",
        "register": "Register",
        "remove": "Remove",
        "install": "Install",
        "installing": "Installing...",
        "uninstall": "Uninstall",
        "launch": "Launch",
        "activate": "Activate",
        "publish": "Publish",
        "publishing": "Publishing...",
        "update": "Update",
        "updating": "Updating...",
        "back": "← Back",
        "file": "File...",
        "folder": "Folder...",

        # Form labels
        "label_display_name": "Display Name",
        "label_name": "Internal Name",
        "name_tooltip": "Derived from the file or folder name. Used as the package identifier and cannot be changed after registration.",
        "label_namespace": "Namespace",
        "namespace_placeholder": "e.g. mystudio (required to publish)",
        "publish_namespace_prompt": "Enter a namespace for this package (spaces and capitals will be auto-converted):",
        "publish_home_registry_mismatch": "This package's home registry is '{}'. Publish to '{}' instead?",
        "label_version": "Version",
        "label_icon": "Icon",
        "label_homepage": "Homepage",
        "label_author": "Author",
        "label_description": "Description",
        "label_path": "Path",
        "label_run_mode": "Run Mode",
        "label_function": "function name",
        "label_plugin_command": "Launch command (Python, optional)",
        "label_maya": "Maya",
        "label_tags": "Tags",
        "label_changelog": "Changelog",
        "label_size": "Size",
        "label_released": "Released",
        "label_type": "Type",
        "open_homepage": "Open Homepage",

        # Main window
        "search_placeholder": "Search packages...",
        "loading": "Loading...",
        "tab_all": "All",
        "tab_installed": "Installed",
        "my_tools": "My Tools",
        "register_script": "+ Register Script",
        "add": "+ Add",
        "update_available": "Carton v{} available",
        "update_pending": "Carton v{} — next Maya restart",
        "confirm_update": "Update {} to v{}?",
        "confirm_uninstall": "Uninstall {}?",
        "confirm_publish": "Publish {} v{} to '{}'?",
        "publish_success": "{} published!",
        "publish_no_registry": "No registries configured.\nAdd a registry from Settings.",
        "publish_create_registry": "Create new registry",
        "publish_add_existing_registry": "Add existing registry",
        "publish_select_registry": "Target registry:",
        "publish_already_published": "v{} is already published.\nIncrement the version from the edit screen before re-publishing.",
        "no_download_url": "No download URL available",
        "install_error": "Install Error",
        "launch_error": "Launch Error",
        "publish_error": "Publish Error",
        "unpublish": "Unpublish",
        "unpublishing": "Unpublishing...",
        "confirm_unpublish": "Unpublish {} from '{}'?\nOther users will no longer be able to install this package.",
        "unpublish_success": "{} has been unpublished from '{}'.",
        "unpublish_select_registry": "Unpublish from which registry?",
        "unpublish_error": "Unpublish Error",
        "register_error": "Register Error",
        "update_error": "Update Error",

        # Registry creation
        "setup_select_folder": "Select folder to create registry",
        "setup_registry_name": "Enter registry name:",

        # Add dialog
        "add_title": "Carton — Register Script",
        "add_select_placeholder": "Select a file or folder...",
        "add_exec_mode": "Execute file (top-level execution)",
        "add_func_mode": "Call function:",
        "add_browse_file": "Select script",
        "add_browse_folder": "Select folder",
        "add_invalid_path": "Please select a valid file or folder.",
        "add_no_display_name": "Please enter a Display Name.",

        # Edit dialog
        "edit_title": "Carton — Edit",
        "edit_confirm_remove": "Remove {} from Carton?\nThe original file will not be deleted.",

        # Settings
        "settings_title": "Carton — Settings",
        "settings_general": "General",
        "settings_registries": "Registries",
        "settings_advanced": "Advanced",
        "settings_language": "Language",
        "settings_language_auto": "Auto (system)",
        "edit": "Edit",
        "settings_edit_registry": "Edit Registry",
        "settings_select_registry": "Select registry.json",
        "settings_add_method": "How to add a registry?",
        "settings_add_local": "Local file",
        "settings_add_github": "GitHub repository",
        "settings_add_url": "Remote URL",
        "settings_github_placeholder": "Enter owner/repo (e.g. cignoir/creg-ari):",
        "settings_github_invalid": "Please enter in owner/repo format.",
        "settings_github_error": "Failed to access GitHub: {}",
        "settings_github_no_registry": "registry.json not found in {}.",
        "settings_url_placeholder": "Enter registry.json URL:",
        "settings_invalid_url": "URL must start with http:// or https://",
        "settings_registry_name": "Enter registry name:",
        "settings_already_exists": "'{}' is already registered.",
        "settings_confirm_remove": "Remove '{}'?\nThe registry contents will not be deleted.",
        "settings_uninstall": "Uninstall Carton",
        "settings_confirm_uninstall": (
            "This will delete Carton and all installed packages.\n"
            "This action cannot be undone.\n\n"
            "Continue?"
        ),
        "settings_uninstall_done": "Carton has been uninstalled.\nPlease restart Maya.",
        "settings_uninstall_errors": "Some errors occurred:\n{}\n\nPlease restart Maya.",
        "settings_uninstall_title": "Uninstall Carton",
    },

    "ja": {
        # Common
        "cancel": "キャンセル",

        # Form labels
        "label_display_name": "表示名",
        "label_name": "内部名",
        "name_tooltip": "ファイル名またはフォルダ名から自動生成されます。パッケージの識別子として使われ、登録後は変更できません。",
        "label_namespace": "ネームスペース",
        "namespace_placeholder": "例: mystudio（公開時に必須）",
        "publish_namespace_prompt": "このパッケージのネームスペースを入力してください（スペースや大文字は自動変換されます）:",
        "publish_home_registry_mismatch": "このパッケージの本籍レジストリは「{}」です。代わりに「{}」へ公開しますか？",
        "label_version": "バージョン",
        "label_icon": "アイコン",
        "label_homepage": "ホームページ",
        "label_author": "作者",
        "label_description": "説明",
        "label_path": "パス",
        "label_run_mode": "実行モード",
        "label_function": "関数名",
        "label_plugin_command": "起動コマンド（Python、任意）",
        "label_maya": "Maya",
        "label_tags": "タグ",
        "label_changelog": "変更履歴",
        "label_size": "サイズ",
        "label_released": "リリース日",
        "label_type": "タイプ",
        "open_homepage": "ホームページを開く",

        "close": "閉じる",
        "save": "保存",
        "register": "登録",
        "remove": "削除",
        "install": "インストール",
        "installing": "インストール中...",
        "uninstall": "アンインストール",
        "launch": "起動",
        "activate": "有効化",
        "publish": "公開",
        "publishing": "公開中...",
        "update": "更新",
        "updating": "更新中...",
        "back": "← 戻る",
        "file": "ファイル...",
        "folder": "フォルダ...",

        # Main window
        "search_placeholder": "パッケージを検索...",
        "loading": "読み込み中...",
        "tab_all": "すべて",
        "tab_installed": "インストール済み",
        "my_tools": "マイツール",
        "register_script": "+ スクリプトを登録",
        "add": "+ 追加",
        "update_available": "Carton v{} が利用可能",
        "update_pending": "Carton v{} — 次回 Maya 起動時に適用",
        "confirm_update": "{} を v{} に更新しますか？",
        "confirm_uninstall": "{} をアンインストールしますか？",
        "confirm_publish": "{} v{} を '{}' に公開しますか？",
        "publish_success": "{} を公開しました！",
        "publish_no_registry": "レジストリが登録されていません。\n設定からレジストリを追加してください。",
        "publish_create_registry": "レジストリを新規作成",
        "publish_add_existing_registry": "既存のレジストリを追加",
        "publish_select_registry": "公開先レジストリ:",
        "publish_already_published": "v{} は既に公開済みです。\n編集画面からバージョンを上げてから再公開してください。",
        "no_download_url": "ダウンロード先が見つかりません",
        "install_error": "インストールエラー",
        "launch_error": "起動エラー",
        "publish_error": "公開エラー",
        "unpublish": "公開取消",
        "unpublishing": "取消中...",
        "confirm_unpublish": "{} を '{}' から取り下げますか？\n他のユーザーはこのパッケージをインストールできなくなります。",
        "unpublish_success": "{} を '{}' から取り下げました。",
        "unpublish_select_registry": "どのレジストリから取り下げますか？",
        "unpublish_error": "取消エラー",
        "register_error": "登録エラー",
        "update_error": "更新エラー",

        # Registry creation
        "setup_select_folder": "レジストリを作成するフォルダを選択",
        "setup_registry_name": "レジストリの名前を入力:",

        # Add dialog
        "add_title": "Carton — スクリプト登録",
        "add_select_placeholder": "ファイルまたはフォルダを選択...",
        "add_exec_mode": "ファイルを直接実行",
        "add_func_mode": "関数を呼び出す:",
        "add_browse_file": "スクリプトを選択",
        "add_browse_folder": "フォルダを選択",
        "add_invalid_path": "有効なファイルまたはフォルダを選択してください。",
        "add_no_display_name": "表示名を入力してください。",

        # Edit dialog
        "edit_title": "Carton — 編集",
        "edit_confirm_remove": "{} の登録を解除しますか？\n元ファイルは削除されません。",

        # Settings
        "settings_title": "Carton — 設定",
        "settings_general": "一般",
        "settings_registries": "レジストリ",
        "settings_advanced": "詳細",
        "settings_language": "言語",
        "settings_language_auto": "自動 (システム)",
        "edit": "編集",
        "settings_edit_registry": "レジストリの編集",
        "settings_select_registry": "registry.json を選択",
        "settings_add_method": "レジストリの追加方法を選択:",
        "settings_add_local": "ローカルファイル",
        "settings_add_github": "GitHub リポジトリ",
        "settings_add_url": "リモート URL",
        "settings_github_placeholder": "owner/repo を入力 (例: cignoir/creg-ari):",
        "settings_github_invalid": "owner/repo の形式で入力してください。",
        "settings_github_error": "GitHub へのアクセスに失敗しました: {}",
        "settings_github_no_registry": "{} に registry.json が見つかりません。",
        "settings_url_placeholder": "registry.json の URL を入力:",
        "settings_invalid_url": "URL は http:// または https:// で始まる必要があります",
        "settings_registry_name": "レジストリの名前を入力:",
        "settings_already_exists": "'{}' は既に登録されています。",
        "settings_confirm_remove": "'{}' を削除しますか？\nレジストリの中身は削除されません。",
        "settings_uninstall": "Carton をアンインストール",
        "settings_confirm_uninstall": (
            "Carton とインストール済みの全パッケージを削除します。\n"
            "この操作は取り消せません。\n\n"
            "続行しますか？"
        ),
        "settings_uninstall_done": "Carton をアンインストールしました。\nMaya を再起動してください。",
        "settings_uninstall_errors": "一部エラーが発生しました:\n{}\n\nMaya を再起動してください。",
        "settings_uninstall_title": "Carton アンインストール",
    },
}


def set_language(lang):
    """Set the current language (e.g. 'en', 'ja')."""
    global _current_lang
    if lang in _STRINGS:
        _current_lang = lang


def get_language():
    """Return the current language code."""
    return _current_lang


def detect_language():
    """Auto-detect language from Maya's UI locale."""
    try:
        import maya.cmds as cmds
        locale = cmds.about(uiLanguage=True)  # e.g. 'ja_JP', 'en_US'
        if locale and locale.startswith("ja"):
            return "ja"
    except ImportError:
        pass
    return "en"


def t(key, *args):
    """Translate a key. Supports format arguments.

    Usage:
        t("confirm_update", "CigRef", "1.0.0")
        → "CigRef を v1.0.0 に更新しますか？"
    """
    strings = _STRINGS.get(_current_lang, _STRINGS["en"])
    text = strings.get(key, _STRINGS["en"].get(key, key))
    if args:
        return text.format(*args)
    return text
