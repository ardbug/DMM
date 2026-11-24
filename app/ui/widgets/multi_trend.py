"""34970A 多通道趋势图：蓝 / 黄 / 绿 / 粉循环。"""

from __future__ import annotations

import csv
import math
from collections import deque

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

_COLORS = (
    QColor("#2563eb"),
    QColor("#eab308"),
    QColor("#16a34a"),
    QColor("#ec4899"),
)


class MultiChannelTrend(QWidget):
    stats_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._series: dict[int, deque[tuple[int, float, int]]] = {}
        self._seq = 0
        self._max_points = 5000
        self._paused = False
        self._include_ovld = False
        self._window_s: float | None = None
        self._sample_count = 0
        self._first_ts = 0
        self._last_ts = 0

    def clear(self) -> None:
        self._series.clear()
        self._seq = 0
        self._sample_count = 0
        self._first_ts = 0
        self._last_ts = 0
        self.update()
        self.stats_changed.emit(self.stats())

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)

    def set_include_ovld(self, include: bool) -> None:
        self._include_ovld = bool(include)

    def set_window_mode(self, mode) -> None:
        if mode == "px" or mode == "all":
            self._window_s = None
        else:
            try:
                self._window_s = float(mode)
            except (TypeError, ValueError):
                self._window_s = None
        self.update()

    def append_samples(self, samples) -> None:
        if self._paused:
            return
        self._seq += 1
        for channel, reading in samples:
            self._sample_count += 1
            ts = int(reading.timestamp_ns or 0)
            if not self._first_ts:
                self._first_ts = ts
            self._last_ts = ts
            if reading.ovld and not self._include_ovld:
                continue
            value = float("nan") if reading.ovld else float(reading.value)
            series = self._series.setdefault(channel, deque())
            series.append((self._seq, value, ts))
            while len(series) > self._max_points:
                series.popleft()
        self.update()
        self.stats_changed.emit(self.stats())

    def stats(self) -> dict[str, float | int]:
        values = [
            value
            for series in self._series.values()
            for _, value, _ in series
            if math.isfinite(value)
        ]
        result: dict[str, float | int] = {
            "count": self._sample_count,
            "duration_s": (
                (self._last_ts - self._first_ts) / 1_000_000_000
                if self._first_ts and self._last_ts >= self._first_ts
                else 0.0
            ),
        }
        if not values:
            return result
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        result.update(
            {
                "min": min(values),
                "max": max(values),
                "avg": mean,
                "std": math.sqrt(variance),
                "pp": max(values) - min(values),
                "cv": (
                    math.sqrt(variance) / abs(mean) * 100
                    if mean
                    else 0.0
                ),
            }
        )
        return result

    def save_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["channel", "sequence", "timestamp_ns", "value"])
            for channel in sorted(self._series):
                for seq, value, ts in self._series[channel]:
                    writer.writerow(
                        [
                            channel,
                            seq,
                            ts,
                            "" if not math.isfinite(value) else f"{value:.15g}",
                        ]
                    )

    def _visible_series(self) -> dict[int, list[tuple[int, float, int]]]:
        if self._window_s is None or not self._last_ts:
            return {
                channel: list(series)
                for channel, series in self._series.items()
            }
        cutoff = self._last_ts - int(self._window_s * 1_000_000_000)
        return {
            channel: [item for item in series if item[2] >= cutoff]
            for channel, series in self._series.items()
            if any(item[2] >= cutoff for item in series)
        }

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        left, top, right, bottom = 66, 42, 18, 52
        plot_left = left
        plot_top = top
        plot_right = max(plot_left + 20, self.width() - right)
        plot_bottom = max(plot_top + 20, self.height() - bottom)

        grid_pen = QPen(QColor("#d8dde5"), 1)
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        for index in range(6):
            y = plot_top + (plot_bottom - plot_top) * index / 5
            painter.drawLine(plot_left, int(y), plot_right, int(y))
            x = plot_left + (plot_right - plot_left) * index / 5
            painter.drawLine(int(x), plot_top, int(x), plot_bottom)
        painter.setPen(QPen(QColor("#8b95a5"), 1))
        painter.drawRect(
            plot_left, plot_top, plot_right - plot_left, plot_bottom - plot_top
        )

        visible = self._visible_series()
        values = [
            value
            for series in visible.values()
            for _, value, _ in series
            if math.isfinite(value)
        ]
        if not values:
            painter.setPen(QColor("#8b95a5"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "等待扫描数据"
            )
            return

        vmin, vmax = min(values), max(values)
        if vmin == vmax:
            delta = max(abs(vmin) * 0.01, 1e-12)
            vmin -= delta
            vmax += delta

        def y_of(value: float) -> float:
            return plot_bottom - (
                (value - vmin) / (vmax - vmin)
            ) * (plot_bottom - plot_top)

        if self._window_s is not None:
            xmin = self._last_ts - int(self._window_s * 1_000_000_000)
            xmax = self._last_ts
            if xmax <= xmin:
                xmax = xmin + 1
            x_of = lambda ts: plot_left + (ts - xmin) / (xmax - xmin) * (
                plot_right - plot_left
            )
        else:
            seqs = [seq for series in visible.values() for seq, _, _ in series]
            smin, smax = min(seqs), max(seqs)
            if smin == smax:
                smax = smin + 1
            x_of = lambda seq: plot_left + (seq - smin) / (smax - smin) * (
                plot_right - plot_left
            )

        font = QFont("Consolas", 9)
        painter.setFont(font)
        painter.setPen(QColor("#5f6875"))
        span = vmax - vmin
        decimals = max(
            0,
            min(9, -int(math.floor(math.log10(span))) + 1)
            if span > 0
            else 6,
        )
        for index in range(6):
            value = vmax - span * index / 5
            y = plot_top + (plot_bottom - plot_top) * index / 5
            painter.drawText(
                4, int(y) + 5, plot_left - 8, 18,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:.{decimals}f}",
            )
        if self._window_s is None:
            seq_values = [
                seq
                for series in visible.values()
                for seq, _, _ in series
            ]
            tick_min, tick_max = min(seq_values), max(seq_values)
            for index in range(6):
                value = int(
                    tick_min + (tick_max - tick_min) * index / 5
                )
                x = plot_left + (plot_right - plot_left) * index / 5
                painter.drawText(
                    int(x) - 24,
                    plot_bottom + 10,
                    48,
                    18,
                    Qt.AlignmentFlag.AlignCenter,
                    str(value),
                )
            painter.drawText(plot_left - 30, plot_bottom + 26, "样本序号")
        else:
            for index in range(6):
                seconds = self._window_s * (index / 5 - 1)
                x = plot_left + (plot_right - plot_left) * index / 5
                painter.drawText(
                    int(x) - 24,
                    plot_bottom + 10,
                    48,
                    18,
                    Qt.AlignmentFlag.AlignCenter,
                    f"{seconds:.0f}s",
                )
            painter.drawText(plot_left - 30, plot_bottom + 26, "时间")
        painter.drawText(
            plot_left,
            self.height() - 6,
            f"{self._sample_count} 样本 · {len(visible)} 通道",
        )

        channels = sorted(visible)
        legend_x = plot_left
        for index, channel in enumerate(channels[:6]):
            color = _COLORS[index % len(_COLORS)]
            painter.setPen(QPen(color, 2))
            painter.drawLine(legend_x, 14, legend_x + 18, 14)
            painter.setPen(QColor("#4b5563"))
            painter.drawText(legend_x + 22, 19, f"CH{channel}")
            legend_x += 90

        for index, channel in enumerate(channels):
            color = _COLORS[index % len(_COLORS)]
            painter.setPen(QPen(color, 1.6))
            points = [
                QPointF(
                    x_of(ts) if self._window_s is not None else x_of(seq),
                    y_of(value),
                )
                for seq, value, ts in visible[channel]
                if math.isfinite(value)
            ]
            if len(points) > 1:
                painter.drawPolyline(points)
            elif points:
                painter.drawPoint(points[0])
