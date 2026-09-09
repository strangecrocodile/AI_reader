import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, configureApiBase } from '../services/api.js';

afterEach(() => {
  configureApiBase('');
  vi.unstubAllGlobals();
});

beforeEach(() => {
  localStorage.clear();
});

describe('api 后端模式（REST）', () => {
  it('fetchBooks 请求 /api/books', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [{ id: 'b1' }] }));
    vi.stubGlobal('fetch', fetchMock);

    const list = await api.fetchBooks();
    expect(list).toEqual([{ id: 'b1' }]);
    expect(fetchMock).toHaveBeenCalledWith('http://backend.test/api/books', expect.anything());
  });

  it('uploadBook 以 multipart 提交 PDF', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: 'b2', title: '新教材', chapters: [] }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['%PDF-demo'], 'new.pdf', { type: 'application/pdf' });

    await expect(api.uploadBook(file)).resolves.toMatchObject({ id: 'b2' });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://backend.test/api/books');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get('file')).toBe(file);
  });

  it('fetchStudyContent 失败时回退 null（章节不存在）', async () => {
    configureApiBase('http://backend.test');
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404 })));

    expect(await api.fetchStudyContent('b1', 'ch9')).toBeNull();
  });

  it('fetchKnowledge 请求知识地图接口', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ bookId: 'b1', concepts: [], relations: [] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.fetchKnowledge('b1')).resolves.toMatchObject({ bookId: 'b1' });
    expect(fetchMock).toHaveBeenCalledWith('http://backend.test/api/books/b1/knowledge', expect.anything());
  });

  it('markChapterProgress 请求章节进度接口', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ status: 'learning', mastery: 15 }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      api.markChapterProgress({ bookId: 'b1', chapterId: 'ch1', status: 'learning', mastery: 15 }),
    ).resolves.toMatchObject({ mastery: 15 });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://backend.test/api/books/b1/chapters/ch1/progress',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('ask 以 POST /api/ask 提交并映射 answer→text', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ answer: '导数即变化率。', sources: ['s2-1'] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const res = await api.ask({ question: '导数是什么？', bookId: 'b1', chapterId: 'ch2', selectedText: '' });
    expect(res).toEqual({ text: '导数即变化率。', sources: ['s2-1'] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://backend.test/api/ask');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toMatchObject({ question: '导数是什么？', bookId: 'b1', chapterId: 'ch2' });
  });

  it('未配置后端时维持演示模式（不发起网络请求）', async () => {
    configureApiBase('');
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] }));
    vi.stubGlobal('fetch', fetchMock);
    const list = await api.fetchBooks();
    expect(list.length).toBeGreaterThan(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
