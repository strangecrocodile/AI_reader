/**
 * 将「片段数组」渲染为富文本，支持：
 *   { t:'text', v } / { t:'b', v } / { t:'i', v } / { t:'src', id, v, kind, segs }
 *   { t:'run', v, style:[...] }
 *
 * `src` 片段渲染为教材源码锚点，可被 focusSource 定位高亮。带 `segs` 的锚点
 * 用来承载段落里的行内版式（粗体/斜体/上下标/字号层级）：锚点仍是最外层元素，
 * 因此划词归属、锚点定位、可见性上报的老逻辑完全不用改。
 *
 * `run` 的 style 是后端白名单里的语义 token（b/i/sup/sub/lg/sm），这里映射成
 * class 而不是内联样式——观感统一由 study.css 决定，也不给后端透传字体名的机会。
 */

/** 样式 token → class 名。与后端 parsing.base.STYLE_TOKENS 一一对应。 */
const RUN_CLASS = {
  b: 'rt-b',
  i: 'rt-i',
  sup: 'rt-sup',
  sub: 'rt-sub',
  lg: 'rt-lg',
  sm: 'rt-sm',
};

/** token 数组 → class 名（未知 token 直接忽略，不让脏数据产生怪样式）。 */
export function runClassName(style) {
  if (!Array.isArray(style)) return '';
  return style.map((token) => RUN_CLASS[token]).filter(Boolean).join(' ');
}

export default function SegmentText({ segs, focusId }) {
  return (segs ?? []).map((seg, i) => {
    switch (seg.t) {
      case 'b':
        return <b key={i}>{seg.v}</b>;
      case 'i':
        return <i key={i}>{seg.v}</i>;
      case 'run': {
        const cls = runClassName(seg.style);
        return cls ? (
          <span key={i} className={cls}>
            {seg.v}
          </span>
        ) : (
          <span key={i}>{seg.v}</span>
        );
      }
      case 'src': {
        const cls = `source${seg.kind === 'definition' ? ' definition' : ''}${focusId === seg.id ? ' focus' : ''}`;
        return (
          <span key={i} id={seg.id} className={cls} data-source-id={seg.id}>
            {/* 有子片段时正文只在子片段里，锚点自身不再重复输出（v 为空串） */}
            {seg.segs ? <SegmentText segs={seg.segs} focusId={focusId} /> : seg.v}
          </span>
        );
      }
      case 'text':
      default:
        return <span key={i}>{seg.v}</span>;
    }
  });
}
