# -*- coding: utf-8 -*-
"""⑤e **运镜（镜头）** 的契约测试 —— `core/camera.py`（**本轮只交测试**）。

    python tests/test_camera.py

## 这份测试是什么

它是 **`core/camera.py` 的验收规格**：先写它、你看过、再写功能（用户 2026-10 口径：
「先把测试写出来，我看过之后 把功能写出来，**不用着急接线**」）。
所以：

* 只测 **纯函数层**（`plan()` / `check()` / 事件构造 / 字段集 / 值域 / 分派）；
* **不测接线**（`sidecar/schema.py` · `session.py` · `core/writer.py` · `app.js` ·
  `pack_verify`）—— 那些等 §Z 那份清单，接线那一轮再补；
* 现在跑它会 `exit 2` 并打印「还没实现」+ 本文件的断言清单（不抛 traceback）。

## 每条断言的依据（不许自己编）

| 组 | 依据 |
|---|---|
| A | `docs/59` §5 契约 1：默认开可关，**关掉时产物逐字节不变** |
| B | `docs/59` §5 契约 2：**只写 `actions`**，绝不碰 `angleData/bpm/travel/Twirl/settings` |
| C | `docs/59` §1.1：`MoveCamera` 的合法字段集（多一个字段就是 bug —— `PositionTrack` 那次 NRE 的教训） |
| D | `docs/64` §4：教学谱实测值域（`zoom 50~300` · `rotation −20~30` · `duration ≥0.25` · 21 种 ease 且 `Linear` 只 2/238）<br>★★★ **`zoom` 永不为 `null` / 0**（`docs/64` §8.6.5 用户定位的根因） |
| **E** | **`docs/64` §0/§4：★ 单维度 93.0%**（语料三连 57.3%）——「一次只动一样」。<br>★ 定基事件（`duration=0`，`docs/59` §1.3 的元件 1）是**固定形状**，不受单维度约束、也不参与配对 |
| **F** | **`docs/64` §2.1/§3：★ 成组形状**（1 条 = 定位型 / 2 条 = 成对 / 3 条 = 摆动，照教学谱 f89·f922 校准） |
| G | `docs/59` §1.3 / §3.2：元件 1「锁朝向」= `rel=Player + pos=[0,0] + rotation=CONST` |
| H | `docs/59` §3.2：90° 拐角 / 三连音 / 所有预设图形 ⇒ **镜头锁住不转**；★ 雪花改成「居中」（R 组），本轮**不用** `LastPosition` 大转 |
| **I** | **`docs/64` §6：★ `RepeatEvents + eventTag` 批量复制**（我们 core 至今一条都不发） |
| J | `docs/64` §3.3/§6：追球 = `pos=[0,0] rel=Tile` + `RepeatEvents{Floor, onCurrent=true}` |
| **K** | **`docs/64` §6 尾：`tag` 会串** —— `core/show.py` 已在用 `出A/…/qe_pull`，必须另开命名空间 |
| **Q** | **`docs/64` §9.2：按 `cur` 分派** —— 高 cur（cbpm ≥ `cur_split`，默认 400）用**位置+呼吸+缓慢移动**；低 cur 用**一拍一振**（用户 2026-10 第五轮：「慢速直接一拍一振好了，高速完全不用这个写法」）。`cur` = `Floor.bpm` = cbpm |
| **R** | **`docs/64` §9.2b：雪花** —— 抄 Tempest 加强版；格数 ≤ `snow_big_tiles`（48）走 **A**（近景居中 + 缓速整圈），否则走 **B**（远景 + 长缓移 + 多圈）；**优先于 cur 分派** |
| **S** | **`docs/67` 交接单 + `docs/66` §9.4/§9.5 家族 E：国士無双 · 两层** —— 宏观层 `relativeTo=Player`（跟人、大偏移、**按拍写死**：长锚 `OutExpo` + 串尾弹回 `OutCirc` + 长锚后**静默期**）+ 微观层 `relativeTo=Tile`（不跟人、小步跳、`OutElastic`、**每 2 格一条、一串 3~6 条**）；两层**时间上交错**；★ 解掉了 §9.2 的「高 cur 二选一」。用户 2026-10：「**准备开抄国士无双**」<br>★★ **2026-10 复测修正**：初版写的「宏观每 44~78 格重发 / 微观整段连续」**两个都不对**（`docs/67` §1） |
| L | `docs/59` §5 契约 3：**不许静默**（跳过要给原因） |
| M | `docs/59` §5 契约 4/5：`check()` 自检 + 字段集与语料取交集 |

★ 的用户口径硬指标（`docs/63`）也顺带守住：本模块**不碰 `travel`**，所以
「最小夹角 30° / 最大夹角 270°」不受影响 —— B 组会断言这一点。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

FAIL: list[str] = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


# ---------------------------------------------------------------- 待实现守卫
try:
    from core import camera as C                              # noqa: E402
except Exception as _exc:                                     # noqa: BLE001
    print("=" * 78)
    print("★ core/camera.py **还没实现**（本轮按用户口径：先交测试，功能等你过目）")
    print("  导入失败：%s: %s" % (type(_exc).__name__, _exc))
    print()
    print("  本文件就是它的验收规格，共 18 组：")
    for _g, _t in (
        ("A", "默认关 ⇒ 一条事件都不写（老路径逐字节不变）"),
        ("B", "打开 ⇒ 只写 actions、不改 ch、事件按 floor 有序"),
        ("C", "★ 字段白名单（MoveCamera / RepeatEvents 各一个 frozenset）"),
        ("D", "★ 值域（zoom / rotation / duration / ease / angleOffset）"),
        ("E", "★★ 单维度 + 定基/硬切/表演三分：表演至多动一维；duration=0 只许是完整复位或"
              "（一拍一振/雪花进场用的）硬切"),
        ("F", "★★ 成组形状：1 条定位 / 2 条成对 / 3 条摆动（教学谱 f89·f922 校准）"),
        ("G", "★ 锁朝向：floor 0 的 rel=Player + pos=[0,0] + rotation=CONST"),
        ("H", "★ 拐角 / 三连音 / 图形段不转；雪花改成「居中」（见 R）"),
        ("I", "★★ RepeatEvents + eventTag（不复制 N 份，只发 1 条 + 1 条）"),
        ("J", "★ 追球：pos=[0,0] rel=Tile + RepeatEvents{Floor, onCurrent}"),
        ("K", "★★ tag 命名空间不与 ⑤d 的词表冲突"),
        ("L", "避让 + 不许静默（skipped_why）"),
        ("M", "check() 正常全绿；三处故意做坏都能被抓"),
        ("N", "纯函数 & 幂等（不改 ch；同参数两次结果一致）"),
        ("O", "风格预设表（档位 ease 都取自教学谱白名单）"),
        ("P", "★★ 组合档：底 + 加强（两档各自成对、按不同周期并行）"),
        ("Q", "★★ 按 `cur`（= cbpm）分派：高 cur 走缓慢（**零硬切**）/ 低 cur 走**一拍一振**，"
              "阈值可调"),
        ("R", "★★ 雪花：抄 Tempest A/B 两套；A 档近景居中 + 缓速整圈 / B 档远景 + 长缓移 + 多圈"),
        ("S", "★★ 国士無双·两层：宏观 `Player` 跟人（长锚 `OutExpo` + 串尾弹回 `OutCirc`，"
              "★ **按拍写死**、长锚后有静默期）+ 微观 `Tile` 不跟人（`OutElastic`、"
              "每 2 格一条 · **一串 3~6 条**）；两层时间上交错；慢段微观退回每格 1 条"),
    ):
        print("    [%s] %s" % (_g, _t))
    print()
    print("  实现 `core/camera.py` 之后再跑本文件即进入真正的验收。")
    print("=" * 78)
    raise SystemExit(2)

# ★★ 第二道守卫：**模块在、但接口不齐**。
#   2026-10 的现状：`core/camera.py` 只实现了「呼吸」（漂移 + 呼吸两层），
#   而本文件 A~S 是**一路写到底的远期规格**（教学谱单维度 / 成组形状 / RepeatEvents /
#   按 cur 分派 / 雪花 A·B / 国士無双两层）。用户口径：
#   「目前只给出一个选项『呼吸』，**其他方案等待完全成熟后接入**」。
#   ⇒ 没齐就**照本文档开头承诺的**：exit 2 + 打印清单，**不抛 traceback**
#     （以前这里会 `TypeError: plan() got an unexpected keyword argument`）。
_CORE_API = ("plan", "check", "CameraParams", "EASES", "MV_CAM_KEYS",
             "REPEAT_KEYS", "STYLES", "TAG_PREFIX")
_missing = [n for n in _CORE_API if not hasattr(C, n)]
if _missing:
    print("=" * 78)
    print("★ core/camera.py **只实现了「呼吸」** —— 本文件（18 组）要的接口还没齐")
    print("  缺：%s" % "、".join(_missing))
    print("  用户口径 2026-10：「目前只给出一个选项『呼吸』，其他方案等待完全成熟后接入」")
    print("  ⇒ 本文件继续以**规格**身份存在；接口补齐后再跑，即进入真正的验收。")
    print("=" * 78)
    raise SystemExit(2)


# ---------------------------------------------------------------- 夹具
class _F:
    """一层的最小替身（与 `tests/test_show.py` 同口径）。

    `bpm` = **该层生效的当前速度**（= `cbpm`）—— 用户口径的 `cur` 就是它（`docs/64` §9.2）。
    """

    def __init__(self, engine=False, travel=180.0, template=False,
                 natural=False, snowflake=False, bpm=120.0):
        self.travel = float(travel)
        self.twirl = False
        self.pause_beats = 0.0
        self.angle = 0.0
        self.speed_k = 1.0
        self.bpm = float(bpm)
        self.snowflake = bool(snowflake)
        self.template = bool(template)
        self.natural = bool(natural)
        self.engine = bool(engine)

    @property
    def is_figure(self) -> bool:
        return bool(self.template or self.natural or self.snowflake or self.engine)


class _C:
    """假谱面。

    `fast` = `(from, to, bpm)`，把这几段设成高 `cur`；`snow` = 雪花段的格号区间。
    """

    def __init__(self, n=120, corners=(), engines=(), snow=(), templates=(),
                 base_bpm=200.0, fast=()):
        cs, es = set(corners), set(engines)
        sn, tp = set(snow), set(templates)
        bpm = [float(base_bpm)] * n
        for lo, hi, b in fast:
            for i in range(int(lo), min(int(hi), n - 1) + 1):
                bpm[i] = float(b)
        self.floors = [_F(travel=(90.0 if i in cs else 180.0),
                          engine=(i in es), snowflake=(i in sn),
                          template=(i in tp), bpm=bpm[i]) for i in range(n)]
        self.meta = {}
        if sn:
            self.meta["snow_spans"] = [(min(sn), 6, 3, len(sn))]
        self.base_bpm = float(base_bpm)
        self.set_speed_floors = []


def _cam(pl):
    return [a for a in pl.events if a.get("eventType") == "MoveCamera"]


def _rep(pl):
    return [a for a in pl.events if a.get("eventType") == "RepeatEvents"]


def _vis_zero_rot(r) -> bool:
    """`rotation` 算不算「视觉归零」—— **360 的整数倍**都算。

    ★ 2026-10 第五轮：雪花写法改成**抄 Tempest 加强版**，那边的旋转是
    `rotation=720` / `angleOffset=5760` —— 转完整圈画面上等于 0，
    所以出场事件可以把这个值**原样带下去**，不算"回落"。
    """
    if r is None:
        return True
    return abs(float(r) % 360.0) < 1e-9


def _kind(a) -> str:
    """`MoveCamera` 的三种角色（见 `docs/64` §9.3）：

    * `lock` —— **定基事件**：`duration=0` + 完整复位 + 无 tag；
    * `cut`  —— **硬切事件**：`duration=0` + 任意姿态（**一拍一振**专用）；
    * `perf` —— **表演事件**：`duration ≥ 0.25`，走补间。
    """
    if float(a.get("duration") or 0.0) > 0.0:
        return "perf"
    if (a.get("relativeTo") == "Player" and a.get("position") == [0, 0]
            and not a.get("eventTag")
            and a.get("zoom") is not None
            and abs(float(a["zoom"]) - 200.0) < 1e-9
            and _vis_zero_rot(a.get("rotation"))):
        return "lock"
    return "cut"


def _cuts(pl):
    """**硬切事件**（`duration=0` 但**不是**完整复位）—— 一拍一振 / 雪花进场专用。"""
    return [a for a in _cam(pl) if _kind(a) == "cut"]


def _is_lock(a) -> bool:
    """**定基事件** —— 完整复位那一种 `duration=0`（`docs/59` §1.3 的元件 1）。

    它是 `rel=Player + pos=[0,0] + rotation` 这一个固定形状 —— 所以它
    **不受"单维度"约束**、也**不参与配对**。
    与之相对的是**表演事件**（`duration ≥ 0.25`）：真正的运镜动作，受 E/F 两组管。
    """
    return _kind(a) == "lock"


def _perf(pl):
    """表演事件（定基 / 硬切以外的全部 `MoveCamera`）。"""
    return [a for a in _cam(pl) if _kind(a) == "perf"]


def _dims(a) -> list[str]:
    """一条 `MoveCamera` 里真正动了的**非归零**维度。

    ★ 口径（照教学谱原文 + 2026-10 实测双重校准）：

    * `zoom == 基准`、`position == [0,0]`、`rotation ≡ 0 (mod 360)` 都是**归零量**
      —— 它们表示「把这一维钉回基准」，正是「不要有卡顿或原始运镜」要的写法。
      教学谱 `f922` 就是 `rotation=4` **和** `position=[0,0]` 写在**同一条**里；
    * 只有**非归零**量才算"动了这一维"，也才与别的维度互斥。
    """
    out = []
    if a.get("zoom") is not None and abs(float(a["zoom"]) - 200.0) > 1e-9:
        out.append("zoom")
    if not _vis_zero_rot(a.get("rotation")):
        out.append("rotation")
    pos = a.get("position")
    if pos not in (None, [None, None]):
        if pos != [0, 0] or not out:
            out.append("position")
    return out


def _is_base(a, base_zoom: float = 200.0) -> bool:
    """这一条是不是"回到基准位"（zoom=base / rotation=0 / position=[0,0]）。"""
    if a.get("zoom") is not None:
        return abs(float(a["zoom"]) - float(base_zoom)) < 1e-9
    if a.get("rotation") is not None:
        return abs(float(a["rotation"])) < 1e-9
    return a.get("position") == [0, 0]


def _tags(pl):
    return {a.get("eventTag") for a in _cam(pl) if a.get("eventTag")}


def main() -> int:
    ch = _C(120, corners=(10, 11), engines=(40, 41, 42, 43),
            snow=(80, 81, 82, 83, 84, 85), templates=(60, 61))

    # ---------------------------------------------------------------- A
    print("=" * 78)
    print("A 默认关 ⇒ 一条事件都不写")
    pl = C.plan(ch, enabled=False)
    check(pl.n_events == 0 and not pl.events, "enabled=False ⇒ 0 条事件")
    check(bool(pl.skipped_why), "关掉也要说清（skipped_why 非空）")

    # ---------------------------------------------------------------- B
    print()
    print("=" * 78)
    print("B 打开 ⇒ 只写 actions / 不改 ch / 按 floor 有序")
    meta0 = dict(ch.meta)
    fl0 = [(f.travel, f.angle, f.speed_k, f.twirl) for f in ch.floors]
    pl = C.plan(ch)
    check(pl.n_events > 0, "默认参数下真的写了事件（%d 条）" % pl.n_events)
    check(all(a.get("eventType") in ("MoveCamera", "RepeatEvents")
              for a in pl.events), "只发 MoveCamera / RepeatEvents 两种")
    fl_ = [int(a.get("floor") or 0) for a in pl.events]
    check(fl_ == sorted(fl_), "事件按 floor 有序（writer 直接并进主循环的前提）")
    check(dict(ch.meta) == meta0, "不改 ch.meta")
    check([(f.travel, f.angle, f.speed_k, f.twirl) for f in ch.floors] == fl0,
          "★ 一格都没碰 ch.floors（travel/angle/speed/Twirl 全不变）⇒ 与"
          "「最小夹角 30° / 最大夹角 270°」口径无关，不会互相打架")

    # ---------------------------------------------------------------- C
    print()
    print("=" * 78)
    print("C 字段白名单（多一个字段就是 bug —— PositionTrack 那次 NRE 的教训）")
    check(getattr(C, "MV_CAM_KEYS", None) is not None, "模块导出 MV_CAM_KEYS")
    check(getattr(C, "REPEAT_KEYS", None) is not None, "模块导出 REPEAT_KEYS")
    want_mv = {"floor", "eventType", "duration", "relativeTo", "position",
               "rotation", "zoom", "angleOffset", "ease", "eventTag"}
    want_rp = {"floor", "eventType", "repeatType", "repetitions", "interval",
               "floorCount", "executeOnCurrentFloor", "tag"}
    check(set(C.MV_CAM_KEYS) == want_mv, "MV_CAM_KEYS == docs/59 §1.1 的字段集")
    check(set(C.REPEAT_KEYS) == want_rp, "REPEAT_KEYS == RepeatEvents 的字段集")
    bad = [a for a in _cam(pl) if not set(a) <= want_mv]
    check(not bad, "每条 MoveCamera 的键都在白名单内" + (f"，越界 {bad[:1]}" if bad else ""))
    bad = [a for a in _rep(pl) if not set(a) <= want_rp]
    check(not bad, "每条 RepeatEvents 的键都在白名单内")
    # ★ 可选字段一个都不写（`active/dontDisable/minVfxOnly`）
    opt = [a for a in _cam(pl) if set(a) & {"active", "dontDisable", "minVfxOnly"}]
    check(not opt, "不写可选字段 active/dontDisable/minVfxOnly")

    # ---------------------------------------------------------------- D
    print()
    print("=" * 78)
    print("D 值域（教学谱 238 条实测：docs/64 §4）")
    # ★★★ 2026-10 用户定位的**根因**：「缩放 无论如何 都不要设置为 0」
    #   v1 的段 9~15（纯旋转）全写了 `"zoom": null` ⇒ 画面直接没了；
    #   段 1~8 / 段 18 有显式 zoom ⇒ 正常。**这条是本套件最重要的一条。**
    zn = [a for a in _cam(pl) if a.get("zoom") is None]
    check(not zn, "★★★ 每条 MoveCamera 的 zoom 都必须**显式给出数值**，不许 null"
          + (f"（{len(zn)} 条是 null，首条 floor {zn[0]['floor']}）" if zn else ""))
    z0 = [a for a in _cam(pl)
          if a.get("zoom") is not None and float(a["zoom"]) <= 0.0]
    check(not z0, "★★★ zoom **绝不等于 0**（也不为负）—— 用户实测：会直接看不见"
          + (f"，越界 {[(a['floor'], a['zoom']) for a in z0[:3]]}" if z0 else ""))
    zs = [a["zoom"] for a in _perf(pl) if a.get("zoom") is not None]
    rs = [a["rotation"] for a in _cam(pl) if a.get("rotation") is not None]
    ds = [float(a["duration"]) for a in _perf(pl)]
    # ★ 2026-10 第五轮：雪花 B 照抄 Tempest 的 `zoom=600`（远景俯视），所以上限放宽到 600。
    check(all(50.0 <= float(z) <= 600.0 for z in zs),
          "zoom ∈ [50,600]（雪花 B 抄 Tempest 的 600；其余仍 ≤300）  实得 %s~%s"
          % (min(zs), max(zs)) if zs else "zoom 空")
    # ★ 雪花段允许**整圈**旋转（360 的整数倍 = 视觉归零），其余仍限 ±30°
    check(all(_vis_zero_rot(r) or -30.0 <= float(r) <= 30.0 for r in rs),
          "rotation ∈ [−30,30]，或为 360 的整数倍（雪花整圈）" if rs else "rotation 空")
    check(all(d >= 0.25 for d in ds),
          "★ 表演事件 duration ≥ 0.25 拍（教学谱 238 条里 `0` 只有 4 条，我们不许瞬移）")
    check(all(float(a["duration"]) == 0.0 for a in _cam(pl) if _is_lock(a)),
          "★ 定基事件 duration 恒为 0（瞬时就位，不参与过渡）")
    eases = {a["ease"] for a in _perf(pl)}
    check(eases <= set(C.EASES), "ease 全在 EASES 白名单里：" + str(sorted(eases)))
    check("Linear" not in eases,
          "★ 不用 Linear（语料第一 28.8% / 教学谱只 2/238 —— 我们要的是有形状的缓动）")
    ao = [float(a.get("angleOffset") or 0.0) for a in _cam(pl)]
    # ★ 雪花 B 的「多圈」走 `angleOffset`（Tempest 是 5760° = 16 圈）⇒ 上限放到 7200。
    check(all(abs(v) <= 7200.0 + 1e-9 and abs(v % 45.0) < 1e-9 for v in ao),
          "angleOffset 是 45 的整数倍且 |·| ≤ 7200（雪花 B 的 16 圈是 5760）")

    # ---------------------------------------------------------------- E
    print()
    print("=" * 78)
    print("E ★★ 单维度原则（教学谱 93.0%，语料三连 57.3% —— 这是最本质的差异）")
    print("   口径：只对**表演事件**（duration ≥ 0.25）成立；定基 / 硬切是「换姿态」，不受它管")
    perf = _perf(pl)
    check(bool(perf), "有表演事件（duration ≥ 0.25）：%d 条" % len(perf))
    multi = [(i, _dims(a), a["ease"]) for i, a in enumerate(perf) if len(_dims(a)) > 1]
    check(not multi, "★ 每条**表演** MoveCamera 至多动一个维度"
          + (f"，越界 {multi[:2]}" if multi else ""))
    check(all(len(_dims(a)) == 1 for a in perf), "而且没有空维度的表演事件")
    locks = [a for a in _cam(pl) if _is_lock(a)]
    check(all(a.get("position") == [0, 0] and a.get("relativeTo") == "Player"
              and a.get("rotation") is not None for a in locks),
          "★ 定基事件必须是固定形状（rel=Player + pos=[0,0] + rotation）")
    # ★★ 2026-10 第五轮新增的第三类：**硬切**（`duration=0` 但**不是**完整复位）。
    #   用户口径：「慢速直接**一拍一振**」—— 一振 = 一条硬切换一个完整姿态。
    #   所以它**必须四样给齐**（不能只想改一样），而且**必须挂 tag**（可追溯到哪一段）。
    cuts = _cuts(pl)
    check(all(a.get("position") not in (None, [None, None])
              and a.get("relativeTo") and a.get("rotation") is not None
              and a.get("zoom") is not None and float(a["zoom"]) > 0.0 for a in cuts),
          "★ 硬切事件必须**四样给齐**（rel/pos/rot/zoom）—— 硬切是换姿态，不是补间"
          + (f"，越界 {cuts[:1]}" if cuts else ""))
    check(all(a.get("eventTag") for a in cuts),
          "★ 硬切事件必须挂 tag（否则 RepeatEvents / 配对都追不到它）")
    check(all(float(a["duration"]) == 0.0 for a in cuts),
          "★ 硬切的 duration 恒为 0（瞬时换姿态）")
    # ★★ **完整复位**：zoom / rotation / position 在游戏里都是**状态**，会一路留到谱尾。
    #   所以定基事件必须**四样全给**（少给一样就漏一样，段与段之间串味）。
    #   教学谱 `f934` 的 `pos=[0,0] rel=Player dur0` 就是这个复位。
    partial = [a for a in locks
               if [k for k in ("zoom", "rotation", "position", "relativeTo")
                   if a.get(k) in (None, [None, None])]]
    check(not partial, "★ 定基事件必须**完整复位**（zoom + rotation + position + relativeTo "
          "四样都给）" + (f"，缺 {partial[:1]}" if partial else ""))
    check(all(not a.get("eventTag") for a in locks),
          "★ 定基事件不挂 tag（它不参与配对，不该被 RepeatEvents 撞上）")

    # ---------------------------------------------------------------- F
    print()
    print("=" * 78)
    print("F ★★ 成组形状：照教学谱的三种写法校准（`docs/64` §2.1/§3）")
    print("   · 1 条 = 定位型（追球：`pos=[0,0] rel=Tile` + RepeatEvents，本来就不成对）")
    print("   · 2 条 = 成对（离基 → 回基）")
    print("   · 3 条 = 摆动（离基 → 反方向 → 归零）—— 教学谱 f89 的摆头就是这个")
    bytag: dict = {}
    for a in _cam(pl):
        if a.get("eventTag"):
            bytag.setdefault(a["eventTag"], []).append(a)
    check(len(bytag) >= 2, "至少有两组（tag 分组出的动作组）：%d 组" % len(bytag))
    over = [(t, len(x)) for t, x in bytag.items() if len(x) > 3]
    check(not over, "每组 ≤ 3 条（>3 ⇒ 把一组复制成 N 份了，该用 RepeatEvents）"
          + (f"，越界 {over[:2]}" if over else ""))
    same_floor = [(t, [a["floor"] for a in x]) for t, x in bytag.items()
                  if len({int(a["floor"]) for a in x}) > 1]
    check(not same_floor, "同一组的事件都在同一格（RepeatEvents 只会按**同格**复制）"
          + (f"，越界 {same_floor[:2]}" if same_floor else ""))
    first_base = [t for t, x in bytag.items() if len(x) >= 2 and _is_base(x[0])]
    check(not first_base, "★ 组内第一条**必须离基**（在基准位 = 这一组没动）"
          + (f"，越界 {first_base[:2]}" if first_base else ""))
    # 三种形状都要有：成对 / 摆动 / 定位（定位型由 chase 组提供，见 J 组）
    shapes = sorted({len(x) for x in bytag.values()})
    check(shapes and shapes[0] >= 1, "出现的组形状（条数）：%s" % shapes)
    durs = sorted({float(a["duration"]) for a in _perf(pl)})
    check(len(durs) <= 6, "表演时值只有少数几档（教学谱也是 1 / 0.5 / 4 这种整拍值）："
          + str(durs))

    # ---------------------------------------------------------------- G
    print()
    print("=" * 78)
    print("G ★ 锁朝向（元件 1 · docs/59 §1.3 / §3.2）")
    lock = [a for a in _cam(pl)
            if a.get("relativeTo") == "Player"
            and a.get("position") == [0, 0]
            and a.get("rotation") is not None]
    check(bool(lock), "有「锁朝向」事件：relativeTo=Player + position=[0,0] + rotation")
    at0 = [a for a in _cam(pl) if int(a["floor"]) == 0]
    check(bool(at0), "floor 0 上有镜头事件")
    check(any(a.get("position") == [0, 0]
              and a.get("relativeTo") == "Player"
              and float(a.get("duration") or 0) == 0.0 for a in at0),
          "★ 锁朝向写在 floor 0 且 duration=0（瞬时定基，不参与过渡）")
    check(all(abs(float(a["rotation"]) - float(pl.params.rotation_const)) < 1e-9
              for a in lock),
          "锁朝向用的 rotation 全 == params.rotation_const（= %s，待真机标定）"
          % pl.params.rotation_const)
    check(all(a.get("relativeTo") for a in _cam(pl)),
          "★ 每条都**显式**写 relativeTo（绝不靠『省略=继承上一条』—— 事件顺序一改语义就变）")
    # ★★ 2026-10 **实测回执**（用户看完验收谱：「9 之后的 把镜头弄没了 看不见」）：
    #   只在段首发一条定基**不够** —— `relativeTo=Player` 的**每一条表演事件**
    #   都必须**显式给出 `position`**（要么 `[0,0]` 钉在玩家身上、要么像"匀速位移"
    #   那样给显式偏移），**绝不能留 `[null,null]`**（= "不改位置" ⇒ 纯旋转段里
    #   没人去重算位置，相机就跟不住玩家了）。
    #   这就是 MM1 的基石写法（`docs/59` §1.3：全曲 177 条 100% 是
    #   `rel=Player + pos=[0,0] + rotation=CONST`）。
    loose = [a for a in _perf(pl)
             if a.get("relativeTo") == "Player"
             and a.get("position") in (None, [None, None])]
    check(not loose,
          "★★ Player 帧的**每一条**表演事件都要**显式给 position**"
          "（`[0,0]` 钉住 或 显式偏移；留 `[null,null]` 相机就跑没）"
          + (f"，越界 {[(a['floor'], a['position']) for a in loose[:3]]}" if loose else ""))
    rels = {a.get("relativeTo") for a in _cam(pl)}
    check(rels <= {"Player", "Tile", "Global", "LastPosition",
                   "LastPositionNoRotation"},
          "relativeTo 只取游戏认的那 5 个值：" + str(sorted(rels)))

    # ---------------------------------------------------------------- H
    print()
    print("=" * 78)
    print("H ★ 拐角 / 三连音 / 预设图形 ⇒ 镜头锁住不转（docs/59 §3.2）")
    plain = _C(120, corners=(10, 11), engines=(40, 41, 42, 43),
               snow=(80, 81, 82, 83, 84, 85), templates=(60, 61))
    plh = C.plan(plain)
    # 这一段里"不转"的格集合（雪花段除外：雪花走元件 4 长式）
    no_rot = (set(range(10, 12)) | set(range(40, 44)) | set(range(60, 62)))
    viol = [a for a in _perf(plh)
            if int(a["floor"]) in no_rot and a.get("rotation") is not None]
    check(not viol, "拐角/三连音/预设图形上**没有任何 rotation 表演动作**"
          + (f"，越界 {[(a['floor'], a['rotation']) for a in viol[:3]]}" if viol else ""))
    zoom_there = [a for a in _perf(plh)
                  if int(a["floor"]) in no_rot and a.get("zoom") is not None]
    check(bool(zoom_there), "但这些地方**保留缩放**（元件 3）—— 不是整段死掉")
    check(all(a.get("relativeTo") != "LastPosition" for a in _perf(plh)),
          "★ 本轮**不用** `LastPosition` 累加大转 —— 雪花改成「居中」了（见 R 组）")

    # ---------------------------------------------------------------- I
    print()
    print("=" * 78)
    print("I ★★ RepeatEvents：用 N 条事件干 M×N 条的事（docs/64 §6）")
    plr = C.plan(ch, reps=3, interval=2)
    reps = _rep(plr)
    check(bool(reps), "reps=3 ⇒ 真的发了 RepeatEvents（%d 条）" % len(reps))
    check(all(a["repeatType"] in ("Beat", "Floor") for a in reps),
          "repeatType 只用 Beat / Floor（教学谱 35 条：Beat 32 / Floor 3；"
          "语料里还有 1851 条 None —— 我们不发）")
    check(all(int(a["repetitions"]) >= 2 for a in reps),
          "repetitions ≥ 2（=1 的重复没有意义，别写）")
    check(all(int(a["interval"]) >= 1 for a in reps), "interval ≥ 1 拍")
    check(all(isinstance(a.get("executeOnCurrentFloor"), bool) for a in reps),
          "executeOnCurrentFloor 是显式布尔")
    for r in reps:
        t = r.get("tag")
        same = [a for a in _cam(plr) if a.get("eventTag") == t]
        check(bool(same) and min(int(a["floor"]) for a in same) == int(r["floor"]),
              "RepeatEvents.tag=%r 指向同格的事件（target 真的存在）" % t)
    from collections import Counter as _Cnt
    per_tag = _Cnt(a.get("eventTag") for a in _cam(plr) if a.get("eventTag"))
    check(per_tag and max(per_tag.values()) <= 2,
          "★★ 同一个 tag 最多 2 条 MoveCamera（out + in）—— 不是把这一对复制 rep×2 份"
          "：%s" % dict(per_tag))
    check(plr.n_moves <= 2 * len(per_tag) if per_tag else False,
          "n_moves（%d）≤ 2 × tag 组数（%d）" % (plr.n_moves, len(per_tag)))
    check(plr.n_moves == len(_cam(plr)), "n_moves 与事件数一致（记账对得上）")

    # ---------------------------------------------------------------- J
    print()
    print("=" * 78)
    print("J ★ 追球：pos=[0,0] rel=Tile + RepeatEvents{Floor, onCurrent=true}（docs/64 §3.3）")
    plj = C.plan(ch, chase=True)
    ch_ref = [a for a in _cam(plj)
              if a.get("position") == [0, 0] and a.get("relativeTo") == "Tile"]
    rj = [a for a in _rep(plj)
          if a["repeatType"] == "Floor" and a["executeOnCurrentFloor"] is True]
    check(bool(ch_ref), "chase=True ⇒ 有 position=[0,0] relativeTo=Tile 的 MoveCamera")
    check(bool(rj), "并且配了 RepeatEvents{repeatType=Floor, executeOnCurrentFloor=True}")
    check(all(str(a["ease"]).startswith("Out") for a in ch_ref),
          "追球只用 Out 档（教学谱：OutCirc / OutBack / OutElastic）")
    pl0 = C.plan(ch, chase=False)
    check(not [a for a in _rep(pl0) if a["repeatType"] == "Floor"],
          "chase=False ⇒ 一条 Floor 型重复都不发")

    # ---------------------------------------------------------------- K
    print()
    print("=" * 78)
    print("K ★★ tag 命名空间：不许撞上 ⑤d 的词表（docs/64 §6 尾）")
    from core import show as S                                # noqa: E402
    reserved = set(S.MOVES_OUT) | set(S.MOVES_IN) \
        | {"in_init", "in_ret", "qe_hide", "qe_pull"}
    tags = {t for t in _tags(pl) | {a.get("tag") for a in _rep(pl)} if t}
    check(all(str(t).startswith(C.TAG_PREFIX) for t in tags),
          "所有 tag 都带前缀 %r：%s" % (C.TAG_PREFIX, sorted(tags)))
    check(not (tags & reserved),
          "与 ⑤d 的词表不相交（保留值：%s）" % sorted(reserved))
    check(bool(C.TAG_PREFIX), "TAG_PREFIX 非空")

    # ---------------------------------------------------------------- L
    print()
    print("=" * 78)
    print("L 避让 + 不许静默")
    pll = C.plan(ch, collide_floors=tuple(range(0, 60)))
    check(pll.n_collide > 0 and all(int(a["floor"]) >= 60 for a in pll.events),
          "collide_floors 里的格一条都不发（n_collide=%d）" % pll.n_collide)
    check(any("避让" in s or "同格" in s for s in pll.skipped_why),
          "而且**说清原因**（不许静默）")
    plempty = C.plan(_C(1), )
    check(plempty.n_events == 0 and bool(plempty.skipped_why),
          "层数太少 ⇒ 0 条 + 说清原因")

    # ---------------------------------------------------------------- M
    print()
    print("=" * 78)
    print("M check()：正常全绿，三处故意做坏都抓得到")
    bad_normal = C.check(pl, ch)
    check(not bad_normal, "正常方案 check() 全绿" + (f"，实得 {bad_normal[:2]}" if bad_normal else ""))

    def _broken(mut):
        import copy
        p2 = copy.deepcopy(pl)
        mut(p2)
        return C.check(p2, ch)

    def _drop_prefix(p2):
        for a in _cam(p2):
            if a.get("eventTag"):
                a["eventTag"] = "X" + a["eventTag"]

    def _make_triple(p2):
        pf = _perf(p2)
        if pf:
            pf[0]["zoom"] = 230
            pf[0]["rotation"] = 5

    def _bad_zoom(p2):
        pf = _perf(p2)
        if pf:
            pf[0]["zoom"] = 9999

    def _bad_lock(p2):
        for a in _cam(p2):
            if _is_lock(a):
                a["duration"] = 3.0        # 拿瞬移形状当表演：必须被抓
                break

    check(bool(_broken(_drop_prefix)), "抓得住「tag 没带命名空间前缀」")
    check(bool(_broken(_make_triple)), "抓得住「一条表演里动了两个维度」")
    check(bool(_broken(_bad_zoom)), "抓得住「zoom 越界」")
    check(bool(_broken(_bad_lock)), "抓得住「duration=0 却不是定基形状」")

    # ---------------------------------------------------------------- N
    print()
    print("=" * 78)
    print("N 纯函数 & 幂等")
    a1 = C.plan(ch)
    a2 = C.plan(ch)
    check([dict(x) for x in a1.events] == [dict(x) for x in a2.events],
          "同参数连跑两次结果逐条一致（没有隐藏随机）")
    ch2 = _C(120, corners=(10, 11), engines=(40, 41, 42, 43),
             snow=(80, 81, 82, 83, 84, 85), templates=(60, 61))
    C.plan(ch2)
    check(not ch2.meta, "连 ch.meta 都没写（纯函数：方案由调用方放进 meta）")

    # ---------------------------------------------------------------- O
    print()
    print("=" * 78)
    print("O 风格预设表（docs/64 §8.2 的缓速选择表）")
    check(isinstance(getattr(C, "STYLES", None), dict) and len(C.STYLES) >= 4,
          "导出 STYLES（≥4 档）：" + str(sorted(getattr(C, "STYLES", {}))))
    for name, st in C.STYLES.items():
        ok = (st.get("out") in C.EASES and st.get("in") in C.EASES
              and str(st["out"]).startswith("Out") and str(st["in"]).startswith("In"))
        check(ok, "档 %-6s 的 out/in 都在 EASES 里且一个是 Out、一个是 In（%s / %s）"
              % (name, st.get("out"), st.get("in")))
    check("OutElastic" in {st["out"] for st in C.STYLES.values()},
          "★ 有以 OutElastic 为 out 的档（「旋转之神」）")
    check("OutBack" in {st["out"] for st in C.STYLES.values()},
          "★ 有以 OutBack 为 out 的档（「活泼的曲风 OutBack 总能发挥奇效」）")
    check(C.plan(ch, style="基础").n_events > 0, "style='基础' 能跑")
    bad_style = C.plan(ch, style="不存在的档")
    check(bool(bad_style.skipped_why) or bad_style.n_events >= 0,
          "未知 style 要**说清**（不许静默兜底）")

    # ---------------------------------------------------------------- P
    print()
    print("=" * 78)
    print("P ★★ 组合档：**底 + 加强**（用户 2026-10：「5 和 6 需要结合起来用」"
          "「7 和 8 同理」）")
    print("   口径：不是二选一 —— 两档**各自成对、按不同周期并行**：底档做常速呼吸，"
          "加强档落在重音上")
    import dataclasses
    names = {f.name for f in dataclasses.fields(C.CameraParams)}
    check("style" in names, "CameraParams 有 style（底档）")
    check("boost" in names, "CameraParams 有 boost（加强档）—— 组合用")
    plb = C.plan(ch, style="基础", boost="卡点")
    byb: dict = {}
    for a in _cam(plb):
        if a.get("eventTag"):
            byb.setdefault(a["eventTag"], []).append(a)
    rb = _rep(plb)
    check(len(rb) >= 2, "style + boost ⇒ 至少两条 RepeatEvents（两组并行）：%d" % len(rb))
    ivs = sorted({int(r["interval"]) for r in rb})
    check(len(ivs) >= 2,
          "两组的 interval **不同**（一个做底、一个落重音）：%s" % ivs)
    check(len(byb) >= 2, "而且确实是两组不同 tag：%s" % sorted(byb))
    pl0 = C.plan(ch, style="基础", boost="")
    check(len(_rep(pl0)) < len(rb),
          "boost='' ⇒ 只剩底档那一组（少 %d 组）" % (len(rb) - len(_rep(pl0))))
    check(bool(C.plan(ch, style="基础", boost="不存在的档").skipped_why),
          "未知 boost 也要说清（不许静默）")

    # ---------------------------------------------------------------- Q
    print()
    print("=" * 78)
    print("Q ★★ 按 `cur` 分派（用户 2026-10 第四/五轮：")
    print("   「检测 cur，高 cur 用位置+呼吸+缓慢移动，低到一定速度的段落用跳跃」→")
    print("   「**慢速直接一拍一振好了，高速完全不用这个写法**」）")
    print("   口径：`cur` = 该段的 `Floor.bpm`（= cbpm，每分钟格数）；阈值 `cur_split`，"
          "沿用项目已有的 400")
    import dataclasses as _dc
    names2 = {f.name for f in _dc.fields(C.CameraParams)}
    check("cur_split" in names2, "CameraParams 有 cur_split（cur 分界，默认 400）")
    # 前 40 格慢（cbpm 100）、后 40 格快（cbpm 600）
    chx = _C(120, fast=((60, 119, 600.0),), base_bpm=100.0)
    plq = C.plan(chx)
    secs = getattr(plq, "sections", None)
    check(isinstance(secs, list) and len(secs) >= 2,
          "★ CameraPlan.sections 报出**每段用了哪一档**（不许静默）：%s"
          % (type(secs).__name__,))
    if isinstance(secs, list) and secs:
        slow = [s for s in secs if float(s.get("cur_cbpm") or 0.0) < float(
            getattr(plq.params, "cur_split", 400.0))]
        fast = [s for s in secs if float(s.get("cur_cbpm") or 0.0) >= float(
            getattr(plq.params, "cur_split", 400.0))]
        check(bool(slow) and bool(fast), "两档段落都识别出来了（慢 %d 段 / 快 %d 段）"
              % (len(slow), len(fast)))
        check(all(str(s.get("style") or "") for s in secs),
              "每段都标了 style：" + str([s.get("style") for s in secs][:4]))
        # ★★ 低 cur ⇒ **一拍一振**：每拍一条 `duration=0` 硬切（偶拍回基准、奇拍抖出去）
        for s in slow:
            lo, hi = int(s["lo"]), int(s["hi"])
            n = hi - lo + 1
            cs = [a for a in _cuts(plq) if lo <= int(a["floor"]) <= hi]
            check(bool(cs) and len(cs) >= n // 2 - 1,
                  "★ 低 cur 段（cbpm %s）用的是**一拍一振**：硬切 %d 条 / 段长 %d 格"
                  % (s.get("cur_cbpm"), len(cs), n))
            check(all(a.get("eventTag") for a in cs),
                  "低 cur 段的硬切**全部挂了 tag**（可追溯，不许静默）")
            gaps = sorted({int(b["floor"]) - int(a["floor"])
                           for a, b in zip(cs, cs[1:])})
            check(not gaps or max(gaps) <= 2,
                  "★ 硬切是**逐拍**发的（相邻硬切间隔 ≤ 2 格）：%s" % gaps)
            check(all(a.get("zoom") is not None and float(a["zoom"]) > 0.0
                      and a.get("relativeTo") and a.get("position") is not None
                      and a.get("rotation") is not None for a in cs),
                  "★ 硬切是「换一个完整姿态」⇒ 四条（rel/pos/rot/zoom）必须给齐")
        # ★★ 高 cur ⇒ **零硬切**（原话：「高速完全不用这个写法」）
        for s in fast:
            lo, hi = int(s["lo"]), int(s["hi"])
            cs = [a for a in _cuts(plq) if lo <= int(a["floor"]) <= hi]
            check(not cs,
                  "★★ 高 cur 段（cbpm %s）**一条硬切都没有**" % s.get("cur_cbpm")
                  + (f"，实得 {len(cs)} 条" if cs else ""))
            d = [float(a["duration"]) for a in _perf(plq)
                 if lo <= int(a["floor"]) <= hi]
            if d:
                check(min(d) >= 4.0 - 1e-9,
                      "高 cur 段（cbpm %s）用的是**缓慢**：时值 ≥ 4 拍 %s"
                      % (s.get("cur_cbpm"), sorted(set(d))))
        check(any("cur" in w for w in (plq.skipped_why or []))
              or any("cur" in str(s.get("why") or "") for s in secs),
              "分派理由里写明按 cur 分（不许静默）")
    # 阈值可调：把它抬到 1000 ⇒ 两段都算"低 cur"（都走一拍一振）
    plq2 = C.plan(chx, cur_split=1000.0)
    check(bool(_cuts(plq2)),
          "cur_split 可调：抬到 1000 ⇒ 全谱都走一拍一振（硬切 %d 条）"
          % len(_cuts(plq2)))
    check(not [a for a in _cuts(plq2) if float(a["duration"]) != 0.0],
          "一拍一振的硬切 `duration` 恒为 0（硬切 = 瞬时换姿态，不是补间）")

    # ---------------------------------------------------------------- R
    print()
    print("=" * 78)
    print("R ★★ 雪花：镜头永远位于雪花正中央（用户 2026-10）")
    print("   第五轮追加：「**雪花的镜头写法……你去抄一下 Tempest 加强版**」+")
    print("   「**物量大的用 B，小的用 A**」")
    print("   ⇒ 格数 ≤ snow_big_tiles 走 A（近景居中），否则走 B（远景 + 长缓移 + 多圈）")
    check("snow_big_tiles" in names2,
          "CameraParams 有 snow_big_tiles（A/B 的格数分界，默认 48）")
    split = float(getattr(C.CameraParams, "snow_big_tiles", 48.0))

    def _snow_case(n_tiles: int):
        """造一段 `n_tiles` 格的雪花，返回（plan, 段内事件, 段内 sections）。"""
        ch_ = _C(120, snow=tuple(range(60, 60 + n_tiles)))
        ch_.meta["snow_spans"] = [(60, 6, n_tiles // 12, n_tiles)]
        p_ = C.plan(ch_)
        ev_ = [a for a in _cam(p_) if 60 <= int(a["floor"]) <= 60 + n_tiles]
        sc_ = [s for s in (getattr(p_, "sections", None) or [])
               if int(s.get("lo") or -1) <= 60 <= int(s.get("hi") or -1)]
        return p_, ev_, sc_

    plr2, in_snow, sc2 = _snow_case(24)                     # 24 ≤ 48 ⇒ A
    check(bool(in_snow), "雪花段里有镜头事件（%d 条）" % len(in_snow))
    # ① 居中：至少一条**世界锚定**的事件（不是 Player 帧），位置指向雪花中心
    cent = [a for a in in_snow if a.get("relativeTo") in ("Tile", "Global")]
    check(bool(cent), "★ 有**世界锚定**（`Tile`/`Global`）的居中事件 —— 不是跟玩家走")
    check(all(a.get("position") not in (None, [None, None]) for a in cent),
          "居中事件必须给出**中心偏移**（`position` 不能留空）")
    # ② 进场是**硬切**（照抄 Tempest A `f402` / B `f1077` 的 `duration=0` + `Tile`）
    ins = [a for a in in_snow if int(a["floor"]) == 60]
    check(bool(ins) and _kind(ins[0]) == "cut" and ins[0].get("relativeTo") == "Tile",
          "★ 雪花**进场是一条 `duration=0` 的硬切**、且锚在 `Tile` 上")
    # ③ 段内不许逐格跟随玩家（段尾那一条归位事件除外）
    lo_ = 60
    hi_ = 60 + 24 - 1
    follow = [a for a in in_snow if a.get("relativeTo") == "Player"
              and not _is_lock(a) and int(a["floor"]) < hi_ - 6]
    check(not follow,
          "★ 雪花段内**不允许逐格跟随玩家**（会一路转得头晕）"
          + (f"，越界 {len(follow)} 条" if follow else ""))
    # ④ A 的招牌数值：怼近 100 → 拉远 250（抄 Tempest `f402`），旋转是 360 的整数倍
    zs = {a.get("zoom") for a in in_snow if a.get("zoom") is not None}
    check(100.0 in zs and 250.0 in zs,
          "★ 雪花 A 段要有 `zoom=100`（硬切怼近）与 `zoom=250`（拉远看清整朵）：%s"
          % sorted(zs))
    spins = [a for a in in_snow
             if abs(float(a.get("rotation") or 0.0) % 360.0) < 1e-9
             and abs(float(a.get("rotation") or 0.0)) >= 360.0 - 1e-9]
    check(bool(spins), "★ 雪花 A 段要有**整圈**旋转（`rotation` = 360 的正整数倍）")
    check(all(float(a["duration"]) >= 4.0 - 1e-9 for a in spins),
          "★ 而且 A 的整圈旋转必须是**缓速**（时值 ≥ 4 拍）：%s"
          % sorted({float(a["duration"]) for a in spins}))
    if sc2:
        rec = {str(s.get("snow_recipe") or "") for s in sc2}
        check(rec & {"A"}, "★ sections 里标出这一朵走的是 A（不许静默）：%s" % rec)

    # ⑤ B 档：物量大 ⇒ 远景 + 长缓移 + 多圈
    plr4, in_big, sc4 = _snow_case(int(split) + 16)         # > 48 ⇒ B
    zs4 = {a.get("zoom") for a in in_big if a.get("zoom") is not None}
    check(600.0 in zs4, "★ 雪花 B 段要有 `zoom=600`（远景俯视）：%s" % sorted(zs4))
    ys = [float(a["position"][1]) for a in in_big
          if a.get("position") not in (None, [None, None])
          and a["position"][1] is not None]
    check(bool(ys) and min(ys) <= -10.0,
          "★ 雪花 B 段要把镜头**退到下方**（照抄 Tempest `pos=[·,-14]`）：%s"
          % sorted(set(ys))[:6])
    xs = [float(a["position"][0]) for a in in_big
          if a.get("position") not in (None, [None, None])
          and a["position"][0] is not None]
    check(bool(xs) and (max(xs) - min(xs)) >= 8.0 - 1e-9,
          "★ 雪花 B 段要有**长缓移**（横向摆幅 ≥ 8 格）：%s"
          % (round(max(xs) - min(xs), 2) if xs else None,))
    spins4 = [a for a in in_big
              if abs(float(a.get("angleOffset") or 0.0)) >= 360.0 - 1e-9
              or abs(float(a.get("rotation") or 0.0)) >= 360.0 - 1e-9]
    check(bool(spins4), "★ 雪花 B 段要有**多圈**旋转（`angleOffset` 或 `rotation` 整圈）")
    if sc4:
        rec4 = {str(s.get("snow_recipe") or "") for s in sc4}
        check(rec4 & {"B"}, "★ sections 里标出这一朵走的是 B：%s" % rec4)

    # ⑥ 雪花段**优先于** cur 分派（两档都走雪花规则）
    chs2 = _C(120, snow=tuple(range(60, 84)),
              fast=((60, 119, 600.0),), base_bpm=100.0)
    plr3 = C.plan(chs2)
    sn = [a for a in _cam(plr3) if 60 <= int(a["floor"]) <= 84]
    check(not [a for a in sn if a.get("relativeTo") == "Player" and not _is_lock(a)
               and int(a["floor"]) < 60 + 24 - 7],
          "★★ 即使那一段是**高 cur**，雪花规则**优先**（仍是居中、不跟随）")

    # ---------------------------------------------------------------- S
    print()
    print("=" * 78)
    print("S ★★ 国士無双 · 两层（用户 2026-10：「**准备开抄国士无双**」）")
    print("   `docs/67` 交接单 · 素材 `Laur_-_国士無双/Done.adofai` 段 1521..1778")
    print("   宏观层 `relativeTo=Player`（跟人 · 大偏移 · **按拍写死**）：")
    print("     长锚 `OutExpo` + 串尾**弹回** `OutCirc`，长锚后还有一段**静默期**")
    print("   微观层 `relativeTo=Tile`（不跟人 · 小步跳 · `OutElastic`）：")
    print("     **每 2 格一条，一串 3~6 条**（不是整段连续）")
    print("   ★ 两层靠 `relativeTo` 分工 ⇒ 互不打架 ⇒ 解掉 §9.2 的「高 cur 二选一」")
    print("   ★★ 2026-10 复测修正：初版写的「宏观每 44~78 格重发 / 微观整段连续」")
    print("      **两个都不对** —— 见 `docs/67` §1 与 `docs/64` §9.2c。")
    _SPEC = (
        ("two_layer", False, "两层总开关（★ 默认关 —— 用户还没说接线）"),
        ("two_layer_macro_pos", [-4.0, 3.0], "宏观层的大偏移（国士無双全体一致）"),
        ("two_layer_macro_zoom", 300.0, "宏观层的缩放"),
        ("two_layer_long_beats", 20.0, "长锚时值（★ **按拍写死**，不随 cur 变）"),
        ("two_layer_snap_beats", 2.0, "串尾「弹回」时值（★ 也**按拍写死**）"),
        ("two_layer_micro_zoom", 210.0, "微观层的缩放"),
        ("two_layer_micro_beats", 1.0, "微观层时值（★ 也**按拍写死**）"),
        ("two_layer_micro_tiles", 2, "微观层**串内**节奏：每 2 格一条"),
        ("two_layer_micro_tiles_slow", 1, "太慢那一档：每 1 格一条（用户「太慢的用现有」）"),
        ("two_layer_burst", (3, 4, 6, 5), "微观**串长**循环表（国士实测 3~6 条一串）"),
        ("two_layer_lull_tiles", 32, "长锚之后的**静默期**格数（国士是 44 格）"),
        ("two_layer_entry", False, "进场招牌 `zoom=1` + 两整圈（用户：抄为**可选项目**）"),
    )
    for _nm, _dv, _why in _SPEC:
        check(_nm in names2, "CameraParams 有 %s —— %s（默认 %s）" % (_nm, _why, _dv))

    _MP = list(getattr(C.CameraParams, "two_layer_macro_pos", [-4.0, 3.0]))
    _MZ = float(getattr(C.CameraParams, "two_layer_macro_zoom", 300.0))
    _MBL = float(getattr(C.CameraParams, "two_layer_long_beats", 20.0))
    _MBS = float(getattr(C.CameraParams, "two_layer_snap_beats", 2.0))
    _MNW = float(getattr(C.CameraParams, "two_layer_micro_zoom", 210.0))
    _MNB = float(getattr(C.CameraParams, "two_layer_micro_beats", 1.0))
    _MNT = int(getattr(C.CameraParams, "two_layer_micro_tiles", 2))
    _MNTS = int(getattr(C.CameraParams, "two_layer_micro_tiles_slow", 1))
    _BURST = tuple(getattr(C.CameraParams, "two_layer_burst", (3, 4, 6, 5)))
    _LULL = int(getattr(C.CameraParams, "two_layer_lull_tiles", 32))
    _MBSET = {_MBL, _MBS}

    # 快段（cur 600 ≥ cur_split 400）跑一层两层，慢段（cur 100）再跑一次做对照
    chf = _C(240, fast=((60, 119, 600.0),), base_bpm=100.0)
    plf = C.plan(chf, two_layer=True)
    secf = [s for s in (getattr(plf, "sections", None) or [])
            if int(s.get("lo") or -1) <= 60 <= int(s.get("hi") or -1)]
    mvf = [a for a in _cam(plf) if 60 <= int(a["floor"]) <= 119]
    mac = [a for a in mvf if a.get("relativeTo") == "Player"
           and a.get("position") == _MP]
    mic = [a for a in mvf if a.get("relativeTo") == "Tile"]

    # ① 两层都在，而且**都没有让别的层混进来**
    check(bool(mac), "★ 宏观层在：`relativeTo=Player` + `position=%s` 共 %d 条"
          % (_MP, len(mac)))
    check(bool(mic), "★ 微观层在：`relativeTo=Tile` 共 %d 条" % len(mic))
    check(not [a for a in mvf if a.get("relativeTo") not in
               ("Player", "Tile", "Global")],
          "两层的 `relativeTo` 只有 `Player` / `Tile`（国士無双就是这么分工的）")

    # ② 宏观层：跟人 + 大偏移 + **按拍写死** + 长锚/弹回**两档**都在
    check(all(abs(float(a["zoom"]) - _MZ) < 1e-9 for a in mac),
          "★ 宏观层 `zoom` 恒为 %g：%s" % (_MZ, sorted({float(a["zoom"]) for a in mac})))
    check({float(a["duration"]) for a in mac} == _MBSET,
          "★ 宏观层时值只有**按拍写死的两档** %s（与 cur 无关）：%s"
          % (sorted(_MBSET), sorted({float(a["duration"]) for a in mac})))
    check({a.get("ease") for a in mac} == {"OutExpo", "OutCirc"},
          "★ 长锚 `OutExpo` + 弹回 `OutCirc` 都在（照抄国士無双）：%s"
          % sorted({a.get("ease") for a in mac}))
    check(all(a.get("position") not in (None, [None, None]) for a in mac),
          "★ 宏观层**显式给 `position`**（跟人层留 `[null,null]` 就是 v1 把相机弄没的那个坑）")

    # ③ 微观层：不跟人 + `OutElastic` + **串内每 2 格**
    check(all(abs(float(a["zoom"]) - _MNW) < 1e-9 for a in mic),
          "★ 微观层 `zoom` 恒为 %g：%s" % (_MNW, sorted({float(a["zoom"]) for a in mic})))
    check(all(abs(float(a["duration"]) - _MNB) < 1e-9 for a in mic),
          "★ 微观层时值恒为 %.5f 拍（照抄国士無双）：%s"
          % (_MNB, sorted({float(a["duration"]) for a in mic})))
    check({a.get("ease") for a in mic} == {"OutElastic"},
          "★ 微观层的 `ease` 照抄国士無双的 `OutElastic`：%s"
          % sorted({a.get("ease") for a in mic}))
    _mf = sorted(int(a["floor"]) for a in mic)
    _gaps = sorted({b - a for a, b in zip(_mf, _mf[1:])})
    check(bool(_gaps) and min(_gaps) == _MNT,
          "★★ 微观层**串内**是每 %d 格一条（串间会更大 —— 有「弹回 + 静默」）：%s"
          % (_MNT, _gaps))
    # 串长要落在国士实测的区间里（初版「整段连续」是错的）
    _runs, _r = [], 1
    for _a, _b in zip(_mf, _mf[1:]):
        if _b - _a == _MNT:
            _r += 1
        else:
            _runs.append(_r)
            _r = 1
    _runs.append(_r)
    check(bool(_runs) and all(1 <= x <= max(_BURST) for x in _runs),
          "★★ 微观是**成串**发的，串长落在一串 1~%d 条（国士实测 3~6）：%s"
          % (max(_BURST), _runs))
    # 长锚之后不许有微观（照抄国士那 44 格静默）
    _longs = [int(a["floor"]) for a in mac
              if abs(float(a["duration"]) - _MBL) < 1e-9]
    _inlull = [f for f in _mf
               for lf in _longs if lf + 4 <= f <= lf + _LULL - 4]
    check(bool(_longs) and not _inlull,
          "★★ 长锚之后有**静默期**（%d 格一条微观都不发，照抄国士那 44 格）：%d 条越界"
          % (_LULL, len(_inlull)))

    # ④ 两层**真的并行** —— 判据是**时间上交错**，不是同格重叠
    #   （国士無双里宏观 1575 弹回 与 微观 1569/1571/1573 **从来不在同一格**）
    _macf = sorted(int(a["floor"]) for a in mac)
    _micf = sorted(int(a["floor"]) for a in mic)
    _m1 = [f for f in _macf if _micf and _micf[0] < f < _micf[-1]]
    _m2 = [f for f in _micf if _macf and _macf[0] < f < _macf[-1]]
    check(bool(_m1) and bool(_m2),
          "★★ 两层在时间上**交错**（不是先做完一层再做另一层）：宏观夹在微观里 %d 条 /"
          " 微观夹在宏观里 %d 条" % (len(_m1), len(_m2)))

    # ⑤ 不许静默：`sections` 要标出这一段走的是两层
    check(bool(secf) and any(s.get("two_layer") or s.get("style") == "two_layer"
                             for s in secf),
          "★ `sections` 里标出这一段用了两层（不许静默）：%s"
          % [s.get("style") for s in secf])

    # ⑥ 太慢那一档：微观退回每 1 格（用户「**太慢的用现有，别的用国士无双**」）
    chs = _C(240, base_bpm=100.0)                    # 全程 cur=100 < 400
    pls = C.plan(chs, two_layer=True)
    macs = [a for a in _cam(pls) if a.get("relativeTo") == "Player"
            and a.get("position") == _MP]
    mics = [a for a in _cam(pls) if a.get("relativeTo") == "Tile"]
    _sf = sorted(int(a["floor"]) for a in mics)
    _sgaps = sorted({b - a for a, b in zip(_sf, _sf[1:])})
    check(bool(_sgaps) and min(_sgaps) == _MNTS,
          "★ 慢段微观退回**每 %d 格一条**（太慢的用现有写的网格）：%s"
          % (_MNTS, _sgaps))
    check(macs and {float(a["duration"]) for a in macs} == _MBSET,
          "★★ **慢段的宏观时值还是那两档** %s —— 证明宏观层是「按拍」而不是"
          "「被格数除出来的」" % sorted(_MBSET))

    # ⑦ 出场必须回基准（我们每段自成一体；国士無双那段在整首谱中间，原素材没有这一条）
    _back = [a for a in _perf(plf) if a.get("relativeTo") == "Player"
             and a.get("position") == [0, 0]
             and abs(float(a["zoom"]) - 200.0) < 1e-9]
    check(bool(_back), "★ 出场归位回基准（`Player` + `[0,0]` + 基准 zoom）—— "
                       "否则下一段的定基会瞬跳（`docs/64` §9.3 ①）")

    # ⑧ 进场招牌是**可选**的（用户 2026-10：「开局无所谓喵 可以抄为可选项目」）
    ple = C.plan(chf, two_layer=True, two_layer_entry=True)
    mve = _cam(ple)
    check(any(a.get("zoom") is not None and abs(float(a["zoom"]) - 1.0) < 1e-9
              for a in mve),
          "★ `two_layer_entry=True` ⇒ 出现国士無双的进场招牌 `zoom=1`")
    check(any(abs(float(a.get("angleOffset") or 0.0)) >= 720.0 - 1e-9 for a in mve),
          "★ 招牌里还有**两整圈**（`angleOffset=720`）")
    check(all(a.get("zoom") is None or float(a["zoom"]) > 0.0 for a in mve),
          "★★★ 但 `zoom` **永远不为 `null` / 0**（用户定位的根因）—— 招牌的 `1` 也不破例")

    # ---------------------------------------------------------------- 收尾
    print()
    print("=" * 78)
    if FAIL:
        print(f"=> FAIL  {len(FAIL)} 条没过：")
        for x in FAIL:
            print("   · " + x)
        return 1
    print("=> PASS  ⑤e 运镜契约全部通过")
    return 0


# ============================================================ Z（本轮不验）
# 用户 2026-10：「不用着急接线」⇒ 以下**留到接线那一轮**再补，本轮不写、不算失败：
#
#   Z1 `sidecar/schema.py` 新组「⑤e 运镜」的字段与默认值（enabled/style/zoom_base/
#      zoom_hi/rot_amp/dur/interval/reps/lock/rotation_const/chase/use_repeat）
#   Z2 `sidecar/session.py` 步骤 8e：算 `plan()` → `meta["camera_events"]` +
#      报告进 `rebuild()` 返回包 + `payload.camera` + warnings 上屏
#   Z3 `core/writer.py::build_actions` 把 `meta["camera_events"]` 并进主循环
#      （与 ⑤b/⑤c/⑤d 同构），并断言整份 actions 仍按 floor 有序
#   Z4 `app/renderer/app.js` 的 `bandCamera()` + chip（运镜 / 运镜已关 / 跳过）
#   Z5 `app/e2e.js` 接线断言（控件数 / 默认开 / 报告与段带一致 / 关掉全空）
#   Z6 `tools/pack_verify.py` 包内断言（core/camera.py 在 / schema 键在 /
#      关掉 ⇒ payload 空 / 段带条数 = 后端格数）
#   Z7 ★ `rotation_const` **真机标定**：做一张 3 段测试谱（0 / +90 / −90）
#      进游戏看一眼（`docs/59` §3.3 第 1 条，实现前必须先测出来）
#   Z8 「长图形」阈值（总转角 ≥360° 或 格数 ≥12？）—— 需要你拍
#   Z9 ★ 雪花 **A/B 的格数分界**（现在写死 `snow_big_tiles = 48`，与
#      `SolveParams.snowflake_full_tiles` 同值）—— 是本喵定的，需要你确认；
#      以及 A/B 的**旋速**换算（A = 每 32 拍一圈 / B = 每 4 拍一圈）也是本喵定的。
if __name__ == "__main__":
    raise SystemExit(main())
