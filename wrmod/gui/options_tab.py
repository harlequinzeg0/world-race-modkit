"""The "Options" tab: the borderless window and the Xbox controller layout.

Every change saves at once. WRSE reads the options from the session when the game starts.
"""
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import options, store

ACTION_NAMES = {
    "accelerate": "Accelerate",
    "brake": "Brake",
    "second_brake": "Brake (second input)",
    "steer": "Steer and barrel roll",
    "flip": "Flip forward / back",
    "handbrake": "Handbrake",
    "nitro": "Nitro boost",
    "camera_change": "Camera change",
    "camera_behind": "Camera behind",
}
INPUT_NAMES = {
    "left_stick": "Left stick",
    "right_stick": "Right stick",
    "a": "A",
    "b": "B",
    "x": "X",
    "y": "Y",
    "lb": "Left bumper",
    "rb": "Right bumper",
    "lt": "Left trigger",
    "rt": "Right trigger",
    "back": "Back",
    "left_stick_click": "Left stick click",
    "right_stick_click": "Right stick click",
}
FIXED_NOTE = "D-pad also steers and flips. Start pauses. In menus: A or Start selects, B goes back."
PAD_WARNING = "Player 1 is set to a controller in the game's launcher. Set it to Keyboard there, or the controller acts twice."
KEYBOARD = "Keyboard"


class OptionsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.game = None
        saved = options.from_settings(store.load_settings())
        self.borderless_box = QCheckBox("Borderless window")
        self.borderless_box.setChecked(saved["borderless"])
        self.controller_box = QCheckBox("Use Xbox controller")
        self.controller_box.setChecked(saved["controller"])
        self._combos = {}
        for action in options.ACTIONS:
            combo = QComboBox()
            for value in options.choices(action):
                combo.addItem(INPUT_NAMES[value], value)
            combo.setCurrentIndex(combo.findData(saved["layout"][action]))
            self._combos[action] = combo
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.reset_button = QPushButton("Reset to default")
        self._build_layout()
        self._update_rows()
        # Connected last, so filling the boxes above saves nothing.
        self.borderless_box.toggled.connect(self._save)
        self.controller_box.toggled.connect(self._controller_changed)
        for combo in self._combos.values():
            combo.currentIndexChanged.connect(self._save)
        self.reset_button.clicked.connect(self.reset)

    def _build_layout(self):
        form = QFormLayout()
        for action in options.ACTIONS:
            form.addRow(ACTION_NAMES[action], self._combos[action])
        note = QLabel(FIXED_NOTE)
        note.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(self.borderless_box)
        layout.addWidget(self.controller_box)
        layout.addWidget(self.warning)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addLayout(buttons)
        layout.addStretch()

    def combo(self, action):
        return self._combos[action]

    def set_game(self, game):
        self.game = game
        self._update_rows()

    def _update_rows(self):
        enabled = self.controller_box.isChecked()
        for combo in self._combos.values():
            combo.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)
        device = options.player_one_device(self.game) if self.game and enabled else None
        self.warning.setText(PAD_WARNING if device not in (None, KEYBOARD) else "")

    def _controller_changed(self):
        self._update_rows()
        self._save()

    def _save(self):
        settings = store.load_settings()
        settings["borderless"] = self.borderless_box.isChecked()
        settings["controller"] = self.controller_box.isChecked()
        settings["layout"] = {action: combo.currentData() for action, combo in self._combos.items()}
        store.save_settings(settings)

    def reset(self):
        for action, value in options.DEFAULT_LAYOUT.items():
            combo = self._combos[action]
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(value))
            combo.blockSignals(False)
        self._save()
