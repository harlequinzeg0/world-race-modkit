from wrmod.options import (
    ACTIONS,
    BUTTONS,
    CONFIG_FILE,
    DEFAULT_LAYOUT,
    STICKS,
    choices,
    from_settings,
    player_one_device,
    session_fields,
)

DEVICE_OFFSET = 0x225


def test_empty_settings_give_defaults():
    assert from_settings({}) == {"borderless": True, "controller": True, "layout": DEFAULT_LAYOUT}


def test_defaults_cover_every_action():
    assert set(DEFAULT_LAYOUT) == set(ACTIONS)
    assert all(DEFAULT_LAYOUT[action] in choices(action) for action in ACTIONS)


def test_saved_choices_are_kept():
    opts = from_settings({"borderless": False, "layout": {"nitro": "y"}})
    assert opts["layout"]["nitro"] == "y"
    assert opts["borderless"] is False
    assert opts["layout"]["brake"] == "lt"


def test_bad_layout_entries_fall_back_to_defaults():
    opts = from_settings({"borderless": "yes", "controller": None, "layout": {"nitro": "z", "steer": "a", "brake": 3, "jump": "a"}})
    assert opts["layout"]["nitro"] == "b"
    assert opts["layout"]["steer"] == "left_stick"
    assert opts["layout"]["brake"] == "lt"
    assert "jump" not in opts["layout"]
    assert opts["borderless"] is True
    assert opts["controller"] is True


def test_a_layout_that_is_not_a_table_gives_the_defaults():
    assert from_settings({"layout": ["a"]})["layout"] == DEFAULT_LAYOUT


def test_face_buttons_and_the_second_brake():
    assert (DEFAULT_LAYOUT["handbrake"], DEFAULT_LAYOUT["nitro"], DEFAULT_LAYOUT["second_brake"]) == ("a", "b", "y")
    assert choices("second_brake") == BUTTONS


def test_choices_by_action():
    assert choices("steer") == STICKS
    assert choices("flip") == STICKS
    assert choices("nitro") == BUTTONS


def test_session_fields_shape():
    opts = from_settings({"controller": False})
    assert session_fields(opts) == {
        "display": {"borderless": True},
        "controller": {"enabled": False, "layout": DEFAULT_LAYOUT},
    }


def test_player_one_device(tmp_path):
    data = bytearray(0x300)
    data[DEVICE_OFFSET:DEVICE_OFFSET + 9] = b"Keyboard\0"
    (tmp_path / CONFIG_FILE).write_bytes(bytes(data))
    assert player_one_device(tmp_path) == "Keyboard"


def test_player_one_device_from_a_short_or_missing_file(tmp_path):
    assert player_one_device(tmp_path) is None
    (tmp_path / CONFIG_FILE).write_bytes(b"short")
    assert player_one_device(tmp_path) is None
