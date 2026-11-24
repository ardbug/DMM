"""中下：实时趋势图与工具栏。"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.acquisition.ring_buffer import RingBuffer
from app.ui.widgets.themed_combo import ThemedComboBox
from app.ui.widgets.trend_chart import TrendChart


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TrendPanel(QFrame):
    clear_requested = Signal()
    save_requested = Signal()
    save_records_requested = Signal()
    record_requested = Signal()

    def __init__(self, ring: RingBuffer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TrendCard")
        self.setMinimumHeight(300)
        self._last_window_s = 10.0
        self._last_stats = None
        self._record_limit = 10
        self._current_function = ""
        self._function_rings: dict[str, RingBuffer] = {}
        self._display_count = 0
        self._target_count = 0
        self._last_batch_start_ns = 0
        self._session_start_ns: int | None = None
        self._session_end_ns: int | None = None
        self._selection_summary: dict | None = None
        self._full_scale = 0.0
        self._cv_mode = "mean"
        self._display_timer = QTimer(self)
        self._display_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._display_timer.setInterval(33)
        self._display_timer.timeout.connect(self._on_display_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title_label = QLabel("实时趋势", self)
        self.title_label.setObjectName("SectionTitle")
        header.addWidget(self.title_label)
        self.view_btn = QPushButton("记录列表", self)
        self.view_btn.setCheckable(True)
        self.view_btn.setToolTip("切换趋势图 / 记录列表")
        header.addWidget(self.view_btn)
        header.addStretch(1)

        self.window_combo = ThemedComboBox(self)
        for label, seconds in (
            ("5 s", 5.0),
            ("10 s", 10.0),
            ("30 s", 30.0),
            ("1 min", 60.0),
        ):
            self.window_combo.addItem(label, seconds)
        self.window_combo.addItem("PX 模式", "px")
        self.window_combo.addItem("ALL TIME", "all")
        self.window_combo.addItem("自定义…", "custom")
        self.window_combo.setCurrentIndex(self.window_combo.findData("px"))
        header.addWidget(self.window_combo)

        self.ovld_check = QCheckBox("OVLD 入图", self)
        self.pause_btn = QPushButton("暂停", self)
        self.pause_btn.setCheckable(True)
        self.clear_btn = QPushButton("清空", self)
        self.save_btn = QPushButton("另存为", self)
        for widget in (
            self.ovld_check,
            self.pause_btn,
            self.clear_btn,
            self.save_btn,
        ):
            header.addWidget(widget)
        self.record_limit_spin = QSpinBox(self)
        self.record_limit_spin.setRange(1, 1000)
        self.record_limit_spin.setValue(10)
        self.record_limit_spin.setSuffix(" 行")
        self.record_limit_spin.setToolTip("记录列表显示行数（1–1000）")
        self.record_limit_spin.setFixedWidth(90)
        self.record_limit_spin.valueChanged.connect(self.set_record_limit)
        header.insertWidget(header.indexOf(self.clear_btn), self.record_limit_spin)
        self.record_limit_spin.hide()
        root.addLayout(header)

        self.data_panel = QWidget(self)
        data_layout = QVBoxLayout(self.data_panel)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(4)
        self.stats_scope_label = QLabel("会话统计", self)
        self.stats_scope_label.setObjectName("Muted")
        data_layout.addWidget(self.stats_scope_label)

        self.metric_values: dict[str, QLabel] = {}
        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(24)
        metrics_grid.setVerticalSpacing(3)
        for index, (key, title) in enumerate(
            (
                ("minimum", "最小值："),
                ("average", "平均值："),
                ("maximum", "最大值："),
                ("cv", "离散系数："),
                ("peak_to_peak", "峰峰值："),
                ("std", "标准差："),
                ("count", "采样数："),
                ("duration", "采样时间："),
            )
        ):
            cell = QWidget(self.data_panel)
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)
            if key == "cv":
                title_label = ClickableLabel(title, cell)
                value_label = ClickableLabel("—", cell)
                title_label.clicked.connect(self._toggle_cv_mode)
                value_label.clicked.connect(self._toggle_cv_mode)
                title_label.setToolTip("点击切换 离散系数 / σ/满度")
                value_label.setToolTip("点击切换 离散系数 / σ/满度")
                title_label.setCursor(Qt.CursorShape.PointingHandCursor)
                value_label.setCursor(Qt.CursorShape.PointingHandCursor)
                self.cv_title_label = title_label
            else:
                title_label = QLabel(title, cell)
                value_label = QLabel("—", cell)
            title_label.setObjectName("Muted")
            title_label.setFont(QFont("Microsoft YaHei UI", 10))
            value_label.setObjectName("ValueLabel")
            value_label.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
            cell_layout.addWidget(title_label)
            cell_layout.addWidget(value_label)
            cell_layout.addStretch(1)
            metrics_grid.addWidget(cell, index // 4, index % 4)
            self.metric_values[key] = value_label
        for column in range(4):
            metrics_grid.setColumnStretch(column, 1)
        data_layout.addLayout(metrics_grid)
        root.addWidget(self.data_panel)

        self.chart = TrendChart(RingBuffer(200_000), self)
        self.view_stack = QStackedWidget(self)
        self.view_stack.addWidget(self.chart)

        self.record_page = QWidget(self)
        record_layout = QVBoxLayout(self.record_page)
        record_layout.setContentsMargins(8, 8, 8, 8)
        record_layout.setSpacing(6)
        self.record_table = QTableWidget(0, 5, self.record_page)
        self.record_table.setHorizontalHeaderLabels(
            ["序号", "时间", "读数", "备注（点击修改）", "参数"]
        )
        self.record_table.verticalHeader().setVisible(False)
        self.record_table.setAlternatingRowColors(True)
        self.record_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.record_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = self.record_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.record_table.cellClicked.connect(self._on_record_cell_clicked)
        record_layout.addWidget(self.record_table, 1)
        self.record_btn = QPushButton("记录当前值", self.record_page)
        self.record_btn.setToolTip("回车键：记录当前值")
        self.record_btn.clicked.connect(self.record_requested)
        record_layout.addWidget(self.record_btn)
        self.view_stack.addWidget(self.record_page)
        root.addWidget(self.view_stack, 1)
        self.set_record_limit(self._record_limit)

        self.window_combo.currentIndexChanged.connect(self._on_window_changed)
        self.ovld_check.toggled.connect(self.chart.set_ovld_visible)
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.chart.selection_stats.connect(self._on_selection_stats)
        self.view_btn.toggled.connect(self._on_view_toggled)
        self.chart.set_px_mode(self.window_combo.currentData() == "px")

    @property
    def record_view_active(self) -> bool:
        return self.view_btn.isChecked()

    def _on_view_toggled(self, record_view: bool) -> None:
        self.view_stack.setCurrentWidget(
            self.record_page if record_view else self.chart
        )
        self.title_label.setText("记录列表" if record_view else "实时趋势")
        self.view_btn.setText("趋势图" if record_view else "记录列表")
        for widget in (
            self.window_combo,
            self.ovld_check,
            self.pause_btn,
        ):
            widget.setVisible(not record_view)
        self.data_panel.setVisible(not record_view)
        self.record_limit_spin.setVisible(record_view)
        self.clear_btn.setText("清空记录" if record_view else "清空")
        self.save_btn.setText("保存记录" if record_view else "另存为")
        self.clear_btn.setToolTip(
            "清空记录列表" if record_view else "清空趋势数据和记录"
        )
        self.save_btn.setToolTip(
            "把记录列表保存为 CSV" if record_view else "趋势数据另存为 CSV"
        )

    def _on_clear_clicked(self) -> None:
        if self.record_view_active:
            self.clear_records()
        else:
            self.clear_requested.emit()

    def _on_save_clicked(self) -> None:
        if self.record_view_active:
            self.save_records_requested.emit()
        else:
            self.save_requested.emit()

    def _blank_record_row(self, row: int) -> None:
        values = (str(row + 1), "", "—", "", "")
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            if column == 3:
                flags |= Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)
            if column == 0:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter
                )
            self.record_table.setItem(row, column, item)

    def set_record_limit(self, limit: int) -> None:
        limit = max(1, min(1000, int(limit)))
        self._record_limit = limit
        while self.record_table.rowCount() > limit:
            self.record_table.removeRow(self.record_table.rowCount() - 1)
        while self.record_table.rowCount() < limit:
            row = self.record_table.rowCount()
            self.record_table.insertRow(row)
            self._blank_record_row(row)

    def clear_records(self) -> None:
        for row in range(self.record_table.rowCount()):
            self._blank_record_row(row)

    def records(self) -> list[tuple[str, str, str, str]]:
        result: list[tuple[str, str, str, str]] = []
        for row in range(self.record_table.rowCount()):
            value_item = self.record_table.item(row, 2)
            value = value_item.text().strip() if value_item is not None else ""
            if not value or value == "—":
                continue
            time_item = self.record_table.item(row, 1)
            note_item = self.record_table.item(row, 3)
            param_item = self.record_table.item(row, 4)
            result.append(
                (
                    time_item.text().strip() if time_item is not None else "",
                    value,
                    note_item.text().strip() if note_item is not None else "",
                    param_item.text().strip() if param_item is not None else "",
                )
            )
        return result

    def add_record(self, text: str, parameter: str = "") -> None:
        value = text.strip()
        if not value:
            return
        self.record_table.insertRow(0)
        self._blank_record_row(0)
        self.record_table.item(0, 1).setText(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self.record_table.item(0, 2).setText(value)
        self.record_table.item(0, 4).setText(parameter.strip())
        if self.record_table.rowCount() > self._record_limit:
            self.record_table.removeRow(self.record_table.rowCount() - 1)
        for row in range(self.record_table.rowCount()):
            number = self.record_table.item(row, 0)
            if number is not None:
                number.setText(str(row + 1))

    def _on_record_cell_clicked(self, row: int, column: int) -> None:
        if column == 3:
            item = self.record_table.item(row, column)
            if item is not None:
                self.record_table.editItem(item)

    def _on_window_changed(self, index: int) -> None:
        data = self.window_combo.itemData(index)
        if data == "px":
            self.chart.set_all_time(False)
            self.chart.set_px_mode(True)
            return
        self.chart.set_px_mode(False)
        if data == "all":
            self.chart.set_all_time(True)
            return
        if data == "custom":
            seconds, ok = QInputDialog.getDouble(
                self,
                "自定义时间窗",
                "时间窗（秒，0.5–3600）：",
                self._last_window_s,
                0.5,
                3600.0,
                1,
            )
            if not ok:
                index = self.window_combo.findData(self._last_window_s)
                if index >= 0:
                    self.window_combo.blockSignals(True)
                    self.window_combo.setCurrentIndex(index)
                    self.window_combo.blockSignals(False)
                return
            self._last_window_s = seconds
        else:
            self._last_window_s = float(data)
        self.chart.set_time_window(self._last_window_s)

    def _on_pause_toggled(self, paused: bool) -> None:
        self.pause_btn.setText("继续" if paused else "暂停")
        self.chart.set_paused(paused)

    def set_measurement_state(self, state: str) -> None:
        if state == "ready":
            self.record_btn.setText("单次读数")
            self.record_btn.setToolTip("单次读数并记录到列表")
            self.record_btn.setEnabled(True)
        elif state == "reading":
            self.record_btn.setText("正在读数…")
            self.record_btn.setToolTip("正在等待单次读数")
            self.record_btn.setEnabled(False)
        elif state == "acquiring":
            self.record_btn.setText("记录当前值")
            self.record_btn.setToolTip("记录当前显示值")
            self.record_btn.setEnabled(True)
        else:
            self.record_btn.setText("记录当前值")
            self.record_btn.setToolTip("串口就绪后才能记录")
            self.record_btn.setEnabled(False)

    def set_function(self, function_label: str) -> None:
        if not function_label:
            return
        if function_label == self._current_function and self.chart.ring is not None:
            return
        ring = self._function_rings.setdefault(
            function_label, RingBuffer(200_000)
        )
        self._current_function = function_label
        self._display_timer.stop()
        self._display_count = len(ring)
        self._target_count = len(ring)
        self._last_batch_start_ns = 0
        self._session_start_ns = None
        self._session_end_ns = None
        self.chart.set_ring(ring)
        latest = ring.latest()
        self.chart.set_display_end_ns(latest[1] if latest else None)
        self._selection_summary = None
        self._render_current_stats()
        self.chart.notify_data()

    def set_display_interval_ms(self, interval_ms: float) -> None:
        interval = max(10, int(round(interval_ms)))
        if interval != self._display_timer.interval():
            self._display_timer.setInterval(interval)

    def notify_data(self, batch=None) -> None:
        if batch is not None and batch.readings:
            label = batch.readings[0].function_label
            ring = self._function_rings.setdefault(label, RingBuffer(200_000))
            ring.append_batch(batch)
            if label != self._current_function or self.chart.ring is not ring:
                self.set_function(label)
            if self._session_start_ns is None:
                self._session_start_ns = batch.readings[0].timestamp_ns
            self._session_end_ns = batch.readings[-1].timestamp_ns
            if self._selection_summary is None:
                self._render_current_stats()
        if batch is not None:
            if len(batch.readings) > 1:
                deltas = [
                    (b.timestamp_ns - a.timestamp_ns) / 1_000_000
                    for a, b in zip(batch.readings, batch.readings[1:])
                ]
                deltas = [delta for delta in deltas if delta > 0]
                if deltas:
                    deltas.sort()
                    self.set_display_interval_ms(deltas[len(deltas) // 2])
            elif self._last_batch_start_ns:
                interval = (batch.start_ns - self._last_batch_start_ns) / 1_000_000
                if interval > 0:
                    self.set_display_interval_ms(interval)
            self._last_batch_start_ns = batch.start_ns
        self._target_count = len(self.chart.ring)
        if batch is not None and len(batch.readings) == 1:
            # 逐条轮询时不需要显示游标等待；样本一到就画，避免固定
            # 一个采样周期的图延迟。批量回退路径才使用游标。
            self._display_timer.stop()
            self._display_count = self._target_count
            self.chart.set_display_end_ns(batch.readings[-1].timestamp_ns)
            self.chart.notify_data()
            return
        if self._display_count > self._target_count:
            self._display_count = self._target_count
        if self._display_count < self._target_count:
            if not self._display_timer.isActive():
                self._display_timer.start()
        else:
            self.chart.notify_data()

    def _on_display_tick(self) -> None:
        if self._display_count >= self._target_count:
            self._display_timer.stop()
            return
        self._display_count += 1
        timestamp = self.chart.ring.timestamp_at(self._display_count - 1)
        self.chart.set_display_end_ns(timestamp)
        self.chart.notify_data()
        if self._display_count >= self._target_count:
            self._display_timer.stop()

    def reset_display_pacing(self) -> None:
        self._display_timer.stop()
        self._display_count = 0
        self._target_count = 0
        self._last_batch_start_ns = 0
        self.chart.set_display_end_ns(None)

    def set_unit(self, unit: str) -> None:
        self.chart.set_unit(unit)
        self._render_current_stats()

    def set_display_unit(self, unit: str, scale: float) -> None:
        self.chart.set_display_unit(unit, scale)
        self._render_current_stats()

    def set_min_y_step(self, value: float) -> None:
        self.chart.set_min_y_step(value)

    def set_overlay_rings(
        self,
        rings: dict[int, "RingBuffer"],
        primary_channel: int | None = None,
    ) -> None:
        """34970A 扫描时叠加其他通道，单通道时传空字典。"""
        self.chart.set_overlay_rings(rings, primary_channel)

    def set_stats(self, snapshot) -> None:
        self._last_stats = snapshot
        if self._selection_summary is None:
            self._render_current_stats()

    def set_full_scale(self, full_scale: float) -> None:
        self._full_scale = max(0.0, float(full_scale))
        if self._cv_mode == "full_scale":
            self._render_current_stats()

    def _toggle_cv_mode(self) -> None:
        self._cv_mode = (
            "full_scale" if self._cv_mode == "mean" else "mean"
        )
        self._render_current_stats()

    def _on_selection_stats(self, summary: dict | None) -> None:
        self._selection_summary = summary
        self._render_current_stats()

    def _render_current_stats(self) -> None:
        if self._selection_summary is not None:
            scale = self.chart.display_scale
            summary = dict(self._selection_summary)
            for key in ("minimum", "maximum", "average", "std", "peak_to_peak"):
                value = summary.get(key)
                summary[key] = None if value is None else value / scale
            self._render_metrics(summary, "框选统计")
            return
        snapshot = self._last_stats
        if snapshot is None or getattr(snapshot, "count", 0) == 0:
            self.stats_scope_label.setText("会话统计")
            self._set_metrics(None)
            return
        scale = self.chart.display_scale
        summary = {
            "minimum": snapshot.minimum / scale,
            "maximum": snapshot.maximum / scale,
            "average": snapshot.average / scale,
            "std": snapshot.std / scale,
            "peak_to_peak": snapshot.peak_to_peak / scale,
            "count": snapshot.count,
            "ovld": snapshot.ovld,
            "duration_s": (
                (self._session_end_ns - self._session_start_ns) / 1_000_000_000
                if self._session_start_ns is not None
                and self._session_end_ns is not None
                else None
            ),
        }
        self._render_metrics(summary, "会话统计")

    @staticmethod
    def _format_duration(seconds) -> str:
        if seconds is None:
            return "—"
        total = max(0, int(round(float(seconds))))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"

    @staticmethod
    def _format_metric(value, decimals: int) -> str:
        if value is None:
            return "—"
        value = float(value)
        if abs(value) < 0.5 * 10 ** (-decimals):
            value = 0.0
        return f"{value:,.{decimals}f}"

    def _set_metrics(self, summary: dict | None) -> None:
        self.cv_title_label.setText(
            "σ/满度：" if self._cv_mode == "full_scale" else "离散系数："
        )
        if summary is None:
            for label in self.metric_values.values():
                label.setText("—")
            return
        self.metric_values["minimum"].setText(
            self._format_metric(summary.get("minimum"), 6)
        )
        self.metric_values["average"].setText(
            self._format_metric(summary.get("average"), 7)
        )
        self.metric_values["maximum"].setText(
            self._format_metric(summary.get("maximum"), 6)
        )
        self.metric_values["peak_to_peak"].setText(
            self._format_metric(summary.get("peak_to_peak"), 6)
        )
        self.metric_values["std"].setText(
            self._format_metric(summary.get("std"), 7)
        )
        average = summary.get("average")
        std = summary.get("std")
        denominator = (
            self._full_scale / self.chart.display_scale
            if self._cv_mode == "full_scale"
            else (abs(float(average)) if average is not None else 0.0)
        )
        if std is None or denominator < 1e-15:
            self.metric_values["cv"].setText("—")
        else:
            cv_ppm = abs(float(std) / denominator) * 1e6
            if cv_ppm > 999.999:
                percent = cv_ppm / 10_000
                if percent > 999_999:
                    self.metric_values["cv"].setText("OVERFLOW")
                elif percent < 1_000:
                    self.metric_values["cv"].setText(f"{percent:.3f}%")
                elif percent < 10_000:
                    self.metric_values["cv"].setText(f"{percent:.2f}%")
                else:
                    self.metric_values["cv"].setText(f"{percent:.1f}%")
            else:
                self.metric_values["cv"].setText(f"{cv_ppm:.3f} ppm")
        duration = summary.get("duration_s")
        self.metric_values["duration"].setText(
            self._format_duration(duration)
        )
        count = summary.get("count")
        self.metric_values["count"].setText(
            f"{int(count):,}" if count is not None else "—"
        )

    def _render_metrics(self, summary: dict, scope: str) -> None:
        ovld = int(summary.get("ovld") or 0)
        self.stats_scope_label.setText(
            f"{scope}（OVLD {ovld}）" if ovld else scope
        )
        self._set_metrics(summary)

    def clear_view(self) -> None:
        self._function_rings.clear()
        self._current_function = ""
        self._last_stats = None
        self._selection_summary = None
        self._session_start_ns = None
        self._session_end_ns = None
        self.chart.set_ring(RingBuffer(200_000))
        self.reset_display_pacing()
        self.chart.clear_overlay()
        self.stats_scope_label.setText("会话统计")
        self._set_metrics(None)
