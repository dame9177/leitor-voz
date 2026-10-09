import pytest

from leitor.config import Settings


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    s = Settings()
    s.update({"voice": "cedar", "speed": 1.25})
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.voice == "cedar"
    assert loaded.speed == 1.25


def test_load_missing_or_corrupt_gives_defaults(tmp_path):
    assert Settings.load(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert Settings.load(bad) == Settings()


def test_update_validates():
    s = Settings()
    with pytest.raises(ValueError):
        s.update({"voice": "robocop"})
    with pytest.raises(ValueError):
        s.update({"speed": 9})
    assert s.voice == "marin" and s.speed == 1.0


def test_output_device_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    s = Settings()
    assert s.output_device == ""
    s.update({"output_device": "bluez_output.AA.1"})
    s.save(path)
    assert Settings.load(path).output_device == "bluez_output.AA.1"
