import { Routes, Route } from 'react-router-dom';
import TopBar from './components/TopBar.jsx';
import HomePage from './pages/HomePage.jsx';
import StudyPage from './pages/StudyPage.jsx';
import KnowledgePage from './pages/KnowledgePage.jsx';
import NotFoundPage from './pages/NotFoundPage.jsx';

export default function App() {
  return (
    <>
      <TopBar />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/study/:bookId/:chapterId" element={<StudyPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}
