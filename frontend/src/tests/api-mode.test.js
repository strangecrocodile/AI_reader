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

  it('uploadBook 以 multipart 提交 PDF', async () => {    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: 'b2', title: '新教材', chapters: [] }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['%PDF-demo'], 'new.pdf', { type: 'application/pdf' });

    // 201（常规解析）走 book 分支，调用方拿到的就是教材元信息
    await expect(api.uploadBook(file)).resolves.toEqual({
      kind: 'book',
      book: { id: 'b2', title: '新教材', chapters: [] },
    });

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

  it('fetchCapabilities 请求能力接口（.doc 是否可用）', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ formats: ['pdf', 'doc'], legacyDoc: true, legacyDocHint: '' }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.fetchCapabilities()).resolves.toMatchObject({ legacyDoc: true });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://backend.test/api/capabilities',
      expect.anything(),
    );
  });

  it('fetchCapabilities 失败时返回 null，不拖垮上传入口', async () => {
    configureApiBase('http://backend.test');
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })));

    expect(await api.fetchCapabilities()).toBeNull();
  });

  it('sourceUrl 只在留存了原文件时给出下载地址', () => {
    configureApiBase('http://backend.test');

    expect(api.sourceUrl({ id: 'b1', hasSource: true })).toBe(
      'http://backend.test/api/books/b1/source',
    );
    expect(api.sourceUrl({ id: 'b1', hasSource: false })).toBe('');
    expect(api.sourceUrl({ id: 'b1' })).toBe('');
    expect(api.sourceUrl(null)).toBe('');
  });

  it('演示模式没有真实原文件，sourceUrl 返回空串', () => {
    configureApiBase('');

    expect(api.sourceUrl({ id: 'b1', hasSource: true })).toBe('');
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

  it('recordLearningEvent 上报学习事件并回传掌握度', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ status: 'learning', mastery: 20, computed: 20, breakdown: [], signals: {} }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      api.recordLearningEvent({ bookId: 'b1', chapterId: 'ch1', kind: 'read', anchorIds: ['s1'] }),
    ).resolves.toMatchObject({ mastery: 20 });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://backend.test/api/books/b1/chapters/ch1/events');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toMatchObject({ kind: 'read', anchorIds: ['s1'] });
  });

  it('ask 以 POST /api/ask 提交并映射 answer→text', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ answer: '导数即变化率。', sources: ['s2-1'] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const res = await api.ask({ question: '导数是什么？', bookId: 'b1', chapterId: 'ch2', selectedText: '' });
    expect(res).toEqual({ text: '导数即变化率。', sources: ['s2-1'], sourceDetails: [] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://backend.test/api/ask');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toMatchObject({ question: '导数是什么？', bookId: 'b1', chapterId: 'ch2' });
  });

  it('askStream 解析 SSE 帧并把增量与最终结果回调出去', async () => {
    configureApiBase('http://backend.test');
    const frames = [
      'event: meta\ndata: {"event":"meta","scope":"book","evidenceCount":2}\n\n',
      'event: delta\ndata: {"event":"delta","text":"导数"}\n\n',
      'event: delta\ndata: {"event":"delta","text":"是变化率"}\n\n',
      'event: done\ndata: {"event":"done","answer":"导数是变化率","sources":["s1"],"sourceDetails":[{"id":"s1","page":3}],"scope":"book"}\n\n',
    ];
    const encoder = new TextEncoder();
    let index = 0;
    const body = {
      getReader: () => ({
        read: async () =>
          index < frames.length
            ? { value: encoder.encode(frames[index++]), done: false }
            : { value: undefined, done: true },
        cancel: async () => {},
      }),
    };
    const fetchMock = vi.fn(async () => ({ ok: true, body }));
    vi.stubGlobal('fetch', fetchMock);

    const deltas = [];
    let done = null;
    await api.askStream(
      { question: '导数是什么？', bookId: 'b1', chapterId: 'ch2', threadId: 'th-1' },
      { onDelta: (text) => deltas.push(text), onDone: (payload) => { done = payload; } },
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://backend.test/api/ask/stream');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toMatchObject({ threadId: 'th-1' });
    expect(deltas.join('')).toBe('导数是变化率');
    expect(done).toMatchObject({ answer: '导数是变化率', sources: ['s1'], scope: 'book' });
  });

  it('fetchThreads 请求本章线程列表', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.fetchThreads('b1', 'ch2')).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://backend.test/api/books/b1/chapters/ch2/threads',
      expect.anything(),
    );
  });

  it('createThread 提交选中原文与锚点', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ id: 'th-1' }) }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      api.createThread({ bookId: 'b1', chapterId: 'ch2', anchorId: 'b1-ch2-s3', selectedText: '原文' }),
    ).resolves.toMatchObject({ id: 'th-1' });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://backend.test/api/threads');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      bookId: 'b1',
      chapterId: 'ch2',
      anchorId: 'b1-ch2-s3',
      selectedText: '原文',
    });
  });

  it('deleteThread 使用 DELETE', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await api.deleteThread('th-1');

    expect(fetchMock).toHaveBeenCalledWith('http://backend.test/api/threads/th-1', {
      method: 'DELETE',
    });
  });

  it('扫描件上传返回 202 时给出 ocr 分支（此时还没有教材）', async () => {
    configureApiBase('http://backend.test');
    const task = { id: 't1', status: 'pending', totalPages: 300, donePages: 0 };
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 202,
      json: async () => ({ task }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['%PDF-scan'], 'scan.pdf', { type: 'application/pdf' });

    await expect(api.uploadBook(file)).resolves.toEqual({ kind: 'ocr', task });
  });

  it('fetchOcrTask 轮询任务进度', async () => {
    configureApiBase('http://backend.test');
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ id: 't1', status: 'running', donePages: 12, totalPages: 300 }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.fetchOcrTask('t1')).resolves.toMatchObject({ donePages: 12 });
    expect(fetchMock).toHaveBeenCalledWith('http://backend.test/api/ocr/tasks/t1');
  });

  it('任务不存在（404）返回 null，网络故障照常抛出', async () => {
    configureApiBase('http://backend.test');
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404 })));
    // 404 是「任务没了」，调用方据此提示重新上传
    await expect(api.fetchOcrTask('gone')).resolves.toBeNull();

    // 断网不能跟 404 混为一谈：那样一次网络抖动就会被误报成「识别已中断」
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await expect(api.fetchOcrTask('t1')).rejects.toThrow();
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
