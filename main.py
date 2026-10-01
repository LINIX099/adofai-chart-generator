"""ADOFAI 谱面生成器 —— 入口。

用法:  python main.py
依赖:  PySide6, numpy （需自行安装）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QFont                                    # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

from ui.main_window import MainWindow                              # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
