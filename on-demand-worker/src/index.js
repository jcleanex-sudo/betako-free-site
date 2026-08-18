const json = (body, status, origin) => new Response(status === 204 ? null : JSON.stringify(body), {
  status,
  headers: {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
    "vary": "Origin",
    "cache-control": "no-store",
  },
});

const todayJst = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return origin === env.ALLOWED_ORIGIN ? json({ ok: true }, 204, origin) : json({ error: "origin blocked" }, 403, "null");
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "betako-on-demand" }, 200, origin === env.ALLOWED_ORIGIN ? origin : "null");
    }
    if (request.method === "GET" && url.pathname === "/official-preview") {
      if (origin !== env.ALLOWED_ORIGIN) return json({ error: "origin blocked" }, 403, "null");
      const venueId = String(url.searchParams.get("venue_id") || "").padStart(2, "0");
      const race = Number(url.searchParams.get("race"));
      const raceDate = url.searchParams.get("race_date") || "";
      if (!/^\d{2}$/.test(venueId) || Number(venueId) < 1 || Number(venueId) > 24 || !Number.isInteger(race) || race < 1 || race > 12) {
        return json({ error: "invalid race" }, 400, origin);
      }
      if (raceDate !== todayJst()) return json({ error: "only today's race can be fetched" }, 400, origin);

      const officialUrl = new URL("https://www.boatrace.jp/owpc/pc/race/beforeinfo");
      officialUrl.search = new URLSearchParams({ jcd: venueId, hd: raceDate.replaceAll("-", ""), rno: String(race) });
      try {
        const official = await fetch(officialUrl, {
          headers: {
            "user-agent": "Mozilla/5.0 BETAKO-Realtime/1.0",
            "accept": "text/html,application/xhtml+xml",
            "accept-language": "ja",
          },
        });
        if (!official.ok || !official.body) {
          console.error(JSON.stringify({ event: "official_preview_failed", status: official.status, venueId, race }));
          return json({ error: "official preview failed" }, 502, origin);
        }
        console.log(JSON.stringify({ event: "official_preview_ok", venueId, race }));
        return new Response(official.body, {
          status: 200,
          headers: {
            "content-type": "text/html; charset=utf-8",
            "access-control-allow-origin": origin,
            "vary": "Origin",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
          },
        });
      } catch (error) {
        console.error(JSON.stringify({ event: "official_preview_error", venueId, race, error: String(error) }));
        return json({ error: "official preview unavailable" }, 502, origin);
      }
    }
    if (request.method !== "POST" || url.pathname !== "/refresh") {
      return json({ error: "not found" }, 404, origin === env.ALLOWED_ORIGIN ? origin : "null");
    }
    if (origin !== env.ALLOWED_ORIGIN) return json({ error: "origin blocked" }, 403, "null");

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid json" }, 400, origin);
    }
    const venueId = String(body.venue_id || "").padStart(2, "0");
    const race = Number(body.race);
    if (!/^\d{2}$/.test(venueId) || Number(venueId) < 1 || Number(venueId) > 24 || !Number.isInteger(race) || race < 1 || race > 12) {
      return json({ error: "invalid race" }, 400, origin);
    }
    if (body.race_date !== todayJst()) return json({ error: "only today's race can be refreshed" }, 400, origin);

    const cache = caches.default;
    const lockKey = new Request(`https://betako-refresh-lock.invalid/${todayJst()}/${venueId}/${race}`);
    if (await cache.match(lockKey)) return json({ ok: true, status: "already_requested" }, 202, origin);

    const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/${env.WORKFLOW_FILE}/dispatches`, {
      method: "POST",
      headers: {
        "authorization": `Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": "BETAKO-On-Demand",
        "content-type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { venue_id: venueId, race: String(race) } }),
    });
    if (!response.ok) {
      console.error(JSON.stringify({ event: "dispatch_failed", status: response.status, venueId, race }));
      return json({ error: "refresh dispatch failed" }, 502, origin);
    }
    ctx.waitUntil(cache.put(lockKey, new Response("1", { headers: { "cache-control": "max-age=120" } })));
    console.log(JSON.stringify({ event: "refresh_dispatched", venueId, race }));
    return json({ ok: true, status: "requested", venue_id: venueId, race }, 202, origin);
  },
};
