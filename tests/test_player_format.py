from PySide6.QtMultimedia import QAudioFormat

from leitor.player import audio_format


def test_mono_has_explicit_channel_config():
    # Without ChannelConfigMono, PipeWire gets an unpositioned AUX0 channel and
    # plays it on the left side only (seen with Bluetooth headphones).
    fmt = audio_format()
    assert fmt.channelCount() == 1
    assert fmt.channelConfig() == QAudioFormat.ChannelConfig.ChannelConfigMono
    assert fmt.sampleRate() == 24_000
    assert fmt.sampleFormat() == QAudioFormat.SampleFormat.Int16
