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
    tk_root.geometry("360x600")
    tk_root.attributes("-topmost", True)
    tk_root.attributes("-toolwindow", True)
    
    def on_closing():
        tk_root.withdraw()
    tk_root.protocol("WM_DELETE_WINDOW", on_closing)

    size_var = tk.DoubleVar(value=config["width"])
    x_var = tk.IntVar(value=config["x"])
    y_var = tk.IntVar(value=config["y"])
    alpha_var = tk.DoubleVar(value=config["alpha"])
    sens_var = tk.DoubleVar(value=config["sensitivity"])
    bars_var = tk.DoubleVar(value=config["bars"])
    decay_var = tk.DoubleVar(value=config["decay"])

    def gui_update(*args):
        global need_resize, need_alpha, smoothed_fft
        
        # 处理圆心锚定缩放：圆心在屏幕上的绝对位置保持不变
        old_width = config["width"]
        old_height = config["height"]
        new_size = int(size_var.get())
        
        if new_size != old_width:
            center_x_screen = config["x"] + old_width / 2
            center_y_screen = config["y"] + old_height / 2
            
            config["width"] = new_size
            config["height"] = new_size
            
            # 反算新的窗口左上角位置
            config["x"] = int(center_x_screen - new_size / 2)
            config["y"] = int(center_y_screen - new_size / 2)
            x_var.set(config["x"])
            y_var.set(config["y"])
            need_resize = True

        # 处理 X/Y 位置更新
        new_x = x_var.get()
        new_y = y_var.get()
        if new_x != config["x"] or new_y != config["y"]:
            config["x"] = new_x
            config["y"] = new_y
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
    
    pos_frame = ttk.Frame(tk_root)
    pos_frame.pack(pady=5)
    ttk.Label(pos_frame, text="位置 X:").pack(side='left')
    ttk.Entry(pos_frame, textvariable=x_var, width=8).pack(side='left', padx=5)
    ttk.Label(pos_frame, text="位置 Y:").pack(side='left')
    ttk.Entry(pos_frame, textvariable=y_var, width=8).pack(side='left', padx=5)
    x_var.trace_add("write", lambda *args: gui_update())
    y_var.trace_add("write", lambda *args: gui_update())

    ttk.Label(tk_root, text="透明度 (Alpha %):").pack()
    ttk.Scale(tk_root, from_=10, to=100, variable=alpha_var, command=gui_update).pack(fill='x', padx=20)

    ttk.Label(tk_root, text="敏感度 (Sensitivity):").pack()
    ttk.Scale(tk_root, from_=0.5, to=5.0, variable=sens_var, command=gui_update).pack(fill='x', padx=20)

    ttk.Label(tk_root, text="柱子数量 (Bars):").pack()
    ttk.Scale(tk_root, from_=20, to=120, variable=bars_var, command=gui_update).pack(fill='x', padx=20)

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
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TRANSPARENT)
    win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(*color_key), int(255 * alpha / 100), win32con.LWA_COLORKEY | win32con.LWA_ALPHA)

def update_window_pos(hwnd, x, y, width, height):
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, width, height, win32con.SWP_SHOWWINDOW)

screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
hwnd = pygame.display.get_wm_info()["window"]
COLOR_KEY = (255, 0, 128)
set_window_layering(hwnd, COLOR_KEY, config["alpha"])

clock = pygame.time.Clock()

while running:
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
import winreg
import tkinter as tk
from tkinter import ttk, colorchooser
from scipy.ndimage import gaussian_filter1d

# 获取真实路径（为了打包后能找到相对路径）
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
        except Exception as e:
            print("Config load error:", e)
            config = DEFAULT_CONFIG.copy()
    else:
        config = DEFAULT_CONFIG.copy()

    # 填充缺失项
    for k, v in DEFAULT_CONFIG.items():
        if k not in config:
            config[k] = v

def save_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print("Config save error:", e)

load_config()

# ---- GUI 界面初始化 ----
tk_root = tk.Tk()
tk_root.title("Ring Spectrum - 设置")
tk_root.geometry("320x570")
tk_root.attributes("-topmost", True)
tk_root.attributes("-toolwindow", True)  # 隐藏 Tkinter 在任务栏的图标

def on_closing():
    tk_root.withdraw() # 只是隐藏窗口，不退出主程序
tk_root.protocol("WM_DELETE_WINDOW", on_closing)

size_var = tk.DoubleVar(value=config["width"])
alpha_var = tk.DoubleVar(value=config["alpha"])
sens_var = tk.DoubleVar(value=config["sensitivity"])
bars_var = tk.DoubleVar(value=config["bars"])
decay_var = tk.DoubleVar(value=config["decay"])

need_resize = False
need_alpha = False
smoothed_fft = np.zeros(config["bars"])

def gui_update(*args):
    global need_resize, need_alpha, smoothed_fft
    old_width = config["width"]
    old_alpha = config["alpha"]
    
    config["width"] = int(size_var.get())
    config["height"] = int(size_var.get())
    config["alpha"] = int(alpha_var.get())
    config["sensitivity"] = float(sens_var.get())
    
    new_bars = int(bars_var.get())
    if new_bars != config["bars"]:
        config["bars"] = new_bars
        smoothed_fft = np.zeros(new_bars)
        
    config["decay"] = float(decay_var.get())
    
    if config["width"] != old_width:
        need_resize = True
    if config["alpha"] != old_alpha:
        need_alpha = True

ttk.Label(tk_root, text="大小 (Size):").pack(pady=(10,0))
ttk.Scale(tk_root, from_=200, to=1500, variable=size_var, command=gui_update).pack(fill='x', padx=20)

ttk.Label(tk_root, text="透明度 (Alpha %):").pack()
ttk.Scale(tk_root, from_=10, to=100, variable=alpha_var, command=gui_update).pack(fill='x', padx=20)

ttk.Label(tk_root, text="敏感度 (Sensitivity):").pack()
ttk.Scale(tk_root, from_=0.1, to=20.0, variable=sens_var, command=gui_update).pack(fill='x', padx=20)

ttk.Label(tk_root, text="柱子数量 (Bars):").pack()
ttk.Scale(tk_root, from_=16, to=256, variable=bars_var, command=gui_update).pack(fill='x', padx=20)

ttk.Label(tk_root, text="衰减速度 (Decay):").pack()
ttk.Scale(tk_root, from_=0.1, to=0.99, variable=decay_var, command=gui_update).pack(fill='x', padx=20)

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

ttk.Label(tk_root, text="提示: 右键点击频谱的可视化柱子可再次打开此窗口", justify="center", foreground="gray").pack(pady=(10, 0))

def set_autostart(enable):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
        if enable:
            winreg.SetValueEx(key, "RingSpectrum", 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            winreg.DeleteValue(key, "RingSpectrum")
        winreg.CloseKey(key)
    except Exception:
        pass

def check_autostart():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "RingSpectrum")
        winreg.CloseKey(key)
        return value == f'"{sys.executable}"'
    except Exception:
        return False

autostart_var = tk.BooleanVar(value=check_autostart())
ttk.Checkbutton(tk_root, text="开机自启 (Start on Boot)", variable=autostart_var, command=lambda: set_autostart(autostart_var.get())).pack(pady=5)

def do_exit():
    global running
    running = False

ttk.Button(tk_root, text="完全退出程序", command=do_exit).pack(pady=5)

# ---- 音频处理 ----
buffer_size = 1024 # 减小缓冲区大小以提升响应速度
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
                data = data[::channels] # 只取一个声道
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
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW)
    win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(*color_key), int(255 * alpha / 100), win32con.LWA_COLORKEY | win32con.LWA_ALPHA)

def update_window_pos(hwnd, x, y, width, height):
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, width, height, win32con.SWP_SHOWWINDOW)

screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
hwnd = pygame.display.get_wm_info()["window"]
COLOR_KEY = (255, 0, 128)
set_window_layering(hwnd, COLOR_KEY, config["alpha"])

clock = pygame.time.Clock()

dragging = False
drag_offset = (0, 0)

preset_colors = [
    ([0, 255, 255], [255, 0, 255]),
    ([255, 0, 0], [255, 255, 0]),
    ([0, 255, 0], [0, 0, 255]),
    ([255, 165, 0], [255, 69, 0]),
    ([255, 255, 255], [100, 100, 100])
]
color_idx = 0

running = True
while running:
    # 刷新 GUI
    try:
        tk_root.update()
    except tk.TclError:
        pass # 主动销毁或者异常时忽略

    # 处理通过 GUI 更新的大小和透明度
    if need_resize:
        screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
        set_window_layering(hwnd, COLOR_KEY, config["alpha"])
        update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
        need_resize = False
    elif need_alpha:
        set_window_layering(hwnd, COLOR_KEY, config["alpha"])
        need_alpha = False

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1: # 左键拖动
                mx, my = event.pos
                cx, cy = config["width"] // 2, config["height"] // 2
                outer_radius = min(config["width"], config["height"]) // 2
                if math.hypot(mx - cx, my - cy) <= outer_radius:
                    dragging = True
                    cx_screen, cy_screen = win32api.GetCursorPos()
                    drag_offset = (cx_screen - config["x"], cy_screen - config["y"])
            elif event.button == 3: # 右键呼出面板
                tk_root.deiconify()
                
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                dragging = False
                
        elif event.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            ctrl = mods & pygame.KMOD_CTRL
            shift = mods & pygame.KMOD_SHIFT
            
            if event.key == pygame.K_ESCAPE:
                running = False
            
            elif event.key == pygame.K_UP and not ctrl:
                config["y"] -= 10
                update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
            elif event.key == pygame.K_DOWN and not ctrl:
                config["y"] += 10
                update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
            elif event.key == pygame.K_LEFT:
                config["x"] -= 10
                update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
            elif event.key == pygame.K_RIGHT:
                config["x"] += 10
                update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
                
            elif event.key == pygame.K_UP and ctrl:
                config["width"] = min(2000, config["width"] + 20)
                config["height"] = min(2000, config["height"] + 20)
                size_var.set(config["width"])
                need_resize = True
            elif event.key == pygame.K_DOWN and ctrl:
                config["width"] = max(200, config["width"] - 20)
                config["height"] = max(200, config["height"] - 20)
                size_var.set(config["width"])
                need_resize = True
                
            elif event.key == pygame.K_LEFTBRACKET and ctrl:
                config["alpha"] = max(10, config["alpha"] - 5)
                alpha_var.set(config["alpha"])
                need_alpha = True
            elif event.key == pygame.K_RIGHTBRACKET and ctrl:
                config["alpha"] = min(100, config["alpha"] + 5)
                alpha_var.set(config["alpha"])
                need_alpha = True
                
            elif event.key == pygame.K_EQUALS or event.key == pygame.K_KP_PLUS:
                config["sensitivity"] = min(100.0, config["sensitivity"] + 0.5)
                sens_var.set(config["sensitivity"])
            elif event.key == pygame.K_MINUS or event.key == pygame.K_KP_MINUS:
                config["sensitivity"] = max(0.1, config["sensitivity"] - 0.5)
                sens_var.set(config["sensitivity"])
                
            elif event.key == pygame.K_n:
                config["bars"] = max(16, config["bars"] - 8)
                bars_var.set(config["bars"])
                smoothed_fft = np.zeros(config["bars"])
            elif event.key == pygame.K_m:
                config["bars"] = min(256, config["bars"] + 8)
                bars_var.set(config["bars"])
                smoothed_fft = np.zeros(config["bars"])
                
            elif event.key == pygame.K_c:
                if shift:
                    config["start_color"] = [random.randint(0,255), random.randint(0,255), random.randint(0,255)]
                    config["end_color"] = [random.randint(0,255), random.randint(0,255), random.randint(0,255)]
                else:
                    color_idx = (color_idx + 1) % len(preset_colors)
                    config["start_color"], config["end_color"] = preset_colors[color_idx]
                if color_mode.get() == "solid":
                    config["end_color"] = config["start_color"].copy()
                    
            elif event.key == pygame.K_a:
                config["decay"] = min(0.99, config["decay"] + 0.02)
                decay_var.set(config["decay"])
            elif event.key == pygame.K_s:
                config["decay"] = max(0.1, config["decay"] - 0.02)
                decay_var.set(config["decay"])

    if dragging:
        cx_screen, cy_screen = win32api.GetCursorPos()
        config["x"] = cx_screen - drag_offset[0]
        config["y"] = cy_screen - drag_offset[1]
        update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])

    window = np.hanning(len(audio_data))
    fft_data = np.abs(np.fft.rfft(audio_data * window))
    
    bars = config["bars"]
    
    # 采用对数刻度划分频段，使低中高频分布更均匀，符合人耳听觉
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
    
    # 使用高斯滤波进行空间平滑，减小sigma让频段反应更锐利、更快
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
        
        # 噪点过滤
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
        # 绘制端点圆角
        if bar_width > 2:
            pygame.draw.circle(screen, color, (int(end_x), int(end_y)), bar_width // 2)

    # 绘制内部背景圆（使用 COLOR_KEY 使其完全透明）
    pygame.draw.circle(screen, COLOR_KEY, center, radius_inner)

    pygame.display.flip()
    clock.tick(60)

save_config()
if 'stream' in globals():
    try:
        stream.stop_stream()
        stream.close()
    except Exception:
        pass
try:
    p.terminate()
except Exception:
    pass
try:
    tk_main_root.destroy()
except Exception:
    pass
try:
    pygame.quit()
except Exception:
    pass
os._exit(0)
