import { describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

import { PDF_WORKER_URL, pdfAssetOptions } from '../utils/pdfAssets.js';

/**
 * pdf.js 的浏览器兼容性防线。
 *
 * 这条测试的由来是一次真实的线上故障：一开始用的是 pdfjs-dist 6.3.289，它在打开
 * PDF 时调用了 `Map.prototype.getOrInsertComputed`——一个很新的引擎 API。用户的浏览器
 * 没有它，于是「原版」阅读面直接打不开，只留下一句
 * 「this._requestsByChunk.getOrInsertComputed is not a function」。
 *
 * 麻烦的地方在于**它也在 worker 线程里用**：主线程可以 polyfill，worker 不行，
 * 所以「补一个 shim」治不了根。正确的做法是换到 Mozilla 为老浏览器出的 legacy 构建
 * （转译 + 自带 core-js polyfill），并把版本锁在 4.x。
 *
 * 所以这个文件不是在测 pdf.js 的功能，而是在**钉住这个决定**：谁要升级 pdf.js，
 * 就得先让这里通过（或在老浏览器上实测过之后改这里）。
 *
 * 这两条断言确实拦得住那次升级：6.3.289 的 legacy 构建里也有 26 处
 * `getOrInsertComputed`（当时核对过），而版本号也不是 4.x。
 */

const require = createRequire(import.meta.url);
const pkgDir = dirname(require.resolve('pdfjs-dist/package.json'));
const version = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf8')).version;

/** 我们**实际加载**的那两个文件（旧构建 + 它的 worker）。 */
const SHIPPED = {
  '主构建': join(pkgDir, 'legacy/build/pdf.mjs'),
  worker: join(pkgDir, 'legacy/build/pdf.worker.mjs'),
};

/**
 * 老浏览器上不存在、一出现就会让整页打不开的引擎 API。
 *
 * `getOrInsertComputed` / `getOrInsert` 是很新的 Map 提案（Chrome 140 上下才有），
 * `URL.parse` 也是新东西。它们都没有语法层面的替代品——Babel 转译不掉，只能靠
 * polyfill（而 worker 里补不了）。
 */
const BANNED = ['getOrInsertComputed', 'getOrInsert(', 'URL.parse'];

describe('pdf.js 的版本与构建选择', () => {
  it('锁在 4.x：5.x/6.x 需要我们目标浏览器没有的引擎 API', () => {
    expect(
      version.startsWith('4.'),
      `当前 pdfjs-dist 是 ${version}。升级前请先在老浏览器上实测原版阅读面，` +
        `并确认下列 API 没有被用到：${BANNED.join('、')}（理由见 utils/pdfAssets.js）`,
    ).toBe(true);
  });

  it.each(Object.entries(SHIPPED))('%s 不引用老浏览器没有的引擎 API', (label, file) => {
    const code = readFileSync(file, 'utf8');
    const hits = BANNED.filter((api) => code.includes(api));
    expect(
      hits,
      `${label} 用了 ${hits.join('、')}——老浏览器上会直接打不开 PDF，` +
        `且 worker 里 polyfill 不了。请换回 4.x 的 legacy 构建。`,
    ).toEqual([]);
  });

  it('worker 指向 legacy 构建（不是需要新引擎的那份）', () => {
    expect(PDF_WORKER_URL).toContain('legacy');
    expect(PDF_WORKER_URL).toContain('pdf.worker');
  });

  it('legacy worker 自带 polyfill：Promise.withResolvers 在调用前已被补上', () => {
    // 4.x 的构建里 11 处直接调用 Promise.withResolvers()，靠 core-js 先打补丁。
    // 少了这个补丁，老浏览器上 worker 一启动就崩。
    const worker = readFileSync(SHIPPED.worker, 'utf8');
    expect(worker).toContain('withResolvers');
    expect(worker).toContain('core-js');
  });

  it('资源目录指向随包分发的 CMap 与字体（不依赖 CDN，离线可跑）', () => {
    const options = pdfAssetOptions();
    expect(options.cMapUrl).toMatch(/cmaps\/$/);
    expect(options.standardFontDataUrl).toMatch(/standard_fonts\/$/);
    expect(options.cMapPacked).toBe(true);
    // 4.x 不认这两个（5.x/6.x 才有），传了没用还容易让人以为在生效
    expect(options).not.toHaveProperty('wasmUrl');
    expect(options).not.toHaveProperty('iccUrl');
  });
});
