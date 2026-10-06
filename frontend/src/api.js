const BASE = "";

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method };
  if (form) {
    opts.body = form;
  } else if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep default */
    }
    throw new Error(msg);
  }
  return res.json();
}

export const fmtInt = (n) => (n ?? 0).toLocaleString();
export const fmtRate = (x) => (x ?? 0).toFixed(2);
export const fmtDate = (ts) =>
  ts == null ? "—" : new Date(ts * 1000).toISOString().slice(0, 10);
export const fmtDT = (ts) => {
  if (ts == null) return "—";
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 16).replace("T", " ");
};
export const shortHash = (h) => (h ? h.slice(0, 10) : "");

/** datetime-local input value -> unix seconds */
export const localToUnix = (v) => (v ? Math.floor(new Date(v).getTime() / 1000) : null);
/** unix seconds -> datetime-local input value */
export const unixToLocal = (ts) => {
  if (ts == null) return "";
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
