import os
import sys
import json
import pygame
import numpy as np
import pyaudiowpatch as pyaudio
import win32api
import win32con
import win32gui
import math
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
from scipy.ndimage import gaussian_filter1d
import pystray
from PIL import Image, ImageDraw
import threading

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(application_path, "config.json")
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
    "color_mode": "gradient",
    "spectrum_style": "ring",
    "spectrum_flip": False,
    "spectrum_rotate_90": False,
    "bar_height": 100.0,
    "bar_length": 100.0
}

config = {}

def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config.update(json.load(f))
        except Exception:
            config = DEFAULT_CONFIG.copy()
    else:
        config = DEFAULT_CONFIG.copy()
    for k, v in DEFAULT_CONFIG.items():
        if k not in config:
            config[k] = v

def save_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception:
        pass

load_config()

# 标志位
running = True
need_resize = False
need_alpha = False
show_settings_flag = False
force_z_update = True
frame_count = 0
smoothed_fft = np.zeros(config["bars"])


# ---- Tkinter 调参窗口 ----
tk_main_root = tk.Tk()
tk_main_root.withdraw()
tk_root = None

def create_settings_window():
    global tk_root, size_var, alpha_var, sens_var, bars_var, decay_var, color_mode
    global x_var, y_var
    
    if tk_root is not None and tk_root.winfo_exists():
        tk_root.deiconify()
        tk_root.lift()
        return

    tk_root = tk.Toplevel(tk_main_root)
    tk_root.title("Ring Spectrum - 设置")
    tk_root.geometry("400x850")
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

    def gui_update(*args):
        global need_resize, need_alpha, smoothed_fft
        
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
        
        if expected_x != config["x"] or expected_y != config["y"] or new_size != config["width"]:
            config["x"] = expected_x
            config["y"] = expected_y
            config["width"] = new_size
            config["height"] = new_size
            need_resize = True

        new_alpha = int(alpha_var.get())
        if new_alpha != config["alpha"]:
            config["alpha"] = new_alpha
            need_alpha = True
            
        config["sensitivity"] = float(sens_var.get())
        
        new_bars = int(bars_var.get())
        if new_bars != config["bars"]:
            config["bars"] = new_bars
            smoothed_fft = np.zeros(new_bars)
            
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

    def on_flip_change():
        config["spectrum_flip"] = bool(spectrum_flip.get())

    def on_rotate_90_change():
        config["spectrum_rotate_90"] = bool(spectrum_rotate_90.get())

    transform_frame = ttk.Frame(tk_root)
    transform_frame.pack(pady=(5,0))
    ttk.Checkbutton(transform_frame, text="频谱翻转", variable=spectrum_flip, command=on_flip_change).pack(side='left', padx=10)
    ttk.Checkbutton(transform_frame, text="旋转90°", variable=spectrum_rotate_90, command=on_rotate_90_change).pack(side='left', padx=10)

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
        config["overlay_target"] = overlay_var.get()
        global force_z_update
        force_z_update = True

    overlay_var.trace_add("write", on_overlay_change)

    ttk.Label(tk_root, text="衰减速度 (Decay):").pack()
    ttk.Scale(tk_root, from_=0.1, to=0.9, variable=decay_var, command=gui_update).pack(fill='x', padx=20)

    color_mode = tk.StringVar(value=config.get("color_mode", "gradient"))

    def choose_start_color():
        color = colorchooser.askcolor(initialcolor=tuple(config["start_color"]), title="选择起始/纯色")
        if color[0]:
            config["start_color"] = [int(c) for c in color[0]]
            if color_mode.get() == "solid":
                config["end_color"] = config["start_color"].copy()

    def choose_end_color():
        color = colorchooser.askcolor(initialcolor=tuple(config["end_color"]), title="选择结束颜色")
        if color[0]:
            config["end_color"] = [int(c) for c in color[0]]

    def on_mode_change():
        config["color_mode"] = color_mode.get()
        if config["color_mode"] == "solid":
            config["end_color"] = config["start_color"].copy()

    ttk.Label(tk_root, text="颜色模式 (Color Mode):").pack(pady=(10,0))
    frame_mode = ttk.Frame(tk_root)
    frame_mode.pack()
    ttk.Radiobutton(frame_mode, text="渐变", variable=color_mode, value="gradient", command=on_mode_change).pack(side='left', padx=10)
    ttk.Radiobutton(frame_mode, text="纯色", variable=color_mode, value="solid", command=on_mode_change).pack(side='left', padx=10)

    ttk.Button(tk_root, text="选择起始颜色 / 纯色", command=choose_start_color).pack(pady=5)
    ttk.Button(tk_root, text="选择结束颜色 (仅渐变)", command=choose_end_color).pack(pady=5)

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

icon = pystray.Icon("RingSpectrum", create_image(), "环形频谱", menu=pystray.Menu(
    pystray.MenuItem("设置", on_settings),
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

def set_window_layering(hwnd, color_key, alpha):
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    # WS_EX_TRANSPARENT 使得鼠标点击穿透，不再处理 Pygame 的鼠标事件
    # 移除强制的 WS_EX_TOPMOST，交给主循环的 Z-order 逻辑动态处理
    new_style = (ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TRANSPARENT) & ~win32con.WS_EX_TOPMOST
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_style)
    win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(*color_key), int(255 * alpha / 100), win32con.LWA_COLORKEY | win32con.LWA_ALPHA)

def update_window_pos(hwnd, x, y, width, height):
    # 使用 SWP_NOZORDER 保持当前的层级，不覆盖上面计算的Z-order
    win32gui.SetWindowPos(hwnd, 0, x, y, width, height, win32con.SWP_SHOWWINDOW | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)

screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
hwnd = pygame.display.get_wm_info()["window"]
COLOR_KEY = (255, 0, 128)
set_window_layering(hwnd, COLOR_KEY, config["alpha"])

clock = pygame.time.Clock()

def get_spectrum_color(index, total):
    sc = config["start_color"]
    ec = config["end_color"]
    ratio = index / max(1, total - 1)
    r = int(sc[0] + (ec[0] - sc[0]) * ratio)
    g = int(sc[1] + (ec[1] - sc[1]) * ratio)
    b = int(sc[2] + (ec[2] - sc[2]) * ratio)
    return (r, g, b)

while running:
    frame_count += 1
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
        set_window_layering(hwnd, COLOR_KEY, config["alpha"])
        update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
        need_resize = False
    elif need_alpha:
        set_window_layering(hwnd, COLOR_KEY, config["alpha"])
        need_alpha = False

    for event in pygame.event.get():
        pass # 完全通过托盘和面板交互，忽略 pygame 事件

    window = np.hanning(len(audio_data))
    fft_data = np.abs(np.fft.rfft(audio_data * window))
    
    bars = config["bars"]
    min_idx = 2
    max_idx = max(3, len(fft_data) // 2)
    log_indices = np.logspace(np.log10(min_idx), np.log10(max_idx), bars + 1).astype(int)
    
    current_bars = []
    for i in range(bars):
        start_idx = log_indices[i]
        end_idx = log_indices[i+1]
        if start_idx == end_idx:
            end_idx = start_idx + 1
            
        band = fft_data[start_idx:end_idx]
        if len(band) > 0:
            current_bars.append(np.mean(band))
        else:
            current_bars.append(0)
            
    current_bars = np.array(current_bars) * config["sensitivity"]
    current_bars = gaussian_filter1d(current_bars, sigma=1.0, mode='wrap')
    smoothed_fft = np.maximum(current_bars, smoothed_fft * config["decay"])

    screen.fill(COLOR_KEY)
    
    width, height = config["width"], config["height"]
    style = config.get("spectrum_style", "ring")
    is_flipped = bool(config.get("spectrum_flip", False))
    is_rotated = bool(config.get("spectrum_rotate_90", False))

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

            for i in range(bars):
                length = smoothed_fft[i]

                if length < 2:
                    continue

                length = min(length * bar_height_ratio, max_len)
                y = axis_start + slot_height * i + slot_height / 2
                x_end = baseline - length if is_flipped else baseline + length
                color = get_spectrum_color(i, bars)

                pygame.draw.line(screen, color, (baseline, y), (x_end, y), bar_width)
                if bar_width > 2:
                    pygame.draw.circle(screen, color, (int(x_end), int(y)), bar_width // 2)
        else:
            margin_x = max(8, width * 0.03)
            edge_padding = max(8, height * 0.06)
            baseline = height / 2
            max_len = max(1, baseline - edge_padding)
            axis_span = max(1, width - margin_x * 2) * bar_length_ratio
            axis_start = (width - axis_span) / 2
            slot_width = max(1, axis_span) / bars
            bar_width = max(1, int(slot_width * 0.72))

            for i in range(bars):
                length = smoothed_fft[i]

                if length < 2:
                    continue

                length = min(length * bar_height_ratio, max_len)
                x = axis_start + slot_width * i + slot_width / 2
                y_end = baseline + length if is_flipped else baseline - length
                color = get_spectrum_color(i, bars)

                pygame.draw.line(screen, color, (x, baseline), (x, y_end), bar_width)
                if bar_width > 2:
                    pygame.draw.circle(screen, color, (int(x), int(y_end)), bar_width // 2)
    else:
        center = (width // 2, height // 2)
        radius_outer = min(width, height) / 2
        radius_inner = min(width, height) / 4
        radius_base = radius_outer if is_flipped else radius_inner
        ring_size = radius_outer - radius_inner
        angle_offset = np.pi / 2 if is_rotated else 0
        max_len = max(1, ring_size)

        for i in range(bars):
            angle = i * (2 * np.pi / bars) - np.pi / 2 + angle_offset
            length = smoothed_fft[i]
            
            if length < 2:
                continue
                
            length = min(length, max_len)
            end_radius = radius_base - length if is_flipped else radius_base + length
            
            start_x = center[0] + radius_base * np.cos(angle)
            start_y = center[1] + radius_base * np.sin(angle)
            
            end_x = center[0] + end_radius * np.cos(angle)
            end_y = center[1] + end_radius * np.sin(angle)
            color = get_spectrum_color(i, bars)
            
            bar_width = max(1, int((2 * np.pi * radius_inner / bars) * 0.8))
            pygame.draw.line(screen, color, (start_x, start_y), (end_x, end_y), bar_width)
            if bar_width > 2:
                pygame.draw.circle(screen, color, (int(end_x), int(end_y)), bar_width // 2)

    pygame.display.flip()
    clock.tick(60)

save_config()
if 'stream' in globals():
    stream.stop_stream()
    stream.close()
p.terminate()
try:
    tk_main_root.destroy()
except:
    pass
pygame.quit()
os._exit(0)
