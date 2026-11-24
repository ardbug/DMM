"""34970A 多通道趋势图：蓝 / 黄 / 绿 / 粉循环。"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

_COLORS = (
    QColor("#2563eb"),
    QColor("#eab308"),
    QColor("#16a34a"),
    QColor("#ec4899"),
)


class MultiChannelTrend(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(260)
        self._series: dict[int, deque[tuple[int, float]]] = {}
        self._seq = 0
        self._max_points = 1200

    def clear(self) -> None:
        self._series.clear()
        self._seq = 0
        self.update()

    def append_samples(self, samples) -> None:
        self._seq += 1
        for channel, reading in samples:
            if reading.ovld:
                continue
            series = self._series.setdefault(channel, deque())
            series.append((self._seq, reading.value))
            while len(series) > self._max_points:
                series.popleft()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        left, top, right, bottom = 66, 42, 18, 34
        plot_left = left
        plot_top = top
        plot_right = max(plot_left + 20, self.width() - right)
        plot_bottom = max(plot_top + 20, self.height() - bottom)

        painter.setPen(QPen(QColor("#d8dde5"), 1))
        for index in range(6):
            y = plot_top + (plot_bottom - plot_top) * index / 5
            painter.drawLine(plot_left, int(y), plot_right, int(y))
            x = plot_left + (plot_right - plot_left) * index / 5
            painter.drawLine(int(x), plot_top, int(x), plot_bottom)
        painter.setPen(QPen(QColor("#8b95a5"), 1))
        painter.drawRect(plot_left, plot_top, plot_right - plot_left, plot_bottom - plot_top)

        values = [
            value
            for series in self._series.values()
            for _, value in series
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

        seqs = [seq for series in self._series.values() for seq, _ in series]
        smin, smax = min(seqs), max(seqs)
        if smin == smax:
            smax = smin + 1

        def x_of(seq: int) -> float:
            return plot_left + (seq - smin) / (smax - smin) * (
                plot_right - plot_left
            )

        font = QFont("Consolas", 9)
        painter.setFont(font)
        painter.setPen(QColor("#5f6875"))
        for index in range(6):
            value = vmax - (vmax - vmin) * index / 5
            y = plot_top + (plot_bottom - plot_top) * index / 5
            painter.drawText(
                4, int(y) + 5, plot_left - 8, 18,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:.5g}",
            )
        painter.drawText(
            plot_left,
            plot_bottom + 12,
            "扫描点",
        )

        channels = sorted(self._series)
        legend_x = plot_left
        for index, channel in enumerate(channels[:6]):
            color = _COLORS[index % len(_COLORS)]
            painter.setPen(QPen(color, 2))
            painter.drawLine(legend_x, 14, legend_x + 18, 14)
            painter.setPen(QColor("#4b5563"))
            text = f"CH{channel}"
            painter.drawText(legend_x + 22, 19, text)
            legend_x += 90

        for index, channel in enumerate(channels):
            color = _COLORS[index % len(_COLORS)]
            painter.setPen(QPen(color, 1.6))
            points = [
                QPointF(x_of(seq), y_of(value))
                for seq, value in self._series[channel]
            ]
            if len(points) > 1:
                painter.drawPolyline(points)
            elif points:
                painter.drawPoint(points[0])
