/**
 * 结构化演示数据（Mock）。
 *
 * 说明：当前版本所有教材、章节、讲解与原文均为前端演示数据，
 * 用于验证完整交互链路。接入真实后端后，本文件只保留为「回退数据」。
 *
 * 段落/讲解正文统一使用「片段数组」表示，便于精确渲染、定位源码锚点：
 *   { t: 'text', v }          普通文本
 *   { t: 'b', v }             加粗
 *   { t: 'i', v }             斜体（数学变量）
 *   { t: 'src', id, v, kind } 教材源码锚点，kind: 'definition' | 'plain'
 * 公式使用 { sub } 子块表示下标。
 */

export const DEFAULT_BOOK_ID = 'calc7';

export const books = [
  {
    id: 'calc7',
    title: '高等数学',
    edition: '第七版',
    author: '同济大学数学系',
    progressText: '18% 已完成',
    tag: '高等数学',
    cover: {
      series: 'CALCULUS · 7TH EDITION',
      lines: ['高等数学', '第七版'],
      formula: ['lim Δx → 0', '∑ f(x)Δx'],
      footer: '同济大学数学系',
    },
    plan: {
      headline: ['从变化率，', '走进微积分。'],
      sub: '今天是第 3 天。我们把一个核心概念讲透，而不是匆匆翻过一页。',
      goalLabel: 'SHORT-TERM GOAL · 09 / 04',
      goal: '理解导数的定义，并能解释它与「瞬时变化率」的关系',
      remaining: '还需 2 个学习单元 · 预计 52 分钟',
    },
    chapters: [
      { id: 'ch1', num: '01', title: '函数与极限', status: 'done', meta: '已完成', progressPct: 100 },
      { id: 'ch2', num: '02', title: '导数与微分', status: 'doing', meta: '正在学习 · 2 / 5', progressPct: 42, isToday: true },
      { id: 'ch3', num: '03', title: '微分中值定理', status: 'todo', meta: '待学习', progressPct: 0 },
    ],
  },
  {
    id: 'linalg6',
    title: '线性代数',
    edition: '第六版',
    author: '同济大学数学系',
    progressText: '6% 已完成',
    tag: '线性代数',
    cover: {
      series: 'LINEAR ALGEBRA · 6TH EDITION',
      lines: ['线性代数', '第六版'],
      formula: ['A⁻¹AX = X', 'det A ≠ 0'],
      footer: '同济大学数学系 · 12 个已识别章节',
    },
    plan: {
      headline: ['从行列式，', '走进线性空间。'],
      sub: '今天的主题是矩阵的秩：一个贯穿线性代数主线的核心概念。',
      goalLabel: 'SHORT-TERM GOAL · 09 / 04',
      goal: '理解矩阵的秩，并能解释它与线性方程组解的关系',
      remaining: '还需 4 个学习单元 · 预计 80 分钟',
    },
    chapters: [
      { id: 'ch1', num: '01', title: '行列式', status: 'done', meta: '已完成', progressPct: 100 },
      { id: 'ch2', num: '02', title: '矩阵', status: 'doing', meta: '正在学习 · 1 / 4', progressPct: 30, isToday: true },
      { id: 'ch3', num: '03', title: '向量组的线性相关性', status: 'todo', meta: '待学习', progressPct: 0 },
      { id: 'ch4', num: '04', title: '线性方程组', status: 'todo', meta: '待学习', progressPct: 0 },
    ],
  },
  {
    id: 'python3',
    title: 'Python 编程：从入门到实践',
    edition: '',
    author: 'Eric Matthes',
    progressText: '0% 已完成',
    tag: 'Python',
    cover: {
      series: 'PYTHON CRASH COURSE · 3RD EDITION',
      lines: ['Python 编程', '从入门到实践'],
      formula: ['print("hello")', 'for x in range(5)'],
      footer: 'Eric Matthes · 20 个已识别章节',
    },
    plan: {
      headline: ['从第一行代码，', '开始动手。'],
      sub: '今天从变量与数据类型开始：先把最小的概念写明白，再读后面的章节。',
      goalLabel: 'SHORT-TERM GOAL · 09 / 04',
      goal: '区分变量、字符串与数字类型，并能编写简单的输出程序',
      remaining: '还需 6 个学习单元 · 预计 90 分钟',
    },
    chapters: [
      { id: 'ch1', num: '01', title: '起步', status: 'todo', meta: '待学习', progressPct: 0 },
      { id: 'ch2', num: '02', title: '变量与简单数据类型', status: 'doing', meta: '正在学习 · 1 / 3', progressPct: 33, isToday: true },
      { id: 'ch3', num: '03', title: '列表简介', status: 'todo', meta: '待学习', progressPct: 0 },
      { id: 'ch4', num: '04', title: '操作列表', status: 'todo', meta: '待学习', progressPct: 0 },
    ],
  },
];

/**
 * 章节学习内容：books[id].chapters[chapterId] → 原文段落 + 备课讲解。
 * 演示范围：高等数学 · 第二章（第 47 页 · 2.1 导数的概念）。
 * 其余章节 fetchStudyContent 返回 null，页面显示「内容尚未准备」占位。
 */
export const studyContents = {
  calc7: {
    ch2: {
      page: 47,
      heading: '2.1 导数的概念',
      intro: '第二章 · 导数与微分　/　第 47 页',
      paragraphs: [
        {
          type: 'p',
          segs: [
            { t: 'text', v: '在生产实践和科学研究中，经常会遇到这样一类问题：' },
            { t: 'src', id: 'source-rate', v: '一个量相对于另一个量的变化率' },
            { t: 'text', v: '。例如，物体作变速直线运动时，它在某一时刻的速度；曲线在某一点处的切线斜率等。' },
          ],
        },
        {
          type: 'p',
          segs: [
            { t: 'text', v: '设函数 ' },
            { t: 'i', v: 'y = f(x)' },
            { t: 'text', v: ' 在点 ' },
            { t: 'i', v: 'x' },
            { t: 'text', v: ' 的某个邻域内有定义。当自变量 ' },
            { t: 'i', v: 'x' },
            { t: 'text', v: ' 在点 ' },
            { t: 'i', v: 'x₀' },
            { t: 'text', v: ' 处取得增量 ' },
            { t: 'i', v: 'Δx' },
            { t: 'text', v: ' 时，相应地函数取得增量 ' },
            { t: 'i', v: 'Δy = f(x₀ + Δx) − f(x₀)' },
            { t: 'text', v: '。' },
          ],
        },
        {
          type: 'p',
          segs: [
            { t: 'text', v: '如果当 ' },
            { t: 'i', v: 'Δx → 0' },
            { t: 'text', v: ' 时，' },
            { t: 'src', id: 'source-limit', v: '比值 Δy / Δx 的极限存在', kind: 'definition' },
            { t: 'text', v: '，那么称这个极限为函数 ' },
            { t: 'i', v: 'y = f(x)' },
            { t: 'text', v: ' 在点 ' },
            { t: 'i', v: 'x₀' },
            { t: 'text', v: ' 处的导数，记作 ' },
            { t: 'i', v: 'f′(x₀)' },
            { t: 'text', v: '，即：' },
          ],
        },
        {
          type: 'formula',
          parts: ['f′(x₀) = lim', { sub: 'Δx→0' }, '　[f(x₀ + Δx) − f(x₀)] / Δx'],
        },
        {
          type: 'p',
          segs: [
            { t: 'text', v: '导数的几何意义是曲线 ' },
            { t: 'i', v: 'y = f(x)' },
            { t: 'text', v: ' 在点 ' },
            { t: 'i', v: '(x₀, f(x₀))' },
            { t: 'text', v: ' 处的' },
            { t: 'src', id: 'source-tangent', v: '切线的斜率' },
            { t: 'text', v: '；它的物理意义则是相应量在该时刻的瞬时变化率。' },
          ],
        },
      ],
      knowledgePoints: [
        {
          id: 'kp-rate',
          kind: 'card',
          title: '先抓住「变化率」',
          body: [
            { t: 'text', v: '把 ' },
            { t: 'b', v: 'Δy / Δx' },
            { t: 'text', v: ' 看成「每前进一小步，y 平均改变多少」。它描述一段区间内的平均变化，还不是某一个时刻的精确速度。' },
          ],
          sourceId: 'source-rate',
          sourceLabel: '定位教材：变化率原文',
        },
        {
          id: 'kp-limit',
          kind: 'card',
          title: '关键一步：让间隔趋近于 0',
          body: [
            { t: 'text', v: '当观察区间越来越小，平均变化率若稳定地趋向一个数，这个数就是导数。' },
            { t: 'b', v: '「极限存在」' },
            { t: 'text', v: ' 是定义成立的前提。' },
          ],
          sourceId: 'source-limit',
          sourceLabel: '定位教材：导数定义',
        },
        {
          id: 'kp-example',
          kind: 'example',
          title: '一个直觉例子',
          body: [
            { t: 'text', v: '汽车 10:00–10:01 行驶 60m，平均速度为 1m/s；把时间缩短到无限小，就逼近 10:00 这一刻的瞬时速度。' },
          ],
        },
      ],
      outline: [
        { index: '01', title: '平均变化率', summary: '先用两个点描述一段变化。', sourceId: 'source-rate' },
        { index: '02', title: '极限与导数定义', summary: '当自变量增量趋近 0。', sourceId: 'source-limit' },
        { index: '03', title: '几何意义', summary: '导数等于切线斜率。', sourceId: 'source-tangent' },
      ],
    },
  },
};
