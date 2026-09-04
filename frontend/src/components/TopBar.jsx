import { Link } from 'react-router-dom';

export default function TopBar() {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="mark" aria-hidden="true"></span>AI讲师
      </div>
      <nav className="top-nav" aria-label="主导航">
        <Link to="/" className="nav-link active">
          我的学习
        </Link>
        <span className="nav-link">教材库</span>
        <span className="nav-link">学习报告</span>
      </nav>
      <div className="avatar">zhang</div>
    </header>
  );
}
