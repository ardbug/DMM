"""软件蜂鸣：2WΩ 低于阈值时循环播放连续提示音。"""

from __future__ import annotations

import io
import math
import struct
import tempfile
import threading
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

try:
    import winsound
except ImportError:  # pragma: no cover - 非 Windows
    winsound = None  # type: ignore[assignment]

from app.domain.models import Reading

_BEEP_FREQUENCY = 1000
_RATE = 16000
_FALLBACK_CHUNK_MS = 150


class OhmsBeeper(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.enabled = False
        self.threshold = 1.0
        self.volume = 60
        self._stop_event = threading.Event()
        self._stop_event.set()
        self._fallback_thread: threading.Thread | None = None

        self._wav_path = Path(tempfile.gettempdir()) / "34401A_beep_loop.wav"
        self._write_tone()
        self._effect = QSoundEffect(self)
        self._effect.setSource(QUrl.fromLocalFile(str(self._wav_path)))
        self._effect.setLoopCount(QSoundEffect.Infinite.value)
        self._effect.setVolume(self.volume / 100.0)

    def _write_tone(self) -> None:
        rate = _RATE
        samples = rate  # 1 秒，1000 Hz 正好 1000 个整周期，循环无缝
        amplitude = int(32767 * 0.45)
        frames = bytearray()
        for index in range(samples):
            value = int(
                amplitude * math.sin(2.0 * math.pi * _BEEP_FREQUENCY * index / rate)
            )
            frames.extend(struct.pack("<h", value))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(bytes(frames))
        try:
            self._wav_path.write_bytes(buffer.getvalue())
        except OSError:
            pass

    def set_settings(self, enabled: bool, threshold: float, volume: int) -> None:
        self.enabled = bool(enabled)
        self.threshold = max(0.0, float(threshold))
        self.volume = max(0, min(100, int(volume)))
        self._effect.setVolume(self.volume / 100.0)
        if not self.enabled:
            self.stop()

    def update_reading(self, reading: Reading) -> None:
        if not self.enabled or reading.function_label != "2WΩ":
            self.stop()
            return
        if reading.ovld or abs(reading.value) >= self.threshold:
            self.stop()
            return
        self._start()

    def _start(self) -> None:
        if (
            self._effect.status() == QSoundEffect.Status.Error
            or not QMediaDevices.audioOutputs()
        ):
            self._start_fallback()
            return
        if not self._effect.isPlaying():
            self._effect.play()

    def _start_fallback(self) -> None:
        if winsound is None:
            return
        if self._fallback_thread is not None and self._fallback_thread.is_alive():
            return
        self._stop_event.clear()
        self._fallback_thread = threading.Thread(
            target=self._fallback_loop, daemon=True
        )
        self._fallback_thread.start()

    def _fallback_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                winsound.Beep(_BEEP_FREQUENCY, _FALLBACK_CHUNK_MS)
            except RuntimeError:
                try:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except RuntimeError:
                    pass
                self._stop_event.wait(0.3)

    def stop(self) -> None:
        self._effect.stop()
        self._stop_event.set()

    def test(self) -> None:
        if (
            self._effect.status() == QSoundEffect.Status.Error
            or not QMediaDevices.audioOutputs()
        ) and winsound is not None:
            threading.Thread(
                target=winsound.Beep,
                args=(_BEEP_FREQUENCY, 250),
                daemon=True,
            ).start()
            return
        self._effect.play()
        threading.Timer(0.4, self._effect.stop).start()
