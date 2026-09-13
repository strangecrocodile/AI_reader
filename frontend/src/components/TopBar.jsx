import { Link, useLocation } from 'react-router-dom';

export default function TopBar() {
  const location = useLocation();

  return (
    <header className="topbar">
      <div className="brand">
        <span className="mark" aria-hidden="true"></span>AI讲师
      </div>
      <nav className="top-nav" aria-label="主导航">
        <Link to="/" className={`nav-link${location.pathname === '/' ? ' active' : ''}`}>
          我的学习
        </Link>
        <Link to="/knowledge" className={`nav-link${location.pathname === '/knowledge' ? ' active' : ''}`}>
          知识地图
        </Link>
        <span className="nav-link soon" aria-disabled="true" title="学习报告正在开发中">
          学习报告<em>即将上线</em>
        </span>
      </nav>
      <div className="avatar">zhang</div>
    </header>
  );
}
