"""The main window."""
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, deploy, gameinfo, profiles, store
from ..gameinfo import GameError, check_game_folder
from .make_tab import MakeTab
from .play_tab import PlayTab

TITLE = "World Race Mod Manager"
COPY_FOLDER = "Hot Wheels World Race"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{TITLE} {__version__}")
        self.resize(900, 620)
        self.play_tab = PlayTab(None)
        self.make_tab = MakeTab(None)

        tabs = QTabWidget()
        tabs.addTab(self.play_tab, "Play with mods")
        tabs.addTab(self.make_tab, "Make a mod")

        self.folder_button = QPushButton("Game folder")
        self.folder_button.clicked.connect(self._change_folder)
        self.play_tab.running_changed.connect(lambda running: self.folder_button.setEnabled(not running))
        bar = QHBoxLayout()
        bar.addWidget(QLabel(TITLE))
        bar.addStretch()
        bar.addWidget(self.folder_button)
        bar.addWidget(self.play_tab.add_zip_button)
        bar.addWidget(self.play_tab.play_button)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(bar)
        layout.addWidget(tabs)
        self.setCentralWidget(central)

    def show_error(self, text):
        QMessageBox.warning(self, TITLE, text)

    def ask_folder(self):
        return QFileDialog.getExistingDirectory(self, "Choose the game folder") or None

    def ask_copy_target(self):
        parent = QFileDialog.getExistingDirectory(self, "Choose where to put a copy of the game")
        return str(Path(parent) / COPY_FOLDER) if parent else None

    def closeEvent(self, event):
        if self.play_tab.running():
            self.show_error("Close the game first. The tool restores your game folder when it exits.")
            event.ignore()
        else:
            event.accept()

    def copy_game(self, src, dst):
        dialog = QProgressDialog("Copying the game", None, 0, 0, self)
        dialog.show()

        def progress(done, total):
            dialog.setMaximum(total)
            dialog.setValue(done)
            QApplication.processEvents()

        gameinfo.copy_game(src, dst, progress)
        dialog.close()

    def _resolve_game(self, path):
        while True:
            if not path:
                path = self.ask_folder()
            if not path:
                return None
            try:
                check_game_folder(path)
                return path
            except GameError as e:
                if e.code != "protected":
                    self.show_error(str(e))
                    path = None
                    continue
                target = self.ask_copy_target()
                if not target:
                    return None
                try:
                    self.copy_game(path, target)
                except (GameError, OSError) as copy_error:
                    self.show_error(str(copy_error))
                    return None
                path = target

    def _use_game(self, path):
        game = self._resolve_game(path)
        self.play_tab.set_game(game)
        self.make_tab.set_game(game)
        if not game:
            return
        settings = store.load_settings()
        settings["game"] = str(game)
        store.save_settings(settings)
        try:
            deploy.restore(self.play_tab.game, store.data_dir())
        except (deploy.DeployError, OSError) as e:
            self.show_error(str(e))

    def _change_folder(self):
        self._use_game(None)

    def start(self):
        settings = store.load_settings()
        self._use_game(settings.get("game"))
        saved_profile = settings.get("profile")
        if saved_profile in profiles.list_profiles(store.profiles_dir()):
            self.play_tab.select_profile(saved_profile)


def run_gui():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.start()
    return app.exec()
