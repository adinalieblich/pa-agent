import { useRef, useState } from "react";

/**
 * Hook that powers swipe-right-to-done on any row component.
 *
 * Returns:
 *   handlers — spread onto the swipeable element (touch events).
 *   style    — apply to the same element to drive the transform/opacity.
 *   swipeProgress — 0..1 — drive a background reveal underneath.
 *   commit() — programmatic equivalent (used by a check-button tap).
 *   armed    — true while the user is mid-drag.
 *
 * Usage:
 *
 *     const swipe = useSwipeDone(() => onDone(row));
 *     return (
 *       <div className="wrap">
 *         <div className="swipe-bg" style={{ opacity: swipe.swipeProgress }}>
 *           ✓ done
 *         </div>
 *         <div className="row" style={swipe.style} {...swipe.handlers} />
 *       </div>
 *     );
 */
export function useSwipeDone(onCommit, {
  commitPx = 120,
  maxDx = 220,
  verticalDeadZone = 30,
  animMs = 220,
} = {}) {
  const [dx, setDx] = useState(0);
  const [doneAnim, setDoneAnim] = useState(false);
  const touchStart = useRef(null);
  const decided = useRef(null); // 'h' | 'v' | null

  const reset = () => setDx(0);

  const commit = () => {
    setDoneAnim(true);
    window.setTimeout(() => {
      onCommit && onCommit();
    }, animMs);
  };

  const onTouchStart = (e) => {
    const t = e.touches[0];
    touchStart.current = { x: t.clientX, y: t.clientY };
    decided.current = null;
  };

  const onTouchMove = (e) => {
    if (!touchStart.current) return;
    const t = e.touches[0];
    const rawDx = t.clientX - touchStart.current.x;
    const rawDy = t.clientY - touchStart.current.y;
    if (decided.current === null) {
      if (Math.abs(rawDx) < 8 && Math.abs(rawDy) < 8) return;
      decided.current = Math.abs(rawDx) > Math.abs(rawDy) ? "h" : "v";
    }
    if (decided.current === "v") return;
    if (Math.abs(rawDy) > verticalDeadZone) {
      reset();
      return;
    }
    setDx(Math.max(0, Math.min(rawDx, maxDx)));
  };

  const onTouchEnd = () => {
    if (decided.current === "h" && dx > commitPx) commit();
    else reset();
    touchStart.current = null;
    decided.current = null;
  };

  const style = doneAnim
    ? {
        transform: "translateX(110%)",
        opacity: 0,
        transition: `transform ${animMs}ms ease-out, opacity ${animMs}ms ease-out`,
      }
    : {
        transform: `translateX(${dx}px)`,
        transition: dx === 0 ? "transform 180ms ease-out" : "none",
      };

  return {
    handlers: {
      onTouchStart,
      onTouchMove,
      onTouchEnd,
      onTouchCancel: onTouchEnd,
    },
    style,
    swipeProgress: Math.min(1, dx / commitPx),
    armed: dx > 0 && !doneAnim,
    commit,
  };
}
