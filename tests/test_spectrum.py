"""Pure-Python FFT helper."""

import math

from etools.core.spectrum import real_magnitude_spectrum


def test_sine_peak_near_expected_bin():
    n = 128
    freq_bin = 8
    samples = [math.sin(2 * math.pi * freq_bin * i / n) for i in range(n)]
    mags = real_magnitude_spectrum(samples, max_n=n)
    assert mags
    peak = max(range(len(mags)), key=mags.__getitem__)
    assert abs(peak - freq_bin) <= 1


def test_rejects_empty_and_non_finite():
    assert real_magnitude_spectrum([]) == []
    assert real_magnitude_spectrum([float("nan"), 1.0]) == []
