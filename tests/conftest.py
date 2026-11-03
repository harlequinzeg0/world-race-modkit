import gc
import os
from pathlib import Path

import pytest


@pytest.fixture
def game_dir():
    path = os.environ.get("WRMOD_GAME")
    if not path:
        pytest.skip("WRMOD_GAME is not set")
    return Path(path)


@pytest.fixture(scope="session")
def qapp():
    widgets = pytest.importorskip("PySide6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield app
    # Widgets must go before the application, or Python crashes at exit.
    core = pytest.importorskip("PySide6.QtCore")
    for widget in widgets.QApplication.topLevelWidgets():
        widget.deleteLater()
    core.QCoreApplication.sendPostedEvents(None, core.QEvent.DeferredDelete)
    gc.collect()
