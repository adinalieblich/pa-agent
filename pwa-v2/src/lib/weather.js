/**
 * Weather fetcher — Open-Meteo (free, no API key).
 *
 * Strategy:
 *   - On first load, ask for geolocation. Cache the granted coords in
 *     localStorage so we don't re-prompt the user every session.
 *   - If geolocation is denied or unavailable, fall back to Sydney
 *     (the only assumption we make about the user — easy to override
 *     via setManualLocation() later).
 *   - Cache the latest weather payload for 15 minutes so changing tabs
 *     doesn't refetch.
 */

const CACHE_KEY = "pa.weather";
const COORDS_KEY = "pa.geo";
const CACHE_MS = 15 * 60 * 1000;
const FALLBACK = { lat: -33.8688, lon: 151.2093, label: "Sydney" };

// Map Open-Meteo weather codes to emoji + short label.
// https://open-meteo.com/en/docs#api_form (weather_code section)
const CODE_TABLE = {
  0:  ["☀️", "clear"],
  1:  ["🌤", "mostly clear"],
  2:  ["⛅", "partly cloudy"],
  3:  ["☁️", "overcast"],
  45: ["🌫", "fog"],
  48: ["🌫", "rime fog"],
  51: ["🌦", "light drizzle"],
  53: ["🌦", "drizzle"],
  55: ["🌧", "drizzle"],
  61: ["🌧", "light rain"],
  63: ["🌧", "rain"],
  65: ["🌧", "heavy rain"],
  66: ["🌧", "freezing rain"],
  67: ["🌧", "freezing rain"],
  71: ["🌨", "snow"],
  73: ["🌨", "snow"],
  75: ["🌨", "heavy snow"],
  77: ["🌨", "snow grains"],
  80: ["🌧", "rain showers"],
  81: ["🌧", "rain showers"],
  82: ["⛈", "violent showers"],
  85: ["🌨", "snow showers"],
  86: ["🌨", "snow showers"],
  95: ["⛈", "thunderstorm"],
  96: ["⛈", "storm + hail"],
  99: ["⛈", "storm + hail"],
};

function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (!obj.fetched_at || Date.now() - obj.fetched_at > CACHE_MS) return null;
    return obj;
  } catch {
    return null;
  }
}

function writeCache(obj) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ ...obj, fetched_at: Date.now() }));
  } catch {/* ignore */}
}

function readCoords() {
  try {
    const raw = localStorage.getItem(COORDS_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeCoords(coords) {
  try {
    localStorage.setItem(COORDS_KEY, JSON.stringify(coords));
  } catch {/* ignore */}
}

async function getCoords() {
  const cached = readCoords();
  if (cached) return cached;
  if (!("geolocation" in navigator)) return FALLBACK;
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const coords = { lat: pos.coords.latitude, lon: pos.coords.longitude, label: "you" };
        writeCoords(coords);
        resolve(coords);
      },
      () => resolve(FALLBACK),
      { timeout: 5000, maximumAge: 60 * 60 * 1000 }
    );
  });
}

/**
 * Fetch current weather. Returns { icon, temp_c, label, place } or null on failure.
 * Cached for 15 minutes in localStorage.
 */
export async function getWeather() {
  const cached = readCache();
  if (cached) return cached;
  try {
    const { lat, lon, label: place } = await getCoords();
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,weather_code&timezone=auto`;
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const data = await resp.json();
    const code = data?.current?.weather_code;
    const temp = data?.current?.temperature_2m;
    const [icon, label] = CODE_TABLE[code] || ["·", "—"];
    const result = {
      icon,
      label,
      temp_c: typeof temp === "number" ? Math.round(temp) : null,
      place,
    };
    writeCache(result);
    return result;
  } catch {
    return null;
  }
}

/** Clear cached coords (forces a re-prompt next call). */
export function resetWeatherCache() {
  try {
    localStorage.removeItem(CACHE_KEY);
    localStorage.removeItem(COORDS_KEY);
  } catch {/* ignore */}
}
