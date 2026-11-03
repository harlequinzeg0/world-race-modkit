"""The "Play with mods" tab: profiles, active and inactive lists, conflicts, Play."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import deploy, modpack, profiles, store
from ..conflicts import find_conflicts
from .worker import PlayWorker

ID_ROLE = Qt.UserRole


class PlayTab(QWidget):
    running_changed = Signal(bool)

    def __init__(self, game):
        super().__init__()
        self.game = Path(game) if game else None
        self.profile = profiles.load(store.profiles_dir(), profiles.STOCK)
        self._mods = {}
        self._worker = None
        self._filling = False

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.play)
        self.add_zip_button = QPushButton("Add zip")
        self.add_zip_button.clicked.connect(self._choose_zip)

        self.profile_box = QComboBox()
        self.profile_box.textActivated.connect(self.select_profile)
        self.active_list = self._make_list()
        self.inactive_list = self._make_list()
        self.conflict_box = QPlainTextEdit(readOnly=True)
        self.conflict_box.setMaximumHeight(90)
        self.status = QLabel()

        self._build_layout()
        self.setAcceptDrops(True)
        self.refresh()

    def _make_list(self):
        widget = QListWidget()
        widget.setDragDropMode(QAbstractItemView.DragDrop)
        widget.setDefaultDropAction(Qt.MoveAction)
        widget.setSelectionMode(QAbstractItemView.SingleSelection)
        widget.model().rowsInserted.connect(self._lists_changed)
        widget.model().rowsMoved.connect(self._lists_changed)
        return widget

    def _button(self, text, handler):
        button = QPushButton(text)
        button.clicked.connect(handler)
        return button

    def _build_layout(self):
        top = QHBoxLayout()
        top.addWidget(QLabel("Profile"))
        top.addWidget(self.profile_box, 1)
        self.profile_buttons = [
            self._button("New", self._ask_new_profile),
            self._button("Rename", self._ask_rename_profile),
            self._button("Duplicate", self._ask_duplicate_profile),
            self._button("Delete", self.delete_profile),
        ]
        for button in self.profile_buttons:
            top.addWidget(button)

        middle = QVBoxLayout()
        middle.addStretch()
        middle.addWidget(self._button("<< Activate", lambda: self._on_selected(self.inactive_list, self.activate)))
        middle.addWidget(self._button("Deactivate >>", lambda: self._on_selected(self.active_list, self.deactivate)))
        middle.addWidget(self._button("Move up", lambda: self._on_selected(self.active_list, lambda m: self.move(m, -1))))
        middle.addWidget(self._button("Move down", lambda: self._on_selected(self.active_list, lambda m: self.move(m, 1))))
        middle.addWidget(self._button("Remove mod", lambda: self._on_selected(self.inactive_list, self.remove_mod)))
        middle.addStretch()

        left = QVBoxLayout()
        left.addWidget(QLabel("Active mods (lower in the list wins)"))
        left.addWidget(self.active_list)
        right = QVBoxLayout()
        right.addWidget(QLabel("Inactive mods"))
        right.addWidget(self.inactive_list)

        lists = QHBoxLayout()
        lists.addLayout(left, 1)
        lists.addLayout(middle)
        lists.addLayout(right, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(lists, 1)
        layout.addWidget(QLabel("Conflicts"))
        layout.addWidget(self.conflict_box)
        layout.addWidget(self.status)

    def show_error(self, text):
        QMessageBox.warning(self, "World Race Mod Manager", text)

    def confirm(self, text):
        return QMessageBox.question(self, "World Race Mod Manager", text) == QMessageBox.Yes

    def set_game(self, game):
        self.game = Path(game) if game else None
        self._update_status()

    def active_ids(self):
        return self._ids(self.active_list)

    def inactive_ids(self):
        return self._ids(self.inactive_list)

    def _ids(self, widget):
        return [widget.item(row).data(ID_ROLE) for row in range(widget.count())]

    def _fill(self, widget, ids):
        widget.clear()
        for mod_id in ids:
            mod = self._mods[mod_id]
            item = QListWidgetItem(f"{mod.name}  [{mod.kind}] {mod.version}")
            item.setData(ID_ROLE, mod_id)
            item.setToolTip(mod.description)
            widget.addItem(item)

    def refresh(self):
        root = store.profiles_dir()
        self._mods = modpack.installed_mods(store.mods_dir())
        self.profile = profiles.load(root, self.profile.name)
        missing = profiles.prune_missing(self.profile, set(self._mods))
        if missing:
            profiles.save(root, self.profile)
            self.show_error(f"Removed from this profile because they are no longer installed: {', '.join(missing)}")

        self._filling = True
        self.profile_box.clear()
        self.profile_box.addItems(profiles.list_profiles(root))
        self.profile_box.setCurrentText(self.profile.name)
        self._fill(self.active_list, self.profile.active)
        self._fill(self.inactive_list, sorted(set(self._mods) - set(self.profile.active)))
        self._filling = False
        self._update_status()

    def _update_status(self):
        self.conflict_box.setPlainText("\n".join(self.conflict_lines()))
        idle = self._worker is None
        self.play_button.setEnabled(bool(self.game) and idle)
        # The save goes back to the running profile by name when the game exits.
        self.profile_box.setEnabled(idle)
        for button in self.profile_buttons:
            button.setEnabled(idle)
        self.running_changed.emit(not idle)
        if not self.game:
            self.status.setText("Choose the game folder to start.")
        elif not idle:
            self.status.setText("The game is running.")
        else:
            self.status.setText(f"Ready. {len(self.profile.active)} mods active.")

    def conflict_lines(self):
        lines = []
        for conflict in find_conflicts(store.mods_dir(), self.profile.active):
            others = ", ".join(mod for mod in conflict.mods if mod != conflict.winner)
            lines.append(f"{conflict.key}: {conflict.winner} wins over {others}")
        for rel in deploy.ignored_files(store.mods_dir(), self.profile.active):
            lines.append(f"{rel}: the game cannot load this file from a mod")
        return lines

    def _save_active(self, active):
        if self.profile.name == profiles.STOCK:
            self.show_error("The Stock profile runs the unmodified game. Create a profile to use mods.")
            self.refresh()
            return
        self.profile.active = active
        profiles.save(store.profiles_dir(), self.profile)
        self.refresh()

    def _lists_changed(self):
        if not self._filling:
            # Qt adds the dropped row before removing the old one, so wait for it.
            QTimer.singleShot(0, lambda: self._save_active(self.active_ids()))

    def _on_selected(self, widget, action):
        item = widget.currentItem()
        if item:
            action(item.data(ID_ROLE))

    def activate(self, mod_id):
        self._save_active([*self.profile.active, mod_id])

    def deactivate(self, mod_id):
        self._save_active([mod for mod in self.profile.active if mod != mod_id])

    def move(self, mod_id, delta):
        active = list(self.profile.active)
        index = active.index(mod_id)
        target = index + delta
        if 0 <= target < len(active):
            active[index], active[target] = active[target], active[index]
            self._save_active(active)

    def add_zip(self, path):
        try:
            modpack.install_zip(path, store.mods_dir())
        except modpack.ModError as e:
            self.show_error(str(e))
            return
        self.refresh()

    def _choose_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add a mod zip", "", "Mod zips (*.zip)")
        if path:
            self.add_zip(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.toLocalFile().lower().endswith(".zip"):
                self.add_zip(url.toLocalFile())
        event.acceptProposedAction()

    def remove_mod(self, mod_id):
        if self.confirm(f"Delete the mod {mod_id} from the tool?"):
            modpack.remove_mod(store.mods_dir(), mod_id)
            self.refresh()

    def select_profile(self, name):
        self.profile = profiles.load(store.profiles_dir(), name)
        settings = store.load_settings()
        settings["profile"] = name
        store.save_settings(settings)
        self.refresh()

    def _profile_action(self, action, *args):
        try:
            return action(store.profiles_dir(), *args)
        except (profiles.ProfileError, OSError) as e:
            self.show_error(str(e))
            return None

    def new_profile(self, name):
        if self._profile_action(profiles.create, name):
            self.select_profile(name)

    def delete_profile(self):
        if self.profile.name == profiles.STOCK:
            self.show_error("The Stock profile cannot be deleted.")
        elif self.confirm(f"Delete the profile {self.profile.name} and its save?"):
            self._profile_action(profiles.delete, self.profile.name)
            self.select_profile(profiles.STOCK)

    def _ask_name(self, title):
        name, accepted = QInputDialog.getText(self, title, "Profile name")
        return name if accepted and name else None

    def _ask_new_profile(self):
        name = self._ask_name("New profile")
        if name:
            self.new_profile(name)

    def _ask_rename_profile(self):
        name = self._ask_name("Rename profile")
        if name:
            self._profile_action(profiles.rename, self.profile.name, name)
            self.select_profile(name if name in profiles.list_profiles(store.profiles_dir()) else self.profile.name)

    def _ask_duplicate_profile(self):
        name = self._ask_name("Duplicate profile")
        if name and self._profile_action(profiles.duplicate, self.profile.name, name):
            self.select_profile(name)

    def running(self):
        return self._worker is not None

    def play(self):
        self._worker = PlayWorker(self.game, store.data_dir(), self.profile)
        self._worker.finished_code.connect(self._play_finished)
        self._worker.failed.connect(self._play_failed)
        self._update_status()
        self._worker.start()

    def _play_finished(self, code):
        self._worker = None
        self._update_status()

    def _play_failed(self, text):
        self._worker = None
        self._update_status()
        self.show_error(text)
