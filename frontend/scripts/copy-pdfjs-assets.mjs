/**
 * 把 pdf.js 的**运行时资源**拷进 `public/pdfjs/`。
 *
 * 为什么不能只 `npm i pdfjs-dist` 就完事：这些文件是 pdf.js 在浏览器里**按需 fetch**
 * 的，不是打包进 bundle 的模块——CMap 缺了中文 PDF 的文字层就空，standard_fonts 缺了
 * 没内嵌字体的 PDF 会渲染成空白。
 *
 * 拷进 `public/` 而不是从 CDN 取：本项目的一条硬约束是**离线可跑**（README：不配任何
 * Key 也能跑通完整演示），CDN 会在没网的评审现场变成一片空白页。
 *
 * 走 `postinstall` 而不是把这几兆第三方资源提交进仓库：新克隆 `npm install` 之后
 * 就能用，仓库里也不多出 1.9 MB 别人家的二进制。
 */
import { cp, mkdir, readdir, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', 'node_modules', 'pdfjs-dist');
const target = join(here, '..', 'public', 'pdfjs');

/** pdf.js 会按这几个 URL 前缀去取资源（见 utils/pdfAssets.js 的 cMapUrl 等）。
 *  5.x/6.x 还多 `wasm/`、`iccs/` 两个目录，4.x 没有——换版本时这里跟着改。 */
const DIRS = ['cmaps', 'standard_fonts'];

if (!existsSync(source)) {
  console.error('[pdfjs] 没找到 node_modules/pdfjs-dist，先跑 npm install');
  process.exit(1);
}

// 先清空：不清的话换过 pdf.js 版本之后，旧版本的资源会一直躺在那里
// （实测踩过：从 6.x 降到 4.x，wasm/ 与 iccs/ 两份没人用的文件留了下来）
await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
const copied = [];
for (const dir of DIRS) {
  const from = join(source, dir);
  if (!existsSync(from)) {
    console.warn(`[pdfjs] 跳过 ${dir}（当前版本没有这个目录）`);
    continue;
  }
  await cp(from, join(target, dir), { recursive: true });
  copied.push(`${dir} ${(await readdir(join(target, dir))).length} 个`);
}

console.log(`[pdfjs] 资源已就绪：${copied.join(' · ')}`);
