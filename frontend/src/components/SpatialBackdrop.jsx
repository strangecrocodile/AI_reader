import { useEffect, useRef } from 'react';

/**
 * 首页的淡色「三维学习空间」背景。
 *
 * ## 为什么不是 three.js
 *
 * 这里画的东西很简单：24 个球 + 一条闭合折线，绕 Y 轴慢慢转，透视投影。
 * 但 three.js 会为它带来 **736 kB（gzip 187 kB）** 的独立 chunk——首页装饰占掉了
 * 整个应用最大的一块载荷，而它在首屏就要加载。
 *
 * 所以改成 Canvas 2D 自己投影：几何、相机、旋转顺序、颜色与透明度都按原来的参数
 * 1:1 搬过来（相机 fov 48°、位置 z=7、`SphereGeometry(1)` 加 scale、Euler XYZ 的
 * `Rx·Ry` 旋转），视觉上保持同一个背景，代价是 0 依赖。
 *
 * 透视投影就三行：屏幕坐标 = 中心 + 世界坐标 / 深度 × 焦距，
 * 其中焦距 f = (H/2) / tan(fov/2)，球在屏幕上的半径 = f × 世界半径 / 深度。
 */

/** 与 three 版本一致的场景参数。 */
const CAMERA_Z = 7;
const FOV_DEG = 48;
const NODE_COUNT = 24;
const PRIMARY = { color: '10, 132, 255', opacity: 0.24 };
const ACCENT = { color: '48, 209, 88', opacity: 0.22 };
const LINE = { color: '142, 142, 147', opacity: 0.14 };

/** 节点在**模型空间**里的位置（与原来 `mesh.position.set(...)` 逐字对应）。 */
const NODES = Array.from({ length: NODE_COUNT }, (_, index) => {
  const ring = index / NODE_COUNT;
  return {
    radius: index % 5 === 0 ? 0.075 : 0.045,
    accent: index % 3 === 0,
    x: Math.cos(ring * Math.PI * 2) * (2.8 + (index % 4) * 0.32),
    y: Math.sin(ring * Math.PI * 2) * (1.3 + (index % 6) * 0.12),
    z: -1.8 + (index % 7) * 0.42,
  };
});

/** 绕 Y 轴旋转（three 的 Ry）。 */
function rotateY(p, angle) {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return { x: p.x * cos + p.z * sin, y: p.y, z: -p.x * sin + p.z * cos };
}

/** 绕 X 轴旋转（three 的 Rx）。Euler 顺序 XYZ 即 R = Rx·Ry，所以先绕 Y 再绕 X。 */
function rotateX(p, angle) {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return { x: p.x, y: p.y * cos - p.z * sin, z: p.y * sin + p.z * cos };
}

export default function SpatialBackdrop() {
  const mountRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || typeof window === 'undefined') return undefined;

    const canvas = document.createElement('canvas');
    // 拿不到 2D 上下文就什么都不画：背景是装饰，为它报错不值得
    const ctx = canvas.getContext?.('2d');
    if (!ctx) return undefined;

    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', '淡色三维学习空间背景');
    mount.appendChild(canvas);

    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    let reduceMotion = Boolean(mq?.matches);
    const handleMotionPreference = (event) => {
      reduceMotion = event.matches;
    };
    mq?.addEventListener?.('change', handleMotionPreference);

    let width = 0;
    let height = 0;
    let focal = 0;

    const resize = () => {
      const rect = mount.getBoundingClientRect();
      width = Math.max(rect.width, 1);
      height = Math.max(rect.height, 1);
      // 与原来 renderer.setPixelRatio(min(dpr, 1.8)) 同一个上限
      const ratio = Math.min(window.devicePixelRatio || 1, 1.8);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      focal = height / 2 / Math.tan((FOV_DEG * Math.PI) / 360);
    };

    /** 投影一个模型空间的点到视口坐标，并按深度排序返回。 */
    const project = (rotationX, rotationY) =>
      NODES.map((node) => {
        const world = rotateX(rotateY(node, rotationY), rotationX);
        const depth = CAMERA_Z - world.z;
        return {
          accent: node.accent,
          depth,
          x: width / 2 + (world.x / depth) * focal,
          y: height / 2 - (world.y / depth) * focal,
          r: (node.radius / depth) * focal,
        };
      }).sort((a, b) => b.depth - a.depth); // 远的先画（画家算法）

    let rotationY = 0;
    let frame = 0;

    const draw = () => {
      const rotationX = reduceMotion ? 0 : Math.sin(Date.now() * 0.00025) * 0.06;
      const points = project(rotationX, rotationY);

      ctx.clearRect(0, 0, width, height);

      // 连线先画，让球压在它上面（原来是靠深度测试，这里按画家算法近似）
      ctx.strokeStyle = `rgba(${LINE.color}, ${LINE.opacity})`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.closePath();
      ctx.stroke();

      for (const point of points) {
        const color = point.accent ? ACCENT : PRIMARY;
        ctx.fillStyle = `rgba(${color.color}, ${color.opacity})`;
        ctx.beginPath();
        ctx.arc(point.x, point.y, Math.max(point.r, 0.5), 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const animate = () => {
      if (!reduceMotion) rotationY += 0.0018;
      draw();
      frame = window.requestAnimationFrame(animate);
    };

    resize();
    window.addEventListener('resize', resize);
    animate();

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', resize);
      mq?.removeEventListener?.('change', handleMotionPreference);
      mount.replaceChildren();
    };
  }, []);

  return <div className="spatial-backdrop" ref={mountRef} />;
}
