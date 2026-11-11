// Small pure helpers for turning data into text.

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  // A plain date (2026-11-01) is a calendar day, not a moment: do not shift it by time zone.
  const date = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00`) : new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 1 decimal under 100, none above: 59.9, 142. */
export function formatNumber(value: number | null | undefined, unit = ""): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const digits = Math.abs(value) < 100 && !Number.isInteger(value) ? 1 : 0;
  const text = value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return unit ? `${text} ${unit}` : text;
}

export function formatDuration(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  if (minutes === 0) return `${rest} s`;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

export function formatMinutes(minutes: number | null | undefined): string {
  if (!minutes) return "";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/** "rtx 3070, B550 ;  0x124" -> ["rtx 3070", "B550", "0x124"] */
export function splitList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/[,;\n]/)) {
    const item = raw.trim().replace(/\s+/g, " ");
    if (item && !seen.has(item.toLowerCase())) {
      seen.add(item.toLowerCase());
      out.push(item);
    }
  }
  return out;
}

/** snake_case evidence keys -> "Cpu temp max c" style labels people can read. */
export function humanizeKey(key: string): string {
  const words = key
    .replace(/_pct$/, " %")
    .replace(/_c$/, " °C")
    .replace(/_mhz$/, " MHz")
    .replace(/_gb$/, " GB")
    .replace(/_ms$/, " ms")
    .replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatEvidence(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") {
    return /^\d{4}-\d{2}-\d{2}T/.test(value) ? formatDateTime(value) : value;
  }
  if (Array.isArray(value)) return value.map(formatEvidence).join(", ");
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key}: ${formatEvidence(item)}`)
    .join(", ");
}

export function today(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}
