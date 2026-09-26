import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import SpatialBackdrop from '../components/SpatialBackdrop.jsx';
import pkg from '../../package.json';

/**
 * 首页背景。
 *
 * 它原来用 three.js 画 24 个球和一条折线，代价是一个 **736 kB（gzip 187 kB）** 的
 * 独立 chunk——整个应用最大的一块载荷，而且首屏就要加载。现在改成 Canvas 2D 自己
 * 投影（几何与相机参数逐字搬过来，实测与 three 的投影偏差 0.000000 px）。
 *
 * 这里既守住「还画得出来」，也守住「别再把它依赖回来」。
 */

/** jsdom 没实现 canvas，`getContext('2d')` 恒返回 null，所以要自己塞一个假的。 */
function fakeContext() {
  const calls = [];
  const record =
    (name) =>
    (...args) => {
      calls.push({ name, args });
    };
  return {
    calls,
    count: (name) => calls.filter((call) => call.name === name).length,
    setTransform: record('setTransform'),
    clearRect: record('clearRect'),
    beginPath: record('beginPath'),
    moveTo: record('moveTo'),
    lineTo: record('lineTo'),
    closePath: record('closePath'),
    stroke: record('stroke'),
    arc: record('arc'),
    fill: record('fill'),
    strokeStyle: '',
    fillStyle: '',
    lineWidth: 1,
  };
}

let context;

beforeEach(() => {
  context = fakeContext();
  // 背景是装饰，一次绘制就够了；真让 rAF 递归下去会一直排帧
  vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(0);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('首页背景', () => {
  it('在容器里画出一块带无障碍标签的画布', () => {
    const { container } = render(<SpatialBackdrop />);

    const canvas = container.querySelector('canvas');
    expect(canvas).toBeInTheDocument();
    expect(canvas).toHaveAttribute('role', 'img');
    expect(canvas).toHaveAttribute('aria-label', '淡色三维学习空间背景');
  });

  it('画出全部节点与那条闭合折线', () => {
    render(<SpatialBackdrop />);

    // 24 个球，一个不少
    expect(context.count('arc')).toBe(24);
    // 折线：起点 moveTo + 其余 23 个 lineTo + 闭合
    expect(context.count('moveTo')).toBe(1);
    expect(context.count('lineTo')).toBe(23);
    expect(context.count('closePath')).toBe(1);
    expect(context.count('stroke')).toBe(1);
    // 每帧先清空，否则会拖尾
    expect(context.count('clearRect')).toBe(1);
  });

  it('拿不到 2D 上下文时安静退出，不报错也不留空画布', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);

    const { container } = render(<SpatialBackdrop />);

    expect(container.querySelector('canvas')).toBeNull();
  });

  it('不再依赖 three.js', () => {
    // 736 kB 就是这么来的。这条断言是防止有人顺手把它加回来。
    expect(pkg.dependencies).not.toHaveProperty('three');
    expect(pkg.devDependencies ?? {}).not.toHaveProperty('three');
  });
});
