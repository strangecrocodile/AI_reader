import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import ChapterNav from '../components/ChapterNav.jsx';

const CHAPTERS = [
  { id: 'ch1', num: '01', title: '函数与极限' },
  { id: 'ch2', num: '02', title: '导数与微分' },
  { id: 'ch3', num: '03', title: '微分中值定理' },
];

function renderNav(props) {
  return render(<ChapterNav chapters={CHAPTERS} onSelect={() => {}} {...props} />);
}

describe('ChapterNav', () => {
  it('下拉列出全部章节，并选中当前章', () => {
    renderNav({ currentId: 'ch2' });

    const select = screen.getByLabelText('选择章节');
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      'ch1',
      'ch2',
      'ch3',
    ]);
    expect(select.options[1].textContent).toBe('02 · 导数与微分');
    expect(select).toHaveValue('ch2');
  });

  it('第一章禁用「上一章」，最后一章禁用「下一章」', () => {
    const { unmount } = renderNav({ currentId: 'ch1' });
    expect(screen.getByRole('button', { name: /上一章/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /下一章/ })).toBeEnabled();
    unmount();

    renderNav({ currentId: 'ch3' });
    expect(screen.getByRole('button', { name: /上一章/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: /下一章/ })).toBeDisabled();
  });

  it('只有一章时两个按钮都禁用（不会跳到自己）', () => {
    render(<ChapterNav chapters={[CHAPTERS[0]]} currentId="ch1" onSelect={() => {}} />);

    expect(screen.getByRole('button', { name: /上一章/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /下一章/ })).toBeDisabled();
  });

  it('上一章 / 下一章回调的是相邻章节的 id', () => {
    const onSelect = vi.fn();
    renderNav({ currentId: 'ch2', onSelect });

    fireEvent.click(screen.getByRole('button', { name: /上一章/ }));
    expect(onSelect).toHaveBeenCalledWith('ch1');

    fireEvent.click(screen.getByRole('button', { name: /下一章/ }));
    expect(onSelect).toHaveBeenCalledWith('ch3');
  });

  it('从下拉里选章节也能切过去', () => {
    const onSelect = vi.fn();
    renderNav({ currentId: 'ch2', onSelect });

    fireEvent.change(screen.getByLabelText('选择章节'), { target: { value: 'ch3' } });

    expect(onSelect).toHaveBeenCalledWith('ch3');
  });

  it('当前章不在列表里（如从知识地图跳进来）不崩，两个按钮都禁用', () => {
    renderNav({ currentId: 'ch9' });

    expect(screen.getByLabelText('选择章节')).toHaveValue('');
    expect(screen.getByRole('button', { name: /上一章/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /下一章/ })).toBeDisabled();
  });

  it('没有章节时不渲染导航', () => {
    const { container } = render(<ChapterNav chapters={[]} onSelect={() => {}} />);

    expect(container).toBeEmptyDOMElement();
  });
});
