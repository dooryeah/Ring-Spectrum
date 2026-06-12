import os
import sys
import json
import copy
import pygame
import numpy as np
import pyaudiowpatch as pyaudio
import win32api
import win32con
import win32gui
import math
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox, filedialog, simpledialog
import pystray
from PIL import Image, ImageDraw
import threading
from collections import deque

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(application_path, "config.json")
APP_NAME = "Ring Spectrum"
APP_VERSION = "0.4.0"
PRESET_EXPORT_FORMAT = "ring-spectrum-presets"
PRESET_EXPORT_VERSION = 1
PERFORMANCE_MODE_POWER_SAVER = "power_saver"
PERFORMANCE_MODE_BALANCED = "balanced"
PERFORMANCE_MODE_QUALITY = "quality"
COLOR_MODE_SOLID = "solid"
COLOR_MODE_ENDPOINT = "gradient"
COLOR_MODE_VERTICAL = "vertical_gradient"
SP_MODE_NORMAL = "normal"
SP_MODE_BEAT = "beat"
BAR_SMOOTH_KERNEL = (1.0, 4.0, 6.0, 4.0, 1.0)

PERFORMANCE_PROFILES = {
    PERFORMANCE_MODE_POWER_SAVER: {
        "label": "省电",
        "fps": 30,
        "root_fade_segments": 24,
        "max_bars": 96
    },
    PERFORMANCE_MODE_BALANCED: {
        "label": "均衡",
        "fps": 45,
        "root_fade_segments": 40,
        "max_bars": 160
    },
    PERFORMANCE_MODE_QUALITY: {
        "label": "高质量",
        "fps": 120,
        "root_fade_segments": 64,
        "max_bars": None
    }
}

AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
ULW_ALPHA = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG)
    ]


class SIZE(ctypes.Structure):
    _fields_ = [
        ("cx", wintypes.LONG),
        ("cy", wintypes.LONG)
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte)
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3)
    ]


user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD
]
gdi32.CreateDIBSection.restype = wintypes.HANDLE


class LayeredWindowBitmap:
    def __init__(self):
        self.width = 0
        self.height = 0
        self.mem_dc = None
        self.bitmap = None
        self.old_bitmap = None
        self.bits = None
        self.bgra = None
        self.alpha_buffer = None
        self.channel_buffer = None

    def close(self):
        if self.mem_dc and self.old_bitmap:
            gdi32.SelectObject(self.mem_dc, self.old_bitmap)
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
        if self.mem_dc:
            gdi32.DeleteDC(self.mem_dc)
        self.width = 0
        self.height = 0
        self.mem_dc = None
        self.bitmap = None
        self.old_bitmap = None
        self.bits = None
        self.bgra = None
        self.alpha_buffer = None
        self.channel_buffer = None

    def ensure_size(self, width, height):
        if self.width == width and self.height == height and self.mem_dc and self.bitmap:
            return

        self.close()
        screen_dc = user32.GetDC(None)
        try:
            self.mem_dc = gdi32.CreateCompatibleDC(screen_dc)
            if not self.mem_dc:
                raise ctypes.WinError()

            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bitmap_info.bmiHeader.biWidth = width
            bitmap_info.bmiHeader.biHeight = -height
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = BI_RGB
            bitmap_info.bmiHeader.biSizeImage = width * height * 4

            bits = ctypes.c_void_p()
            self.bitmap = gdi32.CreateDIBSection(
                self.mem_dc,
                ctypes.byref(bitmap_info),
                DIB_RGB_COLORS,
                ctypes.byref(bits),
                None,
                0
            )
            if not self.bitmap or not bits.value:
                raise ctypes.WinError()

            self.old_bitmap = gdi32.SelectObject(self.mem_dc, self.bitmap)
            self.bits = bits
            self.width = width
            self.height = height
            self.bgra = np.empty((height, width, 4), dtype=np.uint8)
            self.alpha_buffer = np.empty((height, width), dtype=np.uint16)
            self.channel_buffer = np.empty((height, width), dtype=np.uint16)
        finally:
            user32.ReleaseDC(None, screen_dc)

    def update(self, hwnd, surface, x, y, alpha_mask=None, color_mask=None):
        width, height = surface.get_size()
        self.ensure_size(width, height)

        rgb = pygame.surfarray.pixels3d(surface)
        alpha = pygame.surfarray.pixels_alpha(surface)
        try:
            alpha_src = alpha.T
            if alpha_mask is not None:
                np.multiply(alpha_src, alpha_mask, out=self.alpha_buffer, casting="unsafe")
                np.floor_divide(self.alpha_buffer, 255, out=self.alpha_buffer)
            else:
                np.copyto(self.alpha_buffer, alpha_src, casting="unsafe")

            np.copyto(self.bgra[:, :, 3], self.alpha_buffer, casting="unsafe")
            for dst_channel, src_channel in ((0, 2), (1, 1), (2, 0)):
                if color_mask is not None:
                    np.multiply(
                        color_mask[:, :, src_channel],
                        self.alpha_buffer,
                        out=self.channel_buffer,
                        casting="unsafe"
                    )
                else:
                    np.multiply(rgb[:, :, src_channel].T, self.alpha_buffer, out=self.channel_buffer, casting="unsafe")
                np.floor_divide(self.channel_buffer, 255, out=self.channel_buffer)
                np.copyto(self.bgra[:, :, dst_channel], self.channel_buffer, casting="unsafe")
        finally:
            del alpha
            del rgb

        ctypes.memmove(self.bits.value, self.bgra.ctypes.data, self.bgra.nbytes)

        screen_dc = user32.GetDC(None)
        try:
            dst_point = POINT(int(x), int(y))
            size = SIZE(width, height)
            src_point = POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            updated = user32.UpdateLayeredWindow(
                hwnd,
                screen_dc,
                ctypes.byref(dst_point),
                ctypes.byref(size),
                self.mem_dc,
                ctypes.byref(src_point),
                0,
                ctypes.byref(blend),
                ULW_ALPHA
            )
            if not updated:
                raise ctypes.WinError()
        finally:
            user32.ReleaseDC(None, screen_dc)


DEFAULT_CONFIG = {
    "width": 600,
    "height": 600,
    "x": 100,
    "y": 100,
    "alpha": 100,
    "sensitivity": 5.0,
    "start_color": [0, 255, 255],
    "end_color": [255, 0, 255],
    "bars": 64,
    "decay": 0.8,
    "color_mode": COLOR_MODE_ENDPOINT,
    "sp_mode": SP_MODE_NORMAL,
    "spectrum_style": "ring",
    "spectrum_flip": False,
    "spectrum_rotate_90": False,
    "spectrum_root_fade": False,
    "bar_height": 100.0,
    "bar_length": 100.0,
    "overlay_target": "【默认】桌面底层",
    "performance_mode": PERFORMANCE_MODE_BALANCED
}

PRESET_CONFIG_KEYS = tuple(
    key for key in DEFAULT_CONFIG.keys()
    if key not in ("performance_mode",)
)
DEFAULT_CONFIG.update({
    "active_preset": "",
    "presets": {}
})

config = {}

def normalize_color_mode(mode):
    if mode in (COLOR_MODE_SOLID, COLOR_MODE_ENDPOINT, COLOR_MODE_VERTICAL):
        return mode
    return COLOR_MODE_ENDPOINT

def normalize_sp_mode(mode):
    if mode == SP_MODE_BEAT:
        return SP_MODE_BEAT
    return SP_MODE_NORMAL

def normalize_performance_mode(mode):
    if mode in PERFORMANCE_PROFILES:
        return mode
    return PERFORMANCE_MODE_BALANCED

def normalize_preset_name(name):
    if name is None:
        return ""
    return " ".join(str(name).strip().split())

def normalize_bar_count(value):
    try:
        return max(1, int(value))
    except Exception:
        return int(DEFAULT_CONFIG["bars"])

def normalize_color_value(value, fallback):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        value = fallback
    normalized = []
    for channel in value[:3]:
        try:
            normalized.append(max(0, min(255, int(channel))))
        except Exception:
            normalized.append(0)
    return normalized

def normalize_config_values(values):
    values["color_mode"] = normalize_color_mode(values.get("color_mode"))
    values["sp_mode"] = normalize_sp_mode(values.get("sp_mode"))
    if "performance_mode" in values:
        values["performance_mode"] = normalize_performance_mode(values.get("performance_mode"))
    values["bars"] = normalize_bar_count(values.get("bars"))
    values["start_color"] = normalize_color_value(values.get("start_color"), DEFAULT_CONFIG["start_color"])
    values["end_color"] = normalize_color_value(values.get("end_color"), DEFAULT_CONFIG["end_color"])
    return values

def preset_snapshot_from(source, fallback=None):
    source = source if isinstance(source, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else DEFAULT_CONFIG
    snapshot = {}
    for key in PRESET_CONFIG_KEYS:
        if key in source:
            snapshot[key] = copy.deepcopy(source[key])
        else:
            snapshot[key] = copy.deepcopy(fallback[key])
    return normalize_config_values(snapshot)

def normalize_presets():
    presets = config.get("presets")
    if not isinstance(presets, dict):
        presets = {}

    cleaned = {}
    for name, preset in presets.items():
        preset_name = normalize_preset_name(name)
        if preset_name and isinstance(preset, dict):
            cleaned[preset_name] = preset_snapshot_from(preset)

    config["presets"] = cleaned
    active_preset = normalize_preset_name(config.get("active_preset", ""))
    config["active_preset"] = active_preset if active_preset in cleaned else ""

def make_unique_preset_name(base_name):
    base_name = normalize_preset_name(base_name) or "未命名预设"
    presets = config.get("presets", {})
    if base_name not in presets:
        return base_name

    index = 2
    while True:
        candidate = f"{base_name} {index}"
        if candidate not in presets:
            return candidate
        index += 1

def normalize_config():
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = copy.deepcopy(value)
    normalize_config_values(config)
    normalize_presets()

def load_config():
    global config
    loaded_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
                if not isinstance(loaded_config, dict):
                    loaded_config = {}
        except Exception:
            loaded_config = {}

    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(loaded_config)
    normalize_config()

def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

load_config()

# 标志位
running = True
need_resize = False
need_move = False
need_alpha = False
show_settings_flag = False
pending_preset_name = None
force_z_update = True
frame_count = 0
smoothed_fft = np.zeros(config["bars"], dtype=np.float32)
last_use_vertical_gradient = normalize_color_mode(config.get("color_mode")) == COLOR_MODE_VERTICAL
last_root_fade = bool(config.get("spectrum_root_fade", False))
beat_energy_history = deque(maxlen=72)
beat_previous_energy = 0.0
beat_last_frame = -9999
beat_pulse = 0.0
beat_flash = 0.0


# ---- Tkinter 调参窗口 ----
tk_main_root = tk.Tk()
tk_main_root.withdraw()
tk_root = None
settings_refresh_callback = None

def refresh_settings_controls():
    if settings_refresh_callback is not None:
        try:
            settings_refresh_callback()
        except Exception:
            pass

def update_tray_menu():
    try:
        icon.update_menu()
    except Exception:
        pass

def apply_config_snapshot(snapshot, active_preset=""):
    global need_resize, need_move, need_alpha, smoothed_fft, force_z_update

    snapshot = preset_snapshot_from(snapshot, config)
    old_pos = (int(config["x"]), int(config["y"]))
    old_size = (int(config["width"]), int(config["height"]))
    old_alpha = int(config["alpha"])
    old_bars = int(config["bars"])
    old_overlay = config.get("overlay_target")

    for key, value in snapshot.items():
        config[key] = copy.deepcopy(value)

    active_preset = normalize_preset_name(active_preset)
    config["active_preset"] = active_preset if active_preset in config.get("presets", {}) else ""
    normalize_config()

    new_pos = (int(config["x"]), int(config["y"]))
    new_size = (int(config["width"]), int(config["height"]))
    if new_size != old_size:
        need_resize = True
    elif new_pos != old_pos:
        need_move = True
    if int(config["alpha"]) != old_alpha:
        need_alpha = True
    if int(config["bars"]) != old_bars:
        smoothed_fft = np.zeros(config["bars"], dtype=np.float32)
    if config.get("overlay_target") != old_overlay:
        force_z_update = True

    refresh_settings_controls()
    update_tray_menu()
    save_config()

def apply_preset(name):
    name = normalize_preset_name(name)
    preset = config.get("presets", {}).get(name)
    if not preset:
        return False
    apply_config_snapshot(preset, active_preset=name)
    return True

def save_current_preset(name):
    name = normalize_preset_name(name)
    if not name:
        return False
    config["presets"][name] = preset_snapshot_from(config)
    config["active_preset"] = name
    normalize_config()
    save_config()
    refresh_settings_controls()
    update_tray_menu()
    return True

def delete_preset(name):
    name = normalize_preset_name(name)
    if name not in config.get("presets", {}):
        return False
    del config["presets"][name]
    if config.get("active_preset") == name:
        config["active_preset"] = ""
    save_config()
    refresh_settings_controls()
    update_tray_menu()
    return True

def rename_preset(old_name, new_name):
    old_name = normalize_preset_name(old_name)
    new_name = normalize_preset_name(new_name)
    presets = config.get("presets", {})
    if not old_name or old_name not in presets or not new_name or new_name in presets:
        return False

    items = list(presets.items())
    renamed = {}
    for name, preset in items:
        renamed[new_name if name == old_name else name] = preset
    config["presets"] = renamed
    if config.get("active_preset") == old_name:
        config["active_preset"] = new_name
    normalize_config()
    save_config()
    refresh_settings_controls()
    update_tray_menu()
    return True

def duplicate_preset(source_name, new_name=None):
    source_name = normalize_preset_name(source_name)
    presets = config.get("presets", {})
    if source_name not in presets:
        return ""

    if new_name is None:
        new_name = make_unique_preset_name(f"{source_name} 副本")
    else:
        new_name = normalize_preset_name(new_name)
        if not new_name or new_name in presets:
            return ""

    presets[new_name] = preset_snapshot_from(presets[source_name])
    if config.get("active_preset") == source_name:
        config["active_preset"] = new_name
    normalize_config()
    save_config()
    refresh_settings_controls()
    update_tray_menu()
    return new_name

def collect_presets_from_export(data):
    if not isinstance(data, dict):
        return {}

    if data.get("format") == PRESET_EXPORT_FORMAT and isinstance(data.get("presets"), dict):
        source_presets = data.get("presets", {})
    elif isinstance(data.get("presets"), dict):
        source_presets = data.get("presets", {})
    elif all(key in data for key in ("width", "height", "start_color", "end_color", "bars")):
        source_presets = {normalize_preset_name(data.get("name", "导入预设")): data}
    else:
        source_presets = data

    imported = {}
    for name, preset in source_presets.items():
        preset_name = normalize_preset_name(name)
        if preset_name and isinstance(preset, dict):
            imported[preset_name] = preset_snapshot_from(preset)
    return imported

def import_presets_from_file(path, replace_existing=False):
    try:
        imported = collect_presets_from_export(read_json_file(path))
    except Exception:
        return 0

    if not imported:
        return 0

    presets = config.setdefault("presets", {})
    active_preset = config.get("active_preset", "")
    for name, preset in imported.items():
        target_name = name if replace_existing else make_unique_preset_name(name)
        presets[target_name] = preset

    if replace_existing and active_preset in imported:
        config["active_preset"] = ""
    normalize_config()
    save_config()
    refresh_settings_controls()
    update_tray_menu()
    return len(imported)

def export_presets_to_file(path, names=None):
    presets = config.get("presets", {})
    if names is None:
        selected_names = list(presets.keys())
    else:
        selected_names = [
            normalize_preset_name(name)
            for name in names
            if normalize_preset_name(name) in presets
        ]

    if not selected_names:
        return False

    payload = {
        "format": PRESET_EXPORT_FORMAT,
        "version": PRESET_EXPORT_VERSION,
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "presets": {
            name: preset_snapshot_from(presets[name])
            for name in selected_names
        }
    }
    try:
        write_json_file(path, payload)
    except Exception:
        return False
    return True

def get_performance_profile():
    mode = normalize_performance_mode(config.get("performance_mode"))
    if config.get("performance_mode") != mode:
        config["performance_mode"] = mode
    return PERFORMANCE_PROFILES[mode]

def get_effective_bars():
    bars = normalize_bar_count(config.get("bars"))
    max_bars = get_performance_profile().get("max_bars")
    if max_bars is None:
        return bars
    return min(bars, int(max_bars))

def get_target_fps():
    return int(get_performance_profile()["fps"])

def get_root_fade_segments():
    return int(get_performance_profile()["root_fade_segments"])

def set_performance_mode(mode):
    mode = normalize_performance_mode(mode)
    if config.get("performance_mode") == mode:
        return
    config["performance_mode"] = mode
    save_config()
    update_tray_menu()

def create_settings_window():
    global tk_root, settings_refresh_callback
    global size_var, alpha_var, sens_var, bars_var, decay_var, color_mode
    global x_var, y_var
    
    if tk_root is not None and tk_root.winfo_exists():
        refresh_settings_controls()
        tk_root.deiconify()
        tk_root.lift()
        return

    tk_root = tk.Toplevel(tk_main_root)
    tk_root.title(f"{APP_NAME} v{APP_VERSION} - 设置")
    tk_root.geometry("400x1000")
    tk_root.attributes("-topmost", True)
    tk_root.attributes("-toolwindow", True)
    
    def on_closing():
        tk_root.withdraw()
    tk_root.protocol("WM_DELETE_WINDOW", on_closing)

    size_var = tk.DoubleVar(value=config["width"])
    cx_var = tk.IntVar(value=int(config["x"] + config["width"] / 2.0))
    cy_var = tk.IntVar(value=int(config["y"] + config["height"] / 2.0))
    alpha_var = tk.DoubleVar(value=config["alpha"])
    sens_var = tk.DoubleVar(value=config["sensitivity"])
    bars_var = tk.DoubleVar(value=config["bars"])
    decay_var = tk.DoubleVar(value=config["decay"])
    bar_height_var = tk.DoubleVar(value=config.get("bar_height", 100.0))
    bar_length_var = tk.DoubleVar(value=config.get("bar_length", 100.0))
    controls_refreshing = False

    def gui_update(*args):
        global need_resize, need_move, need_alpha, smoothed_fft
        if controls_refreshing:
            return
        
        try:
            new_cx = int(cx_var.get())
        except Exception:
            new_cx = int(config["x"] + config["width"] / 2.0)
        try:
            new_cy = int(cy_var.get())
        except Exception:
            new_cy = int(config["y"] + config["height"] / 2.0)

        new_size = int(size_var.get())
        
        expected_x = int(new_cx - new_size / 2.0)
        expected_y = int(new_cy - new_size / 2.0)
        
        position_changed = expected_x != config["x"] or expected_y != config["y"]
        size_changed = new_size != config["width"] or new_size != config["height"]

        if position_changed:
            config["x"] = expected_x
            config["y"] = expected_y
        if size_changed:
            config["width"] = new_size
            config["height"] = new_size
            need_resize = True
        elif position_changed:
            need_move = True

        new_alpha = int(alpha_var.get())
        if new_alpha != config["alpha"]:
            config["alpha"] = new_alpha
            need_alpha = True
            
        config["sensitivity"] = float(sens_var.get())
        
        new_bars = int(bars_var.get())
        if new_bars != config["bars"]:
            config["bars"] = new_bars
            smoothed_fft = np.zeros(new_bars, dtype=np.float32)
            
        config["decay"] = float(decay_var.get())
        config["bar_height"] = float(bar_height_var.get())
        config["bar_length"] = float(bar_length_var.get())

    ttk.Label(tk_root, text="窗口大小 (频谱中心点锚定缩放):").pack(pady=(10,0))
    ttk.Scale(tk_root, from_=100, to=1500, variable=size_var, command=gui_update).pack(fill='x', padx=20)
    
    def create_repeat_btn(parent, text, action):
        btn = ttk.Button(parent, text=text, width=2)
        state = {"id": None}
        def step():
            action()
            state["id"] = btn.after(30, step)
        def on_press(e):
            action()
            state["id"] = btn.after(300, step)
        def on_release(e):
            if state["id"] is not None:
                btn.after_cancel(state["id"])
                state["id"] = None
        btn.bind('<ButtonPress-1>', on_press)
        btn.bind('<ButtonRelease-1>', on_release)
        btn.bind('<Leave>', on_release)
        return btn

    pos_frame = ttk.Frame(tk_root)
    pos_frame.pack(pady=5)
    ttk.Label(pos_frame, text="频谱中心点 X:").pack(side='left')
    create_repeat_btn(pos_frame, "-", lambda: cx_var.set(cx_var.get() - 1)).pack(side='left')
    ttk.Entry(pos_frame, textvariable=cx_var, width=6).pack(side='left', padx=2)
    create_repeat_btn(pos_frame, "+", lambda: cx_var.set(cx_var.get() + 1)).pack(side='left')
    
    ttk.Label(pos_frame, text="  频谱中心点 Y:").pack(side='left')
    create_repeat_btn(pos_frame, "-", lambda: cy_var.set(cy_var.get() - 1)).pack(side='left')
    ttk.Entry(pos_frame, textvariable=cy_var, width=6).pack(side='left', padx=2)
    create_repeat_btn(pos_frame, "+", lambda: cy_var.set(cy_var.get() + 1)).pack(side='left')

    cx_var.trace_add("write", lambda *args: gui_update())
    cy_var.trace_add("write", lambda *args: gui_update())

    def get_current_monitor_rect():
        cx = int(config["x"] + config["width"] / 2.0)
        cy = int(config["y"] + config["height"] / 2.0)
        monitor = win32api.MonitorFromPoint((cx, cy), win32con.MONITOR_DEFAULTTONEAREST)
        return win32api.GetMonitorInfo(monitor)["Monitor"]

    def get_spectrum_bounds():
        width = config["width"]
        height = config["height"]
        style = config.get("spectrum_style", "ring")

        if style != "bar":
            bars = max(1, int(config["bars"]))
            radius_outer = min(width, height) / 2
            radius_inner = min(width, height) / 4
            radius_base = radius_outer if bool(config.get("spectrum_flip", False)) else radius_inner
            ring_size = radius_outer - radius_inner
            visible_outer_radius = radius_base if bool(config.get("spectrum_flip", False)) else radius_base + ring_size
            bar_width = max(1, int((2 * math.pi * radius_inner / bars) * 0.8))
            bound_radius = min(radius_outer, visible_outer_radius + bar_width / 2)
            center_x = width / 2
            center_y = height / 2
            return center_x - bound_radius, center_y - bound_radius, center_x + bound_radius, center_y + bound_radius

        bars = max(1, int(config["bars"]))
        is_flipped = bool(config.get("spectrum_flip", False))
        is_rotated = bool(config.get("spectrum_rotate_90", False))
        bar_length_ratio = max(0.05, min(1.0, float(config.get("bar_length", 100.0)) / 100.0))

        if is_rotated:
            margin_y = max(8, height * 0.03)
            edge_padding = max(8, width * 0.06)
            baseline = width / 2
            max_len = max(1, baseline - edge_padding)
            axis_span = max(1, height - margin_y * 2) * bar_length_ratio
            axis_start = (height - axis_span) / 2
            slot_height = max(1, axis_span) / bars
            bar_width = max(1, int(slot_height * 0.72))
            half_width = bar_width / 2
            top = axis_start + slot_height / 2 - half_width
            bottom = axis_start + slot_height * (bars - 0.5) + half_width

            if is_flipped:
                left = baseline - max_len - half_width
                right = baseline + half_width
            else:
                left = baseline - half_width
                right = baseline + max_len + half_width
        else:
            margin_x = max(8, width * 0.03)
            edge_padding = max(8, height * 0.06)
            baseline = height / 2
            max_len = max(1, baseline - edge_padding)
            axis_span = max(1, width - margin_x * 2) * bar_length_ratio
            axis_start = (width - axis_span) / 2
            slot_width = max(1, axis_span) / bars
            bar_width = max(1, int(slot_width * 0.72))
            half_width = bar_width / 2
            left = axis_start + slot_width / 2 - half_width
            right = axis_start + slot_width * (bars - 0.5) + half_width

            if is_flipped:
                top = baseline - half_width
                bottom = baseline + max_len + half_width
            else:
                top = baseline - max_len - half_width
                bottom = baseline + half_width

        return left, top, right, bottom

    def align_spectrum(option):
        monitor_left, monitor_top, monitor_right, monitor_bottom = get_current_monitor_rect()
        bounds_left, bounds_top, bounds_right, bounds_bottom = get_spectrum_bounds()
        current_x = config["x"]
        current_y = config["y"]
        new_x = current_x
        new_y = current_y

        if option == "靠左":
            new_x = math.floor(monitor_left - bounds_left)
        elif option == "靠右":
            new_x = math.ceil(monitor_right - bounds_right)
        elif option == "靠上":
            new_y = math.floor(monitor_top - bounds_top)
        elif option == "靠下":
            new_y = math.ceil(monitor_bottom - bounds_bottom)
        elif option == "X轴居中":
            screen_center_x = (monitor_left + monitor_right) / 2
            spectrum_center_x = (bounds_left + bounds_right) / 2
            new_x = round(screen_center_x - spectrum_center_x)
        elif option == "Y轴居中":
            screen_center_y = (monitor_top + monitor_bottom) / 2
            spectrum_center_y = (bounds_top + bounds_bottom) / 2
            new_y = round(screen_center_y - spectrum_center_y)

        if new_x != current_x:
            cx_var.set(int(new_x + math.ceil(config["width"] / 2.0)))
        if new_y != current_y:
            cy_var.set(int(new_y + math.ceil(config["height"] / 2.0)))

    align_options = ["选择对齐", "靠左", "靠右", "靠上", "靠下", "X轴居中", "Y轴居中"]
    align_var = tk.StringVar(value=align_options[0])
    align_frame = ttk.Frame(tk_root)
    align_frame.pack(fill='x', padx=20, pady=5)
    ttk.Label(align_frame, text="屏幕对齐:").pack(side='left')
    align_cb = ttk.Combobox(align_frame, textvariable=align_var, values=align_options, state="readonly", width=25)
    align_cb.pack(side='left', padx=5)

    def on_align_selected(event=None):
        option = align_var.get()
        if option == align_options[0]:
            return
        align_spectrum(option)
        align_var.set(align_options[0])

    align_cb.bind("<<ComboboxSelected>>", on_align_selected)

    ttk.Label(tk_root, text="透明度 (Alpha %):").pack()
    ttk.Scale(tk_root, from_=10, to=100, variable=alpha_var, command=gui_update).pack(fill='x', padx=20)

    ttk.Label(tk_root, text="敏感度 (Sensitivity):").pack()
    ttk.Scale(tk_root, from_=0.5, to=5.0, variable=sens_var, command=gui_update).pack(fill='x', padx=20)

    ttk.Label(tk_root, text="柱子数量 (Bars):").pack()
    ttk.Scale(tk_root, from_=20, to=240, variable=bars_var, command=gui_update).pack(fill='x', padx=20)

    spectrum_style = tk.StringVar(value=config.get("spectrum_style", "ring"))

    def on_style_change():
        config["spectrum_style"] = spectrum_style.get()
        update_bar_controls_visibility()

    ttk.Label(tk_root, text="频谱样式:").pack(pady=(10,0))
    frame_style = ttk.Frame(tk_root)
    frame_style.pack()
    ttk.Radiobutton(frame_style, text="条状", variable=spectrum_style, value="bar", command=on_style_change).pack(side='left', padx=10)
    ttk.Radiobutton(frame_style, text="环状", variable=spectrum_style, value="ring", command=on_style_change).pack(side='left', padx=10)

    bar_params_frame = ttk.Frame(tk_root)
    ttk.Label(bar_params_frame, text="条形高度 (%):").pack()
    ttk.Scale(bar_params_frame, from_=10, to=200, variable=bar_height_var, command=gui_update).pack(fill='x', padx=20)
    ttk.Label(bar_params_frame, text="条形长度 (%):").pack()
    ttk.Scale(bar_params_frame, from_=10, to=100, variable=bar_length_var, command=gui_update).pack(fill='x', padx=20)

    def update_bar_controls_visibility():
        if spectrum_style.get() == "bar":
            bar_params_frame.pack(fill='x', after=frame_style)
        else:
            bar_params_frame.pack_forget()

    update_bar_controls_visibility()

    spectrum_flip = tk.BooleanVar(value=bool(config.get("spectrum_flip", False)))
    spectrum_rotate_90 = tk.BooleanVar(value=bool(config.get("spectrum_rotate_90", False)))
    spectrum_root_fade = tk.BooleanVar(value=bool(config.get("spectrum_root_fade", False)))

    def on_flip_change():
        config["spectrum_flip"] = bool(spectrum_flip.get())

    def on_rotate_90_change():
        config["spectrum_rotate_90"] = bool(spectrum_rotate_90.get())

    def on_root_fade_change():
        config["spectrum_root_fade"] = bool(spectrum_root_fade.get())

    transform_frame = ttk.Frame(tk_root)
    transform_frame.pack(pady=(5,0))
    ttk.Checkbutton(transform_frame, text="频谱翻转", variable=spectrum_flip, command=on_flip_change).pack(side='left', padx=10)
    ttk.Checkbutton(transform_frame, text="旋转90°", variable=spectrum_rotate_90, command=on_rotate_90_change).pack(side='left', padx=10)
    ttk.Checkbutton(transform_frame, text="根部渐隐", variable=spectrum_root_fade, command=on_root_fade_change).pack(side='left', padx=10)

    def get_overlay_options():
        opts = ["【默认】桌面底层", "【全局】始终置顶"]
        def enum_win(h, ctx):
            if win32gui.IsWindowVisible(h):
                title = win32gui.GetWindowText(h)
                if title and title not in ["Program Manager", "Ring Spectrum - 设置"]:
                    opts.append(title)
        win32gui.EnumWindows(enum_win, None)
        seen = set()
        return [o for o in opts if not (o in seen or seen.add(o))]

    overlay_var = tk.StringVar(value=config.get("overlay_target", "【默认】桌面底层"))
    
    overlay_frame = ttk.Frame(tk_root)
    overlay_frame.pack(fill='x', padx=20, pady=5)
    ttk.Label(overlay_frame, text="显示层级:").pack(side='left')
    overlay_cb = ttk.Combobox(overlay_frame, textvariable=overlay_var, state="readonly", width=25)
    overlay_cb.pack(side='left', padx=5)
    overlay_cb.configure(postcommand=lambda: overlay_cb.configure(values=get_overlay_options()))

    def on_overlay_change(*args):
        if controls_refreshing:
            return
        config["overlay_target"] = overlay_var.get()
        global force_z_update
        force_z_update = True

    overlay_var.trace_add("write", on_overlay_change)

    ttk.Label(tk_root, text="衰减速度 (Decay):").pack()
    ttk.Scale(tk_root, from_=0.01, to=0.99, variable=decay_var, command=gui_update).pack(fill='x', padx=20)

    sp_mode_var = tk.StringVar(value=normalize_sp_mode(config.get("sp_mode")))

    def on_sp_mode_change(event=None):
        if controls_refreshing:
            return
        config["sp_mode"] = normalize_sp_mode(sp_mode_var.get())

    ttk.Label(tk_root, text="sp模式:").pack(pady=(10, 0))
    sp_mode_cb = ttk.Combobox(
        tk_root,
        textvariable=sp_mode_var,
        values=(SP_MODE_NORMAL, SP_MODE_BEAT),
        state="readonly",
        width=12
    )
    sp_mode_cb.pack()
    sp_mode_cb.bind("<<ComboboxSelected>>", on_sp_mode_change)

    color_mode = tk.StringVar(value=normalize_color_mode(config.get("color_mode")))

    def choose_start_color():
        color = colorchooser.askcolor(initialcolor=tuple(config["start_color"]), title="选择起始/纯色")
        if color[0]:
            config["start_color"] = [int(c) for c in color[0]]
            if color_mode.get() == COLOR_MODE_SOLID:
                config["end_color"] = config["start_color"].copy()

    def choose_end_color():
        color = colorchooser.askcolor(initialcolor=tuple(config["end_color"]), title="选择结束颜色")
        if color[0]:
            config["end_color"] = [int(c) for c in color[0]]

    def on_mode_change():
        config["color_mode"] = color_mode.get()
        if config["color_mode"] == COLOR_MODE_SOLID:
            config["end_color"] = config["start_color"].copy()

    ttk.Label(tk_root, text="颜色模式 (Color Mode):").pack(pady=(10,0))
    frame_mode = ttk.Frame(tk_root)
    frame_mode.pack()
    ttk.Radiobutton(frame_mode, text="首尾渐变", variable=color_mode, value=COLOR_MODE_ENDPOINT, command=on_mode_change).pack(side='left', padx=6)
    ttk.Radiobutton(frame_mode, text="上下渐变", variable=color_mode, value=COLOR_MODE_VERTICAL, command=on_mode_change).pack(side='left', padx=6)
    ttk.Radiobutton(frame_mode, text="纯色", variable=color_mode, value=COLOR_MODE_SOLID, command=on_mode_change).pack(side='left', padx=6)

    ttk.Button(tk_root, text="选择起始颜色 / 纯色", command=choose_start_color).pack(pady=5)
    ttk.Button(tk_root, text="选择结束颜色 (渐变模式)", command=choose_end_color).pack(pady=5)

    def get_preset_names():
        return list(config.get("presets", {}).keys())

    preset_name_var = tk.StringVar(value=config.get("active_preset", ""))
    preset_frame = ttk.LabelFrame(tk_root, text="预设")
    preset_frame.pack(fill='x', padx=20, pady=(10, 5))
    preset_row = ttk.Frame(preset_frame)
    preset_row.pack(fill='x', padx=8, pady=(8, 4))
    ttk.Label(preset_row, text="名称:").pack(side='left')
    preset_cb = ttk.Combobox(preset_row, textvariable=preset_name_var, values=get_preset_names(), width=24)
    preset_cb.pack(side='left', padx=5, fill='x', expand=True)

    preset_button_row = ttk.Frame(preset_frame)
    preset_button_row.pack(fill='x', padx=8, pady=(0, 8))

    def apply_selected_preset():
        name = normalize_preset_name(preset_name_var.get())
        if not apply_preset(name):
            messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)

    def save_selected_preset():
        name = normalize_preset_name(preset_name_var.get())
        if not save_current_preset(name):
            messagebox.showwarning("提示", "请输入预设名称", parent=tk_root)
            return
        messagebox.showinfo("成功", f"预设“{name}”已保存", parent=tk_root)

    def delete_selected_preset():
        name = normalize_preset_name(preset_name_var.get())
        if name not in config.get("presets", {}):
            messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)
            return
        if messagebox.askyesno("确认", f"删除预设“{name}”？", parent=tk_root):
            delete_preset(name)

    def rename_selected_preset():
        old_name = normalize_preset_name(preset_name_var.get())
        if old_name not in config.get("presets", {}):
            messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)
            return

        new_name = simpledialog.askstring("重命名预设", "新名称:", initialvalue=old_name, parent=tk_root)
        new_name = normalize_preset_name(new_name)
        if not new_name or new_name == old_name:
            return
        if new_name in config.get("presets", {}):
            messagebox.showwarning("提示", "该预设名称已存在", parent=tk_root)
            return
        if rename_preset(old_name, new_name):
            preset_name_var.set(new_name)

    def duplicate_selected_preset():
        name = normalize_preset_name(preset_name_var.get())
        if name not in config.get("presets", {}):
            messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)
            return
        new_name = duplicate_preset(name)
        if new_name:
            preset_name_var.set(new_name)
            messagebox.showinfo("成功", f"已复制为“{new_name}”", parent=tk_root)

    def import_presets():
        path = filedialog.askopenfilename(
            parent=tk_root,
            title="导入预设",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")]
        )
        if not path:
            return
        replace_existing = messagebox.askyesno(
            "导入方式",
            "同名预设是否覆盖？\n选择“否”会自动生成新名称。",
            parent=tk_root
        )
        count = import_presets_from_file(path, replace_existing=replace_existing)
        if count:
            messagebox.showinfo("成功", f"已导入 {count} 个预设", parent=tk_root)
        else:
            messagebox.showwarning("提示", "没有找到可导入的预设", parent=tk_root)

    def export_presets():
        presets = config.get("presets", {})
        if not presets:
            messagebox.showwarning("提示", "当前没有可导出的预设", parent=tk_root)
            return
        active = normalize_preset_name(preset_name_var.get())
        suggested_name = f"{active or 'RingSpectrum'}_presets.json"
        path = filedialog.asksaveasfilename(
            parent=tk_root,
            title="导出预设",
            initialfile=suggested_name,
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")]
        )
        if not path:
            return

        names = None
        if active in presets and not messagebox.askyesno("导出范围", "导出全部预设？\n选择“否”只导出当前选中的预设。", parent=tk_root):
            names = [active]

        if export_presets_to_file(path, names=names):
            messagebox.showinfo("成功", "预设已导出", parent=tk_root)
        else:
            messagebox.showwarning("提示", "导出失败", parent=tk_root)

    ttk.Button(preset_button_row, text="应用", command=apply_selected_preset).pack(side='left', expand=True, fill='x', padx=(0, 3))
    ttk.Button(preset_button_row, text="保存/覆盖", command=save_selected_preset).pack(side='left', expand=True, fill='x', padx=3)

    preset_manage_button = ttk.Menubutton(preset_button_row, text="管理")
    preset_manage_menu = tk.Menu(preset_manage_button, tearoff=False)
    preset_manage_menu.add_command(label="复制", command=duplicate_selected_preset)
    preset_manage_menu.add_command(label="重命名", command=rename_selected_preset)
    preset_manage_menu.add_command(label="删除", command=delete_selected_preset)
    preset_manage_menu.add_separator()
    preset_manage_menu.add_command(label="导入", command=import_presets)
    preset_manage_menu.add_command(label="导出", command=export_presets)
    preset_manage_button.configure(menu=preset_manage_menu)
    preset_manage_button.pack(side='left', expand=True, fill='x', padx=(3, 0))

    def refresh_controls_from_config():
        nonlocal controls_refreshing
        controls_refreshing = True
        try:
            size_var.set(config["width"])
            cx_var.set(int(config["x"] + config["width"] / 2.0))
            cy_var.set(int(config["y"] + config["height"] / 2.0))
            alpha_var.set(config["alpha"])
            sens_var.set(config["sensitivity"])
            bars_var.set(config["bars"])
            decay_var.set(config["decay"])
            bar_height_var.set(config.get("bar_height", 100.0))
            bar_length_var.set(config.get("bar_length", 100.0))
            spectrum_style.set(config.get("spectrum_style", "ring"))
            spectrum_flip.set(bool(config.get("spectrum_flip", False)))
            spectrum_rotate_90.set(bool(config.get("spectrum_rotate_90", False)))
            spectrum_root_fade.set(bool(config.get("spectrum_root_fade", False)))
            overlay_var.set(config.get("overlay_target", "【默认】桌面底层"))
            sp_mode_var.set(normalize_sp_mode(config.get("sp_mode")))
            color_mode.set(normalize_color_mode(config.get("color_mode")))
            preset_name_var.set(config.get("active_preset", ""))
            preset_cb.configure(values=get_preset_names())
            update_bar_controls_visibility()
        finally:
            controls_refreshing = False

    settings_refresh_callback = refresh_controls_from_config

    def do_save():
        save_config()
        messagebox.showinfo("成功", "配置已保存", parent=tk_root)
        
    ttk.Button(tk_root, text="保存配置", command=do_save).pack(pady=(15,5))
    ttk.Button(tk_root, text="关闭面板", command=on_closing).pack(pady=5)


# ---- 系统托盘 ----
def create_image():
    image = Image.new('RGB', (64, 64), color=(255, 255, 255))
    dc = ImageDraw.Draw(image)
    dc.ellipse((10, 10, 54, 54), fill=(0, 255, 255))
    return image

def on_quit(icon, item):
    global running
    running = False
    try:
        icon.stop()
    except Exception:
        pass

def on_settings(icon, item):
    global show_settings_flag
    show_settings_flag = True

def make_preset_action(name):
    def handler(icon, item):
        global pending_preset_name
        pending_preset_name = name
    return handler

def make_preset_checked(name):
    def checked(item):
        return config.get("active_preset") == name
    return checked

def build_preset_menu_items():
    presets = config.get("presets", {})
    if not presets:
        return (pystray.MenuItem("暂无预设", None, enabled=False),)
    return tuple(
        pystray.MenuItem(
            name,
            make_preset_action(name),
            checked=make_preset_checked(name),
            radio=True
        )
        for name in presets.keys()
    )

def make_performance_action(mode):
    def handler(icon, item):
        set_performance_mode(mode)
    return handler

def make_performance_checked(mode):
    def checked(item):
        return normalize_performance_mode(config.get("performance_mode")) == mode
    return checked

def build_performance_menu_items():
    return tuple(
        pystray.MenuItem(
            profile["label"],
            make_performance_action(mode),
            checked=make_performance_checked(mode),
            radio=True
        )
        for mode, profile in PERFORMANCE_PROFILES.items()
    )

icon = pystray.Icon("RingSpectrum", create_image(), f"环形频谱 v{APP_VERSION}", menu=pystray.Menu(
    pystray.MenuItem("设置", on_settings),
    pystray.MenuItem("预设", pystray.Menu(build_preset_menu_items)),
    pystray.MenuItem("性能", pystray.Menu(build_performance_menu_items)),
    pystray.MenuItem("退出", on_quit)
))

def tray_thread():
    icon.run()

t = threading.Thread(target=tray_thread, daemon=True)
t.start()


# ---- 音频处理 ----
buffer_size = 1024
audio_data = np.zeros(buffer_size)
p = pyaudio.PyAudio()
samplerate = 48000
channels = 1

try:
    wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
    if not default_speakers["isLoopbackDevice"]:
        for loopback in p.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                default_speakers = loopback
                break
    samplerate = int(default_speakers["defaultSampleRate"])
    channels = default_speakers["maxInputChannels"]
    
    def audio_callback(in_data, frame_count, time_info, status):
        global audio_data
        if in_data:
            data = np.frombuffer(in_data, dtype=np.float32)
            if channels > 1:
                data = data[::channels]
            audio_data = data
        return (in_data, pyaudio.paContinue)
        
    stream = p.open(format=pyaudio.paFloat32,
                    channels=channels,
                    rate=samplerate,
                    frames_per_buffer=buffer_size,
                    input=True,
                    input_device_index=default_speakers["index"],
                    stream_callback=audio_callback)
    stream.start_stream()
except Exception as e:
    print("Audio init error:", e)


# ---- Pygame 主循环 ----
os.environ['SDL_VIDEO_WINDOW_POS'] = f"{config['x']},{config['y']}"
pygame.init()
COLOR_KEY = (255, 0, 128)
VERTICAL_COLOR_KEY = (0, 0, 0)

def apply_window_ex_style(hwnd, ex_style):
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    win32gui.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        win32con.SWP_NOMOVE
        | win32con.SWP_NOSIZE
        | win32con.SWP_NOZORDER
        | win32con.SWP_NOACTIVATE
        | win32con.SWP_FRAMECHANGED
    )

def show_window_no_activate(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)


def set_window_layering(hwnd, use_per_pixel_alpha, alpha_percent, color_key, hide_during_reset=False):
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    # WS_EX_TRANSPARENT 使得鼠标点击穿透，不再处理 Pygame 的鼠标事件
    # 移除强制的 WS_EX_TOPMOST，交给主循环的 Z-order 逻辑动态处理
    base_style = (ex_style | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TRANSPARENT) & ~win32con.WS_EX_TOPMOST
    layered_style = base_style | win32con.WS_EX_LAYERED
    hidden_for_reset = False

    if use_per_pixel_alpha and (ex_style & win32con.WS_EX_LAYERED):
        # SetLayeredWindowAttributes 会阻止后续 UpdateLayeredWindow，
        # 切换到逐像素 Alpha 前必须先清掉再重新设置 WS_EX_LAYERED。
        if hide_during_reset:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            hidden_for_reset = True
        apply_window_ex_style(hwnd, base_style & ~win32con.WS_EX_LAYERED)

    apply_window_ex_style(hwnd, layered_style)
    if not use_per_pixel_alpha:
        win32gui.SetLayeredWindowAttributes(
            hwnd,
            win32api.RGB(*color_key),
            int(255 * max(0, min(100, int(alpha_percent))) / 100),
            win32con.LWA_COLORKEY | win32con.LWA_ALPHA
        )
    return hidden_for_reset

def update_window_pos(hwnd, x, y, width, height):
    # 使用 SWP_NOZORDER 保持当前的层级，不覆盖上面计算的Z-order
    win32gui.SetWindowPos(hwnd, 0, x, y, width, height, win32con.SWP_SHOWWINDOW | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)

screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
hwnd = pygame.display.get_wm_info()["window"]
canvas = None
vertical_gradient_surface = None
layered_bitmap = LayeredWindowBitmap()
using_per_pixel_alpha = bool(config.get("spectrum_root_fade", False))
initial_vertical_gradient = normalize_color_mode(config.get("color_mode")) == COLOR_MODE_VERTICAL
active_color_key = VERTICAL_COLOR_KEY if initial_vertical_gradient and not using_per_pixel_alpha else COLOR_KEY
set_window_layering(hwnd, using_per_pixel_alpha, config["alpha"], active_color_key)

clock = pygame.time.Clock()

def lerp_color(start_color, end_color, ratio):
    ratio = max(0.0, min(1.0, float(ratio)))
    return (
        int(start_color[0] + (end_color[0] - start_color[0]) * ratio),
        int(start_color[1] + (end_color[1] - start_color[1]) * ratio),
        int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
    )


def get_spectrum_color(index, total, seamless=False):
    sc = config["start_color"]
    ec = config["end_color"]
    if normalize_color_mode(config.get("color_mode")) != COLOR_MODE_ENDPOINT:
        return (int(sc[0]), int(sc[1]), int(sc[2]))

    if seamless:
        angle = 2 * math.pi * (index / max(1, total))
        ratio = (1 - math.cos(angle)) / 2
    else:
        ratio = index / max(1, total - 1)

    return lerp_color(sc, ec, ratio)

def get_alpha_color(color, alpha):
    alpha = max(0, min(255, int(alpha)))
    return (
        int(color[0]),
        int(color[1]),
        int(color[2]),
        alpha
    )

def get_draw_pos(pos):
    return (int(round(float(pos[0]))), int(round(float(pos[1]))))

def ensure_canvas(width, height):
    global canvas
    size = (int(width), int(height))
    if canvas is None or canvas.get_size() != size:
        canvas = pygame.Surface(size, pygame.SRCALPHA)
    return canvas


vertical_color_mask_key = None
vertical_color_mask = None
vertical_gradient_surface_key = None
fft_window_key = None
fft_window = None
log_indices_key = None
log_indices_cache = None
bars_buffer_key = None
bars_buffer = None
smooth_buffer_key = None
smooth_buffer = None


def clear_vertical_gradient_cache(clear_surface=False):
    global vertical_color_mask_key, vertical_color_mask
    global vertical_gradient_surface_key, vertical_gradient_surface
    vertical_color_mask_key = None
    vertical_color_mask = None
    vertical_gradient_surface_key = None
    if clear_surface:
        vertical_gradient_surface = None


def get_fft_window(length):
    global fft_window_key, fft_window
    length = int(length)
    if fft_window_key != length or fft_window is None:
        fft_window = np.hanning(length).astype(np.float32, copy=False)
        fft_window_key = length
    return fft_window


def get_log_indices(fft_len, bars):
    global log_indices_key, log_indices_cache
    fft_len = int(fft_len)
    bars = int(bars)
    min_idx = 2
    max_idx = max(3, fft_len // 2)
    key = (fft_len, bars, min_idx, max_idx)
    if log_indices_key != key or log_indices_cache is None:
        indices = np.logspace(np.log10(min_idx), np.log10(max_idx), bars + 1).astype(np.int32)
        indices = np.clip(indices, 0, max(0, fft_len - 1))
        log_indices_key = key
        log_indices_cache = indices
    return log_indices_cache


def ensure_bars_buffer(bars):
    global bars_buffer_key, bars_buffer
    bars = int(bars)
    if bars_buffer_key != bars or bars_buffer is None:
        bars_buffer = np.zeros(bars, dtype=np.float32)
        bars_buffer_key = bars
    return bars_buffer


def ensure_smooth_buffer(bars):
    global smooth_buffer_key, smooth_buffer
    bars = int(bars)
    if smooth_buffer_key != bars or smooth_buffer is None:
        smooth_buffer = np.zeros(bars, dtype=np.float32)
        smooth_buffer_key = bars
    return smooth_buffer


def smooth_bars(values):
    count = len(values)
    if count < 3:
        return values

    left2, left1, center, right1, right2 = BAR_SMOOTH_KERNEL
    weight_sum = sum(BAR_SMOOTH_KERNEL)
    output = ensure_smooth_buffer(count)
    for index in range(count):
        output[index] = (
            values[(index - 2) % count] * left2
            + values[(index - 1) % count] * left1
            + values[index] * center
            + values[(index + 1) % count] * right1
            + values[(index + 2) % count] * right2
        ) / weight_sum
    return output


def get_sp_mode():
    mode = normalize_sp_mode(config.get("sp_mode"))
    if config.get("sp_mode") != mode:
        config["sp_mode"] = mode
    return mode


def update_beat_pulse(fft_data, samplerate, frame_index):
    global beat_previous_energy, beat_last_frame, beat_pulse, beat_flash

    if get_sp_mode() != SP_MODE_BEAT or len(fft_data) < 8:
        beat_pulse = 0.0
        beat_flash = 0.0
        return 0.0, 0.0

    fft_size = max(2, (len(fft_data) - 1) * 2)
    hz_per_bin = float(samplerate) / fft_size
    bass_start = max(2, int(35 / hz_per_bin))
    bass_end = min(len(fft_data), max(bass_start + 1, int(180 / hz_per_bin)))
    body_end = min(len(fft_data), max(bass_end + 1, int(2400 / hz_per_bin)))

    bass = float(np.mean(fft_data[bass_start:bass_end])) if bass_end > bass_start else 0.0
    body = float(np.mean(fft_data[bass_end:body_end])) if body_end > bass_end else 0.0
    energy = math.log1p(bass * 1.55 + body * 0.22)

    if len(beat_energy_history) >= 18:
        mean = sum(beat_energy_history) / len(beat_energy_history)
        variance = sum((value - mean) ** 2 for value in beat_energy_history) / len(beat_energy_history)
        std = math.sqrt(variance)
        threshold = mean + std * 1.45 + 0.035
    else:
        mean = sum(beat_energy_history) / max(1, len(beat_energy_history))
        std = 0.08
        threshold = mean * 1.7 + 0.08

    rising = energy > beat_previous_energy * 1.08 and energy > 0.05
    ready = frame_index - beat_last_frame > max(8, int(get_target_fps() * 0.18))
    if ready and rising and energy > threshold:
        strength = max(0.35, min(1.0, (energy - threshold) / (std + 0.06)))
        beat_pulse = max(beat_pulse, strength)
        beat_flash = max(beat_flash, strength)
        beat_last_frame = frame_index

    beat_previous_energy = energy
    beat_energy_history.append(energy)
    beat_pulse *= 0.92
    beat_flash *= 0.82
    return beat_pulse, beat_flash


def apply_beat_color(color, pulse, flash):
    if pulse <= 0.001 and flash <= 0.001:
        return color
    boost = 1.0 + pulse * 0.55 + flash * 0.22
    return (
        min(255, int(color[0] * boost)),
        min(255, int(color[1] * boost)),
        min(255, int(color[2] * boost))
    )


def make_vertical_color_mask(distance_from_root, max_length):
    max_length = max(1.0, float(max_length))
    ratio = np.clip(distance_from_root, 0, max_length) / max_length
    sc = np.array(config["start_color"], dtype=np.float32)
    ec = np.array(config["end_color"], dtype=np.float32)
    mask = sc + (ec - sc) * ratio[:, :, None]
    return mask.astype(np.uint8)


def get_vertical_color_mask(width, height, style, is_flipped, is_rotated, max_length, baseline=None, center=None, radius_base=None):
    global vertical_color_mask_key, vertical_color_mask
    key = (
        int(width),
        int(height),
        style,
        bool(is_flipped),
        bool(is_rotated),
        round(float(max_length), 3),
        tuple(int(c) for c in config["start_color"]),
        tuple(int(c) for c in config["end_color"]),
        None if baseline is None else round(float(baseline), 3),
        None if center is None else (round(float(center[0]), 3), round(float(center[1]), 3)),
        None if radius_base is None else round(float(radius_base), 3),
    )
    if key == vertical_color_mask_key and vertical_color_mask is not None:
        return vertical_color_mask

    if style == "bar":
        if is_rotated:
            distance = np.abs(np.arange(width, dtype=np.float32) - float(baseline))
            distance = np.broadcast_to(distance[np.newaxis, :], (height, width))
        else:
            distance = np.abs(np.arange(height, dtype=np.float32) - float(baseline))
            distance = np.broadcast_to(distance[:, np.newaxis], (height, width))
    else:
        cx, cy = center
        x = np.arange(width, dtype=np.float32)[np.newaxis, :] - float(cx)
        y = np.arange(height, dtype=np.float32)[:, np.newaxis] - float(cy)
        radius = np.sqrt(x * x + y * y)
        if is_flipped:
            distance = float(radius_base) - radius
        else:
            distance = radius - float(radius_base)

    vertical_color_mask_key = key
    vertical_color_mask = make_vertical_color_mask(distance, max_length)
    return vertical_color_mask


def update_vertical_gradient_surface(surface, color_mask):
    width, height = surface.get_size()
    if color_mask.shape[:2] != (height, width):
        return
    rgb = pygame.surfarray.pixels3d(surface)
    try:
        target = np.transpose(rgb, (1, 0, 2))
        np.copyto(target, color_mask)
        # RGB 色键画布以纯黑作为透明色，避免纯黑渐变柱也被当作背景。
        target[np.all(target == 0, axis=2)] = 1
    finally:
        del rgb


def get_vertical_gradient_surface(color_mask, width, height, style, is_flipped, is_rotated, max_length, baseline=None, center=None, radius_base=None):
    global vertical_gradient_surface, vertical_gradient_surface_key
    key = (
        int(width),
        int(height),
        style,
        bool(is_flipped),
        bool(is_rotated),
        round(float(max_length), 3),
        tuple(int(c) for c in config["start_color"]),
        tuple(int(c) for c in config["end_color"]),
        None if baseline is None else round(float(baseline), 3),
        None if center is None else (round(float(center[0]), 3), round(float(center[1]), 3)),
        None if radius_base is None else round(float(radius_base), 3),
    )
    if (
        key != vertical_gradient_surface_key
        or vertical_gradient_surface is None
        or vertical_gradient_surface.get_size() != (width, height)
    ):
        vertical_gradient_surface = pygame.Surface((width, height))
        update_vertical_gradient_surface(vertical_gradient_surface, color_mask)
        vertical_gradient_surface_key = key
    return vertical_gradient_surface


def draw_root_fade_spectrum_bar(surface, root_pos, tip_pos, color, bar_width, full_alpha):
    root_x = float(root_pos[0])
    root_y = float(root_pos[1])
    dx = float(tip_pos[0]) - root_x
    dy = float(tip_pos[1]) - root_y
    length = math.hypot(dx, dy)
    if length <= 0:
        return

    segments = max(1, min(get_root_fade_segments(), int(math.ceil(length))))
    previous = (root_x, root_y)
    for segment in range(1, segments + 1):
        ratio = segment / segments
        current = (root_x + dx * ratio, root_y + dy * ratio)
        segment_alpha = int(round(full_alpha * (ratio ** 2)))
        if segment_alpha > 0:
            pygame.draw.line(
                surface,
                get_alpha_color(color, segment_alpha),
                get_draw_pos(previous),
                get_draw_pos(current),
                bar_width
            )
        previous = current

    if bar_width > 2:
        pygame.draw.circle(
            surface,
            get_alpha_color(color, full_alpha),
            get_draw_pos(tip_pos),
            max(1, bar_width // 2)
        )


def draw_spectrum_bar(surface, root_pos, tip_pos, color, bar_width, full_alpha, root_fade=False):
    if root_fade:
        draw_root_fade_spectrum_bar(surface, root_pos, tip_pos, color, bar_width, full_alpha)
        return

    draw_color = get_alpha_color(color, full_alpha)
    pygame.draw.line(surface, draw_color, get_draw_pos(root_pos), get_draw_pos(tip_pos), bar_width)
    if bar_width > 2:
        pygame.draw.circle(
            surface,
            draw_color,
            get_draw_pos(tip_pos),
            max(1, bar_width // 2)
        )

while running:
    frame_count += 1
    if pending_preset_name:
        preset_to_apply = pending_preset_name
        pending_preset_name = None
        apply_preset(preset_to_apply)

    root_fade = bool(config.get("spectrum_root_fade", False))
    color_mode_value = normalize_color_mode(config.get("color_mode"))
    use_vertical_gradient = color_mode_value == COLOR_MODE_VERTICAL
    if last_use_vertical_gradient and not use_vertical_gradient:
        clear_vertical_gradient_cache(clear_surface=True)
    if not last_root_fade and root_fade:
        clear_vertical_gradient_cache(clear_surface=True)
    elif last_root_fade and not root_fade:
        canvas = None
        layered_bitmap.close()
    last_use_vertical_gradient = use_vertical_gradient
    last_root_fade = root_fade
    desired_color_key = VERTICAL_COLOR_KEY if use_vertical_gradient and not root_fade else COLOR_KEY
    show_after_layered_update = False
    show_after_colorkey_update = False
    if frame_count % 15 == 0 or force_z_update:
        force_z_update = False
        target = config.get("overlay_target", "【默认】桌面底层")
        if target == "【默认】桌面底层":
            win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        elif target == "【全局】始终置顶":
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        else:
            target_hwnd = win32gui.FindWindow(None, target)
            if target_hwnd:
                win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                prev = win32gui.GetWindow(target_hwnd, win32con.GW_HWNDPREV)
                if prev != hwnd:
                    insert_after = prev if prev != 0 else win32con.HWND_TOP
                    win32gui.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    if show_settings_flag:
        create_settings_window()
        show_settings_flag = False

    try:
        tk_main_root.update()
        if tk_root is not None and tk_root.winfo_exists():
            tk_root.update()
    except Exception:
        pass

    if need_resize:
        screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
        hwnd = pygame.display.get_wm_info()["window"]
        canvas = None
        clear_vertical_gradient_cache(clear_surface=True)
        if not root_fade:
            layered_bitmap.close()
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            show_after_layered_update = True
        set_window_layering(hwnd, root_fade, config["alpha"], desired_color_key)
        active_color_key = desired_color_key
        using_per_pixel_alpha = root_fade
        update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
        if not root_fade:
            screen.fill(desired_color_key)
            pygame.display.update()
        need_resize = False
        need_move = False
    elif need_move:
        update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
        need_move = False

    if need_alpha:
        if not root_fade:
            set_window_layering(hwnd, False, config["alpha"], desired_color_key)
            active_color_key = desired_color_key
        need_alpha = False

    if using_per_pixel_alpha != root_fade:
        hidden_for_reset = set_window_layering(
            hwnd,
            root_fade,
            config["alpha"],
            desired_color_key,
            hide_during_reset=root_fade
        )
        using_per_pixel_alpha = root_fade
        active_color_key = desired_color_key
        if root_fade:
            if hidden_for_reset:
                show_after_layered_update = True
        else:
            screen.fill(desired_color_key)
            pygame.display.update()
    elif not root_fade and active_color_key != desired_color_key:
        # 切换上下渐变时隐藏旧色键帧，避免背景色短暂闪现。
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        set_window_layering(hwnd, False, config["alpha"], desired_color_key)
        active_color_key = desired_color_key
        show_after_colorkey_update = True

    for event in pygame.event.get():
        pass # 完全通过托盘和面板交互，忽略 pygame 事件

    window = get_fft_window(len(audio_data))
    fft_data = np.abs(np.fft.rfft(audio_data * window))
    current_beat_pulse, current_beat_flash = update_beat_pulse(fft_data, samplerate, frame_count)
    
    bars = get_effective_bars()
    if len(smoothed_fft) != bars:
        smoothed_fft = np.zeros(bars, dtype=np.float32)
    log_indices = get_log_indices(len(fft_data), bars)
    
    current_bars = ensure_bars_buffer(bars)
    for i in range(bars):
        start_idx = log_indices[i]
        end_idx = log_indices[i+1]
        if start_idx == end_idx:
            end_idx = start_idx + 1
            
        band = fft_data[start_idx:end_idx]
        if len(band) > 0:
            current_bars[i] = np.mean(band)
        else:
            current_bars[i] = 0
            
    current_bars *= float(config["sensitivity"])
    current_bars = smooth_bars(current_bars)
    effective_decay = min(0.995, float(config["decay"]) + current_beat_pulse * 0.08)
    smoothed_fft *= effective_decay
    np.maximum(current_bars, smoothed_fft, out=smoothed_fft)

    if root_fade:
        draw_surface = ensure_canvas(config["width"], config["height"])
        draw_surface.fill((0, 0, 0, 0))
    elif use_vertical_gradient:
        draw_surface = screen
        draw_surface.fill(VERTICAL_COLOR_KEY)
    else:
        draw_surface = screen
        draw_surface.fill(COLOR_KEY)
    
    width, height = config["width"], config["height"]
    style = config.get("spectrum_style", "ring")
    is_flipped = bool(config.get("spectrum_flip", False))
    is_rotated = bool(config.get("spectrum_rotate_90", False))
    full_alpha = int(255 * max(0, min(100, int(config["alpha"]))) / 100)
    draw_alpha = full_alpha if root_fade else 255
    beat_length_boost = 1.0 + current_beat_pulse * 0.22
    fade_mask = None
    color_mask = None
    gradient_surface = None

    if style == "bar":
        bar_height_ratio = max(0.05, min(2.0, float(config.get("bar_height", 100.0)) / 100.0))
        bar_length_ratio = max(0.05, min(1.0, float(config.get("bar_length", 100.0)) / 100.0))

        if is_rotated:
            margin_y = max(8, height * 0.03)
            edge_padding = max(8, width * 0.06)
            baseline = width / 2
            max_len = max(1, baseline - edge_padding)
            axis_span = max(1, height - margin_y * 2) * bar_length_ratio
            axis_start = (height - axis_span) / 2
            slot_height = max(1, axis_span) / bars
            bar_width = max(1, int(slot_height * 0.72))
            bar_width = max(1, int(bar_width * (1.0 + current_beat_flash * 0.12)))
            if use_vertical_gradient:
                color_mask = get_vertical_color_mask(
                    width,
                    height,
                    style,
                    is_flipped,
                    is_rotated,
                    max_len,
                    baseline=baseline
                )
                if not root_fade:
                    gradient_surface = get_vertical_gradient_surface(
                        color_mask,
                        width,
                        height,
                        style,
                        is_flipped,
                        is_rotated,
                        max_len,
                        baseline=baseline
                    )

            for i in range(bars):
                length = smoothed_fft[i]

                if length < 2:
                    continue

                length = min(length * beat_length_boost * bar_height_ratio, max_len)
                y = axis_start + slot_height * i + slot_height / 2
                x_end = baseline - length if is_flipped else baseline + length
                color = (255, 255, 255) if use_vertical_gradient else get_spectrum_color(i, bars)
                color = apply_beat_color(color, current_beat_pulse, current_beat_flash)

                draw_spectrum_bar(draw_surface, (baseline, y), (x_end, y), color, bar_width, draw_alpha, root_fade)
        else:
            margin_x = max(8, width * 0.03)
            edge_padding = max(8, height * 0.06)
            baseline = height / 2
            max_len = max(1, baseline - edge_padding)
            axis_span = max(1, width - margin_x * 2) * bar_length_ratio
            axis_start = (width - axis_span) / 2
            slot_width = max(1, axis_span) / bars
            bar_width = max(1, int(slot_width * 0.72))
            bar_width = max(1, int(bar_width * (1.0 + current_beat_flash * 0.12)))
            if use_vertical_gradient:
                color_mask = get_vertical_color_mask(
                    width,
                    height,
                    style,
                    is_flipped,
                    is_rotated,
                    max_len,
                    baseline=baseline
                )
                if not root_fade:
                    gradient_surface = get_vertical_gradient_surface(
                        color_mask,
                        width,
                        height,
                        style,
                        is_flipped,
                        is_rotated,
                        max_len,
                        baseline=baseline
                    )

            for i in range(bars):
                length = smoothed_fft[i]

                if length < 2:
                    continue

                length = min(length * beat_length_boost * bar_height_ratio, max_len)
                x = axis_start + slot_width * i + slot_width / 2
                y_end = baseline + length if is_flipped else baseline - length
                color = (255, 255, 255) if use_vertical_gradient else get_spectrum_color(i, bars)
                color = apply_beat_color(color, current_beat_pulse, current_beat_flash)

                draw_spectrum_bar(draw_surface, (x, baseline), (x, y_end), color, bar_width, draw_alpha, root_fade)
    else:
        center = (width // 2, height // 2)
        radius_outer = min(width, height) / 2
        radius_inner = min(width, height) / 4
        radius_base = radius_outer if is_flipped else radius_inner
        ring_size = radius_outer - radius_inner
        angle_offset = np.pi / 2 if is_rotated else 0
        max_len = max(1, ring_size)
        if use_vertical_gradient:
            color_mask = get_vertical_color_mask(
                width,
                height,
                style,
                is_flipped,
                is_rotated,
                max_len,
                center=center,
                radius_base=radius_base
            )
            if not root_fade:
                gradient_surface = get_vertical_gradient_surface(
                    color_mask,
                    width,
                    height,
                    style,
                    is_flipped,
                    is_rotated,
                    max_len,
                    center=center,
                    radius_base=radius_base
                )

        for i in range(bars):
            angle = i * (2 * np.pi / bars) - np.pi / 2 + angle_offset
            length = smoothed_fft[i]
            
            if length < 2:
                continue
                
            length = min(length * beat_length_boost, max_len)
            end_radius = radius_base - length if is_flipped else radius_base + length
            
            start_x = center[0] + radius_base * np.cos(angle)
            start_y = center[1] + radius_base * np.sin(angle)
            
            end_x = center[0] + end_radius * np.cos(angle)
            end_y = center[1] + end_radius * np.sin(angle)
            color = (255, 255, 255) if use_vertical_gradient else get_spectrum_color(i, bars, seamless=True)
            color = apply_beat_color(color, current_beat_pulse, current_beat_flash)
            
            bar_width = max(1, int((2 * np.pi * radius_inner / bars) * 0.8 * (1.0 + current_beat_flash * 0.12)))
            draw_spectrum_bar(draw_surface, (start_x, start_y), (end_x, end_y), color, bar_width, draw_alpha, root_fade)

    if root_fade:
        layered_bitmap.update(hwnd, canvas, config["x"], config["y"], fade_mask, color_mask)
        if show_after_layered_update:
            show_window_no_activate(hwnd)
            force_z_update = True
    elif use_vertical_gradient:
        # 黑色背景乘以任何渐变色后仍是透明色键，因此可直接在显示 Surface 上混合。
        screen.blit(gradient_surface, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        pygame.display.update()
    else:
        pygame.display.update()
    if show_after_colorkey_update:
        show_window_no_activate(hwnd)
        force_z_update = True
    clock.tick(get_target_fps())

save_config()
if 'stream' in globals():
    stream.stop_stream()
    stream.close()
p.terminate()
layered_bitmap.close()
try:
    tk_main_root.destroy()
except:
    pass
pygame.quit()
os._exit(0)
