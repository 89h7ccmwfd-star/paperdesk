// Ausloeser fuer den Bot: GitHub startet geplante Laeufe oft Stunden zu spaet oder gar nicht
// (06.11.2026: 2 von ~36 Starts, erster um 13:36 New York). Cloudflare-Cron laeuft puenktlich alle 5 Minuten
// und stoesst tick.yml per workflow_dispatch an, wenn zur Boersenzeit kein Lauf aktiv oder wartend ist.
// Nur Simulation: der Worker startet den Papierhandel-Lauf, sonst nichts.

const REPO = "89h7ccmwfd-star/paperdesk";
const WORKFLOW = "tick.yml";

// Gleicher Kalender wie paperdesk/config.py (tests/test_trigger.py prueft, dass beide gleich sind).
export const HOLIDAYS = new Set(["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
  "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
  "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"]);
export const EARLY_CLOSE = new Set(["2026-11-27", "2026-12-24", "2027-11-26"]);

/** Datum, Wochentag und Minute des Tages in New York (Sommer- und Winterzeit ueber Intl). */
export function nyClock(date) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", weekday: "short", hourCycle: "h23",
  }).formatToParts(date).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, weekday: p.weekday, minute: Number(p.hour) * 60 + Number(p.minute) };
}

/** Soll jetzt ein Lauf da sein? Ab 9:30 bis Boersenschluss. Frueher nicht: cloud-loop.sh beendet sich vor
 * Boersenstart sofort, wenn sich nichts geaendert hat. */
export function shouldRun(date) {
  const { day, weekday, minute } = nyClock(date);
  if (weekday === "Sat" || weekday === "Sun" || HOLIDAYS.has(day)) return false;
  const close = EARLY_CLOSE.has(day) ? 13 * 60 : 16 * 60;
  return minute >= 9 * 60 + 30 && minute < close;
}

async function gh(env, path, init = {}) {
  const res = await fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "paperdesk-trigger", ...(init.headers || {}),
    },
  });
  if (!res.ok && res.status !== 204) throw new Error(`GitHub ${path}: ${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

/** Ein Takt: Laeuft oder wartet schon ein tick-Lauf, nichts tun; sonst einen anstossen. */
export async function beat(env, now = new Date()) {
  if (!shouldRun(now)) return "ausserhalb der Boersenzeit";
  for (const status of ["in_progress", "queued", "waiting", "pending", "requested"]) {
    const r = await gh(env, `/actions/workflows/${WORKFLOW}/runs?status=${status}&per_page=1`);
    if (r.total_count > 0) return `Lauf aktiv (${status})`;
  }
  await gh(env, `/actions/workflows/${WORKFLOW}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main" }) });
  return "Lauf angestossen";
}

/** Nur lesen: Ist der Token gueltig und gerade Boersenzeit? Stoesst nichts an. */
export async function check(env, now = new Date()) {
  let token;
  try {
    const wf = await gh(env, `/actions/workflows/${WORKFLOW}`);
    token = `ok (${wf.state})`;
  } catch (e) {
    token = env.GH_TOKEN ? `Fehler: ${String(e.message).slice(0, 80)}` : "fehlt";
  }
  return { boersenzeit: shouldRun(now), token, ny: nyClock(now) };
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname !== "/check") return new Response("paperdesk-trigger", { status: 404 });
    return Response.json(await check(env));
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(beat(env, new Date(event.scheduledTime)).then((msg) => console.log(msg)));
  },
};
