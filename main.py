import copy
import os
import threading

import numpy as np
import pygame
import win32con
import win32gui

import app_config as cfg
import startup
from app_config import (
    APP_VERSION,
    COLOR_MODE_VERTICAL,
    PERFORMANCE_PROFILES,
    config,
)
from audio_capture import LoopbackAudioCapture
from rendering import SpectrumRenderer
from settings_panel import SettingsPanel
from tray_menu import create_tray_icon
from windowing import (
    LayeredWindowBitmap,
    set_window_layering,
    show_window_no_activate,
    update_window_pos,
)


COLOR_KEY = (255, 0, 128)
VERTICAL_COLOR_KEY = (0, 0, 0)


cfg.load_config()
actual_startup_enabled = startup.is_startup_enabled()
if bool(config.get("startup_enabled", False)) != actual_startup_enabled:
    config["startup_enabled"] = actual_startup_enabled
    cfg.save_config()


running = True
need_resize = False
need_move = False
need_alpha = False
show_settings_flag = False
pending_preset_name = None
force_z_update = True
frame_count = 0
smoothed_fft = np.zeros(cfg.normalize_bar_count(config["bars"]), dtype=np.float32)
last_use_vertical_gradient = cfg.normalize_color_mode(config.get("color_mode")) == COLOR_MODE_VERTICAL
last_root_fade = bool(config.get("spectrum_root_fade", False))

settings_panel = None
icon = None


def refresh_settings_controls():
    if settings_panel is not None:
        settings_panel.refresh()


def update_tray_menu():
    if icon is None:
        return
    try:
        icon.update_menu()
    except Exception:
        pass


def mark_resize_needed():
    global need_resize
    need_resize = True


def mark_move_needed():
    global need_move, force_z_update
    need_move = True
    force_z_update = True
    try:
        update_window_pos(hwnd, config["x"], config["y"], config["width"], config["height"])
    except Exception:
        pass


def mark_alpha_needed():
    global need_alpha
    need_alpha = True


def mark_z_update_needed():
    global force_z_update
    force_z_update = True


def reset_smoothed_fft(bar_count):
    global smoothed_fft
    smoothed_fft = np.zeros(cfg.normalize_bar_count(bar_count), dtype=np.float32)


def apply_config_snapshot(snapshot, active_preset=""):
    global need_resize, need_move, need_alpha, smoothed_fft, force_z_update

    snapshot = cfg.preset_snapshot_from(snapshot, config)
    old_pos = (int(config["x"]), int(config["y"]))
    old_size = (int(config["width"]), int(config["height"]))
    old_alpha = int(config["alpha"])
    old_bars = int(config["bars"])
    old_overlay = config.get("overlay_target")

    for key, value in snapshot.items():
        config[key] = copy.deepcopy(value)

    active_preset = cfg.normalize_preset_name(active_preset)
    config["active_preset"] = active_preset if active_preset in config.get("presets", {}) else ""
    cfg.normalize_config()

    new_pos = (int(config["x"]), int(config["y"]))
    new_size = (int(config["width"]), int(config["height"]))
    if new_size != old_size:
        need_resize = True
    elif new_pos != old_pos:
        need_move = True
    if int(config["alpha"]) != old_alpha:
        need_alpha = True
    if int(config["bars"]) != old_bars:
        smoothed_fft = np.zeros(cfg.normalize_bar_count(config["bars"]), dtype=np.float32)
    if config.get("overlay_target") != old_overlay:
        force_z_update = True

    refresh_settings_controls()
    update_tray_menu()
    cfg.save_config()


def apply_preset(name):
    name = cfg.normalize_preset_name(name)
    preset = config.get("presets", {}).get(name)
    if not preset:
        return False
    apply_config_snapshot(preset, active_preset=name)
    return True


def save_current_preset(name):
    if not cfg.save_current_preset(name):
        return False
    refresh_settings_controls()
    update_tray_menu()
    return True


def delete_preset(name):
    if not cfg.delete_preset(name):
        return False
    refresh_settings_controls()
    update_tray_menu()
    return True


def rename_preset(old_name, new_name):
    if not cfg.rename_preset(old_name, new_name):
        return False
    refresh_settings_controls()
    update_tray_menu()
    return True


def duplicate_preset(source_name, new_name=None):
    new_name = cfg.duplicate_preset(source_name, new_name)
    if new_name:
        refresh_settings_controls()
        update_tray_menu()
    return new_name


def import_presets_from_file(path, replace_existing=False):
    count = cfg.import_presets_from_file(path, replace_existing=replace_existing)
    if count:
        refresh_settings_controls()
        update_tray_menu()
    return count


def export_presets_to_file(path, names=None):
    return cfg.export_presets_to_file(path, names=names)


def get_effective_bars():
    return cfg.get_effective_bars()


def get_target_fps():
    return cfg.get_target_fps()


def get_root_fade_segments():
    return cfg.get_root_fade_segments()


def set_performance_mode(mode):
    if cfg.set_performance_mode(mode):
        update_tray_menu()


def set_startup_enabled(enabled):
    try:
        startup.sync_startup_shortcut(bool(enabled), cfg.application_path)
        config["startup_enabled"] = startup.is_startup_enabled()
        cfg.save_config()
        return True, ""
    except Exception as exc:
        config["startup_enabled"] = startup.is_startup_enabled()
        cfg.save_config()
        return False, str(exc)


def on_quit(tray_icon, item):
    global running
    running = False
    try:
        tray_icon.stop()
    except Exception:
        pass


def on_settings(tray_icon, item):
    global show_settings_flag
    show_settings_flag = True


def queue_preset(name):
    global pending_preset_name
    pending_preset_name = name


settings_panel = SettingsPanel(
    config,
    mark_resize_needed,
    mark_move_needed,
    mark_alpha_needed,
    mark_z_update_needed,
    reset_smoothed_fft,
    apply_preset,
    save_current_preset,
    delete_preset,
    rename_preset,
    duplicate_preset,
    import_presets_from_file,
    export_presets_to_file,
    set_startup_enabled,
)

icon = create_tray_icon(
    APP_VERSION,
    config,
    on_settings,
    on_quit,
    queue_preset,
    set_performance_mode,
    PERFORMANCE_PROFILES,
    cfg.normalize_performance_mode,
)


def tray_thread():
    icon.run()


t = threading.Thread(target=tray_thread, daemon=True)
t.start()


audio_capture = LoopbackAudioCapture(buffer_size=1024)
audio_capture.start()

os.environ["SDL_VIDEO_WINDOW_POS"] = f"{config['x']},{config['y']}"
pygame.init()
screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
hwnd = pygame.display.get_wm_info()["window"]
layered_bitmap = LayeredWindowBitmap()
using_per_pixel_alpha = bool(config.get("spectrum_root_fade", False))
initial_vertical_gradient = cfg.normalize_color_mode(config.get("color_mode")) == COLOR_MODE_VERTICAL
active_color_key = VERTICAL_COLOR_KEY if initial_vertical_gradient and not using_per_pixel_alpha else COLOR_KEY
set_window_layering(hwnd, using_per_pixel_alpha, config["alpha"], active_color_key)
renderer = SpectrumRenderer(config, get_target_fps, get_root_fade_segments)
clock = pygame.time.Clock()


while running:
    frame_count += 1
    if pending_preset_name:
        preset_to_apply = pending_preset_name
        pending_preset_name = None
        apply_preset(preset_to_apply)

    root_fade = bool(config.get("spectrum_root_fade", False))
    color_mode_value = cfg.normalize_color_mode(config.get("color_mode"))
    use_vertical_gradient = color_mode_value == COLOR_MODE_VERTICAL
    if last_use_vertical_gradient and not use_vertical_gradient:
        renderer.clear_vertical_gradient_cache(clear_surface=True)
    if not last_root_fade and root_fade:
        renderer.clear_vertical_gradient_cache(clear_surface=True)
    elif last_root_fade and not root_fade:
        renderer.reset_canvas()
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
        settings_panel.show()
        show_settings_flag = False

    settings_panel.update()

    if need_resize:
        screen = pygame.display.set_mode((config["width"], config["height"]), pygame.NOFRAME)
        hwnd = pygame.display.get_wm_info()["window"]
        renderer.reset_canvas()
        renderer.clear_vertical_gradient_cache(clear_surface=True)
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
            hide_during_reset=root_fade,
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
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        set_window_layering(hwnd, False, config["alpha"], desired_color_key)
        active_color_key = desired_color_key
        show_after_colorkey_update = True

    for event in pygame.event.get():
        pass

    audio_data = audio_capture.read()
    bars = get_effective_bars()
    if len(smoothed_fft) != bars:
        smoothed_fft = np.zeros(bars, dtype=np.float32)

    current_beat_pulse, current_beat_flash = renderer.analyze_audio(
        audio_data,
        audio_capture.samplerate,
        bars,
        frame_count,
        smoothed_fft,
    )

    draw_surface, color_mask, gradient_surface = renderer.draw(
        screen,
        smoothed_fft,
        bars,
        root_fade,
        use_vertical_gradient,
        COLOR_KEY,
        VERTICAL_COLOR_KEY,
        current_beat_pulse,
        current_beat_flash,
    )

    if root_fade:
        layered_bitmap.update(hwnd, draw_surface, config["x"], config["y"], None, color_mask)
        if show_after_layered_update:
            show_window_no_activate(hwnd)
            force_z_update = True
    elif use_vertical_gradient:
        screen.blit(gradient_surface, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        pygame.display.update()
    else:
        pygame.display.update()

    if show_after_colorkey_update:
        show_window_no_activate(hwnd)
        force_z_update = True
    clock.tick(get_target_fps())


cfg.save_config()
audio_capture.close()
layered_bitmap.close()
settings_panel.destroy()
pygame.quit()
os._exit(0)
