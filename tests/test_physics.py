import pytest

from wrmod.physics import PhysicsError, read_physics, rebase, split_params, write_physics

STOCK = (
    "// Params for base\r\nNENGINEBINS\t2\r\nENGINETORQUECURVE\r\n\t1.0\r\n\t1.0\r\n"
    "ENGINETORQUEMAX\t1.18\r\nENGINEFRICTION\t3.0\r\nNGEARS\t2\r\nGEARRATIOS\r\n"
    "\t-4.0\t0\t0\t\t// REVERSE\r\n\t0.9\t6000\t3150\r\nINAIRGRAVSCALEUPSHORT\t1.585\r\n"
    "NWHEELS\t4\r\nWHEEL\t0\r\nWHEELRADIUS\t0.43\r\nEND\r\n"
)
OVERHAUL = (
    "NENGINEBINS\t3\r\nENGINETORQUECURVE\r\n\t1.6\r\n\t1.6\r\n\t1.6\r\nENGINETORQUEMAX\t1.5\r\n"
    "ENGINEFRICTION\t1.0\r\nNGEARS\t2\r\nGEARRATIOS\r\n\t-4.0\t0\t0\r\n\t0.8\t6000\t3150\r\n"
    "SIDEFORCEMAX\t130.0\t130.0\r\nMAXSTEERANGLE\t26.0\r\nNWHEELS\t4\r\nWHEEL\t0\r\nWHEELRADIUS\t0.43\r\nEND\r\n"
)
S = read_physics(STOCK)


def rebased(mod_text, stock=S):
    return read_physics(rebase(mod_text, stock, OVERHAUL))


def test_read_physics_reads_scalars_curves_and_gears():
    assert S["ENGINETORQUEMAX"] == [1.18]
    assert S["ENGINETORQUECURVE"] == [1.0, 1.0]
    assert S["GEARRATIOS"] == [-4, 0, 0, 0.9, 6000, 3150]
    assert "WHEELRADIUS" not in S
    assert list(S)[0] == "NENGINEBINS"


def test_crlf_and_comments_parse_the_same():
    assert read_physics(STOCK.replace("\r\n", "\n")) == S


def test_unreadable_token_raises_physics_error():
    with pytest.raises(PhysicsError):
        read_physics("ENGINETORQUEMAX\tabc\r\n")


def test_split_params_starts_wheels_at_nwheels():
    assert split_params(STOCK)[1].startswith("NWHEELS")


def test_split_params_starts_wheels_at_first_wheel_without_nwheels():
    assert split_params(STOCK.replace("NWHEELS\t4\r\n", ""))[1].startswith("WHEEL\t0")


def test_write_then_read_round_trips():
    assert read_physics(write_physics(S)) == S


def test_unchanged_mod_takes_overhaul_physics_and_keeps_its_wheels():
    mod = STOCK.replace("WHEELRADIUS\t0.43", "WHEELRADIUS\t0.38")
    out = rebase(mod, S, OVERHAUL)
    assert read_physics(out) == read_physics(OVERHAUL)
    assert split_params(out)[1] == split_params(mod)[1]
    assert "INAIRGRAVSCALEUPSHORT" not in out


def test_changed_value_scales_by_ratio():
    assert rebased(STOCK.replace("1.18", "0.8"))["ENGINETORQUEMAX"] == [pytest.approx(1.5 * 0.8 / 1.18)]


def test_changed_gear_row_scales_each_number():
    out = rebased(STOCK.replace("\t0.9\t6000\t3150", "\t0.79\t6000\t3150"))
    assert out["GEARRATIOS"] == pytest.approx([-4, 0, 0, 0.8 * 0.79 / 0.9, 6000, 3150])
    assert out["NGEARS"] == [2]


def test_changed_curve_of_another_length_keeps_mod_curve_and_count():
    out = rebased(STOCK.replace("\t1.0\r\n\t1.0\r\n", "\t1.2\r\n\t1.2\r\n"))
    assert out["ENGINETORQUECURVE"] == [1.2, 1.2]
    assert out["NENGINEBINS"] == [2]


def test_unchanged_curve_takes_overhaul_count():
    assert rebased(STOCK)["NENGINEBINS"] == [3]


def test_key_added_by_mod_is_kept():
    out = rebased(STOCK.replace("NWHEELS", "LENGTH\t4.5\r\nSIDEFORCEMAX\t120.0\t120.0\r\nNWHEELS"))
    assert out["LENGTH"] == [4.5]
    assert out["SIDEFORCEMAX"] == [120, 120]


def test_changed_key_missing_from_overhaul_is_kept():
    assert rebased(STOCK.replace("1.585", "1.7"))["INAIRGRAVSCALEUPSHORT"] == [1.7]


def test_key_removed_by_mod_is_left_out():
    assert "ENGINEFRICTION" not in rebased(STOCK.replace("ENGINEFRICTION\t3.0\r\n", ""))


def test_zero_stock_value_uses_mod_value():
    stock = {**S, "ENGINEFRICTION": [0.0]}
    assert rebased(STOCK.replace("ENGINEFRICTION\t3.0", "ENGINEFRICTION\t2.0"), stock)["ENGINEFRICTION"] == [2.0]


def test_overhaul_only_keys_are_added():
    out = rebased(STOCK)
    assert out["MAXSTEERANGLE"] == [26]
    assert out["SIDEFORCEMAX"] == [130, 130]
