import { Component } from 'react';

/**
 * 渲染异常兜底：任一组件抛错时给出可读页面，而不是整页白屏。
 * 这是「教材列表为空导致主页解构 undefined」那类问题的最后一道防线。
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // 保留到控制台，方便定位（生产环境可换成上报）
    console.error('页面渲染出错：', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <section className="page active">
        <div className="placeholder-card state-card" role="alert">
          <div className="eyebrow">RENDER ERROR</div>
          <h2>页面出了点问题</h2>
          <p>这一屏没能渲染出来，刷新通常就能恢复。</p>
          <p className="state-hint">{String(error?.message || error)}</p>
          <div className="state-actions">
            <button className="back-home" type="button" onClick={() => window.location.reload()}>
              重新加载页面
            </button>
          </div>
        </div>
      </section>
    );
  }
}
