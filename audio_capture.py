import threading

import numpy as np
import pyaudiowpatch as pyaudio


class LoopbackAudioCapture:
    def __init__(self, buffer_size=1024):
        self.buffer_size = int(buffer_size)
        self.lock = threading.Lock()
        self.audio_data = np.zeros(self.buffer_size, dtype=np.float32)
        self.p = None
        self.stream = None
        self.samplerate = 48000
        self.channels = 1
        self.error = ""

    def start(self):
        self.p = pyaudio.PyAudio()
        try:
            wasapi_info = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = self.p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            if not default_speakers["isLoopbackDevice"]:
                for loopback in self.p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break

            self.samplerate = int(default_speakers["defaultSampleRate"])
            self.channels = max(1, int(default_speakers["maxInputChannels"]))

            self.stream = self.p.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.samplerate,
                frames_per_buffer=self.buffer_size,
                input=True,
                input_device_index=default_speakers["index"],
                stream_callback=self._callback,
            )
            self.stream.start_stream()
        except Exception as exc:
            self.error = str(exc)
            print("Audio init error:", exc)

    def _callback(self, in_data, frame_count, time_info, status):
        if in_data:
            data = np.frombuffer(in_data, dtype=np.float32)
            if self.channels > 1:
                data = data[::self.channels]
            with self.lock:
                self.audio_data = data.astype(np.float32, copy=False)
        return (in_data, pyaudio.paContinue)

    def read(self):
        with self.lock:
            return self.audio_data.copy()

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.p is not None:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None
