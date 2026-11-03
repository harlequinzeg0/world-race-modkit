"""The "Make a mod" tab: start from a stock car, edit, and build a zip."""
import json
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import addon, bog, merge, modpack, template

NOTICE = '"Start from this car" changes that stock car. "New car based on this one" adds a new car beside it.'


class MakeTab(QWidget):
    def __init__(self, game):
        super().__init__()
        self.game = None
        self.project = None

        self.car_box = QComboBox()
        self.start_button = self._button("Start from this car", self._ask_start)
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("new_car_name")
        self.team_box = QComboBox()
        self.team_box.setEditable(True)
        self.team_box.addItems(merge.STOCK_TEAMS)
        self.new_button = self._button("New car based on this one", self._ask_new)
        self.team_name_edit = QLineEdit()
        self.team_name_edit.setPlaceholderText("Neon Riders")
        self.base_team_box = QComboBox()
        self.base_team_box.addItems(merge.STOCK_TEAMS)
        self.team_button = self._button("Make a team for this car", self._ask_team)
        self.open_button = self._button("Open project", self._ask_open)
        self.folder_button = self._button("Open folder", self.open_folder)
        self.convert_button = self._button("Convert a texture", self._ask_convert)
        self.addon_button = self._button("Save Blender add-on", self._ask_addon)
        self.refresh_button = self._button("Refresh", self.refresh_changes)
        self.build_button = self._button("Build zip", self._ask_build)

        self.project_label = QLabel("No project open.")
        self.name_edit = QLineEdit()
        self.version_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.kind_box = QComboBox()
        self.kind_box.addItems(modpack.KINDS)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setMaximumHeight(70)
        self.change_list = QListWidget()

        self._build_layout()
        self.set_game(game)
        self._update_buttons()

    def _button(self, text, handler):
        button = QPushButton(text)
        button.clicked.connect(lambda: handler())
        return button

    def _build_layout(self):
        start = QHBoxLayout()
        start.addWidget(QLabel("Stock car"))
        start.addWidget(self.car_box, 1)
        start.addWidget(self.start_button)
        start.addWidget(self.open_button)
        start.addWidget(self.convert_button)

        new_car = QHBoxLayout()
        new_car.addWidget(QLabel("New car name"))
        new_car.addWidget(self.new_name_edit, 1)
        new_car.addWidget(QLabel("Team"))
        new_car.addWidget(self.team_box)
        new_car.addWidget(self.new_button)

        new_team = QHBoxLayout()
        new_team.addWidget(QLabel("New team name"))
        new_team.addWidget(self.team_name_edit, 1)
        new_team.addWidget(QLabel("Based on"))
        new_team.addWidget(self.base_team_box)
        new_team.addWidget(self.team_button)

        project = QHBoxLayout()
        project.addWidget(self.project_label, 1)
        project.addWidget(self.folder_button)
        project.addWidget(self.addon_button)

        form = QFormLayout()
        form.addRow("Mod name", self.name_edit)
        form.addRow("Version", self.version_edit)
        form.addRow("Author", self.author_edit)
        form.addRow("Kind", self.kind_box)
        form.addRow("Description", self.description_edit)

        changes = QHBoxLayout()
        changes.addWidget(QLabel("Changed files (only these go in the zip)"), 1)
        changes.addWidget(self.refresh_button)

        layout = QVBoxLayout(self)
        layout.addLayout(start)
        layout.addLayout(new_car)
        layout.addLayout(new_team)
        layout.addWidget(QLabel(NOTICE))
        layout.addLayout(project)
        layout.addLayout(form)
        layout.addLayout(changes)
        layout.addWidget(self.change_list, 1)
        layout.addWidget(self.build_button)

    def show_error(self, text):
        QMessageBox.warning(self, "World Race Mod Manager", text)

    def set_game(self, game):
        self.game = game
        self.car_box.clear()
        if game:
            try:
                self.car_box.addItems(template.list_stock_cars(game))
            except (OSError, KeyError, ValueError):
                pass
        self.start_button.setEnabled(self.car_box.count() > 0)
        self.new_button.setEnabled(self.car_box.count() > 0)

    def _update_buttons(self):
        for widget in (self.build_button, self.folder_button, self.refresh_button, self.team_button):
            widget.setEnabled(self.project is not None)

    def _load_details(self):
        meta = json.loads((self.project / modpack.MANIFEST).read_text(encoding="utf-8"))
        self.name_edit.setText(meta["name"])
        self.version_edit.setText(meta["version"])
        self.author_edit.setText(meta["author"])
        self.kind_box.setCurrentText(meta["kind"])
        self.description_edit.setPlainText(meta["description"])

    def save_details(self):
        path = self.project / modpack.MANIFEST
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta.update(
            name=self.name_edit.text(),
            version=self.version_edit.text(),
            author=self.author_edit.text(),
            kind=self.kind_box.currentText(),
            description=self.description_edit.toPlainText(),
        )
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def changed_list(self):
        return template.changed_files(self.project, self.game)

    def refresh_changes(self):
        self.change_list.clear()
        self.change_list.addItems(self.changed_list())

    def start_from_car(self, car, dest):
        try:
            self.open_project(template.create_car_project(self.game, car, dest))
        except (template.ProjectError, OSError) as e:
            self.show_error(str(e))

    def new_from_car(self, base, name, team, dest):
        try:
            self.open_project(template.create_new_car_project(self.game, base, name, team, dest))
        except (template.ProjectError, OSError) as e:
            self.show_error(str(e))

    def open_project(self, path):
        path = Path(path)
        if not (path / modpack.MANIFEST).is_file():
            self.show_error(f"{path} is not a mod project.")
            return
        try:
            if self.game:
                template.add_missing_art(self.game, path)
        except (template.ProjectError, OSError, ValueError) as e:
            self.show_error(str(e))
            return
        self.project = path
        self.project_label.setText(f"Project: {path}")
        self._load_details()
        self.refresh_changes()
        self._update_buttons()

    def make_team(self, name, base):
        try:
            team = template.add_team(self.game, self.project, name, base)
        except (template.ProjectError, OSError, ValueError) as e:
            self.show_error(str(e))
            return
        self.team_box.setEditText(team)
        self.refresh_changes()

    def _ask_team(self):
        self.make_team(self.team_name_edit.text(), self.base_team_box.currentText())

    def build(self, out):
        try:
            self.save_details()
            result = template.build_mod_zip(self.project, self.game, out)
        except (template.ProjectError, OSError) as e:
            self.show_error(str(e))
            return None
        self.refresh_changes()
        return result

    def convert_file(self, path):
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in (".bog", ".dds"):
            self.show_error("Choose a .bog or .dds file.")
            return None
        target = path.with_suffix(".dds" if suffix == ".bog" else ".bog")
        if target.exists():
            self.show_error(f"{target} already exists.")
            return None
        try:
            data = path.read_bytes()
            target.write_bytes(bog.bog_to_dds(data) if suffix == ".bog" else bog.dds_to_bog(data, None))
        except (bog.BogError, OSError) as e:
            self.show_error(f"{path.name}: {e}")
            return None
        return target

    def save_addon(self, path):
        try:
            return addon.build_addon(path)
        except OSError as e:
            self.show_error(str(e))
            return None

    def open_folder(self):
        os.startfile(str(self.project))

    def _ask_start(self):
        parent = QFileDialog.getExistingDirectory(self, "Choose where to create the project")
        if parent:
            car = self.car_box.currentText()
            self.start_from_car(car, Path(parent) / f"{car}_mod")

    def _ask_new(self):
        name = self.new_name_edit.text().strip()
        if not name:
            self.show_error("Type a name for the new car first.")
            return
        parent = QFileDialog.getExistingDirectory(self, "Choose where to create the project")
        if parent:
            self.new_from_car(self.car_box.currentText(), name, self.team_box.currentText(), Path(parent) / f"{name}_mod")

    def _ask_open(self):
        path = QFileDialog.getExistingDirectory(self, "Open a mod project")
        if path:
            self.open_project(path)

    def _ask_addon(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the Blender add-on", "world_race_models.zip", "Add-on zips (*.zip)")
        if path and self.save_addon(path):
            QMessageBox.information(self, "World Race Mod Manager", f"Saved {path}. Install it in Blender under Edit, Preferences, Add-ons.")

    def _ask_convert(self):
        path, _ = QFileDialog.getOpenFileName(self, "Convert a texture", "", "Textures (*.bog *.dds)")
        if path and self.convert_file(path):
            QMessageBox.information(self, "World Race Mod Manager", "Converted.")

    def _ask_build(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the mod zip", "", "Mod zips (*.zip)")
        if path and self.build(path):
            QMessageBox.information(self, "World Race Mod Manager", f"Built {path}")
