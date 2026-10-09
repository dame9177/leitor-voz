from leitor.outputs import OutputChooser

SPEAKER = "alsa_output.analog-stereo"
BASEUS = "bluez_output.AA.1"
RS19 = "bluez_output.BB.1"


def test_starts_on_system_default():
    c = OutputChooser([SPEAKER, BASEUS], default_id=SPEAKER)
    assert c.choose() == SPEAKER


def test_newly_connected_device_wins_even_if_not_system_default():
    c = OutputChooser([SPEAKER], default_id=SPEAKER)
    c.update([SPEAKER, RS19], default_id=SPEAKER)  # system didn't switch to it
    assert c.choose() == RS19


def test_system_default_change_wins():
    c = OutputChooser([SPEAKER, BASEUS, RS19], default_id=SPEAKER)
    c.update([SPEAKER, BASEUS, RS19], default_id=BASEUS)  # user picked it in GNOME
    assert c.choose() == BASEUS


def test_disconnecting_preferred_falls_back_to_default():
    c = OutputChooser([SPEAKER], default_id=SPEAKER)
    c.update([SPEAKER, RS19], default_id=SPEAKER)
    c.update([SPEAKER], default_id=SPEAKER)
    assert c.choose() == SPEAKER


def test_reconnecting_counts_as_new_connection():
    c = OutputChooser([SPEAKER, RS19], default_id=SPEAKER)
    c.update([SPEAKER], default_id=SPEAKER)
    c.update([SPEAKER, RS19], default_id=SPEAKER)
    assert c.choose() == RS19


def test_manual_choice_when_present_else_automatic():
    c = OutputChooser([SPEAKER, RS19], default_id=SPEAKER)
    assert c.choose(manual=RS19) == RS19
    c.update([SPEAKER], default_id=SPEAKER)
    assert c.choose(manual=RS19) == SPEAKER


def test_unknown_default_and_no_devices():
    c = OutputChooser([], default_id="")
    assert c.choose() == ""
