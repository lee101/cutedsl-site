import pytest

from training_store import safe_join


def test_safe_join_confines_to_base(tmp_path):
    base = tmp_path / "datasets"
    base.mkdir()
    (tmp_path / "outside").mkdir()
    (base / "link").symlink_to(tmp_path / "outside")
    assert safe_join(base, "cats") == str((base / "cats").resolve())
    assert safe_join(base, "a/b.png") == str((base / "a" / "b.png").resolve())
    for bad in ["", ".", "..", "../x", "a/../../x", "/etc/passwd", "a\\b", "a\x00b", "link/x"]:
        with pytest.raises(ValueError):
            safe_join(base, bad)
