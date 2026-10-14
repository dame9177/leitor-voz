import json

import pytest

from leitor.config import Settings


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    s = Settings()
    s.update({"voice": "Puck", "speed": 1.25})
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.voice == "Puck"
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
    assert s.voice == "Sadaltager" and s.speed == 1.0


def test_v01_openai_settings_are_migrated(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "voice": "marin", "speed": 1.25, "model": "gpt-4o-mini-tts",
        "instructions": "Leia em português do Brasil…", "output_device": "x",
    }))
    s = Settings.load(path)
    assert s.voice == "Sadaltager"
    assert s.model == "gemini-3.8-flash-tts"
    assert s.style == Settings().style
    assert s.speed == 1.25 and s.output_device == "x"


def test_output_device_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    s = Settings()
    assert s.output_device == ""
    s.update({"output_device": "bluez_output.AA.1"})
    s.save(path)
    assert Settings.load(path).output_device == "bluez_output.AA.1"
