"""Lightweight real-FFT helpers for serial plot frequency view (no numpy)."""

from __future__ import annotations

import cmath
import math


def _next_power_of_two(n: int) -> int:
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def _fft(values: list[complex]) -> list[complex]:
    n = len(values)
    if n <= 1:
        return values
    if n & (n - 1):
        raise ValueError("FFT length must be a power of two")
    even = _fft(values[0::2])
    odd = _fft(values[1::2])
    out = [0j] * n
    half = n // 2
    for k in range(half):
        twiddle = cmath.exp(-2j * math.pi * k / n) * odd[k]
        out[k] = even[k] + twiddle
        out[k + half] = even[k] - twiddle
    return out


def real_magnitude_spectrum(samples: list[float], *, max_n: int = 1024) -> list[float]:
    """Return non-negative FFT magnitudes for a real sample window.

    Uses the most recent ``min(len(samples), max_n)`` points, zero-pads to the
    next power of two, and returns only the useful half of the spectrum.
    """
    if not samples:
        return []
    window = samples[-max_n:]
    finite = [float(v) for v in window if math.isfinite(float(v))]
    if len(finite) < 2:
        return []
    n = _next_power_of_two(len(finite))
    if n > max_n:
        n = max_n if (max_n & (max_n - 1)) == 0 else _next_power_of_two(max_n) // 2
        n = max(2, n)
        finite = finite[-n:]
        if len(finite) < n:
            finite = finite + [0.0] * (n - len(finite))
    else:
        finite = finite + [0.0] * (n - len(finite))
    spectrum = _fft([complex(v, 0.0) for v in finite])
    half = n // 2
    scale = 1.0 / max(1, n)
    return [abs(spectrum[k]) * scale for k in range(half)]
