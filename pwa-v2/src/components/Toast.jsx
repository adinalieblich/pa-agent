import { useEffect, useState } from "react";
import { useShakeUndo } from "../lib/useShakeUndo";

/**
 * Self-dismissing toast with optional undo support.
 *
 * Two undo paths, both wired when ``onAction`` is provided:
 *   1. Tap the "undo" button on the toast.
 *   2. Shake the phone (iOS / Android — requires motion permission, which
 *      the caller should have already granted via :func:`requestMotionPermission`).
 *
 * Variants: success (emerald), error (ruby), muted (ink-soft), default ink.
 */
export default function Toast({
  message,
  variant = "default",
  onDismiss,
  duration = 2400,
  actionLabel,
  onAction,
}) {
  const hasAction = Boolean(actionLabel && onAction);
  // Slightly longer window when there's an undo to react to.
  const effectiveDuration = hasAction ? Math.max(duration, 5500) : duration;
  const [acting, setActing] = useState(false);

  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDismiss, effectiveDuration);
    return () => clearTimeout(t);
  }, [message, effectiveDuration, onDismiss]);

  // Listen for shake while the toast is visible AND it has an undo action.
  useShakeUndo(Boolean(message && hasAction && !acting), () => {
    if (!hasAction || acting) return;
    setActing(true);
    onAction();
    onDismiss();
  });

  if (!message) return null;
  const cls = "toast" + (variant !== "default" ? " " + variant : "");

  const handleClick = (e) => {
    e.stopPropagation();
    if (acting) return;
    setActing(true);
    onAction();
    onDismiss();
  };

  return (
    <div className={cls} role="status" aria-live="polite">
      <span className="toast-message">{message}</span>
      {hasAction && (
        <button
          type="button"
          className="toast-action"
          onClick={handleClick}
          disabled={acting}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
