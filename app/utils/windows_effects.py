from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, WinDLL, byref, c_int, c_size_t, c_uint, c_void_p


class ACCENT_POLICY(Structure):
    _fields_ = [
        ("AccentState", c_int),
        ("AccentFlags", c_int),
        ("GradientColor", c_uint),
        ("AnimationId", c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(Structure):
    _fields_ = [
        ("Attribute", c_int),
        ("Data", c_void_p),
        ("SizeOfData", c_size_t),
    ]


def _abgr_with_alpha(alpha: int, red: int, green: int, blue: int) -> int:
    return (alpha << 24) | (blue << 16) | (green << 8) | red


def apply_window_effects(window) -> None:
    try:
        hwnd = window.winfo_id()
    except Exception:
        return

    try:
        user32 = WinDLL("user32")
        set_composition = user32.SetWindowCompositionAttribute
    except Exception:
        set_composition = None

    if set_composition:
        gradient = _abgr_with_alpha(170, 12, 16, 23)
        accent = ACCENT_POLICY(4, 2, gradient, 0)
        data = WINDOWCOMPOSITIONATTRIBDATA(
            19,
            ctypes.cast(byref(accent), c_void_p),
            ctypes.sizeof(accent),
        )
        try:
            set_composition(hwnd, byref(data))
        except Exception:
            try:
                accent = ACCENT_POLICY(3, 0, gradient, 0)
                data = WINDOWCOMPOSITIONATTRIBDATA(
                    19,
                    ctypes.cast(byref(accent), c_void_p),
                    ctypes.sizeof(accent),
                )
                set_composition(hwnd, byref(data))
            except Exception:
                pass

    try:
        dwmapi = WinDLL("dwmapi")
        preference = c_int(2)
        dwmapi.DwmSetWindowAttribute(hwnd, 33, byref(preference), ctypes.sizeof(preference))
    except Exception:
        return
