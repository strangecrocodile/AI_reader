import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // 相对路径产物：构建后可直接本地预览，也便于静态托管
  base: './',
  server: {
    port: 3000,          // 自定义开发端口
    open: true,          // 启动时自动打开浏览器
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/tests/setup.js',
  },
});
