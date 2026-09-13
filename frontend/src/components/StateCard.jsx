/**
 * 通用状态卡片：空态 / 错误态 / 占位提示共用一套外观。
 * 样式复用 study.css 的 .placeholder-card（全局生效），这里只补动作区。
 */
export default function StateCard({ title, description, hint, actionLabel, onAction, children }) {
  return (
    <div className="placeholder-card state-card" role="status">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {hint && <p className="state-hint">{hint}</p>}
      {children}
      {(actionLabel || children) && (
        <div className="state-actions">
          {actionLabel && (
            <button className="back-home" type="button" onClick={onAction}>
              {actionLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
