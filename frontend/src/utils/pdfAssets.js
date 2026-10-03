/**
 * pdf.js 的运行时资源地址。
 *
 * 分两类，取法不同，别混：
 *
 * - **worker**：走 Vite 的 `?url` 静态产物。它必须与主包一起被打包/指纹化，
 *   交给构建工具处理才不会在 `base: './'` 的子路径部署下 404。
 * - **CMap / 标准字体 / wasm / ICC**：pdf.js 在浏览器里按 `cMapUrl` 这类前缀
 *   自己拼文件名去 fetch，所以只能是一个**目录 URL**，没法用 `?url` 逐个导入。
 *   目录由 `scripts/copy-pdfjs-assets.mjs` 在 `npm install` 后拷进 `public/pdfjs/`。
 *
 * 目录基准刻意用 `document.baseURI` 而不是写死 `/pdfjs/`：vite.config.mjs 是
 * `base: './'`（产物可静态托管、也能本地直开），写死绝对路径在子路径部署下会 404。
 *
 * ## 为什么用 legacy 构建、为什么锁 4.x（别随手升级）
 *
 * 6.x 的构建调用了 `Map.prototype.getOrInsertComputed`——这是很新的引擎 API，
 * 老一些的浏览器上根本没有，症状是打开 PDF 直接报
 * 「this._requestsByChunk.getOrInsertComputed is not a function」。
 * 更麻烦的是**它在 worker 线程里也用了**：主线程能 polyfill，worker 不行，
 * 所以「在主线程补一个」治不了根。
 *
 * `legacy/` 是 Mozilla 自己为老浏览器出的构建（转译 + core-js polyfill，
 * 连 `Promise.withResolvers` 这类都在内），且不碰 `getOrInsertComputed`。
 * 代价是体积略大一点，换来的是「评审现场用谁的电脑都能打开」——
 * 这个项目的目标环境本来就是不可控的机器。**升级前先在老浏览器上实测一次。**
 */
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';

/** pdf.js 的 worker 地址。`GlobalWorkerOptions.workerSrc` 用这个值。 */
export const PDF_WORKER_URL = workerUrl;

function assetBase() {
  if (typeof document === 'undefined') return '';
  return new URL('pdfjs/', document.baseURI).href;
}

/**
 * 传给 `getDocument` 的资源选项。
 *
 * 这几个不配也能跑，只是会在别的 PDF 上悄悄缺东西——中文 PDF 少 CMap 时文字层
 * 是空的（既没法划词，也没法高亮），没内嵌字体的 PDF 少 standard_fonts 会渲染成
 * 空白页。都不报错，只看得到结果不对。
 *
 * 只列这个版本（4.x）认得的项：`wasmUrl` / `iccUrl` 是 5.x/6.x 为 JPEG2000、JBIG2
 * 与 ICC 色彩配置加的，4.x 没有这两个概念，传了也没用。
 */
export function pdfAssetOptions() {
  const base = assetBase();
  return {
    cMapUrl: `${base}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${base}standard_fonts/`,
  };
}
