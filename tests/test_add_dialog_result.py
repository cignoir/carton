"""What AddDialog hands back is what gets written to installed.json.

Registration is where a package's identity and its entry_point are
decided, and a mistake here doesn't surface until Launch — as an
import error that says nothing about the registration. These tests
drive ``_on_register`` against real files on disk and assert on the
result dict rather than on any pixel.
"""

import json

import pytest

pytest.importorskip("pytestqt")

from carton.ui.compat import QtWidgets
import carton.ui.add_dialog as ad_module
from carton.ui.add_dialog import AddDialog


@pytest.fixture
def silent(monkeypatch):
    """Capture the warnings AddDialog would have shown."""
    shown = []
    monkeypatch.setattr(
        ad_module.QtWidgets.QMessageBox, "warning",
        staticmethod(lambda parent, title, text: shown.append(text)),
    )
    return shown


def _dialog(qtbot, path, display_name="My Tool", namespace="acme",
            is_folder=False):
    dialog = AddDialog()
    qtbot.addWidget(dialog)
    dialog._selected_path = str(path)
    dialog._is_folder = is_folder
    dialog._name_input.setText(display_name)
    dialog._namespace_input.setText(namespace)
    return dialog


def _py_package(tmp_path, name="my_tool", package_json=None):
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text(
        "def show():\n    pass\n", encoding="utf-8")
    if package_json is not None:
        (root / "package.json").write_text(
            json.dumps(package_json), encoding="utf-8")
    return root


class TestValidation:
    def test_missing_path_is_refused(self, qtbot, tmp_path, silent):
        dialog = _dialog(qtbot, tmp_path / "does_not_exist.py")

        dialog._on_register()

        assert dialog.get_result() is None
        assert len(silent) == 1

    def test_blank_display_name_is_refused(self, qtbot, tmp_path, silent):
        script = tmp_path / "my_tool.py"
        script.write_text("def show(): pass\n", encoding="utf-8")
        dialog = _dialog(qtbot, script, display_name="")

        dialog._on_register()

        assert dialog.get_result() is None
        assert len(silent) == 1

    def test_blank_namespace_is_refused(self, qtbot, tmp_path, silent):
        """A registration without one cannot be published later."""
        script = tmp_path / "my_tool.py"
        script.write_text("def show(): pass\n", encoding="utf-8")
        dialog = _dialog(qtbot, script, namespace="")

        dialog._on_register()

        assert dialog.get_result() is None
        assert len(silent) == 1


class TestNamespaceHandling:
    def test_namespace_is_slugified(self, qtbot, tmp_path, silent):
        script = tmp_path / "my_tool.py"
        script.write_text("def show(): pass\n", encoding="utf-8")
        dialog = _dialog(qtbot, script, namespace="My Studio")

        dialog._on_register()

        assert dialog.get_result()["namespace"] == "my-studio"

    def test_prefilled_namespace_is_used_when_untouched(self, qtbot, tmp_path,
                                                        silent):
        script = tmp_path / "my_tool.py"
        script.write_text("def show(): pass\n", encoding="utf-8")
        dialog = AddDialog(default_namespace="mystudio")
        qtbot.addWidget(dialog)
        dialog._selected_path = str(script)
        dialog._is_folder = False
        dialog._name_input.setText("My Tool")

        dialog._on_register()

        assert dialog.get_result()["namespace"] == "mystudio"


class TestFolderPackages:
    def test_auto_detected_entry_point_is_dispatchable(self, qtbot, tmp_path,
                                                       silent):
        root = _py_package(tmp_path)
        dialog = _dialog(qtbot, root, is_folder=True)
        dialog._func_combo.addItem("show")
        dialog._func_combo.setCurrentText("show")

        dialog._on_register()

        result = dialog.get_result()
        assert result["is_folder"] is True
        assert result["type"] == "python_package"
        assert result["entry_point"]["type"] == "python"
        assert result["entry_point"]["module"] == "my_tool"

    def test_valid_package_json_entry_point_is_adopted(self, qtbot, tmp_path,
                                                       silent):
        root = _py_package(tmp_path, package_json={
            "name": "my_tool", "version": "2.3.4", "author": "someone",
            "type": "python_package",
            "entry_point": {"type": "python", "module": "my_tool",
                            "function": "main"},
        })
        dialog = _dialog(qtbot, root, is_folder=True)
        dialog._detected_info = {
            "has_package_json": True, "name": "my_tool", "version": "2.3.4",
            "author": "someone", "type": "python_package",
            "entry_point": {"type": "python", "module": "my_tool",
                            "function": "main"},
        }

        dialog._on_register()

        result = dialog.get_result()
        assert result["entry_point"]["function"] == "main"
        assert result["version"] == "2.3.4"
        assert result["author"] == "someone"

    def test_undispatchable_package_json_entry_point_is_rejected(
            self, qtbot, tmp_path, silent):
        """Adopting it verbatim moved the failure to launch time.

        A manifest whose entry_point can't be dispatched used to be
        taken at face value; the tool then registered cleanly and blew
        up on the first click, where the error is far harder to act on.
        """
        root = _py_package(tmp_path)
        dialog = _dialog(qtbot, root, is_folder=True)
        dialog._detected_info = {
            "has_package_json": True, "name": "my_tool",
            "type": "python_package",
            "entry_point": {"nonsense": True},
        }
        dialog._func_combo.addItem("show")
        dialog._func_combo.setCurrentText("show")

        dialog._on_register()

        result = dialog.get_result()
        # Fell back to auto-detection instead of adopting the bad shape.
        assert result["entry_point"]["type"] == "python"
        assert "nonsense" not in result["entry_point"]

    def test_maya_module_registers_without_an_entry_point(self, qtbot,
                                                          tmp_path, silent):
        root = tmp_path / "my_module"
        root.mkdir()
        dialog = _dialog(qtbot, root, is_folder=True)
        dialog._detected_info = {"is_maya_module": True, "name": "my_module"}

        dialog._on_register()

        result = dialog.get_result()
        assert result["type"] == "maya_module"
        assert result["entry_point"] == {}
        assert result["is_folder"] is True

    def test_home_origin_survives_the_auto_detect_fallback(self, qtbot,
                                                           tmp_path, silent):
        """Falling back on entry_point shouldn't discard the rest."""
        root = _py_package(tmp_path)
        dialog = _dialog(qtbot, root, is_folder=True)
        dialog._detected_info = {
            "has_package_json": True, "name": "my_tool",
            "type": "python_package",
            "entry_point": {"broken": True},
            "home_origin": {"type": "github", "repo": "acme/tools"},
            "version": "1.2.3",
        }
        dialog._func_combo.addItem("show")
        dialog._func_combo.setCurrentText("show")

        dialog._on_register()

        result = dialog.get_result()
        assert result["home_origin"] == {"type": "github",
                                         "repo": "acme/tools"}
        assert result["version"] == "1.2.3"


class TestSingleFiles:
    def test_function_mode_builds_a_python_entry_point(self, qtbot, tmp_path,
                                                       silent):
        script = tmp_path / "my_tool.py"
        script.write_text("def show():\n    pass\n", encoding="utf-8")
        dialog = _dialog(qtbot, script)
        dialog._mode_func.setChecked(True)
        dialog._func_combo.addItem("show")
        dialog._func_combo.setCurrentText("show")

        dialog._on_register()

        result = dialog.get_result()
        assert result["is_folder"] is False
        assert result["entry_point"]["type"] == "python"
        assert result["entry_point"]["module"] == "my_tool"

    def test_exec_mode_builds_an_exec_entry_point(self, qtbot, tmp_path,
                                                 silent):
        script = tmp_path / "make_sphere.py"
        script.write_text("print('hi')\n", encoding="utf-8")
        dialog = _dialog(qtbot, script)
        dialog._mode_exec.setChecked(True)

        dialog._on_register()

        assert dialog.get_result()["entry_point"]["type"] == "exec"

    def test_mel_script_registers_as_mel(self, qtbot, tmp_path, silent):
        script = tmp_path / "my_tool.mel"
        script.write_text('global proc my_tool() {}\n', encoding="utf-8")
        dialog = _dialog(qtbot, script)

        dialog._on_register()

        assert dialog.get_result()["type"] == "mel_script"

    def test_a_filename_importlib_cannot_load_is_refused(self, qtbot,
                                                         tmp_path, silent):
        """Function mode goes through importlib, so the stem must be valid."""
        script = tmp_path / "my-tool.py"
        script.write_text("def show():\n    pass\n", encoding="utf-8")
        dialog = _dialog(qtbot, script)
        dialog._mode_func.setChecked(True)

        dialog._on_register()

        assert dialog.get_result() is None
        assert len(silent) == 1

    def test_exec_mode_exempts_that_filename_rule(self, qtbot, tmp_path,
                                                  silent):
        """Nothing imports an exec-mode script, so the stem is free."""
        script = tmp_path / "my-tool.py"
        script.write_text("print('hi')\n", encoding="utf-8")
        dialog = _dialog(qtbot, script)
        dialog._mode_exec.setChecked(True)

        dialog._on_register()

        assert dialog.get_result() is not None
        assert silent == []


class TestDefaults:
    def test_icon_defaults_when_left_blank(self, qtbot, tmp_path, silent):
        script = tmp_path / "my_tool.py"
        script.write_text("def show(): pass\n", encoding="utf-8")
        dialog = _dialog(qtbot, script)
        dialog._icon_input.setText("")

        dialog._on_register()

        assert dialog.get_result()["icon"] == "🔧"

    def test_display_name_is_carried_through_verbatim(self, qtbot, tmp_path,
                                                      silent):
        """Only the internal name is slugified; the label is the user's."""
        script = tmp_path / "my_tool.py"
        script.write_text("def show(): pass\n", encoding="utf-8")
        dialog = _dialog(qtbot, script, display_name="My Cool Tool ✨")

        dialog._on_register()

        assert dialog.get_result()["display_name"] == "My Cool Tool ✨"
