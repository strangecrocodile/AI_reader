"""生成示例演示教材 PDF（内容为团队原创，版权合规）。

用法：backend/.venv/Scripts/python.exe scripts/make_demo_pdf.py [输出路径]
默认输出到 backend/data/demo_textbook.pdf
"""
import sys
from pathlib import Path

import pymupdf as fitz

PAGE_W, PAGE_H = 595, 842
MARGIN = 62
BODY_FONT = 11.5
HEADING_FONT = 16
LINE_H = 1.75
FOOT_H = 30  # 底部留白（页码区）

# (层级, 标题, [段落文本...]) —— 文本为团队原创的演示内容
CHUNKS = [
    (1, "第1章 函数与极限", [
        "本章先回顾函数的基本概念，再讨论数列与函数的极限。极限是微积分中第一个重要的工具，后续的导数与积分都建立在极限之上。",
        "学习本章时，请把注意力放在「变化过程」上：当我们让某个量无限趋近于一个目标时，观察另一个量是否也稳定地趋近某个数。这一直觉将在下一章直接用于定义导数。",
    ]),
    (2, "1.1 函数的概念", [
        "在生活和工程中，我们经常遇到这样的关系：一个量由另一个量确定。例如，行驶时间确定之后，路程也就确定了；温度确定之后，电池的电压也基本确定。",
        "数学上，我们把这种关系抽象为函数：设 D 是实数集合中的一个子集，如果对 D 中的每一个数 x，按照某个对应规则，都能得到唯一的数 y，就称 y 是关于 x 的一个函数，记作 y = f(x)，x 称为自变量，D 称为定义域。",
        "函数的表示方法常见的有三种：解析式、表格和图像。解析式便于计算，图像便于观察变化趋势，表格便于查取个别数值。三种方法经常在一起使用。",
        "一个直观的例子：设 f(x) = 2x + 1，那么 x = 1 时 f(1) = 3，x = 2 时 f(2) = 5。随着 x 增大，f(x) 也线性地增大。",
    ]),
    (2, "1.2 极限的概念", [
        "先看一个具体的数列：1/2，2/3，3/4，4/5，……。观察发现，通项 n/(n+1) 随着 n 增大，越来越接近 1，但始终不等于 1。我们把 1 称为这个数列的极限。",
        "一般地，如果当 n 无限增大时，数列的通项 a_n 无限接近一个常数 A，就说数列收敛于 A，记作 lim(n→∞) a_n = A。这里「无限接近」的意思是：不管要求多接近，只要 n 足够大，就能达到。",
        "极限描述的是趋势，而不是某一个具体取值。这一点非常重要：一个数列的极限可以是 1，即使它的每一项都不等于 1。",
        "同样可以定义函数在一点处的极限：当自变量 x 无限接近 x₀ 时，如果 f(x) 稳定地趋近于常数 A，就称 A 为 f(x) 在点 x₀ 处的极限。注意，这要求的是 x 从两侧逼近时结果一致。",
    ]),
    (1, "第2章 导数与微分", [
        "本章在极限的基础上定义导数，这是微积分最重要的概念之一。导数刻画的是一个量相对于另一个量的变化率，也就是「变化的快慢」。",
        "学习本章时，请始终记住：平均来看是一回事，某一点上的精确变化率是另一回事。导数把后者说清楚了。",
    ]),
    (2, "2.1 导数的概念", [
        "设函数 y = f(x) 在点 x₀ 的某个邻域内有定义。当自变量 x 从 x₀ 改变一个小量 Δx 时，函数值相应地从 f(x₀) 改变为 f(x₀ + Δx)，增量记为 Δy = f(x₀ + Δx) − f(x₀)。",
        "比值 Δy / Δx 衡量了在这段区间内，函数值随自变量变化的平均快慢，称为平均变化率。它只代表一段区间的整体表现。",
        "让 Δx 越来越小，平均变化率若稳定地趋近于一个确定的数，就把这个数定义为函数在点 x₀ 处的瞬时变化率，也就是导数，记作 f′(x₀)。数学上写作：f′(x₀) = lim(Δx→0) [f(x₀ + Δx) − f(x₀)] / Δx。",
        "导数的几何意义：曲线 y = f(x) 在点 (x₀, f(x₀)) 处的切线斜率就是 f′(x₀)。物理意义：路程对时间的导数就是瞬时速度。",
        "一个直觉例子：汽车在某一段 10 分钟内行驶了 20 公里，平均速度是每分钟 2 公里；把时间区间缩短到极短，就逼近某一瞬间的瞬时速度。",
    ]),
    (2, "2.2 简单函数的导数", [
        "用定义直接求导数称为「定义法」，过程一般是：写出增量表达式、化简、取极限。下面用定义法求几个简单函数的导数。",
        "例1：f(x) = x²。计算 Δy = (x + Δx)² − x² = 2x·Δx + (Δx)²，于是 Δy/Δx = 2x + Δx。当 Δx → 0 时，结果趋近于 2x。所以 (x²)′ = 2x。",
        "例2：f(x) = 3x + 2。计算 Δy = 3Δx，于是 Δy/Δx = 3，极限也是 3。常数的导数为 0，因为函数值不变，变化率为零。",
        "求导公式（略去推导，建议读者自行用定义验证）：(x^n)′ = n·x^(n−1)。这一公式与线性性（函数的和、常数倍的导数规则）一起，可以求出几乎所有多项式函数的导数。",
    ]),
]


def build_demo_pdf(path: Path) -> Path:
    doc = fitz.open()
    toc = []
    y = MARGIN  # 当前页写作游标

    def new_page() -> fitz.Page:
        return doc.new_page(width=PAGE_W, height=PAGE_H)

    def wrap(text: str, chars: int) -> list:
        lines, cur = [], ""
        for ch in text:
            cur += ch
            if len(cur) >= chars:
                lines.append(cur)
                cur = ""
        if cur:
            lines.append(cur)
        return lines

    def put_text(page: fitz.Page, text: str, fontsize: float, chars: int) -> fitz.Page:
        nonlocal y
        for line in wrap(text, chars):
            if y + fontsize * LINE_H > PAGE_H - FOOT_H:
                page = new_page()
                y = MARGIN
            page.insert_text((MARGIN, y), line, fontsize=fontsize, fontname="china-s")
            y += fontsize * LINE_H
        return page

    # 封面
    cover = new_page()
    cover.insert_text((MARGIN, 200), "微积分入门", fontsize=30, fontname="china-s")
    cover.insert_text((MARGIN, 245), "——示例教材（团队原创，仅作演示）", fontsize=14, fontname="china-s")
    cover.insert_text((MARGIN, 300), "面向 AI 讲师项目的演示材料", fontsize=12, fontname="china-s")
    cover.insert_text((MARGIN, 335), "正文页码从第 2 页起（与 PDF 物理页码一致）", fontsize=12, fontname="china-s")

    page = new_page()
    for level, title, paras in CHUNKS:
        # 章级标题另起一页（首章除外）
        if level == 1 and y > MARGIN:
            page = new_page()
            y = MARGIN
        fontsize = HEADING_FONT if level == 1 else 14
        chars = int((PAGE_W - 2 * MARGIN) / (fontsize * 0.92))
        if y + (fontsize + 8) * LINE_H > PAGE_H - FOOT_H:
            page = new_page()
            y = MARGIN
        if level in (1, 2):
            toc.append([level, title, len(doc)])  # 标题将落在当前页
        page = put_text(page, title, fontsize, chars)
        y += fontsize  # 标题与正文间距
        for para in paras:
            page = put_text(page, para, BODY_FONT, int((PAGE_W - 2 * MARGIN) / (BODY_FONT * 0.92)))
        y += fontsize

    # 每页加页码（与 PDF 物理页码一致，便于与解析结果对照；封面不加）
    for i, p in enumerate(doc, start=1):
        if i == 1:
            continue
        p.insert_text((PAGE_W - MARGIN - 30, PAGE_H - 20), str(i), fontsize=9, fontname="china-s")

    doc.set_metadata({"title": "微积分入门（示例教材）"})
    doc.set_toc(toc)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


if __name__ == "__main__":  # pragma: no cover
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "demo_textbook.pdf"
    print(build_demo_pdf(out))
