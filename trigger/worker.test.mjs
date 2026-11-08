// node --test trigger/worker.test.mjs   (ohne Netz, fetch wird ersetzt)
import assert from "node:assert/strict";
import { test } from "node:test";
import { beat, shouldRun } from "./worker.js";

const at = (iso) => new Date(iso);

test("Boersenzeit New York, Sommer- und Winterzeit", () => {
  assert.equal(shouldRun(at("2026-11-06T14:30:00Z")), true); // Fr 9:30 NY (Winterzeit)
  assert.equal(shouldRun(at("2026-11-06T14:25:00Z")), false); // 9:25 NY
  assert.equal(shouldRun(at("2026-11-06T20:55:00Z")), true); // 15:55 NY
  assert.equal(shouldRun(at("2026-11-06T21:00:00Z")), false); // 16:00 NY
  assert.equal(shouldRun(at("2026-10-30T13:30:00Z")), true); // 9:30 NY (Sommerzeit)
  assert.equal(shouldRun(at("2026-11-07T15:00:00Z")), false); // Samstag
  assert.equal(shouldRun(at("2026-11-26T15:00:00Z")), false); // Thanksgiving
  assert.equal(shouldRun(at("2026-11-27T18:30:00Z")), false); // Halbtag, 13:30 NY
});

function fakeGitHub(active) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push([init.method || "GET", url]);
    if (url.includes("/dispatches")) return new Response(null, { status: 204 });
    const status = new URL(url).searchParams.get("status");
    return Response.json({ total_count: status === active ? 1 : 0 });
  };
  return calls;
}

test("kein Lauf aktiv: tick.yml wird angestossen", async () => {
  const calls = fakeGitHub(null);
  assert.equal(await beat({ GH_TOKEN: "x" }, at("2026-11-06T14:40:00Z")), "Lauf angestossen");
  assert.deepEqual(calls.at(-1), ["POST", "https://api.github.com/repos/89h7ccmwfd-star/paperdesk/actions/workflows/tick.yml/dispatches"]);
});

test("Lauf aktiv oder wartend: nichts anstossen", async () => {
  for (const s of ["in_progress", "queued"]) {
    const calls = fakeGitHub(s);
    assert.equal(await beat({ GH_TOKEN: "x" }, at("2026-11-06T15:00:00Z")), `Lauf aktiv (${s})`);
    assert.ok(!calls.some(([m]) => m === "POST"));
  }
});

test("ausserhalb der Boersenzeit: kein Aufruf bei GitHub", async () => {
  const calls = fakeGitHub(null);
  assert.equal(await beat({ GH_TOKEN: "x" }, at("2026-11-07T15:00:00Z")), "ausserhalb der Boersenzeit");
  assert.equal(calls.length, 0);
});

test("Pruefung stoesst nichts an und meldet fehlenden Token", async () => {
  globalThis.fetch = async () => new Response("Bad credentials", { status: 401 });
  const r = await (await import("./worker.js")).check({}, at("2026-11-06T15:00:00Z"));
  assert.equal(r.token, "fehlt");
  assert.equal(r.boersenzeit, true);
});
