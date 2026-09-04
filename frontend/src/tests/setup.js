import '@testing-library/jest-dom/vitest';

// jsdom 未实现 scrollIntoView，打桩避免测试报错
window.HTMLElement.prototype.scrollIntoView = function () {};
