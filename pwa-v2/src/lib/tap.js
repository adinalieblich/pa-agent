/**
 * Build the spread-props needed to make any element behave as an
 * accessible tap target without wrapping it in a <button>.
 *
 * Returns: { role, tabIndex, onClick, onKeyDown, className } that you
 * spread onto the element. Optional ``extraClass`` is appended to
 * "tappable" so you don't lose existing classes.
 *
 * Why not <button>? Wrapping a <div> (or any flow-content element)
 * inside a <button> is invalid HTML, breaks Mobile Safari tap targets,
 * and produces React validateDOMNesting warnings. role="button" +
 * tabIndex=0 + a synthetic keyboard handler is the standards-compliant
 * pattern for "make this div clickable".
 */
export function tap(onClick, extraClass = "") {
  return {
    role: "button",
    tabIndex: 0,
    onClick,
    onKeyDown: (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onClick(e);
      }
    },
    className: ("tappable " + extraClass).trim(),
  };
}
