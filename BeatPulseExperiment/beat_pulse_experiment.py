import math
import threading
import time
from collections import deque

import numpy as np
import pygame
import pyaudiowpatch as pyaudio


WIDTH = 900
HEIGHT = 900
FPS = 120
BUFFER_SIZE = 1024
BARS = 96

BG_COLOR = (5, 7, 12)
START_COLOR = (62, 230, 255)
MID_COLOR = (255, 216, 92)
END_COLOR = (255, 72, 184)


def clamp(value, low, high):
    return max(low, min(high, value))


def draw_pos(x, y):
    return (int(round(float(x))), int(round(float(y))))


def lerp_color(a, b, t):
    t = clamp(float(t), 0.0, 1.0)
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def spectrum_color(index, total, pulse):
    ratio = index / max(1, total - 1)
    if ratio < 0.5:
        color = lerp_color(START_COLOR, MID_COLOR, ratio * 2.0)
    else:
        color = lerp_color(MID_COLOR, END_COLOR, (ratio - 0.5) * 2.0)

    boost = 0.82 + pulse * 0.75
    return tuple(min(255, int(channel * boost)) for channel in color)


class LoopbackAudio:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = np.zeros(BUFFER_SIZE, dtype=np.float32)
        self.samplerate = 48000
        self.channels = 1
        self.pa = None
        self.stream = None
        self.error = ""

    def start(self):
        try:
            self.pa = pyaudio.PyAudio()
            wasapi_info = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            device = self.pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            if not device["isLoopbackDevice"]:
                for loopback in self.pa.get_loopback_device_info_generator():
                    if device["name"] in loopback["name"]:
                        device = loopback
                        break

            self.samplerate = int(device["defaultSampleRate"])
            self.channels = max(1, int(device["maxInputChannels"]))

            def callback(in_data, frame_count, time_info, status):
                if in_data:
                    data = np.frombuffer(in_data, dtype=np.float32)
                    if self.channels > 1:
                        usable = data.size - (data.size % self.channels)
                        if usable > 0:
                            data = data[:usable].reshape(-1, self.channels)[:, 0]
                    with self.lock:
                        self.frame = data.astype(np.float32, copy=True)
                return (in_data, pyaudio.paContinue)

            self.stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.samplerate,
                frames_per_buffer=BUFFER_SIZE,
                input=True,
                input_device_index=device["index"],
                stream_callback=callback,
            )
            self.stream.start_stream()
        except Exception as exc:
            self.error = str(exc)
            self.close()

    def read(self):
        with self.lock:
            return self.frame.copy(), self.samplerate, self.error

    def close(self):
        try:
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        try:
            if self.pa is not None:
                self.pa.terminate()
        except Exception:
            pass
        self.pa = None


class BeatDetector:
    def __init__(self):
        self.history = deque(maxlen=72)
        self.previous_energy = 0.0
        self.last_beat_time = 0.0

    def update(self, magnitude, samplerate, now):
        if magnitude.size < 8:
            return 0.0

        fft_size = max(2, (magnitude.size - 1) * 2)
        hz_per_bin = samplerate / fft_size
        bass_start = max(2, int(35 / hz_per_bin))
        bass_end = min(magnitude.size, max(bass_start + 1, int(180 / hz_per_bin)))
        body_end = min(magnitude.size, max(bass_end + 1, int(2400 / hz_per_bin)))

        bass = float(np.mean(magnitude[bass_start:bass_end])) if bass_end > bass_start else 0.0
        body = float(np.mean(magnitude[bass_end:body_end])) if body_end > bass_end else 0.0
        energy = math.log1p(bass * 1.55 + body * 0.22)

        if len(self.history) >= 18:
            mean = sum(self.history) / len(self.history)
            variance = sum((value - mean) ** 2 for value in self.history) / len(self.history)
            std = math.sqrt(variance)
            threshold = mean + std * 1.45 + 0.035
        else:
            mean = sum(self.history) / max(1, len(self.history))
            std = 0.08
            threshold = mean * 1.7 + 0.08

        rising = energy > self.previous_energy * 1.08 and energy > 0.05
        ready = now - self.last_beat_time > 0.18
        strength = 0.0
        if ready and rising and energy > threshold:
            strength = clamp((energy - threshold) / (std + 0.06), 0.35, 1.0)
            self.last_beat_time = now

        self.previous_energy = energy
        self.history.append(energy)
        return strength


class SpectrumAnalyzer:
    def __init__(self, bars):
        self.bars = bars
        self.window_key = None
        self.window = None
        self.index_key = None
        self.indices = None
        self.raw = np.zeros(bars, dtype=np.float32)
        self.smoothed = np.zeros(bars, dtype=np.float32)
        self.auto_gain = 0.2

    def get_window(self, length):
        if self.window_key != length or self.window is None:
            self.window = np.hanning(length).astype(np.float32, copy=False)
            self.window_key = length
        return self.window

    def get_indices(self, magnitude_len):
        key = (magnitude_len, self.bars)
        if self.index_key != key or self.indices is None:
            min_idx = 2
            max_idx = max(min_idx + 1, int(magnitude_len * 0.48))
            indices = np.logspace(np.log10(min_idx), np.log10(max_idx), self.bars + 1)
            self.indices = np.clip(indices.astype(np.int32), 0, max(0, magnitude_len - 1))
            self.index_key = key
        return self.indices

    def magnitude(self, frame):
        if frame.size < 8:
            return np.zeros(8, dtype=np.float32)
        window = self.get_window(frame.size)
        return np.abs(np.fft.rfft(frame * window))

    def update(self, magnitude, sensitivity, pulse):
        indices = self.get_indices(magnitude.size)
        for index in range(self.bars):
            start = int(indices[index])
            end = int(indices[index + 1])
            if start == end:
                end = start + 1
            band = magnitude[start:end]
            self.raw[index] = math.log1p(float(np.mean(band)) * sensitivity) if band.size else 0.0

        peak = max(0.05, float(np.max(self.raw)))
        if peak > self.auto_gain:
            self.auto_gain = peak
        else:
            self.auto_gain = self.auto_gain * 0.985 + peak * 0.015

        normalized = np.clip(self.raw / max(0.05, self.auto_gain), 0.0, 1.35)
        decay = 0.80 + pulse * 0.10
        self.smoothed *= decay
        np.maximum(self.smoothed, normalized, out=self.smoothed)
        return self.smoothed


def synthetic_bars(now, beat_phase, bars):
    positions = np.linspace(0.0, 1.0, bars, dtype=np.float32)
    ripple = (np.sin(positions * 26.0 + now * 2.5) + 1.0) * 0.16
    bass = np.exp(-positions * 4.2) * (0.45 + beat_phase * 0.75)
    spark = (np.sin(positions * 73.0 - now * 8.0) + 1.0) * 0.05
    return np.clip(ripple + bass + spark, 0.0, 1.25)


def draw_scene(screen, fade_surface, overlay, bars, pulse, beat_flash, rotation, fallback):
    fade_alpha = int(clamp(54 - pulse * 34, 16, 54))
    fade_surface.fill((BG_COLOR[0], BG_COLOR[1], BG_COLOR[2], fade_alpha))
    screen.blit(fade_surface, (0, 0))

    center_x = WIDTH / 2
    center_y = HEIGHT / 2
    base_radius = 150 + pulse * 32
    max_length = 235 + pulse * 70
    total = len(bars)

    for index, value in enumerate(bars):
        angle = (index / total) * math.tau - math.pi / 2 + rotation
        wave = 0.92 + 0.08 * math.sin(rotation * 3.0 + index * 0.31)
        length = 18 + float(value) * max_length * wave
        root_radius = base_radius + pulse * 12
        tip_radius = root_radius + length
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        x0 = center_x + cos_a * root_radius
        y0 = center_y + sin_a * root_radius
        x1 = center_x + cos_a * tip_radius
        y1 = center_y + sin_a * tip_radius
        width = max(2, int(2 + value * 6 + pulse * 3))
        color = spectrum_color(index, total, pulse)
        pygame.draw.line(screen, color, draw_pos(x0, y0), draw_pos(x1, y1), width)
        if width > 3:
            pygame.draw.circle(screen, color, draw_pos(x1, y1), max(1, width // 2))

    overlay.fill((0, 0, 0, 0))
    if pulse > 0.015:
        ring_alpha = int(150 * pulse)
        pygame.draw.circle(
            overlay,
            (96, 226, 255, ring_alpha),
            draw_pos(center_x, center_y),
            int(118 + pulse * 180),
            3,
        )
        pygame.draw.circle(
            overlay,
            (255, 98, 190, int(95 * pulse)),
            draw_pos(center_x, center_y),
            int(205 + pulse * 125),
            2,
        )

    core_radius = int(32 + pulse * 22 + beat_flash * 10)
    core_alpha = int(150 + beat_flash * 85)
    pygame.draw.circle(overlay, (255, 255, 255, core_alpha), draw_pos(center_x, center_y), core_radius)
    pygame.draw.circle(overlay, (62, 230, 255, 170), draw_pos(center_x, center_y), max(4, core_radius - 12))

    if fallback:
        pygame.draw.circle(overlay, (255, 216, 92, 120), (WIDTH - 32, 32), 7)
    screen.blit(overlay, (0, 0))


def main():
    pygame.init()
    pygame.display.set_caption("Beat Pulse Experiment")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    screen.fill(BG_COLOR)
    clock = pygame.time.Clock()
    fade_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

    audio = LoopbackAudio()
    audio.start()
    analyzer = SpectrumAnalyzer(BARS)
    detector = BeatDetector()

    pulse = 0.0
    beat_flash = 0.0
    rotation = 0.0
    last_synthetic_beat = 0.0
    running = True

    try:
        while running:
            dt = clock.tick(FPS) / 1000.0
            now = time.perf_counter()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False

            frame, samplerate, error = audio.read()
            fallback = bool(error)
            beat_strength = 0.0
            if fallback:
                if now - last_synthetic_beat > 0.72:
                    beat_strength = 0.92
                    last_synthetic_beat = now
                beat_phase = max(0.0, 1.0 - (now - last_synthetic_beat) * 3.2)
                bars = synthetic_bars(now, beat_phase, BARS)
            else:
                magnitude = analyzer.magnitude(frame)
                beat_strength = detector.update(magnitude, samplerate, now)
                bars = analyzer.update(magnitude, sensitivity=5.2, pulse=pulse)

            if beat_strength > 0.0:
                pulse = max(pulse, beat_strength)
                beat_flash = max(beat_flash, beat_strength)

            pulse *= math.exp(-dt * 4.2)
            beat_flash *= math.exp(-dt * 8.5)
            rotation += dt * (0.16 + pulse * 0.36)

            draw_scene(screen, fade_surface, overlay, bars, pulse, beat_flash, rotation, fallback)
            pygame.display.flip()
    finally:
        audio.close()
        pygame.quit()


if __name__ == "__main__":
    main()
