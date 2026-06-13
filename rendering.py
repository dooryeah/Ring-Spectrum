import math
from collections import deque

import numpy as np
import pygame

from app_config import (
    BAR_SMOOTH_KERNEL,
    COLOR_MODE_ENDPOINT,
    CUSTOM_FREQUENCY_BANDS,
    COLOR_MODE_VERTICAL,
    SP_MODE_BEAT,
    normalize_color_mode,
    normalize_custom_bands,
    normalize_sp_mode,
)


class SpectrumRenderer:
    def __init__(self, config, get_target_fps, get_root_fade_segments):
        self.config = config
        self.get_target_fps = get_target_fps
        self.get_root_fade_segments = get_root_fade_segments
        self.canvas = None
        self.vertical_color_mask_key = None
        self.vertical_color_mask = None
        self.vertical_gradient_surface_key = None
        self.vertical_gradient_surface = None
        self.fft_window_key = None
        self.fft_window = None
        self.log_indices_key = None
        self.log_indices_cache = None
        self.bars_buffer_key = None
        self.bars_buffer = None
        self.smooth_buffer_key = None
        self.smooth_buffer = None
        self.beat_energy_history = deque(maxlen=72)
        self.beat_previous_energy = 0.0
        self.beat_last_frame = -9999
        self.beat_pulse = 0.0
        self.beat_flash = 0.0

    def reset_canvas(self):
        self.canvas = None

    def clear_vertical_gradient_cache(self, clear_surface=False):
        self.vertical_color_mask_key = None
        self.vertical_color_mask = None
        self.vertical_gradient_surface_key = None
        if clear_surface:
            self.vertical_gradient_surface = None

    def ensure_canvas(self, width, height):
        size = (int(width), int(height))
        if self.canvas is None or self.canvas.get_size() != size:
            self.canvas = pygame.Surface(size, pygame.SRCALPHA)
        return self.canvas

    def get_fft_window(self, length):
        length = int(length)
        if self.fft_window_key != length or self.fft_window is None:
            self.fft_window = np.hanning(length).astype(np.float32, copy=False)
            self.fft_window_key = length
        return self.fft_window

    def get_log_indices(self, fft_len, bars):
        fft_len = int(fft_len)
        bars = int(bars)
        min_idx = 2
        max_idx = max(3, fft_len // 2)
        key = (fft_len, bars, min_idx, max_idx)
        if self.log_indices_key != key or self.log_indices_cache is None:
            indices = np.logspace(np.log10(min_idx), np.log10(max_idx), bars + 1).astype(np.int32)
            indices = np.clip(indices, 0, max(0, fft_len - 1))
            self.log_indices_key = key
            self.log_indices_cache = indices
        return self.log_indices_cache

    def ensure_bars_buffer(self, bars):
        bars = int(bars)
        if self.bars_buffer_key != bars or self.bars_buffer is None:
            self.bars_buffer = np.zeros(bars, dtype=np.float32)
            self.bars_buffer_key = bars
        return self.bars_buffer

    def ensure_smooth_buffer(self, bars):
        bars = int(bars)
        if self.smooth_buffer_key != bars or self.smooth_buffer is None:
            self.smooth_buffer = np.zeros(bars, dtype=np.float32)
            self.smooth_buffer_key = bars
        return self.smooth_buffer

    def get_bar_frequencies(self, bars, fft_len, samplerate):
        try:
            sample_rate = float(samplerate)
        except Exception:
            return None

        fft_len = int(fft_len or 0)
        if sample_rate <= 0 or fft_len <= 1:
            return None

        indices = self.get_log_indices(fft_len, bars)
        starts = indices[:-1].astype(np.float32, copy=False)
        ends = np.maximum(indices[1:].astype(np.float32, copy=False), starts + 1.0)
        fft_size = max(2, (fft_len - 1) * 2)
        frequencies = np.sqrt(starts * ends) * (sample_rate / fft_size)
        return np.maximum(frequencies, 1.0)

    def apply_custom_bands(self, values, fft_len=None, samplerate=None):
        if not bool(self.config.get("custom_bands_enabled", False)) or len(values) <= 0:
            return values

        frequencies = self.get_bar_frequencies(len(values), fft_len, samplerate)
        if frequencies is None:
            return values

        custom_bands = normalize_custom_bands(self.config.get("custom_bands"))
        for band in CUSTOM_FREQUENCY_BANDS:
            band_values = custom_bands[band["id"]]
            amplitude = float(band_values["amplitude"])
            sensitivity = float(band_values["sensitivity"])
            if abs(amplitude - 1.0) < 0.001 and abs(sensitivity - 1.0) < 0.001:
                continue

            mask = (frequencies >= band["min_hz"]) & (frequencies < band["max_hz"])
            if not np.any(mask):
                continue

            if abs(sensitivity - 1.0) >= 0.001:
                band_values_view = values[mask]
                active = band_values_view[band_values_view > 0]
                if len(active) > 0:
                    anchor = max(float(np.percentile(active, 70.0)), 1e-6)
                    normalized = np.maximum(band_values_view, 0.0) / anchor
                    response = np.power(normalized, 1.0 / sensitivity) * anchor
                    values[mask] = response.astype(np.float32, copy=False)

            if abs(amplitude - 1.0) >= 0.001:
                values[mask] *= amplitude
        return values

    def smooth_bars(self, values):
        count = len(values)
        if count < 3:
            return values

        left2, left1, center, right1, right2 = BAR_SMOOTH_KERNEL
        weight_sum = sum(BAR_SMOOTH_KERNEL)
        output = self.ensure_smooth_buffer(count)
        for index in range(count):
            output[index] = (
                values[(index - 2) % count] * left2
                + values[(index - 1) % count] * left1
                + values[index] * center
                + values[(index + 1) % count] * right1
                + values[(index + 2) % count] * right2
            ) / weight_sum
        return output

    def get_sp_mode(self):
        mode = normalize_sp_mode(self.config.get("sp_mode"))
        if self.config.get("sp_mode") != mode:
            self.config["sp_mode"] = mode
        return mode

    def get_config_float(self, key, fallback, minimum, maximum):
        try:
            value = float(self.config.get(key, fallback))
        except Exception:
            value = float(fallback)
        return max(float(minimum), min(float(maximum), value))

    def get_beat_intensity(self):
        return self.get_config_float("beat_intensity", 1.0, 0.0, 2.0)

    def get_beat_sensitivity(self):
        return self.get_config_float("beat_sensitivity", 1.0, 0.25, 3.0)

    def get_beat_expand(self):
        return self.get_config_float("beat_expand", 0.22, 0.0, 1.2)

    def get_beat_brightness(self):
        return self.get_config_float("beat_brightness", 0.55, 0.0, 1.5)

    def get_beat_tail(self):
        return self.get_config_float("beat_tail", 0.08, 0.0, 0.6)

    def update_beat_pulse(self, fft_data, samplerate, frame_index):
        if self.get_sp_mode() != SP_MODE_BEAT or len(fft_data) < 8:
            self.beat_pulse = 0.0
            self.beat_flash = 0.0
            return 0.0, 0.0

        fft_size = max(2, (len(fft_data) - 1) * 2)
        hz_per_bin = float(samplerate) / fft_size
        bass_start = max(2, int(35 / hz_per_bin))
        bass_end = min(len(fft_data), max(bass_start + 1, int(180 / hz_per_bin)))
        body_end = min(len(fft_data), max(bass_end + 1, int(2400 / hz_per_bin)))

        bass = float(np.mean(fft_data[bass_start:bass_end])) if bass_end > bass_start else 0.0
        body = float(np.mean(fft_data[bass_end:body_end])) if body_end > bass_end else 0.0
        energy = math.log1p(bass * 1.55 + body * 0.22)
        beat_sensitivity = self.get_beat_sensitivity()

        if len(self.beat_energy_history) >= 18:
            mean = sum(self.beat_energy_history) / len(self.beat_energy_history)
            variance = sum((value - mean) ** 2 for value in self.beat_energy_history) / len(self.beat_energy_history)
            std = math.sqrt(variance)
            threshold = mean + std * (1.45 / beat_sensitivity) + (0.035 / beat_sensitivity)
        else:
            mean = sum(self.beat_energy_history) / max(1, len(self.beat_energy_history))
            std = 0.08
            threshold = mean * (1.0 + 0.7 / beat_sensitivity) + 0.08 / beat_sensitivity

        rising = energy > self.beat_previous_energy * (1.0 + 0.08 / beat_sensitivity) and energy > 0.05 / beat_sensitivity
        ready = frame_index - self.beat_last_frame > max(5, int(self.get_target_fps() * (0.18 / beat_sensitivity)))
        if ready and rising and energy > threshold:
            strength = max(0.35, min(1.0, (energy - threshold) / (std + 0.06)))
            strength = max(0.0, min(1.0, strength * self.get_beat_intensity()))
            self.beat_pulse = max(self.beat_pulse, strength)
            self.beat_flash = max(self.beat_flash, strength)
            self.beat_last_frame = frame_index

        self.beat_previous_energy = energy
        self.beat_energy_history.append(energy)
        self.beat_pulse *= 0.92
        self.beat_flash *= 0.82
        return self.beat_pulse, self.beat_flash

    def apply_beat_color(self, color, pulse, flash):
        if pulse <= 0.001 and flash <= 0.001:
            return color
        boost = 1.0 + pulse * self.get_beat_brightness() + flash * (self.get_beat_brightness() * 0.4)
        return (
            min(255, int(color[0] * boost)),
            min(255, int(color[1] * boost)),
            min(255, int(color[2] * boost)),
        )

    def lerp_color(self, start_color, end_color, ratio):
        ratio = max(0.0, min(1.0, float(ratio)))
        return (
            int(start_color[0] + (end_color[0] - start_color[0]) * ratio),
            int(start_color[1] + (end_color[1] - start_color[1]) * ratio),
            int(start_color[2] + (end_color[2] - start_color[2]) * ratio),
        )

    def get_spectrum_color(self, index, total, seamless=False):
        sc = self.config["start_color"]
        ec = self.config["end_color"]
        if normalize_color_mode(self.config.get("color_mode")) != COLOR_MODE_ENDPOINT:
            return (int(sc[0]), int(sc[1]), int(sc[2]))

        if seamless:
            angle = 2 * math.pi * (index / max(1, total))
            ratio = (1 - math.cos(angle)) / 2
        else:
            ratio = index / max(1, total - 1)

        return self.lerp_color(sc, ec, ratio)

    def get_alpha_color(self, color, alpha):
        alpha = max(0, min(255, int(alpha)))
        return (
            int(color[0]),
            int(color[1]),
            int(color[2]),
            alpha,
        )

    def get_draw_pos(self, pos):
        return (int(round(float(pos[0]))), int(round(float(pos[1]))))

    def make_vertical_color_mask(self, distance_from_root, max_length):
        max_length = max(1.0, float(max_length))
        ratio = np.clip(distance_from_root, 0, max_length) / max_length
        sc = np.array(self.config["start_color"], dtype=np.float32)
        ec = np.array(self.config["end_color"], dtype=np.float32)
        mask = sc + (ec - sc) * ratio[:, :, None]
        return mask.astype(np.uint8)

    def get_vertical_color_mask(self, width, height, style, is_flipped, is_rotated, max_length, baseline=None, center=None, radius_base=None):
        key = (
            int(width),
            int(height),
            style,
            bool(is_flipped),
            bool(is_rotated),
            round(float(max_length), 3),
            tuple(int(c) for c in self.config["start_color"]),
            tuple(int(c) for c in self.config["end_color"]),
            None if baseline is None else round(float(baseline), 3),
            None if center is None else (round(float(center[0]), 3), round(float(center[1]), 3)),
            None if radius_base is None else round(float(radius_base), 3),
        )
        if key == self.vertical_color_mask_key and self.vertical_color_mask is not None:
            return self.vertical_color_mask

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

        self.vertical_color_mask_key = key
        self.vertical_color_mask = self.make_vertical_color_mask(distance, max_length)
        return self.vertical_color_mask

    def update_vertical_gradient_surface(self, surface, color_mask):
        width, height = surface.get_size()
        if color_mask.shape[:2] != (height, width):
            return
        rgb = pygame.surfarray.pixels3d(surface)
        try:
            target = np.transpose(rgb, (1, 0, 2))
            np.copyto(target, color_mask)
            target[np.all(target == 0, axis=2)] = 1
        finally:
            del rgb

    def get_vertical_gradient_surface(self, color_mask, width, height, style, is_flipped, is_rotated, max_length, baseline=None, center=None, radius_base=None):
        key = (
            int(width),
            int(height),
            style,
            bool(is_flipped),
            bool(is_rotated),
            round(float(max_length), 3),
            tuple(int(c) for c in self.config["start_color"]),
            tuple(int(c) for c in self.config["end_color"]),
            None if baseline is None else round(float(baseline), 3),
            None if center is None else (round(float(center[0]), 3), round(float(center[1]), 3)),
            None if radius_base is None else round(float(radius_base), 3),
        )
        if (
            key != self.vertical_gradient_surface_key
            or self.vertical_gradient_surface is None
            or self.vertical_gradient_surface.get_size() != (width, height)
        ):
            self.vertical_gradient_surface = pygame.Surface((width, height))
            self.update_vertical_gradient_surface(self.vertical_gradient_surface, color_mask)
            self.vertical_gradient_surface_key = key
        return self.vertical_gradient_surface

    def draw_root_fade_spectrum_bar(self, surface, root_pos, tip_pos, color, bar_width, full_alpha):
        root_x = float(root_pos[0])
        root_y = float(root_pos[1])
        dx = float(tip_pos[0]) - root_x
        dy = float(tip_pos[1]) - root_y
        length = math.hypot(dx, dy)
        if length <= 0:
            return

        segments = max(1, min(self.get_root_fade_segments(), int(math.ceil(length))))
        previous = (root_x, root_y)
        for segment in range(1, segments + 1):
            ratio = segment / segments
            current = (root_x + dx * ratio, root_y + dy * ratio)
            segment_alpha = int(round(full_alpha * (ratio ** 2)))
            if segment_alpha > 0:
                pygame.draw.line(
                    surface,
                    self.get_alpha_color(color, segment_alpha),
                    self.get_draw_pos(previous),
                    self.get_draw_pos(current),
                    bar_width,
                )
            previous = current

        if bar_width > 2:
            pygame.draw.circle(
                surface,
                self.get_alpha_color(color, full_alpha),
                self.get_draw_pos(tip_pos),
                max(1, bar_width // 2),
            )

    def draw_spectrum_bar(self, surface, root_pos, tip_pos, color, bar_width, full_alpha, root_fade=False):
        if root_fade:
            self.draw_root_fade_spectrum_bar(surface, root_pos, tip_pos, color, bar_width, full_alpha)
            return

        draw_color = self.get_alpha_color(color, full_alpha)
        pygame.draw.line(surface, draw_color, self.get_draw_pos(root_pos), self.get_draw_pos(tip_pos), bar_width)
        if bar_width > 2:
            pygame.draw.circle(
                surface,
                draw_color,
                self.get_draw_pos(tip_pos),
                max(1, bar_width // 2),
            )

    def analyze_audio(self, audio_data, samplerate, bars, frame_index, smoothed_fft):
        window = self.get_fft_window(len(audio_data))
        fft_data = np.abs(np.fft.rfft(audio_data * window))
        current_beat_pulse, current_beat_flash = self.update_beat_pulse(fft_data, samplerate, frame_index)
        log_indices = self.get_log_indices(len(fft_data), bars)

        current_bars = self.ensure_bars_buffer(bars)
        for i in range(bars):
            start_idx = log_indices[i]
            end_idx = log_indices[i + 1]
            if start_idx == end_idx:
                end_idx = start_idx + 1

            band = fft_data[start_idx:end_idx]
            if len(band) > 0:
                current_bars[i] = np.mean(band)
            else:
                current_bars[i] = 0

        current_bars *= float(self.config["sensitivity"])
        current_bars = self.apply_custom_bands(current_bars, fft_len=len(fft_data), samplerate=samplerate)
        current_bars = self.smooth_bars(current_bars)
        effective_decay = min(0.995, float(self.config["decay"]) + current_beat_pulse * self.get_beat_tail())
        smoothed_fft *= effective_decay
        np.maximum(current_bars, smoothed_fft, out=smoothed_fft)
        return current_beat_pulse, current_beat_flash

    def draw(
        self,
        screen,
        smoothed_fft,
        bars,
        root_fade,
        use_vertical_gradient,
        color_key,
        vertical_color_key,
        current_beat_pulse,
        current_beat_flash,
    ):
        if root_fade:
            draw_surface = self.ensure_canvas(self.config["width"], self.config["height"])
            draw_surface.fill((0, 0, 0, 0))
        elif use_vertical_gradient:
            draw_surface = screen
            draw_surface.fill(vertical_color_key)
        else:
            draw_surface = screen
            draw_surface.fill(color_key)

        width, height = self.config["width"], self.config["height"]
        style = self.config.get("spectrum_style", "ring")
        is_flipped = bool(self.config.get("spectrum_flip", False))
        is_rotated = bool(self.config.get("spectrum_rotate_90", False))
        full_alpha = int(255 * max(0, min(100, int(self.config["alpha"]))) / 100)
        draw_alpha = full_alpha if root_fade else 255
        beat_length_boost = 1.0 + current_beat_pulse * self.get_beat_expand()
        color_mask = None
        gradient_surface = None

        if style == "bar":
            bar_height_ratio = max(0.05, min(2.0, float(self.config.get("bar_height", 100.0)) / 100.0))
            bar_length_ratio = max(0.05, min(1.0, float(self.config.get("bar_length", 100.0)) / 100.0))

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
                    color_mask = self.get_vertical_color_mask(width, height, style, is_flipped, is_rotated, max_len, baseline=baseline)
                    if not root_fade:
                        gradient_surface = self.get_vertical_gradient_surface(color_mask, width, height, style, is_flipped, is_rotated, max_len, baseline=baseline)

                for i in range(bars):
                    length = smoothed_fft[i]
                    if length < 2:
                        continue

                    length = min(length * beat_length_boost * bar_height_ratio, max_len)
                    y = axis_start + slot_height * i + slot_height / 2
                    x_end = baseline - length if is_flipped else baseline + length
                    color = (255, 255, 255) if use_vertical_gradient else self.get_spectrum_color(i, bars)
                    color = self.apply_beat_color(color, current_beat_pulse, current_beat_flash)
                    self.draw_spectrum_bar(draw_surface, (baseline, y), (x_end, y), color, bar_width, draw_alpha, root_fade)
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
                    color_mask = self.get_vertical_color_mask(width, height, style, is_flipped, is_rotated, max_len, baseline=baseline)
                    if not root_fade:
                        gradient_surface = self.get_vertical_gradient_surface(color_mask, width, height, style, is_flipped, is_rotated, max_len, baseline=baseline)

                for i in range(bars):
                    length = smoothed_fft[i]
                    if length < 2:
                        continue

                    length = min(length * beat_length_boost * bar_height_ratio, max_len)
                    x = axis_start + slot_width * i + slot_width / 2
                    y_end = baseline + length if is_flipped else baseline - length
                    color = (255, 255, 255) if use_vertical_gradient else self.get_spectrum_color(i, bars)
                    color = self.apply_beat_color(color, current_beat_pulse, current_beat_flash)
                    self.draw_spectrum_bar(draw_surface, (x, baseline), (x, y_end), color, bar_width, draw_alpha, root_fade)
        else:
            center = (width // 2, height // 2)
            radius_outer = min(width, height) / 2
            radius_inner = min(width, height) / 4
            radius_base = radius_outer if is_flipped else radius_inner
            ring_size = radius_outer - radius_inner
            angle_offset = np.pi / 2 if is_rotated else 0
            max_len = max(1, ring_size)
            bar_width = max(1, int((2 * np.pi * radius_inner / bars) * 0.8 * (1.0 + current_beat_flash * 0.12)))
            if use_vertical_gradient:
                color_mask = self.get_vertical_color_mask(width, height, style, is_flipped, is_rotated, max_len, center=center, radius_base=radius_base)
                if not root_fade:
                    gradient_surface = self.get_vertical_gradient_surface(color_mask, width, height, style, is_flipped, is_rotated, max_len, center=center, radius_base=radius_base)

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
                color = (255, 255, 255) if use_vertical_gradient else self.get_spectrum_color(i, bars, seamless=True)
                color = self.apply_beat_color(color, current_beat_pulse, current_beat_flash)
                self.draw_spectrum_bar(draw_surface, (start_x, start_y), (end_x, end_y), color, bar_width, draw_alpha, root_fade)

        return draw_surface, color_mask, gradient_surface
