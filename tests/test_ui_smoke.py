"""UI 冒烟测试（离屏）：构造窗口、加载样本、生成、三个视图各截一张图。

QT_QPA_PLATFORM=offscreen 下不会有窗口弹到你屏幕上。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from PySide6.QtCore import QTimer                                  # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

from ui.main_window import MainWindow                              # noqa: E402

OUT = os.path.join(_ROOT, "out", "_shots")
SAMPLES = os.path.join(_ROOT, "samples")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(1600, 950)
    w.show()

    def go():
        try:
            # 选一个样本，挑一条轨
            p = os.path.join(SAMPLES, "FallenEra.mid")
            w.load_midi(p)
            w.lst_tracks.setCurrentRow(0)
            w.sp_speed.setValue(120)
            w.rebuild()
            print("状态:", w.statusBar().currentMessage())
            app.processEvents()

            for i, name in enumerate(("roll", "path", "falling")):
                w.tabs.setCurrentIndex(i)
                app.processEvents()
                # 多取几个时间点，避免"恰好那 1.5 秒没有右半区音符"
                for t in (12000, 30000, 61000):
                    w.roll.set_playhead(t)
                    w.pathv.set_playhead_ms(t)
                    w.falling.set_time(t)
                    app.processEvents()
                f = os.path.join(OUT, f"{name}.png")
                w.grab().save(f)
                print("saved", f, os.path.getsize(f), "bytes")

            # 再测一下导出（不弹对话框，直接调 writer）
            import core.writer as writer
            from core import verify
            outdir = os.path.join(_ROOT, "out", "_smoke")
            tp = writer.write_dir(w.chart, outdir, name="main",
                                  song="smoke", artist="a", author="b",
                                  offset_ms=w.sp_offset.value())
            vr = verify.verify_file(tp, [o.t_ms for o in w.onsets], tol_ms=1.0)
            print("导出:", tp)
            print("校验:", vr.summary())
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            app.quit()

    QTimer.singleShot(300, go)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
