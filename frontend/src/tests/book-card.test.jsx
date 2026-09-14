import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BookCard from '../components/BookCard.jsx';
import { configureApiBase } from '../services/api.js';

/** 一份最小可用的教材对象（BookCard 只用到封面与进度文本）。 */
function book(extra = {}) {
  return {
    id: 'bk1',
    title: '神经网络与深度学习',
    edition: '',
    progressText: '32% 已完成',
    cover: {
      series: 'AI LECTURER · IMPORTED TEXTBOOK',
      lines: ['神经网络与深度学习', '注：演示数据'],
      formula: ['f′(x₀) = lim Δx→0 …', '∫ f(x) dx'],
      footer: '第 4 章已识别',
    },
    ...extra,
  };
}

describe('BookCard 下载原文件', () => {
  it('留存了原文件时给出下载链接', () => {
    configureApiBase('http://localhost:8000');
    render(<BookCard book={book({ hasSource: true, sourceFormat: 'pdf' })} onSwap={() => {}} />);

    const link = screen.getByRole('link', { name: /下载原文件/ });
    expect(link).toHaveAttribute('href', 'http://localhost:8000/api/books/bk1/source');
    // 带 download 属性，点击就是下载而不是在标签页里预览
    expect(link).toHaveAttribute('download');
  });

  it('没有原文件时不给坏链接', () => {
    configureApiBase('http://localhost:8000');
    render(<BookCard book={book({ hasSource: false })} onSwap={() => {}} />);

    expect(screen.queryByRole('link', { name: /下载原文件/ })).toBeNull();
    // 更换教材按钮仍在
    expect(screen.getByRole('button', { name: /更换教材/ })).toBeInTheDocument();
  });

  it('字段缺失（老接口返回）时也不报错', () => {
    configureApiBase('http://localhost:8000');
    render(<BookCard book={book()} onSwap={() => {}} />);

    expect(screen.queryByRole('link', { name: /下载原文件/ })).toBeNull();
  });

  it('演示模式没有真实原文件，不显示下载入口', () => {
    configureApiBase('');
    render(<BookCard book={book({ hasSource: true })} onSwap={() => {}} />);

    expect(screen.queryByRole('link', { name: /下载原文件/ })).toBeNull();
  });
});
