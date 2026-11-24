"""自绘实时趋势图：时间窗、px 模式、悬停、框选统计、OVLD 断线。"""

from __future__ import annotations

import math
import time
from datetime import datetime

from PySide6.QtCore import QLineF, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from app.acquisition.ring_buffer import RingBuffer
from app.ui.widgets.common import format_measurement, plain_number

_LEFT = 76
_RIGHT = 16
_TOP = 12
_BOTTOM = 56
_NICE_STEPS = (1.0, 2.0, 5.0)


def _nice_step(value: float) -> float:
    """把任意间隔向上取到 1/2/5 × 10^n。"""

    if not math.isfinite(value) or value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10.0 ** exponent
    for multiplier in _NICE_STEPS:
        step = multiplier * base
        if value <= step * (1 + 1e-12):
            return step
    return 10.0 * base


class TrendChart(QWidget):
    selection_stats = Signal(object)
    hover_stats = Signal(str)

    def __init__(self, ring: RingBuffer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ring = ring
        self.unit = "V"
        self._display_scale = 1.0
        self.window_s = 10.0
        self._effective_span_s = 10.0
        self.all_time = False
        self.px_mode = False
        self._px_stretch = False
        self.ovld_visible = False
        self.paused = False
        self._overlay_rings: dict[int, RingBuffer] = {}
        self._primary_channel: int | None = None
        self._hover: QPoint | None = None
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None
        self._selection: tuple[float, float] | None = None
        self._frozen_samples: list[tuple[float, int, bool]] | None = None
        self._display_end_ns: int | None = None
        self._last_valid_samples: list[tuple[float, int, bool]] = []
        self.min_y_step = 0.0
        self._all_time_total = 0
        self._x_start = 0.0
        self._x_end = 1.0
        self.line_width = 2.0
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(50)
        self._redraw_timer.timeout.connect(self.update)
        self._x_count = 1
        self._plot = QRect()
        self.last_paint_ms = 0.0
        self.setMouseTracking(True)
        self.setMinimumHeight(220)

    def set_ring(self, ring: RingBuffer) -> None:
        self.ring = ring
        self._selection = None
        self._hover = None
        self._last_valid_samples = []
        self._display_end_ns = None
        self.update()

    def set_unit(self, unit: str) -> None:
        self.set_display_unit(unit, 1.0)

    @property
    def display_scale(self) -> float:
        return self._display_scale

    def set_display_unit(self, unit: str, scale: float) -> None:
        if not unit:
            return
        scale = scale if scale > 0 else 1.0
        if unit != self.unit or scale != self._display_scale:
            self.unit = unit
            self._display_scale = scale
            self._selection = None
            self.update()

    def set_time_window(self, seconds: float) -> None:
        self.window_s = max(0.5, seconds)
        self.all_time = False
        self._effective_span_s = _nice_step(self.window_s / 10.0) * 10.0
        self.update()

    def set_all_time(self, enabled: bool) -> None:
        self.all_time = enabled
        self._selection = None
        self.update()

    def set_px_mode(self, enabled: bool) -> None:
        self.px_mode = enabled
        self._selection = None
        self.update()

    def set_ovld_visible(self, enabled: bool) -> None:
        self.ovld_visible = enabled
        self.update()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if paused:
            # 冻结当前可见快照，鼠标悬停/框选仍可在冻结曲线上操作。
            self._frozen_samples = self._visible_samples()
        else:
            self._frozen_samples = None
            self.update()

    def set_min_y_step(self, value: float) -> None:
        value = max(0.0, float(value))
        if value != self.min_y_step:
            self.min_y_step = value
            self.update()

    def set_display_end_ns(self, timestamp_ns: int | None) -> None:
        self._display_end_ns = timestamp_ns

    def set_overlay_rings(
        self,
        rings: dict[int, RingBuffer],
        primary_channel: int | None = None,
    ) -> None:
        self._overlay_rings = dict(rings)
        self._primary_channel = primary_channel
        self.update()

    def set_line_width(self, width: float) -> None:
        self.line_width = max(1.0, min(4.0, float(width)))
        self.update()

    def notify_data(self) -> None:
        if self.paused:
            return
        # 30 Hz 采样时不要把每次数据都排进绘制队列；合并到最多约 20 fps。
        if not self._redraw_timer.isActive():
            self._redraw_timer.start()

    def clear_overlay(self) -> None:
        self._selection = None
        self._hover = None
        self._last_valid_samples = []
        self.selection_stats.emit(None)
        if self.paused:
            self._frozen_samples = []
        self.update()

    def _sample_width(self) -> int:
        return max(120, self.width() - _LEFT - _RIGHT)

    def _thin_for_render(
        self, samples: list[tuple[float, int, bool]]
    ) -> list[tuple[float, int, bool]]:
        """按像素桶保留首尾与极值，避免几万点逐条 drawLine 卡顿。"""

        limit = max(600, self._sample_width())
        if len(samples) <= limit:
            return samples
        bucket_size = max(1, math.ceil(len(samples) / limit))
        thinned: list[tuple[float, int, bool]] = []
        for start in range(0, len(samples), bucket_size):
            bucket = samples[start : start + bucket_size]
            if len(bucket) <= 2:
                thinned.extend(bucket)
                continue
            min_index = min(range(len(bucket)), key=lambda i: bucket[i][0])
            max_index = max(range(len(bucket)), key=lambda i: bucket[i][0])
            keep = sorted({0, min_index, max_index, len(bucket) - 1})
            thinned.extend(bucket[index] for index in keep)
        return thinned

    def _visible_samples(self) -> list[tuple[float, int, bool]]:
        if self._frozen_samples is not None:
            return self._frozen_samples
        if len(self.ring) == 0:
            return []
        latest = self.ring.latest()
        if latest is None:
            return []
        end_ns = latest[1]
        if self._display_end_ns is not None:
            end_ns = min(end_ns, self._display_end_ns)
        if self.px_mode:
            samples = self.ring.latest_n(min(len(self.ring), self._sample_width() * 2))
            samples = [sample for sample in samples if sample[1] <= end_ns]
            samples = samples[-self._sample_width() :]
        elif self.all_time:
            all_samples = [
                sample for sample in self.ring.iter_ordered() if sample[1] <= end_ns
            ]
            self._all_time_total = len(all_samples)
            # 全部时间可能包含几十万点；等间隔抽稀到屏幕可承受的点数，
            # 时间范围仍然是全部数据。
            limit = max(1200, self._sample_width() * 4)
            if len(all_samples) > limit:
                stride = max(1, len(all_samples) // limit)
                samples = all_samples[::stride]
                if samples[-1] != all_samples[-1]:
                    samples.append(all_samples[-1])
            else:
                samples = all_samples
        else:
            start_ns = end_ns - int(self._effective_span_s * 1_000_000_000)
            samples = self.ring.slice_by_time(start_ns, end_ns)
        if self.ovld_visible:
            return samples
        # 最新样本就是 OVLD：立即冻结在上一帧，窗口里的旧有效样本
        # 也不能继续向左消失。
        if samples and samples[-1][2]:
            return self._last_valid_samples
        valid = [sample for sample in samples if not sample[2]]
        if valid:
            self._last_valid_samples = valid
            return valid
        return self._last_valid_samples

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        paint_started = time.perf_counter()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.Mid)
        painter.fillRect(self.rect(), base)

        self._plot = QRect(
            _LEFT,
            _TOP,
            max(50, self.width() - _LEFT - _RIGHT),
            max(50, self.height() - _TOP - _BOTTOM),
        )
        samples = self._visible_samples()
        if not samples:
            # 空趋势图：只画网格，不显示“等待采集数据”占位文字。
            grid_pen = QPen(muted)
            grid_pen.setStyle(Qt.PenStyle.DotLine)
            grid_pen.setWidthF(1.0)
            grid_pen.setCosmetic(True)
            painter.setPen(grid_pen)
            for index in range(7):
                y = self._plot.top() + self._plot.height() * index / 6
                painter.drawLine(
                    self._plot.left(), int(y), self._plot.right(), int(y)
                )
            for index in range(11):
                x = self._plot.left() + self._plot.width() * index / 10
                painter.drawLine(
                    int(x), self._plot.top(), int(x), self._plot.bottom()
                )
            return

        render_samples = self._thin_for_render(samples)
        valid = [
            (v, ts)
            for v, ts, ovld in render_samples
            if not ovld and math.isfinite(v)
        ]
        data_min = min((v for v, _ in valid), default=0.0)
        data_max = max((v for v, _ in valid), default=1.0)
        # 扫描时其他通道可能和主通道量级不同，Y 轴必须把所有叠加
        # 通道一起纳入，否则黄色/绿色曲线会落到绘图区外看不见。
        for ring in self._overlay_rings.values():
            for value, _ts, ovld in ring.iter_ordered():
                if ovld or not math.isfinite(value):
                    continue
                data_min = min(data_min, value)
                data_max = max(data_max, value)
        if math.isclose(data_min, data_max):
            span = abs(data_min) * 0.02 or 1.0
            data_min -= span
            data_max += span

        # 纵向固定 6 格，步长取 1/2/5 × 10^n。
        y_step = _nice_step((data_max - data_min) / 6.0)
        if self.min_y_step > 0:
            # 每格至少覆盖 3 倍当前显示分辨率。
            y_step = max(y_step, _nice_step(self.min_y_step * 3.0))
        y_min = math.floor(data_min / y_step) * y_step
        y_max = y_min + 6.0 * y_step
        while y_max < data_max:
            y_min += y_step
            y_max += y_step

        if self.px_mode:
            # PX 模式原本是一点一像素；低采样率（34970A 1 Hz）会把曲线
            # 挤在右边。样本不足一屏时自动铺满宽度，34401A 高速数据不受影响。
            self._px_stretch = len(samples) <= max(2, self._plot.width())
            if self._px_stretch:
                x_start = 0.0
                x_end = 1.0
            else:
                x_start = float(
                    self._plot.right() - max(0, len(samples) - 1)
                )
                x_end = float(self._plot.right())
        else:
            x_end = float(samples[-1][1])
            if self.all_time:
                x_start = float(samples[0][1])
                self._effective_span_s = max(
                    0.5, (x_end - x_start) / 1_000_000_000
                )
            else:
                x_start = x_end - self._effective_span_s * 1_000_000_000
        self._x_start = x_start
        self._x_end = x_end
        self._x_count = len(samples)
        x_span = max(1.0, abs(x_end - x_start))
        y_span = max(1e-30, abs(y_max - y_min))

        def map_x(ts: int, index: int) -> float:
            if self.px_mode:
                if self._px_stretch:
                    return self._plot.left() + (
                        index / max(1, len(samples) - 1)
                    ) * self._plot.width()
                return float(self._plot.right() - (len(samples) - 1 - index))
            return self._plot.left() + ((ts - x_start) / x_span) * self._plot.width()

        def map_y(value: float) -> float:
            return self._plot.bottom() - ((value - y_min) / y_span) * self._plot.height()

        # 网格：横向 6 格、纵向 10 格；线宽 1px。
        grid_pen = QPen(muted)
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        grid_pen.setWidthF(1.0)
        grid_pen.setCosmetic(True)
        painter.setPen(grid_pen)
        for index in range(7):
            y = self._plot.top() + self._plot.height() * index / 6
            painter.drawLine(self._plot.left(), int(y), self._plot.right(), int(y))
            value = y_max - y_step * index
            if abs(value) < max(1e-15, abs(y_step) * 1e-6):
                value = 0.0
            axis_step = y_step / self._display_scale
            decimals = max(0, min(9, int(math.ceil(-math.log10(axis_step) - 1e-12))))
            painter.setPen(text)
            painter.setFont(QFont(self.font().family(), 8))
            painter.drawText(
                QRect(2, int(y) - 8, _LEFT - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                plain_number(value / self._display_scale, decimals),
            )
            painter.setPen(grid_pen)

        step_s = self._effective_span_s / 10.0
        for index in range(11):
            x = self._plot.left() + self._plot.width() * index / 10
            painter.drawLine(int(x), self._plot.top(), int(x), self._plot.bottom())
            if self.px_mode:
                if self._px_stretch:
                    sample_index = int(
                        round(index / 10 * max(0, len(samples) - 1))
                    )
                else:
                    sample_index = len(samples) - 1 - int(
                        round(self._plot.right() - x)
                    )
                label = str(sample_index + 1) if sample_index >= 0 else "—"
            else:
                ts = int(x_start + step_s * index * 1_000_000_000)
                moment = datetime.fromtimestamp(ts / 1e9)
                if step_s < 1:
                    label = moment.strftime("%H:%M:%S") + f".{moment.microsecond // 100000}"
                elif self._effective_span_s >= 3600:
                    label = moment.strftime("%H:%M")
                else:
                    label = moment.strftime("%H:%M:%S")
            painter.setPen(text)
            painter.setFont(QFont(self.font().family(), 8))
            label_x = max(0, min(self.width() - 68, int(x) - 34))
            painter.drawText(
                QRect(label_x, self._plot.bottom() + 6, 68, 18),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
            painter.setPen(grid_pen)

        # 曲线；OVLD 关闭时断线，开启时在顶部画红色标记。
        line_color = palette.color(QPalette.ColorRole.Highlight)
        line_pen = QPen(line_color)
        line_pen.setWidthF(self.line_width)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(line_pen)
        # 密集曲线关闭抗锯齿，并用每个像素列的 min/max 包络绘制。
        # 这样既保留尖峰，又不会让几万条线段逐条 drawLine 拖慢界面。
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if len(samples) > max(2000, self._plot.width() * 2):
            step = 2
            columns = max(1, (self._plot.width() + step - 1) // step)
            lows: list[float | None] = [None] * columns
            highs: list[float | None] = [None] * columns
            centers: list[QPointF | None] = [None] * columns
            for index, (value, ts, ovld) in enumerate(render_samples):
                if ovld or not math.isfinite(value):
                    continue
                column = (int(map_x(ts, index)) - self._plot.left()) // step
                if column < 0 or column >= columns:
                    continue
                y = map_y(value)
                low = lows[column]
                high = highs[column]
                if low is None or y > low:
                    lows[column] = y
                if high is None or y < high:
                    highs[column] = y
                centers[column] = QPointF(self._plot.left() + column * step, y)
            lines: list[QLineF] = []
            points: list[QPointF] = []
            for column in range(columns):
                low = lows[column]
                high = highs[column]
                if low is None or high is None:
                    continue
                x = self._plot.left() + column * step
                if abs(low - high) < 0.5:
                    points.append(QPointF(x, low))
                else:
                    lines.append(QLineF(x, high, x, low))
            if lines:
                painter.drawLines(lines)
            for point in points:
                painter.drawPoint(point)
            # 包络只画竖线时，相邻列的上升沿可能看起来断开；
            # 再用每列最后一个值连一条细折线，保证边沿连续。
            center_points = [point for point in centers if point is not None]
            if len(center_points) >= 2:
                painter.drawPolyline(QPolygonF(center_points))
        else:
            points: list[QPointF] = []
            plot_samples = render_samples
            for index, (value, ts, ovld) in enumerate(plot_samples):
                if ovld:
                    if len(points) >= 2:
                        painter.drawPolyline(QPolygonF(points))
                    points = []
                    if self.ovld_visible:
                        x = map_x(ts, index)
                        painter.fillRect(
                            int(x) - 2,
                            self._plot.top() + 2,
                            4,
                            5,
                            QColor("#dc2626"),
                        )
                    continue
                if not math.isfinite(value):
                    if len(points) >= 2:
                        painter.drawPolyline(QPolygonF(points))
                    points = []
                    continue
                points.append(QPointF(map_x(ts, index), map_y(value)))
                if index == len(plot_samples) - 1 or (
                    index + 1 < len(plot_samples) and plot_samples[index + 1][2]
                ):
                    if len(points) >= 2:
                        painter.drawPolyline(QPolygonF(points))
                    points = []
            if len(points) >= 2:
                painter.drawPolyline(QPolygonF(points))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 34970A 多通道叠加：主通道蓝色，其余黄/绿/粉。
        overlay_colors = (
            QColor("#eab308"),
            QColor("#16a34a"),
            QColor("#ec4899"),
        )
        overlay_index = 0
        for channel in sorted(self._overlay_rings):
            if channel == self._primary_channel:
                continue
            ring = self._overlay_rings[channel]
            if self.px_mode:
                overlay = list(ring.iter_ordered())[-max(1, len(samples)):]
                offset = max(0, len(samples) - len(overlay))
                overlay_points = [
                    QPointF(
                        map_x(0, offset + index),
                        map_y(value),
                    )
                    for index, (value, _ts, ovld) in enumerate(overlay)
                    if not ovld and math.isfinite(value)
                ]
            else:
                overlay = ring.slice_by_time(int(x_start), int(x_end))
                overlay_points = [
                    QPointF(map_x(ts, 0), map_y(value))
                    for value, ts, ovld in overlay
                    if not ovld and math.isfinite(value)
                ]
            color = overlay_colors[overlay_index % len(overlay_colors)]
            overlay_index += 1
            overlay_pen = QPen(color)
            overlay_pen.setWidthF(self.line_width)
            overlay_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            overlay_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(overlay_pen)
            if len(overlay_points) >= 2:
                painter.drawPolyline(QPolygonF(overlay_points))
            elif overlay_points:
                painter.drawPoint(overlay_points[0])

        # 框选：已完成的区间保持淡色，拖动中再画选框。
        if self._selection is not None:
            left = int(min(self._selection[0], self._selection[1]))
            right = int(max(self._selection[0], self._selection[1]))
            selected = QRect(left, self._plot.top(), right - left, self._plot.height())
            selected = selected.intersected(self._plot)
            painter.fillRect(selected, QColor(37, 99, 235, 30))
            painter.setPen(QPen(line_color, 1, Qt.PenStyle.DotLine))
            painter.drawRect(selected)
        if self._drag_start is not None and self._drag_current is not None:
            rect = QRect(self._drag_start, self._drag_current).normalized()
            rect = rect.intersected(self._plot)
            painter.fillRect(rect, QColor(37, 99, 235, 40))
            painter.setPen(QPen(line_color, 1, Qt.PenStyle.DashLine))
            painter.drawRect(rect)

        # 悬停十字线 + 浮层
        if self._hover is not None and self._plot.contains(self._hover) and self._drag_start is None:
            index = self._nearest_index(samples, self._hover.x())
            if index is not None:
                value, ts, ovld = samples[index]
                x = map_x(ts, index)
                y = map_y(value) if not ovld else self._plot.top() + 8
                cross_pen = QPen(muted, 1, Qt.PenStyle.DashLine)
                painter.setPen(cross_pen)
                painter.drawLine(int(x), self._plot.top(), int(x), self._plot.bottom())
                painter.drawLine(self._plot.left(), int(y), self._plot.right(), int(y))
                axis_step = y_step / self._display_scale
                hover_decimals = max(
                    3,
                    min(9, int(math.ceil(-math.log10(axis_step) - 1e-12))) + 2,
                )
                label = (
                    "OVLD"
                    if ovld
                    else (
                        f"{plain_number(value / self._display_scale, hover_decimals)} "
                        f"{self.unit}"
                    )
                )
                time_text = datetime.fromtimestamp(ts / 1e9).strftime("%H:%M:%S.%f")[:-3]
                text_line = f"{time_text}    {label}"
                metrics = QFontMetrics(self.font())
                box_width = metrics.horizontalAdvance(text_line) + 16
                box_height = metrics.height() + 8
                bx = int(x) + 10
                by = int(y) - box_height - 8
                if bx + box_width > self._plot.right():
                    bx = int(x) - box_width - 10
                if by < self._plot.top():
                    by = int(y) + 10
                box = QRect(bx, by, box_width, box_height)
                painter.fillRect(box, QColor(31, 41, 55, 220))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    box.adjusted(8, 4, -8, -4),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    text_line,
                )

        # 状态行放在图表底部左侧（红框位置），不再占用绘图区。
        painter.setPen(muted)
        painter.setFont(QFont(self.font().family(), 8))
        if self.px_mode:
            mode = f"px · {len(samples)} 样本"
        elif self.all_time:
            mode = f"全部时间 · {self._all_time_total} 样本"
        else:
            mode = f"时间窗 {self._effective_span_s:g} s"
        y_axis_step = y_step / self._display_scale
        y_decimals = max(
            0, min(9, int(math.ceil(-math.log10(y_axis_step) - 1e-12)))
        )
        y_div_text = f"{plain_number(y_axis_step, y_decimals)} {self.unit}/div"
        if self.px_mode:
            if self._px_stretch:
                per_div = max(1, round(len(samples) / 10))
            else:
                per_div = max(1, round(self._plot.width() / 10))
            x_div_text = f"{per_div} 样本/div"
        else:
            x_div_text = f"{plain_number(step_s, 3)} s/div"
        status = f"{y_div_text}    {mode} · {self.unit}    {x_div_text}"
        painter.drawText(
            QRect(
                8,
                self._plot.bottom() + 24,
                max(50, self.width() - 16),
                18,
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            status,
        )
        if self._overlay_rings:
            metrics = QFontMetrics(QFont(self.font().family(), 8))
            legend_x = 8 + metrics.horizontalAdvance(status) + 14
            legend_y = self._plot.bottom() + 33
            channels = []
            if self._primary_channel is not None:
                channels.append(self._primary_channel)
            channels.extend(
                channel
                for channel in sorted(self._overlay_rings)
                if channel != self._primary_channel
            )
            colors = [line_color, QColor("#eab308"), QColor("#16a34a"), QColor("#ec4899")]
            for index, channel in enumerate(channels):
                color = colors[min(index, len(colors) - 1)]
                text = f"CH{channel}"
                width = metrics.horizontalAdvance(text) + 22
                if legend_x + width > self.width() - 6:
                    break
                painter.setPen(QPen(color, 2))
                painter.drawLine(
                    int(legend_x), legend_y - 4, int(legend_x) + 12, legend_y - 4
                )
                painter.setPen(muted)
                painter.drawText(
                    int(legend_x) + 15,
                    legend_y,
                    text,
                )
                legend_x += width
        self.last_paint_ms = (time.perf_counter() - paint_started) * 1000.0

    def _nearest_index(self, samples: list[tuple[float, int, bool]], mouse_x: int) -> int | None:
        if not samples:
            return None
        if self.px_mode:
            if self._px_stretch:
                index = round(
                    (mouse_x - self._plot.left())
                    / max(1, self._plot.width())
                    * max(0, len(samples) - 1)
                )
                return max(0, min(len(samples) - 1, index))
            index = len(samples) - 1 - round(self._plot.right() - mouse_x)
            if index < 0:
                return None
            return min(len(samples) - 1, index)
        x_start = self._x_start
        x_end = self._x_end
        if x_end <= x_start:
            return 0
        target = x_start + (mouse_x - self._plot.left()) / max(1, self._plot.width()) * (
            x_end - x_start
        )
        low, high = 0, len(samples) - 1
        while low < high:
            mid = (low + high) // 2
            if samples[mid][1] < target:
                low = mid + 1
            else:
                high = mid
        if low > 0 and abs(samples[low - 1][1] - target) < abs(samples[low][1] - target):
            low -= 1
        return low

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt 命名
        pos = event.position().toPoint()
        if self._drag_start is not None:
            self._drag_current = pos
        if self._plot.contains(pos) or self._drag_start is not None:
            self._hover = pos
        else:
            self._hover = None
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton and self._plot.contains(
            event.position().toPoint()
        ):
            self._drag_start = event.position().toPoint()
            self._drag_current = self._drag_start
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt 命名
        if event.button() != Qt.MouseButton.LeftButton or self._drag_start is None:
            return
        start = self._drag_start
        end = event.position().toPoint()
        self._drag_start = None
        self._drag_current = None
        rect = QRect(start, end).normalized().intersected(self._plot)
        if rect.width() < 5:
            self._selection = None
            self.selection_stats.emit(None)
            self.update()
            return
        samples = self._visible_samples()
        if not samples:
            return
        if self.px_mode:
            indices = [
                self._nearest_index(samples, rect.left()),
                self._nearest_index(samples, rect.right()),
            ]
            if any(index is None for index in indices):
                return
            lo = min(indices)  # type: ignore[type-var]
            hi = max(indices)  # type: ignore[type-var]
            selected = samples[lo : hi + 1]
        else:
            left_index = self._nearest_index(samples, rect.left())
            right_index = self._nearest_index(samples, rect.right())
            if left_index is None or right_index is None:
                return
            t1 = samples[left_index][1]
            t2 = samples[right_index][1]
            selected = self.ring.slice_by_time(min(t1, t2), max(t1, t2))
        self._selection = (float(rect.left()), float(rect.right()))
        self.selection_stats.emit(self._format_stats(selected))
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover = None
        self.update()

    def _format_stats(self, samples: list[tuple[float, int, bool]]) -> dict:
        # 保留基本单位数值；界面按当前显示单位统一换算。
        values = [
            value
            for value, _, ovld in samples
            if not ovld and math.isfinite(value)
        ]
        ovld_count = sum(1 for _, _, ovld in samples if ovld)
        timestamps = [timestamp for _, timestamp, _ in samples]
        duration_s = (
            (max(timestamps) - min(timestamps)) / 1_000_000_000
            if len(timestamps) > 1
            else 0.0
        )
        if not values:
            return {
                "count": 0,
                "ovld": ovld_count,
                "minimum": None,
                "maximum": None,
                "average": None,
                "std": None,
                "peak_to_peak": None,
                "duration_s": duration_s,
            }
        count = len(values)
        average = sum(values) / count
        if count > 1:
            variance = sum((value - average) ** 2 for value in values) / (count - 1)
            std = math.sqrt(variance)
        else:
            std = 0.0
        return {
            "count": count,
            "ovld": ovld_count,
            "minimum": min(values),
            "maximum": max(values),
            "average": average,
            "std": std,
            "peak_to_peak": max(values) - min(values),
            "duration_s": duration_s,
        }
