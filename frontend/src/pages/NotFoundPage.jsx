import { Link, useLocation } from 'react-router-dom';

/** 404：未知路由兜底，避免只剩顶栏的空白页。 */
export default function NotFoundPage() {
  const location = useLocation();

  return (
    <section className="page active">
      <div className="placeholder-card state-card">
        <div className="eyebrow">404</div>
        <h2>这个页面不存在</h2>
        <p>
          没有找到 <code>{location.pathname}</code> 对应的页面。
        </p>
        <div className="state-actions">
          <Link className="back-home" to="/">
            返回学习计划
          </Link>
          <Link className="back-home ghost" to="/knowledge">
            去知识地图
          </Link>
        </div>
      </div>
    </section>
  );
}
