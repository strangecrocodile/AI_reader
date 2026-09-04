/**
 * 将「片段数组」渲染为富文本，支持：
 *   { t:'text', v } / { t:'b', v } / { t:'i', v } / { t:'src', id, v, kind }
 * 其中 src 片段渲染为教材源码锚点，可被 focusSource 定位高亮。
 */
export default function SegmentText({ segs, focusId }) {
  return segs.map((seg, i) => {
    switch (seg.t) {
      case 'b':
        return <b key={i}>{seg.v}</b>;
      case 'i':
        return <i key={i}>{seg.v}</i>;
      case 'src': {
        const cls = `source${seg.kind === 'definition' ? ' definition' : ''}${focusId === seg.id ? ' focus' : ''}`;
        return (
          <span key={i} id={seg.id} className={cls} data-source-id={seg.id}>
            {seg.v}
          </span>
        );
      }
      case 'text':
      default:
        return <span key={i}>{seg.v}</span>;
    }
  });
}
