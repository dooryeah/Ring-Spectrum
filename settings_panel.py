import math
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

import win32api
import win32con
import win32gui

import app_config as cfg
import startup
from app_config import (
    APP_NAME,
    APP_VERSION,
    COLOR_MODE_ENDPOINT,
    COLOR_MODE_SOLID,
    COLOR_MODE_VERTICAL,
    SP_MODE_BEAT,
    SP_MODE_NORMAL,
)
from windowing import get_overlay_options


SETTINGS_TITLE = f"{APP_NAME} v{APP_VERSION} - 设置"
CUSTOM_BAND_LABELS = {band["label"]: band["id"] for band in cfg.CUSTOM_FREQUENCY_BANDS}
DEFAULT_CUSTOM_BAND_LABEL = cfg.CUSTOM_FREQUENCY_BANDS[0]["label"]


class SettingsPanel:
    def __init__(
        self,
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
    ):
        self.config = config
        self.mark_resize_needed = mark_resize_needed
        self.mark_move_needed = mark_move_needed
        self.mark_alpha_needed = mark_alpha_needed
        self.mark_z_update_needed = mark_z_update_needed
        self.reset_smoothed_fft = reset_smoothed_fft
        self.apply_preset = apply_preset
        self.save_current_preset = save_current_preset
        self.delete_preset = delete_preset
        self.rename_preset = rename_preset
        self.duplicate_preset = duplicate_preset
        self.import_presets_from_file = import_presets_from_file
        self.export_presets_to_file = export_presets_to_file
        self.set_startup_enabled = set_startup_enabled

        self.root = tk.Tk()
        self.root.withdraw()
        self.window = None
        self.refresh_callback = None

    def refresh(self):
        if self.refresh_callback is not None:
            try:
                self.refresh_callback()
            except Exception:
                pass

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.refresh()
            self.window.deiconify()
            self.window.lift()
            return
        self._create_window()

    def update(self):
        try:
            self.root.update()
            if self.window is not None and self.window.winfo_exists():
                self.window.update()
        except Exception:
            pass

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _create_window(self):
        config = self.config
        self.window = tk.Toplevel(self.root)
        tk_window = self.window
        tk_window.title(SETTINGS_TITLE)
        tk_window.geometry("420x760")
        tk_window.attributes("-topmost", True)
        tk_window.attributes("-toolwindow", True)

        def on_closing():
            tk_window.withdraw()

        tk_window.protocol("WM_DELETE_WINDOW", on_closing)

        canvas = tk.Canvas(tk_window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tk_window, orient="vertical", command=canvas.yview)
        content_frame = ttk.Frame(canvas)
        content_window_id = canvas.create_window((0, 0), window=content_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def update_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(content_window_id, width=canvas.winfo_width())

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        content_frame.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_scroll_region)
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        tk_root = content_frame

        size_var = tk.DoubleVar(value=config["width"])
        cx_var = tk.IntVar(value=int(config["x"] + config["width"] / 2.0))
        cy_var = tk.IntVar(value=int(config["y"] + config["height"] / 2.0))
        alpha_var = tk.DoubleVar(value=config["alpha"])
        sens_var = tk.DoubleVar(value=config["sensitivity"])
        bars_var = tk.DoubleVar(value=config["bars"])
        decay_var = tk.DoubleVar(value=config["decay"])
        bar_height_var = tk.DoubleVar(value=config.get("bar_height", 100.0))
        bar_length_var = tk.DoubleVar(value=config.get("bar_length", 100.0))
        beat_intensity_var = tk.DoubleVar(value=config.get("beat_intensity", 1.0))
        beat_sensitivity_var = tk.DoubleVar(value=config.get("beat_sensitivity", 1.0))
        beat_expand_var = tk.DoubleVar(value=config.get("beat_expand", 0.22) * 100.0)
        beat_brightness_var = tk.DoubleVar(value=config.get("beat_brightness", 0.55) * 100.0)
        beat_tail_var = tk.DoubleVar(value=config.get("beat_tail", 0.08) * 100.0)
        custom_bands_enabled_var = tk.BooleanVar(value=bool(config.get("custom_bands_enabled", False)))
        custom_band_var = tk.StringVar(value=DEFAULT_CUSTOM_BAND_LABEL)
        custom_band_amplitude_var = tk.DoubleVar(value=1.0)
        custom_band_sensitivity_var = tk.DoubleVar(value=1.0)
        controls_refreshing = False

        def gui_update(*args):
            nonlocal controls_refreshing
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
                self.mark_resize_needed()
            elif position_changed:
                self.mark_move_needed()

            new_alpha = int(alpha_var.get())
            if new_alpha != config["alpha"]:
                config["alpha"] = new_alpha
                self.mark_alpha_needed()

            config["sensitivity"] = float(sens_var.get())

            new_bars = int(bars_var.get())
            if new_bars != config["bars"]:
                config["bars"] = new_bars
                self.reset_smoothed_fft(new_bars)

            config["decay"] = float(decay_var.get())
            config["bar_height"] = float(bar_height_var.get())
            config["bar_length"] = float(bar_length_var.get())
            config["beat_intensity"] = float(beat_intensity_var.get())
            config["beat_sensitivity"] = float(beat_sensitivity_var.get())
            config["beat_expand"] = float(beat_expand_var.get()) / 100.0
            config["beat_brightness"] = float(beat_brightness_var.get()) / 100.0
            config["beat_tail"] = float(beat_tail_var.get()) / 100.0

        ttk.Label(tk_root, text="窗口大小 (频谱中心点锚定缩放):").pack(pady=(10, 0))
        ttk.Scale(tk_root, from_=100, to=1500, variable=size_var, command=gui_update).pack(fill="x", padx=20)

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

            btn.bind("<ButtonPress-1>", on_press)
            btn.bind("<ButtonRelease-1>", on_release)
            btn.bind("<Leave>", on_release)
            return btn

        ttk.Label(tk_root, text="频谱中心 X:").pack()
        frame_x = ttk.Frame(tk_root)
        frame_x.pack()
        create_repeat_btn(frame_x, "-", lambda: (cx_var.set(cx_var.get() - 1), gui_update())).pack(side="left")
        ttk.Entry(frame_x, textvariable=cx_var, width=8).pack(side="left")
        create_repeat_btn(frame_x, "+", lambda: (cx_var.set(cx_var.get() + 1), gui_update())).pack(side="left")

        ttk.Label(tk_root, text="频谱中心 Y:").pack()
        frame_y = ttk.Frame(tk_root)
        frame_y.pack()
        create_repeat_btn(frame_y, "-", lambda: (cy_var.set(cy_var.get() - 1), gui_update())).pack(side="left")
        ttk.Entry(frame_y, textvariable=cy_var, width=8).pack(side="left")
        create_repeat_btn(frame_y, "+", lambda: (cy_var.set(cy_var.get() + 1), gui_update())).pack(side="left")

        cx_var.trace_add("write", gui_update)
        cy_var.trace_add("write", gui_update)

        align_frame = ttk.Frame(tk_root)
        align_frame.pack(pady=5)
        ttk.Label(align_frame, text="屏幕对齐:").pack(side="left")
        align_options = ["选择对齐", "靠左", "靠右", "靠上", "靠下", "X轴居中", "Y轴居中"]
        align_var = tk.StringVar(value=align_options[0])
        align_cb = ttk.Combobox(
            align_frame,
            textvariable=align_var,
            values=align_options,
            state="readonly",
            width=12,
        )
        align_cb.pack(side="left", padx=5)

        def get_current_monitor_rect():
            center_x = int(config["x"] + config["width"] / 2.0)
            center_y = int(config["y"] + config["height"] / 2.0)
            monitor = win32api.MonitorFromPoint((center_x, center_y), win32con.MONITOR_DEFAULTTONEAREST)
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
            if option == align_options[0]:
                return

            monitor_left, monitor_top, monitor_right, monitor_bottom = get_current_monitor_rect()
            bounds_left, bounds_top, bounds_right, bounds_bottom = get_spectrum_bounds()
            new_x = int(config["x"])
            new_y = int(config["y"])

            if option == "靠左":
                new_x = math.floor(monitor_left - bounds_left)
            elif option == "靠右":
                new_x = math.ceil(monitor_right - bounds_right)
            elif option == "靠上":
                new_y = math.floor(monitor_top - bounds_top)
            elif option == "靠下":
                new_y = math.ceil(monitor_bottom - bounds_bottom)
            elif option == "X轴居中":
                cx_var.set(int(round((monitor_left + monitor_right) / 2)))
                return
            elif option == "Y轴居中":
                cy_var.set(int(round((monitor_top + monitor_bottom) / 2)))
                return

            if new_x != config["x"]:
                cx_var.set(int(new_x + math.ceil(config["width"] / 2.0)))
            if new_y != config["y"]:
                cy_var.set(int(new_y + math.ceil(config["height"] / 2.0)))

        def on_align_selected(event=None):
            option = align_var.get()
            align_spectrum(option)
            align_var.set(align_options[0])

        align_cb.bind("<<ComboboxSelected>>", on_align_selected)

        ttk.Label(tk_root, text="透明度 (Alpha %):").pack()
        ttk.Scale(tk_root, from_=10, to=100, variable=alpha_var, command=gui_update).pack(fill="x", padx=20)

        ttk.Label(tk_root, text="敏感度 (Sensitivity):").pack()
        ttk.Scale(tk_root, from_=0.5, to=5.0, variable=sens_var, command=gui_update).pack(fill="x", padx=20)

        ttk.Label(tk_root, text="柱子数量 (Bars):").pack()
        ttk.Scale(tk_root, from_=20, to=240, variable=bars_var, command=gui_update).pack(fill="x", padx=20)

        spectrum_style = tk.StringVar(value=config.get("spectrum_style", "ring"))

        def on_style_change():
            config["spectrum_style"] = spectrum_style.get()
            update_bar_controls_visibility()

        ttk.Label(tk_root, text="频谱样式:").pack(pady=(10, 0))
        frame_style = ttk.Frame(tk_root)
        frame_style.pack()
        ttk.Radiobutton(frame_style, text="条状", variable=spectrum_style, value="bar", command=on_style_change).pack(side="left", padx=10)
        ttk.Radiobutton(frame_style, text="环状", variable=spectrum_style, value="ring", command=on_style_change).pack(side="left", padx=10)

        bar_params_frame = ttk.Frame(tk_root)
        ttk.Label(bar_params_frame, text="条形高度 (%):").pack()
        ttk.Scale(bar_params_frame, from_=10, to=200, variable=bar_height_var, command=gui_update).pack(fill="x", padx=20)
        ttk.Label(bar_params_frame, text="条形长度 (%):").pack()
        ttk.Scale(bar_params_frame, from_=10, to=100, variable=bar_length_var, command=gui_update).pack(fill="x", padx=20)

        def update_bar_controls_visibility():
            if spectrum_style.get() == "bar":
                bar_params_frame.pack(fill="x", after=frame_style)
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
        transform_frame.pack(pady=(5, 0))
        ttk.Checkbutton(transform_frame, text="频谱翻转", variable=spectrum_flip, command=on_flip_change).pack(side="left", padx=10)
        ttk.Checkbutton(transform_frame, text="旋转90°", variable=spectrum_rotate_90, command=on_rotate_90_change).pack(side="left", padx=10)
        ttk.Checkbutton(transform_frame, text="根部渐隐", variable=spectrum_root_fade, command=on_root_fade_change).pack(side="left", padx=10)

        overlay_var = tk.StringVar(value=config.get("overlay_target", "【默认】桌面底层"))
        overlay_frame = ttk.Frame(tk_root)
        overlay_frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(overlay_frame, text="显示层级:").pack(side="left")
        overlay_cb = ttk.Combobox(overlay_frame, textvariable=overlay_var, state="readonly", width=25)
        overlay_cb.pack(side="left", padx=5)
        overlay_cb.configure(postcommand=lambda: overlay_cb.configure(values=get_overlay_options(SETTINGS_TITLE)))

        def on_overlay_change(*args):
            if controls_refreshing:
                return
            config["overlay_target"] = overlay_var.get()
            self.mark_z_update_needed()

        overlay_var.trace_add("write", on_overlay_change)

        ttk.Label(tk_root, text="衰减速度 (Decay):").pack()
        ttk.Scale(tk_root, from_=0.01, to=0.99, variable=decay_var, command=gui_update).pack(fill="x", padx=20)

        def ensure_custom_bands():
            config["custom_bands"] = cfg.normalize_custom_bands(config.get("custom_bands"))
            return config["custom_bands"]

        def get_selected_custom_band_id():
            return CUSTOM_BAND_LABELS.get(custom_band_var.get(), cfg.CUSTOM_FREQUENCY_BANDS[0]["id"])

        def set_custom_band_vars_from_config():
            custom_bands = ensure_custom_bands()
            band_values = custom_bands.get(get_selected_custom_band_id(), {"amplitude": 1.0, "sensitivity": 1.0})
            custom_band_amplitude_var.set(float(band_values.get("amplitude", 1.0)))
            custom_band_sensitivity_var.set(float(band_values.get("sensitivity", 1.0)))

        def save_selected_custom_band_values(*args):
            if controls_refreshing:
                return
            custom_bands = ensure_custom_bands()
            band_id = get_selected_custom_band_id()
            custom_bands[band_id] = {
                "amplitude": cfg.normalize_float_range(
                    custom_band_amplitude_var.get(),
                    cfg.DEFAULT_CUSTOM_BANDS[band_id]["amplitude"],
                    cfg.CUSTOM_BAND_MIN_VALUE,
                    cfg.CUSTOM_BAND_MAX_VALUE,
                ),
                "sensitivity": cfg.normalize_float_range(
                    custom_band_sensitivity_var.get(),
                    cfg.DEFAULT_CUSTOM_BANDS[band_id]["sensitivity"],
                    cfg.CUSTOM_BAND_MIN_VALUE,
                    cfg.CUSTOM_BAND_MAX_VALUE,
                ),
            }

        def on_custom_band_selected(event=None):
            nonlocal controls_refreshing
            if custom_band_var.get() not in CUSTOM_BAND_LABELS:
                custom_band_var.set(DEFAULT_CUSTOM_BAND_LABEL)
            was_refreshing = controls_refreshing
            controls_refreshing = True
            try:
                set_custom_band_vars_from_config()
            finally:
                controls_refreshing = was_refreshing

        def update_custom_band_controls_visibility():
            if custom_bands_enabled_var.get():
                custom_band_controls.pack(fill="x", padx=8, pady=(2, 8))
            else:
                custom_band_controls.pack_forget()

        def on_custom_bands_enabled_change():
            if controls_refreshing:
                return
            config["custom_bands_enabled"] = bool(custom_bands_enabled_var.get())
            ensure_custom_bands()
            update_custom_band_controls_visibility()

        custom_band_frame = ttk.LabelFrame(tk_root, text="频谱均衡器")
        custom_band_frame.pack(fill="x", padx=20, pady=(8, 4))
        ttk.Checkbutton(
            custom_band_frame,
            text="启用频谱均衡器",
            variable=custom_bands_enabled_var,
            command=on_custom_bands_enabled_change,
        ).pack(anchor="w", padx=8, pady=(6, 3))

        custom_band_controls = ttk.Frame(custom_band_frame)
        custom_band_row = ttk.Frame(custom_band_controls)
        custom_band_row.pack(fill="x", pady=3)
        ttk.Label(custom_band_row, text="频段", width=8).pack(side="left")
        custom_band_cb = ttk.Combobox(
            custom_band_row,
            textvariable=custom_band_var,
            values=tuple(CUSTOM_BAND_LABELS.keys()),
            state="readonly",
            width=24,
        )
        custom_band_cb.pack(side="left", fill="x", expand=True, padx=6)
        custom_band_cb.bind("<<ComboboxSelected>>", on_custom_band_selected)

        def add_custom_band_slider(parent, label, variable):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=8).pack(side="left")
            value_label = ttk.Label(row, width=7)
            value_label.pack(side="right")

            def refresh_value(*args):
                value_label.configure(text=f"{float(variable.get()):.2f}x")

            scale = ttk.Scale(
                row,
                from_=cfg.CUSTOM_BAND_MIN_VALUE,
                to=cfg.CUSTOM_BAND_MAX_VALUE,
                variable=variable,
                command=lambda value: (refresh_value(), save_selected_custom_band_values()),
            )
            scale.pack(side="left", fill="x", expand=True, padx=6)
            variable.trace_add("write", refresh_value)
            refresh_value()
            return row

        add_custom_band_slider(custom_band_controls, "振幅倍率", custom_band_amplitude_var)
        add_custom_band_slider(custom_band_controls, "敏感度", custom_band_sensitivity_var)

        custom_band_button_row = ttk.Frame(custom_band_controls)
        custom_band_button_row.pack(fill="x", pady=(4, 0))

        def reset_selected_custom_band():
            nonlocal controls_refreshing
            band_id = get_selected_custom_band_id()
            custom_bands = ensure_custom_bands()
            custom_bands[band_id] = {
                "amplitude": cfg.DEFAULT_CUSTOM_BANDS[band_id]["amplitude"],
                "sensitivity": cfg.DEFAULT_CUSTOM_BANDS[band_id]["sensitivity"],
            }
            was_refreshing = controls_refreshing
            controls_refreshing = True
            try:
                set_custom_band_vars_from_config()
            finally:
                controls_refreshing = was_refreshing

        def reset_all_custom_bands():
            nonlocal controls_refreshing
            config["custom_bands"] = cfg.normalize_custom_bands({})
            was_refreshing = controls_refreshing
            controls_refreshing = True
            try:
                set_custom_band_vars_from_config()
            finally:
                controls_refreshing = was_refreshing

        ttk.Button(custom_band_button_row, text="重置当前频段", command=reset_selected_custom_band).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(custom_band_button_row, text="全部重置", command=reset_all_custom_bands).pack(side="left", expand=True, fill="x", padx=(4, 0))
        set_custom_band_vars_from_config()
        update_custom_band_controls_visibility()

        sp_mode_var = tk.StringVar(value=cfg.normalize_sp_mode(config.get("sp_mode")))

        def on_sp_mode_change(event=None):
            if controls_refreshing:
                return
            config["sp_mode"] = cfg.normalize_sp_mode(sp_mode_var.get())
            update_beat_controls_visibility()

        ttk.Label(tk_root, text="sp模式:").pack(pady=(10, 0))
        sp_mode_cb = ttk.Combobox(tk_root, textvariable=sp_mode_var, values=(SP_MODE_NORMAL, SP_MODE_BEAT), state="readonly", width=12)
        sp_mode_cb.pack()
        sp_mode_cb.bind("<<ComboboxSelected>>", on_sp_mode_change)

        beat_params_frame = ttk.LabelFrame(tk_root, text="Beat 参数")

        def add_beat_slider(parent, label, variable, from_, to_, value_format):
            row = ttk.Frame(parent)
            row.pack(fill="x", padx=8, pady=3)
            ttk.Label(row, text=label, width=12).pack(side="left")
            value_label = ttk.Label(row, width=7)
            value_label.pack(side="right")

            def refresh_value(*args):
                value_label.configure(text=value_format(variable.get()))

            scale = ttk.Scale(row, from_=from_, to=to_, variable=variable, command=lambda value: (refresh_value(), gui_update()))
            scale.pack(side="left", fill="x", expand=True, padx=6)
            variable.trace_add("write", refresh_value)
            refresh_value()
            return row

        add_beat_slider(beat_params_frame, "节拍强度", beat_intensity_var, 0.0, 2.0, lambda value: f"{float(value):.2f}")
        add_beat_slider(beat_params_frame, "节拍灵敏度", beat_sensitivity_var, 0.25, 3.0, lambda value: f"{float(value):.2f}")
        add_beat_slider(beat_params_frame, "扩张幅度", beat_expand_var, 0.0, 120.0, lambda value: f"{float(value):.0f}%")
        add_beat_slider(beat_params_frame, "亮度脉冲", beat_brightness_var, 0.0, 150.0, lambda value: f"{float(value):.0f}%")
        add_beat_slider(beat_params_frame, "拖尾增强", beat_tail_var, 0.0, 60.0, lambda value: f"{float(value):.0f}%")

        def reset_beat_defaults():
            beat_intensity_var.set(cfg.DEFAULT_CONFIG["beat_intensity"])
            beat_sensitivity_var.set(cfg.DEFAULT_CONFIG["beat_sensitivity"])
            beat_expand_var.set(cfg.DEFAULT_CONFIG["beat_expand"] * 100.0)
            beat_brightness_var.set(cfg.DEFAULT_CONFIG["beat_brightness"] * 100.0)
            beat_tail_var.set(cfg.DEFAULT_CONFIG["beat_tail"] * 100.0)
            gui_update()

        ttk.Button(beat_params_frame, text="恢复 Beat 默认值", command=reset_beat_defaults).pack(pady=(6, 8))

        def update_beat_controls_visibility():
            if sp_mode_var.get() == SP_MODE_BEAT:
                beat_params_frame.pack(fill="x", padx=20, pady=(6, 4), after=sp_mode_cb)
            else:
                beat_params_frame.pack_forget()

        update_beat_controls_visibility()

        color_mode = tk.StringVar(value=cfg.normalize_color_mode(config.get("color_mode")))

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

        ttk.Label(tk_root, text="颜色模式 (Color Mode):").pack(pady=(10, 0))
        frame_mode = ttk.Frame(tk_root)
        frame_mode.pack()
        ttk.Radiobutton(frame_mode, text="首尾渐变", variable=color_mode, value=COLOR_MODE_ENDPOINT, command=on_mode_change).pack(side="left", padx=6)
        ttk.Radiobutton(frame_mode, text="上下渐变", variable=color_mode, value=COLOR_MODE_VERTICAL, command=on_mode_change).pack(side="left", padx=6)
        ttk.Radiobutton(frame_mode, text="纯色", variable=color_mode, value=COLOR_MODE_SOLID, command=on_mode_change).pack(side="left", padx=6)

        ttk.Button(tk_root, text="选择起始颜色 / 纯色", command=choose_start_color).pack(pady=5)
        ttk.Button(tk_root, text="选择结束颜色 (渐变模式)", command=choose_end_color).pack(pady=5)

        def get_preset_names():
            return list(config.get("presets", {}).keys())

        preset_name_var = tk.StringVar(value=config.get("active_preset", ""))
        preset_frame = ttk.LabelFrame(tk_root, text="预设")
        preset_frame.pack(fill="x", padx=20, pady=(10, 5))
        preset_row = ttk.Frame(preset_frame)
        preset_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(preset_row, text="名称:").pack(side="left")
        preset_cb = ttk.Combobox(preset_row, textvariable=preset_name_var, values=get_preset_names(), width=24)
        preset_cb.pack(side="left", padx=5, fill="x", expand=True)

        preset_button_row = ttk.Frame(preset_frame)
        preset_button_row.pack(fill="x", padx=8, pady=(0, 8))

        def apply_selected_preset():
            name = cfg.normalize_preset_name(preset_name_var.get())
            if not self.apply_preset(name):
                messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)

        def save_selected_preset():
            name = cfg.normalize_preset_name(preset_name_var.get())
            if not self.save_current_preset(name):
                messagebox.showwarning("提示", "请输入预设名称", parent=tk_root)
                return
            messagebox.showinfo("成功", f"预设“{name}”已保存", parent=tk_root)

        def delete_selected_preset():
            name = cfg.normalize_preset_name(preset_name_var.get())
            if name not in config.get("presets", {}):
                messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)
                return
            if messagebox.askyesno("确认", f"删除预设“{name}”？", parent=tk_root):
                self.delete_preset(name)

        def rename_selected_preset():
            old_name = cfg.normalize_preset_name(preset_name_var.get())
            if old_name not in config.get("presets", {}):
                messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)
                return

            new_name = simpledialog.askstring("重命名预设", "新名称:", initialvalue=old_name, parent=tk_root)
            new_name = cfg.normalize_preset_name(new_name)
            if not new_name or new_name == old_name:
                return
            if new_name in config.get("presets", {}):
                messagebox.showwarning("提示", "该预设名称已存在", parent=tk_root)
                return
            if self.rename_preset(old_name, new_name):
                preset_name_var.set(new_name)

        def duplicate_selected_preset():
            name = cfg.normalize_preset_name(preset_name_var.get())
            if name not in config.get("presets", {}):
                messagebox.showwarning("提示", "请选择已有预设", parent=tk_root)
                return
            new_name = self.duplicate_preset(name)
            if new_name:
                preset_name_var.set(new_name)
                messagebox.showinfo("成功", f"已复制为“{new_name}”", parent=tk_root)

        def import_presets():
            path = filedialog.askopenfilename(parent=tk_root, title="导入预设", filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
            if not path:
                return
            replace_existing = messagebox.askyesno("导入方式", "同名预设是否覆盖？\n选择“否”会自动生成新名称。", parent=tk_root)
            count = self.import_presets_from_file(path, replace_existing=replace_existing)
            if count:
                messagebox.showinfo("成功", f"已导入 {count} 个预设", parent=tk_root)
            else:
                messagebox.showwarning("提示", "没有找到可导入的预设", parent=tk_root)

        def export_presets():
            presets = config.get("presets", {})
            if not presets:
                messagebox.showwarning("提示", "当前没有可导出的预设", parent=tk_root)
                return
            active = cfg.normalize_preset_name(preset_name_var.get())
            suggested_name = f"{active or 'RingSpectrum'}_presets.json"
            path = filedialog.asksaveasfilename(
                parent=tk_root,
                title="导出预设",
                initialfile=suggested_name,
                defaultextension=".json",
                filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            )
            if not path:
                return

            names = None
            if active in presets and not messagebox.askyesno("导出范围", "导出全部预设？\n选择“否”只导出当前选中的预设。", parent=tk_root):
                names = [active]

            if self.export_presets_to_file(path, names=names):
                messagebox.showinfo("成功", "预设已导出", parent=tk_root)
            else:
                messagebox.showwarning("提示", "导出失败", parent=tk_root)

        ttk.Button(preset_button_row, text="应用", command=apply_selected_preset).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ttk.Button(preset_button_row, text="保存/覆盖", command=save_selected_preset).pack(side="left", expand=True, fill="x", padx=3)

        preset_manage_button = ttk.Menubutton(preset_button_row, text="管理")
        preset_manage_menu = tk.Menu(preset_manage_button, tearoff=False)
        preset_manage_menu.add_command(label="复制", command=duplicate_selected_preset)
        preset_manage_menu.add_command(label="重命名", command=rename_selected_preset)
        preset_manage_menu.add_command(label="删除", command=delete_selected_preset)
        preset_manage_menu.add_separator()
        preset_manage_menu.add_command(label="导入", command=import_presets)
        preset_manage_menu.add_command(label="导出", command=export_presets)
        preset_manage_button.configure(menu=preset_manage_menu)
        preset_manage_button.pack(side="left", expand=True, fill="x", padx=(3, 0))

        startup_var = tk.BooleanVar(value=bool(config.get("startup_enabled", False)))

        def on_startup_change():
            if controls_refreshing:
                return
            ok, error = self.set_startup_enabled(startup_var.get())
            startup_var.set(bool(config.get("startup_enabled", False)))
            if not ok:
                messagebox.showwarning("提示", f"开机自启设置失败：{error}", parent=tk_root)

        ttk.Checkbutton(tk_root, text="开机自启", variable=startup_var, command=on_startup_change).pack(pady=(8, 0))

        def refresh_controls_from_config():
            nonlocal controls_refreshing
            controls_refreshing = True
            try:
                config["startup_enabled"] = startup.is_startup_enabled()
                size_var.set(config["width"])
                cx_var.set(int(config["x"] + config["width"] / 2.0))
                cy_var.set(int(config["y"] + config["height"] / 2.0))
                alpha_var.set(config["alpha"])
                sens_var.set(config["sensitivity"])
                bars_var.set(config["bars"])
                decay_var.set(config["decay"])
                bar_height_var.set(config.get("bar_height", 100.0))
                bar_length_var.set(config.get("bar_length", 100.0))
                beat_intensity_var.set(config.get("beat_intensity", cfg.DEFAULT_CONFIG["beat_intensity"]))
                beat_sensitivity_var.set(config.get("beat_sensitivity", cfg.DEFAULT_CONFIG["beat_sensitivity"]))
                beat_expand_var.set(config.get("beat_expand", cfg.DEFAULT_CONFIG["beat_expand"]) * 100.0)
                beat_brightness_var.set(config.get("beat_brightness", cfg.DEFAULT_CONFIG["beat_brightness"]) * 100.0)
                beat_tail_var.set(config.get("beat_tail", cfg.DEFAULT_CONFIG["beat_tail"]) * 100.0)
                spectrum_style.set(config.get("spectrum_style", "ring"))
                spectrum_flip.set(bool(config.get("spectrum_flip", False)))
                spectrum_rotate_90.set(bool(config.get("spectrum_rotate_90", False)))
                spectrum_root_fade.set(bool(config.get("spectrum_root_fade", False)))
                overlay_var.set(config.get("overlay_target", "【默认】桌面底层"))
                config["custom_bands"] = cfg.normalize_custom_bands(config.get("custom_bands"))
                custom_bands_enabled_var.set(bool(config.get("custom_bands_enabled", False)))
                if custom_band_var.get() not in CUSTOM_BAND_LABELS:
                    custom_band_var.set(DEFAULT_CUSTOM_BAND_LABEL)
                set_custom_band_vars_from_config()
                sp_mode_var.set(cfg.normalize_sp_mode(config.get("sp_mode")))
                color_mode.set(cfg.normalize_color_mode(config.get("color_mode")))
                preset_name_var.set(config.get("active_preset", ""))
                preset_cb.configure(values=get_preset_names())
                startup_var.set(bool(config.get("startup_enabled", False)))
                update_bar_controls_visibility()
                update_custom_band_controls_visibility()
                update_beat_controls_visibility()
            finally:
                controls_refreshing = False

        self.refresh_callback = refresh_controls_from_config

        def do_save():
            cfg.save_config()
            messagebox.showinfo("成功", "配置已保存", parent=tk_root)

        ttk.Button(tk_root, text="保存配置", command=do_save).pack(pady=(15, 5))
        ttk.Button(tk_root, text="关闭面板", command=on_closing).pack(pady=5)
