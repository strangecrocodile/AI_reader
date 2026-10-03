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
 */
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

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
 * 空白页，JPEG2000/JBIG2 图少 wasm 就直接不显示。都不报错，只看得到结果不对。
 */
export function pdfAssetOptions() {
  const base = assetBase();
  return {
    cMapUrl: `${base}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${base}standard_fonts/`,
    wasmUrl: `${base}wasm/`,
    iccUrl: `${base}iccs/`,
  };
}
