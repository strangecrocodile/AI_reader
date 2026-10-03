import { Routes, Route, useLocation } from 'react-router-dom';
import TopBar from './components/TopBar.jsx';
import HomePage from './pages/HomePage.jsx';
import StudyPage from './pages/StudyPage.jsx';
import KnowledgePage from './pages/KnowledgePage.jsx';
import NotFoundPage from './pages/NotFoundPage.jsx';

/**
 * 学习页**不显示顶部导航**。
 *
 * 读书时最不需要的就是一排可以去别处的链接：一次分神换来的是一段要重读的原文。
 * 页面内部本来就有自己的工具行（返回学习计划 / 全书搜索 / 章节导航 / 阅读方式），
 * 退出学习这条路径是通的，只是不再摆在眼前。
 */
export default function App() {
  const { pathname } = useLocation();
  const studying = pathname.startsWith('/study/');

  return (
    <>
      {studying ? null : <TopBar />}
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/study/:bookId/:chapterId" element={<StudyPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}
