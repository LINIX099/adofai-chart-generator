"""端到端：GUI 直接吃 OGG（不用 MIDI）。

    python tests/test_ogg_source.py [ogg]
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication          # noqa: E402

from ui.main_window import MainWindow               # noqa: E402

ogg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "samples", "audio", "FallenEra_MaySnow.ogg")

app = QApplication.instance() or QApplication([])
w = MainWindow()
w.load_midi(ogg)

assert w.midi is not None, "OGG 没加载成功"
print(f"[1] 加载      {os.path.basename(ogg)}")
print(f"    stats     {w.midi.stats()}")
print(f"[2] 音源      source_audio={w.source_audio}")

idx = w._selected_track_indexes() or [w._current_track()]
print(f"[3] 选中轨    {idx}  （音频源只有 1 条「音头轨」）")

w.build_onsets() if hasattr(w, "build_onsets") else None
print(f"[4] onset 数  {len(getattr(w, 'onsets', []) or [])}")

aud = w._audio_for_current()
print(f"[5] 预览音源  {aud}")
assert aud and os.path.exists(aud), "预览音源不可用"
assert os.path.abspath(aud) == os.path.abspath(ogg), \
    "音频源应当直接用原曲，而不是合成音色"

print("[6] 全部通过：OGG 可以直接进 GUI，导出时会带上原曲")
