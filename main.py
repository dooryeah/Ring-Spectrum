import os
import sys
import json
import pygame
import numpy as np
import pyaudiowpatch as pyaudio
import random
import win32api
import win32con
import win32gui
import math
import tkinter as tk
from tkinter import ttk, colorchooser
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
    "color_mode": "gradient"
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
    tk_root.geometry("400x650")
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

    ttk.Label(tk_root, text="窗口大小 (圆心锚定缩放):").pack(pady=(10,0))
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
    ttk.Label(pos_frame, text="圆心 X:").pack(side='left')
    create_repeat_btn(pos_frame, "-", lambda: cx_var.set(cx_var.get() - 1)).pack(side='left')
    ttk.Entry(pos_frame, textvariable=cx_var, width=6).pack(side='left', padx=2)
    create_repeat_btn(pos_frame, "+", lambda: cx_var.set(cx_var.get() + 1)).pack(side='left')
    
    ttk.Label(pos_frame, text="  圆心 Y:").pack(side='left')
    create_repeat_btn(pos_frame, "-", lambda: cy_var.set(cy_var.get() - 1)).pack(side='left')
    ttk.Entry(pos_frame, textvariable=cy_var, width=6).pack(side='left', padx=2)
    create_repeat_btn(pos_frame, "+", lambda: cy_var.set(cy_var.get() + 1)).pack(side='left')

    cx_var.trace_add("write", lambda *args: gui_update())
    cy_var.trace_add("write", lambda *args: gui_update())

    ttk.Label(tk_root, text="透明度 (Alpha %):").pack()
    ttk.Scale(tk_root, from_=10, to=100, variable=alpha_var, command=gui_update).pack(fill='x', padx=20)

    ttk.Label(tk_root, text="敏感度 (Sensitivity):").pack()
    ttk.Scale(tk_root, from_=0.5, to=5.0, variable=sens_var, command=gui_update).pack(fill='x', padx=20)

    ttk.Label(tk_root, text="柱子数量 (Bars):").pack()
    ttk.Scale(tk_root, from_=20, to=240, variable=bars_var, command=gui_update).pack(fill='x', padx=20)

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
        tk.messagebox.showinfo("成功", "配置已保存", parent=tk_root)
        
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
    center = (width // 2, height // 2)
    radius_inner = min(width, height) // 4

    sc = config["start_color"]
    ec = config["end_color"]

    for i in range(bars):
        angle = i * (2 * np.pi / bars) - np.pi / 2
        length = smoothed_fft[i]
        
        if length < 2:
            continue
            
        max_len = min(width, height) // 2 - radius_inner - 10
        length = min(length, max_len)
        
        start_x = center[0] + radius_inner * np.cos(angle)
        start_y = center[1] + radius_inner * np.sin(angle)
        
        end_x = center[0] + (radius_inner + length) * np.cos(angle)
        end_y = center[1] + (radius_inner + length) * np.sin(angle)
        
        ratio = i / max(1, bars - 1)
        r = int(sc[0] + (ec[0] - sc[0]) * ratio)
        g = int(sc[1] + (ec[1] - sc[1]) * ratio)
        b = int(sc[2] + (ec[2] - sc[2]) * ratio)
        color = (r, g, b)
        
        bar_width = max(1, int((2 * np.pi * radius_inner / bars) * 0.8))
        pygame.draw.line(screen, color, (start_x, start_y), (end_x, end_y), bar_width)
        if bar_width > 2:
            pygame.draw.circle(screen, color, (int(end_x), int(end_y)), bar_width // 2)

    pygame.draw.circle(screen, COLOR_KEY, center, radius_inner)

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
