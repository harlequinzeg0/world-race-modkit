"""Run Play away from the UI thread, because it lasts as long as the game does."""
from PySide6.QtCore import QThread, Signal

from .. import deploy


class PlayWorker(QThread):
    # Windows crash codes do not fit a signed 32-bit integer.
    finished_code = Signal(object)
    failed = Signal(str)

    def __init__(self, game, data, profile):
        super().__init__()
        self._game = game
        self._data = data
        self._profile = profile

    def run(self):
        # Any error must reach the window, or it stays locked as "running" forever.
        try:
            self.finished_code.emit(deploy.play(self._game, self._data, self._profile))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
