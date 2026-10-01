"""回归基线：用 521 张真实谱面测试 vendored 时间模型。

基线（打补丁前）:  517 / 521 通过，4 张因 actions 缺 eventType 而 KeyError
基线（打补丁后）:  应为 521 / 521

如果这个数字掉了，说明 vendor 的 parser 被动过、或语料变了。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import verify  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

CORPUS_DEFAULT = CORPUS
EXPECT_MIN = 521


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else CORPUS_DEFAULT
    if not os.path.isdir(root):
        print(f"[SKIP] 语料目录不存在: {root}")
        return 0
    ok, total, fails = verify.corpus_smoke(root)
    print(f"[语料回归] 解析成功 {ok} / {total}")
    for p, e in fails[:10]:
        print("   FAIL", os.path.basename(p), "->", e)
    if total < EXPECT_MIN:
        print(f"[WARN] 语料比基线少（{total} < {EXPECT_MIN}），可能目录被移动过")
    good = (ok == total)
    print("=> " + ("PASS" if good else "FAIL"))
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
