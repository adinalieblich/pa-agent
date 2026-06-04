/**
 * Display-formatting helpers used across screens.
 *
 * Keep all date / number formatting here so screen components stay
 * declarative and tests can pin formatting decisions in one place.
 */

const WEEKDAYS_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** "Mon · 4 May" uppercase — matches mockup's .page-date format. */
export function pageDateLabel(d = new Date()) {
  const wd = WEEKDAYS_SHORT[d.getDay()];
  return `${wd} · ${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}

/** Greeting word for the page title, by local hour. */
export function greetingWord(d = new Date()) {
  const h = d.getHours();
  if (h < 5)  return "evening"; // small hours read as still last evening
  if (h < 12) return "morning";
  if (h < 18) return "afternoon";
  return "evening";
}

/**
 * Greeting prefix — "good" most days, "happy" on weekends.
 *
 * Reads alongside greetingWord/greetingEmoji to produce the locked
 * variants from PROJECT_STATUS: "good morning ☕" / "good evening 🌙" /
 * "happy weekend 🌴".
 */
export function greetingPrefix(d = new Date()) {
  const dow = d.getDay();
  return (dow === 0 || dow === 6) ? "happy" : "good";
}

/** Weekend gets its own "word", overriding the time-of-day variant. */
export function greetingWordPolished(d = new Date()) {
  const dow = d.getDay();
  if (dow === 0 || dow === 6) return "weekend";
  return greetingWord(d);
}

/** Trailing emoji matching the greeting word. Empty string when unknown. */
export function greetingEmoji(d = new Date()) {
  const dow = d.getDay();
  if (dow === 0 || dow === 6) return "🌴";
  const word = greetingWord(d);
  switch (word) {
    case "morning":   return "☕";
    case "evening":   return "🌙";
    case "afternoon": return ""; // no emoji per locked decision
    default:          return "";
  }
}

/**
 * Relative date label for a YYYY-MM-DD string. "today" / "tomorrow" /
 * "due Fri" / "3d overdue" / "12 May".
 *
 * Returns null if input is falsy.
 */
export function relativeDueLabel(yyyyMmDd) {
  if (!yyyyMmDd) return null;
  const due = new Date(yyyyMmDd + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((due - today) / 86400000);
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  if (days === -1) return "yesterday";
  if (days < -1) return `${-days}d overdue`;
  if (days < 7) return `due ${WEEKDAYS_SHORT[due.getDay()]}`;
  return `${due.getDate()} ${MONTHS_SHORT[due.getMonth()]}`;
}

/** Map a Priority string to a tag CSS class (jewel-tone). */
export function priorityTagClass(priority) {
  switch (priority) {
    case "Urgent":    return "ruby";
    case "Important": return "topaz";
    case "Someday":   return "sapphire";
    case "Normal":
    default:          return "amethyst";
  }
}

/** Lowercased label suitable for the tag pill ("urgent", "normal", ...). */
export function priorityTagLabel(priority) {
  return (priority || "normal").toLowerCase();
}
