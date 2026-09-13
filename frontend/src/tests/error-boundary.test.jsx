import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

function Boom() {
  throw new Error('组件爆炸了');
}

describe('错误边界', () => {
  it('渲染异常时给出可读页面，而不是整页白屏', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('页面出了点问题');
    expect(alert).toHaveTextContent('组件爆炸了');
    expect(screen.getByRole('button', { name: '重新加载页面' })).toBeInTheDocument();
    spy.mockRestore();
  });
});
