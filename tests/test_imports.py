def test_main_window_module_imports() -> None:
    from app.ui.main_window import MainWindow

    assert MainWindow.__name__ == "MainWindow"
