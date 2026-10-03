/**
 * 布局探针：用真实 Chrome 量页面（开发工具，不参与构建，也不进产物）。
 *
 * ## 为什么需要它
 *
 * jsdom 没有排版引擎，单元测试量不到「元素在不在视口里」。而真实故障恰恰藏在那里：
 * 页码栏曾经落在 `y=1171`，而视口只有 802px——`position: sticky; bottom: 0` 看着没问题，
 * 真正的原因是网格行被右栏内容撑到 1301px，`.reader` 底部整个被推到视口外面。
 * 这个数字用眼睛看、用单元测试都拿不到，只有量出来才知道。
 *
 * 命令行 `--screenshot` 也不够：pdf.js 的渲染在 worker 里，headless 的虚拟时间推不动它，
 * 截出来永远是「还没加载完」的空阅读区。这里用 DevTools 协议，真时间、真测量。
 *
 * ## 用法（先起好后端 8000 与前端 3000）
 *
 *   node scripts/probe-layout.mjs <url> [宽] [高] [等待毫秒] [截图路径] [先点的按钮文字]
 *
 * 例：
 *   node scripts/probe-layout.mjs http://localhost:3000/study/<bookId>/<chapterId> 1600 900 15000 out.png
 *   node scripts/probe-layout.mjs http://localhost:3000/study/<bookId>/<chapterId> 1024 768 14000 out.png 结构化
 *
 * 输出是一段 JSON：视口、阅读区高度、页码栏位置与 `barVisible`（栏是否落在视口内）、
 * 纸的页脚是不是最后一个元素等。**改布局前后各跑一次对比**，别凭感觉调像素。
 */
import { writeFileSync } from 'node:fs';
import { spawn } from 'node:child_process';

const [url, width = '1600', height = '900', waitMs = '12000', out = 'probe.png', clickText = ''] =
  process.argv.slice(2);

if (!url) {
  console.error('用法：node scripts/probe-layout.mjs <url> [宽] [高] [等待毫秒] [截图路径] [先点的按钮文字]');
  process.exit(1);
}

//: headless 也需要一个真浏览器；按平台挑一个存在的
const CANDIDATES = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].filter(Boolean);

import { existsSync } from 'node:fs';
const CHROME = CANDIDATES.find((path) => existsSync(path));
if (!CHROME) {
  console.error('没找到 Chrome / Edge，可用 CHROME_PATH 环境变量指定');
  process.exit(1);
}

const PORT = 9333;
const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    `--remote-debugging-port=${PORT}`,
    `--window-size=${width},${height}`,
    `--user-data-dir=${process.env.TEMP || '/tmp'}/chrome-probe-${Date.now()}`,
    'about:blank',
  ],
  { stdio: 'ignore' },
);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function targetUrl() {
  for (let i = 0; i < 40; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const page = list.find((item) => item.type === 'page');
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {
      /* 浏览器还没起来 */
    }
    await sleep(250);
  }
  throw new Error('连不上 Chrome 调试端口');
}

const ws = new WebSocket(await targetUrl());
let nextId = 1;
const pending = new Map();

ws.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message.result);
    pending.delete(message.id);
  }
});

const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = nextId++;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });

await new Promise((resolve) => ws.addEventListener('open', resolve));
await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url });
await sleep(Number(waitMs));

// 可选：先点一个按钮（例如切到「结构化」阅读面再看布局）
if (clickText) {
  await send('Runtime.evaluate', {
    expression: `(() => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === ${JSON.stringify(clickText)});
      if (btn) btn.click();
      return Boolean(btn);
    })()`,
    returnByValue: true,
  });
  await sleep(2500);
}

const expression = `(() => {
  const rect = (selector) => document.querySelector(selector)?.getBoundingClientRect() ?? null;
  const box = (selector) => {
    const b = rect(selector);
    return b ? { top: Math.round(b.top), bottom: Math.round(b.bottom), height: Math.round(b.height) } : null;
  };
  const bar = rect('.pdf-bar');
  const reader = document.querySelector('.reader');
  return JSON.stringify({
    viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio },
    surface: document.querySelector('.pdf-reader') ? 'pdf' : (document.querySelector('.paper') ? 'structured' : 'none'),
    pdfPages: document.querySelectorAll('.pdf-page').length,
    pdfCanvases: document.querySelectorAll('.pdf-page canvas').length,
    study: box('.study'),
    column: box('.reader-column'),
    reader: box('.reader'),
    readerScroll: reader ? { scrollTop: Math.round(reader.scrollTop), scrollHeight: reader.scrollHeight, clientHeight: reader.clientHeight } : null,
    bar: box('.pdf-bar'),
    barVisible: bar ? (bar.bottom <= window.innerHeight + 1 && bar.top >= 0) : null,
    paper: box('.paper'),
    paperFooter: box('.page-num'),
    paperFooterText: document.querySelector('.page-num')?.textContent?.trim() ?? null,
    paperFooterIsLastChild: (() => {
      const paper = document.querySelector('.paper');
      const footer = document.querySelector('.page-num');
      return paper && footer ? paper.lastElementChild === footer : null;
    })(),
    pageBar: box('.page-bar'),
    tip: box('.reader-tip'),
    docScroll: {
      scrollHeight: document.documentElement.scrollHeight,
      clientHeight: document.documentElement.clientHeight,
      scrollTop: Math.round(window.scrollY),
    },
    note: document.querySelector('.pdf-note')?.textContent?.trim() ?? null,
  }, null, 1);
})()`;

const result = await send('Runtime.evaluate', { expression, returnByValue: true });
console.log(result?.result?.value ?? JSON.stringify(result));

const shot = await send('Page.captureScreenshot', { format: 'png' });
if (shot?.data) {
  writeFileSync(out, Buffer.from(shot.data, 'base64'));
  console.log(`\n截图已保存：${out}`);
}

ws.close();
chrome.kill();
