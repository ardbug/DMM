from PySide6.QtWidgets import QApplication

from app.ui.sections.tool_panel import ToolPanel
from app.ui.widgets.collapsible import CollapsibleSection


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tool_panel_sections_are_collapsible() -> None:
    _app()
    panel = ToolPanel()
    assert [section.header.text() for section in panel.sections] == [
        "数据记录",
        "悬浮窗",
        "平均值",
        "2WΩ 软件蜂鸣",
    ]
    assert all(isinstance(section, CollapsibleSection) for section in panel.sections)

    for section in panel.sections:
        section.set_expanded(False)
        assert not section.body.isVisible()

    panel.sections[0].set_expanded(True)
    assert panel.sections[0].is_expanded()


def test_new_section_uses_collapsible_container() -> None:
    _app()
    panel = ToolPanel()
    section = panel.add_section("未来工具")
    assert isinstance(section, CollapsibleSection)
    assert panel.sections[-1] is section


def test_sections_move_up_and_down() -> None:
    _app()
    panel = ToolPanel()
    orders = []
    panel.section_order_changed.connect(orders.append)
    first = panel.sections[0]
    panel.move_section(first, 1)
    assert panel.sections[1] is first
    assert orders[-1] == [item.key for item in panel.sections]
    assert panel.sections[-1].down_btn.isEnabled() is False
    assert panel.sections[0].up_btn.isEnabled() is False


def test_section_order_is_restored() -> None:
    _app()
    panel = ToolPanel(section_order=["beep", "average", "csv", "floating"])
    assert [section.key for section in panel.sections] == [
        "beep",
        "average",
        "csv",
        "floating",
    ]
