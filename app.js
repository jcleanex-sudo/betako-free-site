const venues = ["桐生","戸田","江戸川","平和島","多摩川","浜名湖","蒲郡","常滑","津","三国","びわこ","住之江","尼崎","鳴門","丸亀","児島","宮島","徳山","下関","若松","芦屋","福岡","唐津","大村"];
const venueSelect = document.querySelector("#venue");
const raceSelect = document.querySelector("#race");
const dateInput = document.querySelector("#raceDate");
const pendingRefreshes = new Set();
const PUBLIC_THRESHOLDS = Object.freeze({ score: 75, agreement: 75, dataRate: 100 });
const FIXED_PORTFOLIO_COUNTS = Object.freeze({ trifecta: 6, trio: 2, exacta: 2, quinella: 3 });
let latestManualPrediction = null;

const jstToday = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });

venueSelect.replaceChildren(new Option("公式開催場を確認中", ""));
venueSelect.disabled = true;
for (let race = 1; race <= 12; race += 1) raceSelect.add(new Option(`${race}R`, String(race)));
dateInput.value = jstToday();

function populateActiveVenues(payload) {
  const official = Array.isArray(payload.official_venues) && payload.official_venues.length
    ? payload.official_venues
    : [...new Set((payload.all_races || []).map((item) => item.venue))].map((venue) => {
        const venueRaces = (payload.all_races || []).filter((item) => item.venue === venue);
        const fetchedRaces = venueRaces.length;
        const referenceRate = venueRaces.length
          ? Math.min(...venueRaces.map((item) => Number(item.data_rate || 0)))
          : 0;
        return {
          venue,
          venue_id: String(venueRaces[0]?.venue_id || venues.indexOf(venue) + 1).padStart(2, "0"),
          fetched_races: fetchedRaces,
          reference_rate: referenceRate,
          complete: fetchedRaces === 12,
        };
      });
  const current = venueSelect.value;
  const activeByVenue = new Map(official.map((item) => [item.venue, item]));
  const venueOptions = venues.map((venue, index) => {
    const active = activeByVenue.get(venue);
    const venueId = String(active?.venue_id || index + 1).padStart(2, "0");
    const label = active
      ? `${venueId} ${venue}${active.complete === false ? `（${active.fetched_races}/12R）` : ""}`
      : `${venueId} ${venue}（本日非開催）`;
    const option = new Option(label, venue);
    option.disabled = !active;
    return option;
  });
  venueSelect.replaceChildren(...venueOptions);
  const currentDate = payload.race_date === jstToday();
  const available = currentDate && payload.status === "OK" && official.length > 0 && official.every((item) => item.complete !== false);
  venueSelect.disabled = !available;
  document.querySelector("#predictionForm button[type='submit']").disabled = !available;
  const preferred = official.some((item) => item.venue === current)
    ? current
    : payload.rankings?.[0]?.venue || official[0]?.venue || "";
  venueSelect.value = preferred;
}

function buildBetPlan(contenders = [], leadingPick = "") {
  const contenderBoats = contenders.map((item) => String(item.boat));
  const leadingBoats = String(leadingPick).split("-").filter((boat) => contenderBoats.includes(boat));
  const boats = [...new Set([...leadingBoats, ...contenderBoats])];
  if (boats.length < 5) return { main: [], cover: [] };
  const ticket = (first, second, third) => `${boats[first]}-${boats[second]}-${boats[third]}`;
  return {
    main: [ticket(0, 1, 2), ticket(0, 2, 1), ticket(0, 1, 3), ticket(0, 2, 3), ticket(0, 3, 1), ticket(0, 3, 2)],
    cover: [ticket(1, 0, 2), ticket(2, 0, 1), ticket(1, 0, 3), ticket(2, 0, 3), ticket(0, 1, 4), ticket(0, 2, 4)],
  };
}

function buildAxisEvidence(match) {
  const contenders = match?.contenders || [];
  const axisBoat = Number(String(match?.pick || "").split("-")[0]);
  const axis = contenders.find((item) => Number(item.boat) === axisBoat) || contenders[0];
  const runnerUp = contenders.find((item) => Number(item.boat) !== Number(axis?.boat));
  if (!axis || !runnerUp) return [];

  const axisProbability = Number(axis.relative_win_probability || 0);
  const runnerUpProbability = Number(runnerUp.relative_win_probability || 0);
  const probabilityGap = axisProbability - runnerUpProbability;
  const modelPointGap = axisProbability > 0 && runnerUpProbability > 0
    ? 14.16 * Math.log(axisProbability / runnerUpProbability)
    : 0;
  const evidence = [
    `軸比較：${axis.boat}号艇 ${axis.name} ${axisProbability.toFixed(1)}%／次点 ${runnerUp.boat}号艇 ${runnerUp.name} ${runnerUpProbability.toFixed(1)}%（確率差 ${probabilityGap.toFixed(1)}pt・内部評価差 ${modelPointGap.toFixed(1)}点）`,
  ];

  if (axis.class === "B2") {
    const courseText = Number(axis.boat) === 1
      ? "1コース補正 +39.4点"
      : `${axis.boat}コース補正を適用`;
    evidence.push(`B2確認：級別補正 -1.4点を適用済み。${courseText}と基礎成績を合わせた結果です`);
  }

  const strict = Number(match.score) >= PUBLIC_THRESHOLDS.score
    && Number(match.agreement) >= PUBLIC_THRESHOLDS.agreement
    && Number(match.data_rate) >= PUBLIC_THRESHOLDS.dataRate;
  evidence.push(strict
    ? `採用判定：指数 ${Number(match.score).toFixed(1)}・因子一致 ${Number(match.agreement).toFixed(0)}%で厳格基準を通過`
    : `見送り判定：指数 ${Number(match.score).toFixed(1)}・因子一致 ${Number(match.agreement).toFixed(0)}%。買い目は比較用で本線採用ではありません`);
  return evidence;
}

function renderFormation(target, tickets) {
  if (!tickets.length) {
    target.classList.remove("singleFormation");
    target.textContent = "--";
    return;
  }
  const formations = compressTicketsToFormations(tickets);
  target.classList.toggle("singleFormation", formations.length === 1);
  target.replaceChildren(...formations.map((formation, formationIndex) => {
    const card = document.createElement("div");
    card.className = "formationCard";
    const header = document.createElement("div");
    header.className = "formationHeader";
    header.innerHTML = `<b>FORMATION ${formationIndex + 1}</b><em>${formation.points}点</em>`;
    const columns = document.createElement("div");
    columns.className = "formationColumns";
    [["1着", formation.first], ["2着", formation.second], ["3着", formation.third]].forEach(([label, boats]) => {
      const column = document.createElement("section");
      const caption = document.createElement("small");
      caption.textContent = label;
      const choices = document.createElement("div");
      choices.className = "boatChoices";
      boats.forEach((boat) => {
        const choice = document.createElement("span");
        choice.className = `boatChoice boat${boat}`;
        choice.textContent = boat;
        choice.setAttribute("aria-label", `${label} ${boat}号艇`);
        choices.append(choice);
      });
      column.append(caption, choices);
      columns.append(column);
    });
    card.append(header, columns);
    return card;
  }));
}

function ticketText(ticket) {
  return typeof ticket === "string" ? ticket : ticket?.pick || "--";
}

function compressTicketsToFormations(tickets = []) {
  const parsed = [...new Set(tickets.map(ticketText))]
    .map((pick) => pick.split("-"))
    .filter((boats) => boats.length === 3 && new Set(boats).size === 3);
  const count = parsed.length;
  if (!count) return [];
  const candidates = [];
  for (let mask = 1; mask < (1 << count); mask += 1) {
    const selected = parsed.filter((_, index) => mask & (1 << index));
    const first = [...new Set(selected.map((boats) => boats[0]))];
    const second = [...new Set(selected.map((boats) => boats[1]))];
    const third = [...new Set(selected.map((boats) => boats[2]))];
    const selectedSet = new Set(selected.map((boats) => boats.join("-")));
    const generated = [];
    first.forEach((a) => second.forEach((b) => third.forEach((c) => {
      if (a !== b && a !== c && b !== c) generated.push(`${a}-${b}-${c}`);
    })));
    if (generated.length === selected.length && generated.every((pick) => selectedSet.has(pick))) {
      candidates.push({ mask, first, second, third, points: generated.length });
    }
  }
  const memo = new Map();
  const solve = (mask) => {
    if (!mask) return [];
    if (memo.has(mask)) return memo.get(mask);
    const anchor = mask & -mask;
    let best = null;
    candidates.forEach((candidate) => {
      if (!(candidate.mask & anchor) || (candidate.mask & mask) !== candidate.mask) return;
      const tail = solve(mask ^ candidate.mask);
      if (!tail) return;
      const option = [candidate, ...tail];
      const optionChoices = option.reduce((sum, item) => sum + item.first.length + item.second.length + item.third.length, 0);
      const bestChoices = best?.reduce((sum, item) => sum + item.first.length + item.second.length + item.third.length, 0) ?? Infinity;
      if (!best || option.length < best.length || (option.length === best.length && optionChoices < bestChoices)) best = option;
    });
    memo.set(mask, best);
    return best;
  };
  return solve((1 << count) - 1) || [];
}

function formationCopyLines(label, tickets) {
  const formations = compressTicketsToFormations(tickets);
  return formations.map((formation, index) => {
    const suffix = formations.length > 1 ? String(index + 1) : "";
    return `${label}${suffix}:${formation.first.join("")}-${formation.second.join("")}-${formation.third.join("")}(${formation.points}点)`;
  });
}

function portfolioCopyLines(portfolio = {}) {
  const labels = { trio: "3連複", exacta: "2連単", quinella: "2連複" };
  return Object.entries(labels).map(([market, label]) => {
    const picks = (portfolio[market] || []).map(ticketText).filter((pick) => pick !== "--");
    return picks.length ? `${label}:${picks.join("・")}(${picks.length}点)` : null;
  }).filter(Boolean);
}

function buildDevelopmentPrediction(leadingPick, reasons = [], finalReady = false) {
  const boats = String(leadingPick || "").split("-").filter(Boolean);
  if (boats.length < 3) return "データ不足のため展開を確定できません。見送り対象です。";
  const [axis, second, third] = boats;
  const phase = finalReady ? "展示後データでは" : "朝データでは";
  const reason = reasons.filter(Boolean).slice(0, 2).join("。 ");
  return `${phase}${axis}号艇の先頭争いを軸に、${second}号艇と${third}号艇の連下進出を評価。${reason ? `${reason}。` : "進入や展示気配が変われば評価を下げます。"}`;
}

function buildManualCopyText(payload) {
  const date = String(payload.date || "").replaceAll("-", "/");
  const fixedPortfolio = payload.portfolio && Object.keys(payload.portfolio).length;
  const fixedLines = [
    `${date} ${payload.venue}${payload.race}R`,
    ...formationCopyLines(fixedPortfolio ? "3連単" : "本線", payload.main),
    ...(fixedPortfolio ? portfolioCopyLines(payload.portfolio) : formationCopyLines("押さえ", payload.cover)),
    "※検証中・的中利益保証なし",
  ];
  const maxJapaneseCharacters = 140;
  const developmentPrefix = "展開:";
  const reserved = Array.from(fixedLines.join("\n")).length + developmentPrefix.length + 1;
  const development = Array.from(payload.development || "").slice(0, Math.max(0, maxJapaneseCharacters - reserved)).join("");
  return [fixedLines[0], `${developmentPrefix}${development}`, ...fixedLines.slice(1)].join("\n");
}

function buildNoGamiDoraPlan(main = [], cover = []) {
  const tickets = [...main, ...cover].map((ticket) => ({
    pick: ticketText(ticket),
    odds: Number(typeof ticket === "string" ? 0 : ticket?.odds || 0),
    netEdge: Number(typeof ticket === "string" ? Number.NEGATIVE_INFINITY : ticket?.net_edge),
  }));
  if (tickets.length !== 12 || tickets.some((ticket) => !ticket.pick || !Number.isFinite(ticket.odds) || ticket.odds <= 0)) {
    return { status: "DATA BLOCKED", reason: "12点すべての3連単オッズが揃っていません。", dora: [], stakes: [] };
  }
  let best = null;
  for (let first = 0; first < tickets.length; first += 1) {
    for (let second = first + 1; second < tickets.length; second += 1) {
      const doraIndexes = new Set([first, second]);
      const stakes = tickets.map((ticket, index) => ({ ...ticket, stake: doraIndexes.has(index) ? 1000 : 100 }));
      const totalStake = stakes.reduce((sum, ticket) => sum + ticket.stake, 0);
      if (!stakes.every((ticket) => ticket.stake * ticket.odds >= totalStake)) continue;
      const score = [first, second].reduce((sum, index) => sum + (Number.isFinite(tickets[index].netEdge) ? tickets[index].netEdge : -999), 0);
      if (!best || score > best.score) best = { score, totalStake, stakes, dora: [tickets[first], tickets[second]] };
    }
  }
  if (!best) return { status: "WATCH", reason: "旧配分では全候補をガミなしにできません。", dora: [], stakes: [] };
  return { status: "READY", reason: "全12点で的中時払戻しが総投資3,000円以上。", ...best };
}

function buildNoteDraft(payload, paid = false) {
  const date = String(payload.date || "").replaceAll("-", "/");
  const serious = ["WATCH", "DATA BLOCKED"].includes(payload.judgement);
  const fixedPortfolio = payload.portfolio && Object.keys(payload.portfolio).length;
  const portfolioTickets = fixedPortfolio
    ? ["trio", "exacta", "quinella"].flatMap((market) => payload.portfolio[market] || [])
    : [];
  const doraPlan = fixedPortfolio
    ? { status: "FIXED", reason: "固定13点・各100円", dora: [], stakes: [] }
    : buildNoGamiDoraPlan(payload.main, payload.cover);
  const startOrder = (payload.exhibition || []).slice()
    .sort((a, b) => (Number(a.course) || Number(a.boat)) - (Number(b.course) || Number(b.boat)))
    .map((item) => item.boat).join("-");
  const fastest = (payload.exhibition || []).filter((item) => item.time != null)
    .sort((a, b) => Number(a.time) - Number(b.time))[0];
  const bestSt = (payload.exhibition || []).filter((item) => item.st != null && Number(item.st) >= 0 && !String(item.st).toUpperCase().startsWith("F"))
    .sort((a, b) => Number(a.st) - Number(b.st))[0];
  const doraText = doraPlan.dora.length
    ? doraPlan.dora.map((ticket) => `${ticket.pick} 各1,000円（${ticket.odds.toFixed(1)}倍）`).join("／")
    : `設定なし（${doraPlan.reason}）`;
  const regularText = fixedPortfolio
    ? [...payload.main, ...portfolioTickets].map((ticket) => `${ticketText(ticket)} 100円`).join("、")
    : doraPlan.stakes.length
    ? doraPlan.stakes.filter((ticket) => ticket.stake === 100).map((ticket) => `${ticket.pick} 100円`).join("、")
    : [...payload.main, ...payload.cover].map((ticket) => `${ticketText(ticket)} 100円`).join("、");
  const opening = serious
    ? payload.judgement === "DATA BLOCKED"
      ? "私、水面ベタ子です。必要なデータが揃っていないため、今回は予想を出しません。"
      : "私、水面ベタ子です。今回は無理をせず、見送りも含めて慎重に確認してください。"
    : "私、水面ベタ子の展示後最終予想、いくよ〜！ アっチッチかもかも❤️";
  const development = serious
    ? `${payload.development}\n根拠が弱い状態では無理に勝負しません。`
    : `${payload.development}\n私はこの展開を本線で見てるかもかも❤️`;
  const reasonLines = (payload.reasons || []).slice(0, paid ? 5 : 3).map((reason) => serious
    ? `・${reason}`
    : `・${String(reason).replace(/[。.!！?？]+$/, "")}。ここを評価してるよ❤️`);
  const commonLines = [
    `【水面ベタ子｜note ${paid ? "有料会員版" : "無料版"}】`,
    `${date} ${payload.venue}${payload.race}R`, opening, "",
    `【現在判断】${payload.judgement}`,
    `期待度指数 ${payload.score ?? "--"}／一致度 ${payload.agreement ?? "--"}%／データ取得率 ${payload.dataRate ?? "--"}%`,
    serious ? "数字と展示内容を確認し、慎重に判断しています。" : "数字だけじゃなく、展示の気配まで私がしっかり見たよ❤️", "",
    "【展開予想】", development, "",
    "【進入・展示】",
    `進入順 ${startOrder || "未確認"}${payload.entryChanged ? "（前付け・進入変化あり）" : "（枠なり）"}`,
    `展示最速 ${fastest ? `${fastest.boat}号艇 ${Number(fastest.time).toFixed(2)}` : "未確認"}／ST展示トップ ${bestSt ? `${bestSt.boat}号艇 ${Number(bestSt.st).toFixed(2)}` : "未確認"}`,
    serious ? "進入や展示に不確定要素がある場合は見送ります。" : "進入とスリットの変化も見逃してないかもかも❤️", "",
    "【私が見た根拠】", ...reasonLines, "",
  ];
  const memberLines = paid ? [
    serious ? "【買い目・資金配分】条件を満たしていないため、購入は推奨しません。" : "【有料会員さん用｜私の買い目と資金配分】",
    ...formationCopyLines(fixedPortfolio ? "3連単" : "本線", payload.main),
    ...(fixedPortfolio ? portfolioCopyLines(payload.portfolio) : formationCopyLines("押さえ", payload.cover)),
    ...(fixedPortfolio ? [] : [`ドラ：${doraText}`]), `通常配分：${regularText}`, `資金判定：${doraPlan.status}｜${doraPlan.reason}`,
    serious
      ? "オッズと条件が改善するまでは購入しないでください。"
      : fixedPortfolio
        ? "各100円・合計1,300円。4券種を期待値順に選んだ固定13点で検証するかもかも❤️"
        : "直前オッズを確認して資金配分を調整するかもかも❤️", "",
    fixedPortfolio
      ? "【会員情報】3連単6点・3連複2点・2連単2点・2連複3点を、直前オッズで期待値順に再計算します。"
      : "【会員情報】本線・押さえ・ドラ・資金配分は、直前オッズで再計算します。", "",
  ] : [
    "【無料公開範囲】",
    serious
      ? "展開・進入・展示評価まで公開します。条件が整うまでは具体的な買い目を出しません。"
      : fixedPortfolio
        ? "無料版は展開・進入・展示評価までだよ。固定13点（3連単6・3連複2・2連単2・2連複3）は有料会員版で公開するかもかも❤️"
        : "無料版は展開・進入・展示評価までだよ。買い目と資金配分は有料会員版で公開するかもかも❤️", "",
  ];
  return [
    ...commonLines, ...memberLines,
    "【無効条件】", payload.invalidConditions || "直前オッズ・進入・展示気配が想定から変わった場合", "",
    serious ? "今回は慎重に判断してください。無理な購入はおすすめしません。" : "条件が崩れたら無理しないでね。次のアっチッチを一緒に待つよ❤️", "",
    "※検証中の分析情報です。的中・利益を保証しません。オッズ急変時は買い目と資金配分を再計算します。",
  ].join("\n");
}

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const liveDataBase = "https://raw.githubusercontent.com/jcleanex-sudo/betako-free-site/main/data";

async function probeLiveExhibitionVersion() {
  const response = await fetch(`${liveDataBase}/exhibition.json?probe=${Date.now()}`, {
    cache: "no-store",
    headers: { Range: "bytes=0-1023" },
  });
  if (!response.ok && response.status !== 206) throw new Error(`probe ${response.status}`);
  const prefix = await response.text();
  return prefix.match(/"updated_at"\s*:\s*"([^"]+)"/)?.[1] || null;
}

async function fetchLiveExhibition() {
  const response = await fetch(`${liveDataBase}/exhibition.json?ts=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`live exhibition ${response.status}`);
  return response.json();
}

function parseOfficialExhibitionHtml(html) {
  const documentNode = new DOMParser().parseFromString(html, "text/html");
  const byBoat = new Map();
  const numberFrom = (value) => {
    const match = String(value || "").replaceAll(",", "").match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  };
  documentNode.querySelectorAll("table.is-w748 tr").forEach((row) => {
    const cells = Array.from(row.children)
      .filter((cell) => ["TD", "TH"].includes(cell.tagName))
      .map((cell) => cell.textContent.trim());
    if (cells.length < 6) return;
    const boat = numberFrom(cells[0]);
    if (!Number.isInteger(boat) || boat < 1 || boat > 6) return;
    const weightValue = numberFrom(cells[3]);
    const timeValue = numberFrom(cells[4]);
    const tiltValue = numberFrom(cells[5]);
    byBoat.set(boat, {
      boat,
      course: null,
      time: timeValue >= 6 && timeValue <= 7.5 ? timeValue : null,
      tilt: tiltValue >= -1.5 && tiltValue <= 3 ? tiltValue : null,
      weight: weightValue >= 40 && weightValue <= 70 ? weightValue : null,
      st: null,
      time_rank: null,
      st_rank: null,
    });
  });
  documentNode.querySelectorAll("table.is-w238 .table1_boatImage1").forEach((item, index) => {
    const boat = numberFrom(item.querySelector(".table1_boatImage1Number")?.textContent);
    if (!Number.isInteger(boat) || boat < 1 || boat > 6) return;
    const stText = item.querySelector(".table1_boatImage1Time")?.textContent.trim() || "";
    const st = stText.match(/F?(?:\d+)?\.\d+/)?.[0] || null;
    const current = byBoat.get(boat) || { boat, time: null, tilt: null, weight: null, time_rank: null, st_rank: null };
    byBoat.set(boat, { ...current, course: index + 1, st });
  });
  const rows = [...byBoat.values()].sort((a, b) => a.boat - b.boat);
  rows.filter((item) => item.time != null).sort((a, b) => a.time - b.time)
    .forEach((item, index) => { item.time_rank = index + 1; });
  const stValue = (value) => String(value || "").startsWith("F")
    ? -Number(String(value).slice(1))
    : Number(value);
  rows.filter((item) => item.st != null).sort((a, b) => stValue(a.st) - stValue(b.st))
    .forEach((item, index) => { item.st_rank = index + 1; });
  return rows;
}

async function fetchOfficialExhibitionPreview(api, venueId, race, raceDate) {
  const query = new URLSearchParams({ venue_id: venueId, race: String(race), race_date: raceDate });
  const response = await fetch(`${api.replace(/\/$/, "")}/official-preview?${query}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`preview ${response.status}`);
  return parseOfficialExhibitionHtml(await response.text());
}

async function requestRaceRefresh(api, venueId, race, raceDate) {
  const response = await fetch(`${api.replace(/\/$/, "")}/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ venue_id: venueId, race, race_date: raceDate }),
  });
  if (!response.ok) throw new Error(`refresh ${response.status}`);
  return response.json().catch(() => ({ status: "requested" }));
}

function isCompleteExhibition(rows) {
  return Array.isArray(rows)
    && rows.length === 6
    && new Set(rows.map((item) => Number(item.boat))).size === 6
    && rows.every((item) => (
      item.time != null
      && Number(item.course) >= 1
      && Number(item.course) <= 6
      && item.st != null
      && item.st !== ""
    ));
}

function isCurrentRaceSelection({ venueId, race, raceDate }) {
  const selectedVenueId = String(venues.indexOf(venueSelect.value) + 1).padStart(2, "0");
  return dateInput.value === raceDate
    && selectedVenueId === String(venueId).padStart(2, "0")
    && raceSelect.value === String(race)
    && document.querySelector("#predictionType").value === "展示後AI最終予想";
}

async function refreshSelectedRace({ venueId, race, raceDate, previousFetchedAt, previousUpdatedAt }) {
  const api = window.betakoRuntime?.on_demand_api;
  const badge = document.querySelector("#exhibitionBadge");
  const detail = document.querySelector("#predictionDetail");
  const key = `${raceDate}-${venueId}-${race}`;
  if (!api || pendingRefreshes.has(key)) return;

  pendingRefreshes.add(key);
  badge.hidden = false;
  badge.textContent = "展示前・更新中";
  detail.textContent = "選択したレースの展示データだけを取得しています（通常1〜3分）。";

  try {
    const previewRows = await fetchOfficialExhibitionPreview(api, venueId, race, raceDate).catch(() => []);
    let previewComplete = false;
    let recalculationRequested = false;
    let lastRecalculationRequestAt = 0;
    let observedUpdatedAt = previousUpdatedAt;
    if (previewRows.length) {
      if (!isCurrentRaceSelection({ venueId, race, raceDate })) return;
      renderExhibitionTimes({ exhibition: previewRows }, true);
      previewComplete = isCompleteExhibition(previewRows);
      badge.textContent = previewComplete ? "展示取得済・予想計算中" : "展示一部取得・進入/ST待ち";
      detail.textContent = previewComplete
        ? "展示タイム・進入・STを公式から直接取得しました。固定13点を計算しています。"
        : "公式の展示欄が埋まるまで、このレースだけを5秒間隔で自動確認します。";
    }

    let attempt = 0;
    while (isCurrentRaceSelection({ venueId, race, raceDate })) {
      if (attempt > 0) await delay(attempt < 36 ? 5000 : 15000);
      if (!isCurrentRaceSelection({ venueId, race, raceDate })) return;
      if (attempt === 3) {
        badge.textContent = "展示更新・公式取得中";
        detail.textContent = "公式の展示・進入・ST・5券種オッズを取得しています。";
      } else if (attempt === 9) {
        badge.textContent = "展示更新・反映中";
        detail.textContent = "取得した予想を公開データへ反映しています。";
      } else if (attempt === 36) {
        badge.textContent = "公式展示・継続監視中";
        detail.textContent = "公式データが揃うまで、このレースだけを自動確認し続けています。";
      }
      const [liveVersion, latestPreview] = await Promise.all([
        probeLiveExhibitionVersion().catch(() => null),
        previewComplete ? Promise.resolve([]) : fetchOfficialExhibitionPreview(api, venueId, race, raceDate).catch(() => []),
      ]);
      if (!previewComplete && latestPreview.length) {
        renderExhibitionTimes({ exhibition: latestPreview }, true);
        previewComplete = isCompleteExhibition(latestPreview);
        if (previewComplete) {
          badge.textContent = "展示取得済・予想再計算中";
          detail.textContent = "公式展示を確認しました。最新値で固定13点を再計算しています。";
        }
      }
      const recalculationExpired = Date.now() - lastRecalculationRequestAt >= 120000;
      if (previewComplete && (!recalculationRequested || recalculationExpired)) {
        const refreshResult = await requestRaceRefresh(api, venueId, race, raceDate).catch(() => null);
        if (["requested", "already_requested"].includes(refreshResult?.status)) {
          recalculationRequested = true;
          lastRecalculationRequestAt = Date.now();
        }
      }
      if (!liveVersion || liveVersion === observedUpdatedAt) {
        attempt += 1;
        continue;
      }
      const payload = await fetchLiveExhibition().catch(() => null);
      if (!payload || payload.race_date !== raceDate) {
        attempt += 1;
        continue;
      }
      observedUpdatedAt = payload.updated_at || liveVersion;
      const refreshed = payload.races?.find((item) => item.venue_id === venueId && String(item.race) === String(race));
      if (refreshed?.status === "FINAL" && refreshed?.fetched_at && refreshed.fetched_at !== previousFetchedAt) {
        window.betakoExhibition = payload;
        renderLongshots(window.betakoPredictions?.longshots || []);
        document.querySelector("#predictionForm").requestSubmit();
        return;
      }
      attempt += 1;
    }
  } catch {
    if (isCurrentRaceSelection({ venueId, race, raceDate })) {
      badge.textContent = "展示前";
      detail.textContent = "更新を開始できませんでした。朝の予想を表示し、購入は見送り対象にします。";
    }
  } finally {
    pendingRefreshes.delete(key);
  }
}

function renderExhibitionTimes(finalData, finalMode) {
  let panel = document.querySelector("#exhibitionTimes");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "exhibitionTimes";
    panel.className = "exhibitionTimes";
    document.querySelector("#predictionDetail").insertAdjacentElement("afterend", panel);
  }
  const rows = Array.isArray(finalData?.exhibition) ? finalData.exhibition : [];
  const startOrder = rows.slice()
    .sort((a, b) => (Number(a.course) || Number(a.boat)) - (Number(b.course) || Number(b.boat)))
    .map((item) => Number(item.boat));
  const entryChanged = startOrder.length === 6 && startOrder.some((boat, index) => boat !== index + 1);
  const formatSt = (value) => {
    if (value == null || value === "") return "--";
    const text = String(value).toUpperCase();
    return text.startsWith("F") ? text : Number(text).toFixed(2);
  };
  panel.hidden = !finalMode || !rows.length;
  panel.innerHTML = rows.length
    ? `<div class="exhibitionTimesHead"><b>展示タイム</b><span>6艇リアルタイム</span></div><div class="startOrder ${entryChanged ? "changed" : ""}"><b>${entryChanged ? "前付け・進入変化" : "枠なり進入"}</b><span>${startOrder.join(" - ")}</span></div><div class="exhibitionTimesGrid">${rows.map((item) => `<div class="exhibitionBoat boat${Number(item.boat) || 0}"><b>${Number(item.boat) || "--"}号艇 <em>${item.course ? `${Number(item.course)}コース` : ""}</em></b><strong>${item.time == null ? "--" : Number(item.time).toFixed(2)}</strong><small>展示 ${item.time_rank || "--"}位｜ST ${formatSt(item.st)}${item.st_rank ? `（${item.st_rank}位）` : ""}</small></div>`).join("")}</div>`
    : "";
}

function renderMarketComparison(finalData, finalReady) {
  const panel = document.querySelector("#marketComparison");
  const rows = Array.isArray(finalData?.market_comparison) ? finalData.market_comparison : [];
  panel.hidden = !finalReady;
  if (!finalReady) {
    panel.replaceChildren();
    return;
  }
  const value = finalData?.value || {};
  const heading = document.createElement("div");
  heading.className = "marketComparisonHead";
  heading.innerHTML = `<b>5券種 期待値ランキング</b><span>公式オッズ取得率 ${Number(value.data_rate || 0)}%</span>`;
  const list = document.createElement("div");
  list.className = "marketComparisonList";
  if (!rows.length) {
    list.textContent = "DATA BLOCKED：5券種のオッズが揃うまで予想を出しません。";
  } else {
    rows.slice(0, 6).forEach((row, index) => {
      const item = document.createElement("div");
      item.className = `marketRow ${index === 0 ? "best" : ""}`;
      item.innerHTML = `<strong>${index + 1}</strong><b>${escapeHtml(row.bet_type_label)} ${escapeHtml(row.pick)}</b><span>${Number(row.odds).toFixed(1)}倍</span><small>的中推定 ${Number(row.model_probability).toFixed(1)}%｜net edge ${Number(row.net_edge).toFixed(1)}%｜100円期待損益 ${Number(row.expected_profit_yen) >= 0 ? "+" : ""}${Number(row.expected_profit_yen)}円</small>`;
      list.append(item);
    });
  }
  panel.replaceChildren(heading, list);
}

function renderFixedPortfolio(portfolio, finalReady) {
  const panel = document.querySelector("#marketTicketPlan");
  panel.hidden = !finalReady;
  if (!finalReady) {
    panel.replaceChildren();
    return;
  }
  const definitions = [
    ["trifecta", "3連単", 6],
    ["trio", "3連複", 2], ["exacta", "2連単", 2], ["quinella", "2連複", 3],
  ];
  const heading = document.createElement("div");
  heading.className = "marketTicketHead";
  heading.innerHTML = "<b>固定13点プラン</b><span>3連単6＋3連複2＋2連単2＋2連複3</span>";
  const groups = document.createElement("div");
  groups.className = "marketTicketGroups";
  definitions.forEach(([market, label, expected]) => {
    const tickets = portfolio?.[market] || [];
    const group = document.createElement("section");
    const chips = tickets.map((ticket) => `<span class="${ticket.qualifies ? "qualified" : "reference"}">${escapeHtml(ticket.pick)} <small>${Number(ticket.odds).toFixed(1)}倍</small></span>`).join("");
    group.innerHTML = `<b>${label} ${expected}点</b><div>${chips || '<span class="reference">DATA BLOCKED</span>'}</div>`;
    groups.append(group);
  });
  panel.replaceChildren(heading, groups);
}

function hasCompleteFixedPortfolio(finalData) {
  const portfolio = finalData?.value?.portfolio;
  const completeMarkets = Object.entries(FIXED_PORTFOLIO_COUNTS).every(([market, expected]) => {
    const tickets = portfolio?.[market];
    if (!Array.isArray(tickets) || tickets.length !== expected) return false;
    const picks = tickets.map((ticket) => String(ticket?.pick || ""));
    return picks.every(Boolean) && new Set(picks).size === expected;
  });
  const main = finalData?.ticket_plan?.main;
  return completeMarkets && Array.isArray(main) && main.length === FIXED_PORTFOLIO_COUNTS.trifecta;
}

document.querySelector("#predictionForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const venue = venueSelect.value;
  const predictionDate = window.betakoPredictions?.race_date;
  const dateMatches = !predictionDate || predictionDate === dateInput.value;
  const predictionRows = window.betakoPredictions?.all_races || window.betakoPredictions?.rankings || [];
  const match = dateMatches
    ? predictionRows.find((item) => item.venue === venue && String(item.race) === raceSelect.value)
    : null;
  const officialVenue = window.betakoPredictions?.official_venues?.find((item) => item.venue === venue);
  const venueId = String(match?.venue_id || officialVenue?.venue_id || venues.indexOf(venue) + 1).padStart(2, "0");
  document.querySelector("#venueCode").textContent = venueId;
  const finalMode = document.querySelector("#predictionType").value === "展示後AI最終予想";
  const exhibitionDateMatches = window.betakoExhibition?.race_date === dateInput.value;
  const finalData = exhibitionDateMatches
    ? window.betakoExhibition?.races?.find((item) => item.venue === venue && String(item.race) === raceSelect.value)
    : null;
  const finalReady = finalMode && finalData?.status === "FINAL" && hasCompleteFixedPortfolio(finalData);
  renderExhibitionTimes(finalData, finalMode);
  renderMarketComparison(finalData, finalReady);
  renderFixedPortfolio(finalData?.value?.portfolio, finalReady);
  document.querySelector(".ticketPlan").hidden = finalReady;
  const exhibitionBadge = document.querySelector("#exhibitionBadge");
  exhibitionBadge.hidden = !finalMode || finalReady;
  exhibitionBadge.textContent = "展示前";
  const value = finalData?.value;
  const deadlineAt = value?.deadline ? new Date(`${dateInput.value}T${value.deadline}:00+09:00`) : null;
  const liveRemaining = deadlineAt && !Number.isNaN(deadlineAt.getTime())
    ? (deadlineAt.getTime() - Date.now()) / 60000
    : null;
  const cutoffReached = liveRemaining !== null && liveRemaining < 5;
  const valueStatus = cutoffReached ? "WATCH" : (value?.status || "DATA BLOCKED");
  const valueMessage = cutoffReached ? "締切5分前を過ぎたため新規判定を停止" : value?.message;
  const referenceBlocked = Boolean(match) && Number(match.data_rate) < PUBLIC_THRESHOLDS.dataRate;
  const morningSkip = !match
    || match.label !== "厳格候補"
    || Number(match.score) < PUBLIC_THRESHOLDS.score
    || Number(match.agreement) < PUBLIC_THRESHOLDS.agreement
    || referenceBlocked;
  const skipTarget = referenceBlocked || (finalMode ? !finalReady || valueStatus !== "UP" : morningSkip);
  const decisionBadge = document.querySelector("#decisionBadge");
  decisionBadge.hidden = !skipTarget;
  decisionBadge.textContent = referenceBlocked ? "DATA BLOCKED" : "見送り対象";
  const candidatePlan = referenceBlocked
    ? { main: [], cover: [] }
    : buildBetPlan(match?.contenders, finalReady ? finalData.final_pick : match?.pick);
  const betPlan = referenceBlocked
    ? candidatePlan
    : finalMode && finalData?.ticket_plan ? finalData.ticket_plan : candidatePlan;
  document.querySelector("#coverGroup").hidden = finalReady;
  document.querySelector("#mainLabel").textContent = referenceBlocked
    ? "予想停止（参考データ不足）"
    : finalReady
    ? "3連単 本線6点"
    : skipTarget
    ? "参考買い目6点（見送り）"
    : betPlan.ranked_by_edge ? "期待値上位6点" : "本線候補6点";
  renderFormation(document.querySelector("#mainPicks"), betPlan.main);
  renderFormation(document.querySelector("#coverPicks"), betPlan.cover);
  document.querySelector("#selectionText").textContent = referenceBlocked
    ? `${venue} ${raceSelect.value}R・DATA BLOCKED（参考データ ${Number(match.data_rate).toFixed(1)}%）`
    : finalReady
      ? `${venue} ${raceSelect.value}R・展示後指数 ${Math.round(finalData.final_score)}（FINAL）`
    : match
      ? `${venue} ${raceSelect.value}R・期待度指数 ${Math.round(match.score)}（${finalMode ? finalData?.status || "WAIT" : match.label}）`
    : `${dateInput.value}・${venue} ${raceSelect.value}R・DATA BLOCKED`;
  document.querySelector("#predictionDetail").textContent = referenceBlocked
    ? `参考データ取得率 ${Number(match.data_rate).toFixed(1)}%｜100%未満のため買い目を生成しません`
    : finalReady
      ? `期待値最上位 ${value?.bet_type_label || "券種未確定"} ${finalData.best_value_pick || finalData.final_pick}｜オッズ ${value?.odds ? `${value.odds}倍` : "未公開"}｜的中推定 ${value?.model_probability == null ? "--" : `${value.model_probability}%`}｜net edge ${value?.net_edge == null ? "--" : `${value.net_edge}%`}｜残り ${liveRemaining == null ? "--" : `${Math.max(0, liveRemaining).toFixed(0)}分`}｜判定 ${valueStatus}`
    : match
      ? `本線候補 ${match.pick}｜相対1着推定 ${Math.round(match.estimated_probability)}%｜一致度 ${Math.round(match.agreement)}%｜データ取得率 ${Math.round(match.data_rate)}%`
    : dateMatches
      ? "公式データを取得できなかったレースです。DATA BLOCKEDとして見送ります。"
      : "選択日の予想データはありません。本日の日付を選択してください。";
  const reasons = document.querySelector("#predictionReasons");
  const displayedReasons = referenceBlocked
    ? [`全国・当地・モーター・ボート・STのいずれかが欠損しています。100%取得までこのレースだけ予想を停止します`]
    : finalReady
    ? finalData.reasons
    : [...(match?.reasons || []), ...buildAxisEvidence(match)];
  const leadingPick = referenceBlocked ? "" : finalReady ? finalData.final_pick : match?.pick;
  const development = referenceBlocked
    ? "DATA BLOCKED：参考データが揃うまで展開予想を生成しません。"
    : buildDevelopmentPrediction(leadingPick, displayedReasons, finalReady);
  document.querySelector("#developmentText").textContent = development;
  reasons.replaceChildren(...displayedReasons.map((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    return item;
  }));
  document.querySelector("#invalidConditions").textContent = finalReady
    ? `期待値判定：${valueMessage || "オッズ未公開のため判定なし"}｜無効条件：締切5分未満、オッズ急変、展示データ欠損、公式情報取得失敗`
    : finalMode && !finalReady
    ? `WAIT：${finalData?.message || "展示データが未取得です。朝予想を維持します。"}｜締切 ${value?.deadline || "未取得"}｜期待値判定 ${valueStatus}：${valueMessage || "5券種オッズ未公開"}`
    : match
      ? `無効条件：${(match.invalid_conditions || []).join("／")}`
    : `見送り条件：${dateMatches ? "公式データの取得失敗" : "選択日が本日ではない"}`;
  latestManualPrediction = {
    date: dateInput.value,
    venue,
    race: raceSelect.value,
    development,
    mainLabel: document.querySelector("#mainLabel").textContent,
    main: betPlan.main || [],
    cover: betPlan.cover || [],
    portfolio: finalReady ? value?.portfolio || null : null,
    detail: document.querySelector("#predictionDetail").textContent,
    invalidConditions: document.querySelector("#invalidConditions").textContent,
    finalReady,
    judgement: referenceBlocked ? "DATA BLOCKED" : finalReady ? valueStatus : "WATCH",
    score: finalReady ? Math.round(finalData.final_score) : Math.round(match?.score || 0),
    agreement: Math.round(match?.agreement || 0),
    dataRate: Math.round(match?.data_rate || 0),
    reasons: displayedReasons,
    exhibition: finalData?.exhibition || [],
    entryChanged: (finalData?.exhibition || []).some((item) => Number(item.course || item.boat) !== Number(item.boat)),
  };
  document.querySelector("#manualCopyStatus").textContent = "";
  document.querySelector("#noteDraftPanel").hidden = true;
  document.querySelector("#selectionResult").hidden = false;
  if (finalMode && !finalReady && match) {
    void refreshSelectedRace({
      venueId,
      race: Number(raceSelect.value),
      raceDate: dateInput.value,
      previousFetchedAt: finalData?.fetched_at,
      previousUpdatedAt: window.betakoExhibition?.updated_at,
    });
  }
});

document.querySelector("#copyManualPrediction").addEventListener("click", async () => {
  const status = document.querySelector("#manualCopyStatus");
  if (!latestManualPrediction) {
    status.textContent = "先に開催場とレースを選んで予想してください。";
    return;
  }
  try {
    await navigator.clipboard.writeText(buildManualCopyText(latestManualPrediction));
    status.textContent = "X投稿用（140文字以内）でコピーしました。";
  } catch {
    status.textContent = "コピーできませんでした。ブラウザの許可を確認してください。";
  }
});

async function createAndCopyNoteDraft(paid) {
  const status = document.querySelector("#manualCopyStatus");
  const panel = document.querySelector("#noteDraftPanel");
  if (!latestManualPrediction) {
    status.textContent = "先に開催場とレースを選んで予想してください。";
    return;
  }
  if (!latestManualPrediction.finalReady) {
    status.textContent = "note用の最終買い目は、展示後AI最終予想が完成してから作成します。";
    panel.hidden = true;
    return;
  }
  const draft = buildNoteDraft(latestManualPrediction, paid);
  document.querySelector("#noteDraftTitle").textContent = paid ? "note 有料会員版原稿" : "note 無料版原稿";
  document.querySelector("#noteDraftText").textContent = draft;
  panel.hidden = false;
  try {
    await navigator.clipboard.writeText(draft);
    status.textContent = paid
      ? "有料会員版（買い目・資金配分付き）を作成してコピーしました。"
      : "無料版（展開予想まで）を作成してコピーしました。";
  } catch {
    status.textContent = `${paid ? "有料会員版" : "無料版"}を作成しました。下の原稿を選択してコピーしてください。`;
  }
}

document.querySelector("#createFreeNoteDraft").addEventListener("click", () => {
  void createAndCopyNoteDraft(false);
});

document.querySelector("#createPaidNoteDraft").addEventListener("click", () => {
  void createAndCopyNoteDraft(true);
});

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function renderLongshots(longshots) {
  const longshotGrid = document.querySelector("#longshotGrid");
  const checks = window.betakoExhibition?.race_date === dateInput.value
    ? (window.betakoExhibition?.longshots || [])
    : [];
  longshotGrid.innerHTML = longshots.length ? longshots.map((item) => {
    const check = checks.find((candidate) => candidate.venue === item.venue && String(candidate.race) === String(item.race) && String(candidate.boat) === String(item.boat));
    const deadlineAt = check?.deadline ? new Date(`${dateInput.value}T${check.deadline}:00+09:00`) : null;
    const remaining = deadlineAt && !Number.isNaN(deadlineAt.getTime()) ? (deadlineAt.getTime() - Date.now()) / 60000 : null;
    const cutoffReached = remaining !== null && remaining < 5;
    const status = cutoffReached ? "WATCH" : (check?.status || item.status || "WATCH");
    const message = cutoffReached ? "締切5分前を過ぎたため新規判定を停止" : (check?.message || item.condition);
    const realtime = check
      ? `展示順位 ${check.time_rank || "--"}位｜最低オッズ ${check.min_odds ? `${check.min_odds}倍` : "--"}｜net edge ${check.net_edge == null ? "--" : `${check.net_edge}%`}｜残り ${remaining == null ? "--" : `${Math.max(0, remaining).toFixed(0)}分`}`
      : "展示・オッズ条件を確認中";
    return `<article class="longshotCard">
      <span>${escapeHtml(status)}</span>
      <h3>${escapeHtml(item.venue)} ${escapeHtml(item.race)}R <small>${escapeHtml(item.boat)}号艇</small></h3>
      <div class="longshotIndex">穴指数 ${Number(item.hole_index).toFixed(0)}</div>
      <p>${escapeHtml(item.boat)}号艇 ${escapeHtml(item.name)}（${escapeHtml(item.class)}）｜組み込み候補 ${escapeHtml(item.formation)}</p>
      <ul>${(item.reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
      <p>${escapeHtml(realtime)}</p>
      <p class="longshotCondition">判定：${escapeHtml(message)}</p>
    </article>`;
  }).join("") : `<article class="longshotCard"><span>WATCH</span><h3>穴候補なし</h3><p>条件を満たす人気薄がないため見送ります。</p></article>`;
}

function renderRankings(payload) {
  window.betakoPredictions = payload;
  populateActiveVenues(payload);
  const grid = document.querySelector("#rankingGrid");
  const status = document.querySelector("#dataStatus");
  const updated = document.querySelector("#dataUpdated");
  let rankings = Array.isArray(payload.rankings) ? payload.rankings : [];
  let longshots = Array.isArray(payload.longshots) ? payload.longshots : [];
  const venueCount = Number(payload.venue_count || payload.official_venues?.length || new Set((payload.all_races || []).map((item) => item.venue)).size || 0);
  const expectedRaces = Number(payload.expected_races || venueCount * 12 || 0);
  const fetchedRaces = Number(payload.fetched_races || payload.all_races?.length || 0);
  const collectionRate = Number(payload.collection_rate ?? (expectedRaces ? fetchedRaces / expectedRaces * 100 : 0));
  const referenceExpected = Number(payload.reference_expected || expectedRaces * 6 * 5 || 0);
  const referenceFetched = Number(payload.reference_fetched || Math.round((payload.all_races || []).reduce(
    (total, item) => total + Number(item.data_rate || 0) / 100 * 6 * 5,
    0,
  )));
  const referenceRate = Number(payload.reference_rate ?? (referenceExpected ? referenceFetched / referenceExpected * 100 : 0));
  const completeRaceCount = (payload.all_races || []).filter((item) => Number(item.data_rate) >= PUBLIC_THRESHOLDS.dataRate).length;
  const jstParts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date()).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  const jstDate = `${jstParts.year}-${jstParts.month}-${jstParts.day}`;
  const updateHour = Number(jstParts.hour || 0);
  const waitingForMorningUpdate = payload.race_date !== jstDate && updateHour < 9;
  const stalePrediction = payload.race_date !== jstDate && updateHour >= 9;
  const coverageReady = payload.status === "OK" && collectionRate >= 100 && payload.race_date === jstDate;
  if (!coverageReady) {
    rankings = [];
    longshots = [];
  } else {
    rankings = rankings.filter((item) => Number(item.data_rate) >= PUBLIC_THRESHOLDS.dataRate);
    longshots = longshots.filter((item) => (payload.all_races || []).some(
      (race) => race.venue === item.venue && Number(race.race) === Number(item.race) && Number(race.data_rate) >= PUBLIC_THRESHOLDS.dataRate,
    ));
  }
  window.betakoPredictions = { ...payload, rankings, longshots };
  renderDailyPerformance();
  renderTodayVenuePerformance();
  status.classList.toggle("staleTag", stalePrediction);
  status.textContent = stalePrediction
    ? `更新停止：${jstDate}の予想データ未取得`
    : waitingForMorningUpdate
      ? `本日8:15の更新待ち（現在は${payload.race_date || "前日"}データ）`
      : coverageReady
        ? `公式${venueCount}場 ${fetchedRaces}/${expectedRaces}R・予想可能 ${completeRaceCount}/${expectedRaces}R（不足${expectedRaces - completeRaceCount}Rのみ停止）`
        : `DATA BLOCKED ${fetchedRaces}/${expectedRaces}R（${collectionRate.toFixed(1)}%）`;
  updated.textContent = payload.updated_at ? `${payload.updated_at} 更新` : "更新時刻不明";

  if (!rankings.length) {
    const blockedMessage = stalePrediction
      ? `${jstDate}の公式データが未更新です。古い予想は表示しません`
      : !coverageReady
      ? `公式レース取得が${fetchedRaces}/${expectedRaces}Rのため全体停止`
      : payload.message || "基準通過なし";
    grid.innerHTML = `<article class="rankCard gold"><div class="rankTop"><span class="rankNumber">--</span><span class="candidate">見送り</span></div><h3>公開できる候補なし</h3><div class="index"><span>状態</span><strong>--</strong></div><div class="pick"><span>理由</span><b>${escapeHtml(blockedMessage)}</b></div><div class="meter"><i style="width:0"></i></div></article>`;
    return;
  }

  venueSelect.value = rankings[0].venue;
  raceSelect.value = String(rankings[0].race);

  grid.innerHTML = rankings.slice(0, 3).map((item, index) => {
    const tone = index === 0 ? "cyan" : index === 1 ? "blue" : "gold";
    const lead = item.contenders?.[0];
    const rankingPicks = buildBetPlan(item.contenders, item.pick).main;
    return `<article class="rankCard ${tone}">
      <div class="rankTop"><span class="rankNumber">${String(index + 1).padStart(2, "0")}</span><span class="candidate">${escapeHtml(item.label)}</span></div>
      <h3>${escapeHtml(item.venue)} <small>${escapeHtml(item.race)}R</small></h3>
      <div class="index"><span>期待度指数</span><strong>${Number(item.score).toFixed(0)}</strong></div>
      <div class="pick"><span>軸目</span><b>${escapeHtml(item.pick)}</b></div>
      <div class="rankSix"><span>予想6点</span><div>${rankingPicks.map((pick) => `<b>${escapeHtml(pick)}</b>`).join("")}</div></div>
      <p class="rankLead">軸：${escapeHtml(lead ? `${lead.boat}号艇 ${lead.name}（${lead.class}）` : "データ確認中")}</p>
      <div class="meter"><i style="width:${Math.max(0, Math.min(100, Number(item.score)))}%"></i></div>
      <p class="disclaimer">一致度 ${Number(item.agreement).toFixed(0)}%・データ取得率 ${Number(item.data_rate).toFixed(0)}%</p>
    </article>`;
  }).join("");

  renderLongshots(longshots);
}

function deriveDailyRecords(payload = {}) {
  if (payload.daily && Object.keys(payload.daily).length) return payload.daily;
  const groups = {};
  Object.values(payload.evaluated || {}).forEach((item) => {
    const date = String(item.key || "").slice(0, 8);
    if (!/^\d{8}$/.test(date)) return;
    (groups[date] ||= []).push(item);
  });
  return Object.fromEntries(Object.entries(groups).map(([date, records]) => {
    const hits = records.filter((item) => item.hit).length;
    const net = records.reduce((sum, item) => sum + Number(item.profit_yen || 0), 0);
    return [date, {
      date: `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6)}`,
      published: records.length,
      evaluated: records.length,
      samples: records.length,
      hits,
      hit_rate: records.length ? hits / records.length * 100 : 0,
      net_profit_yen: net,
      pending: 0,
    }];
  }));
}

function renderDailyPerformance() {
  const predictions = window.betakoPredictions;
  const performance = window.betakoPerformance || {};
  if (!predictions) return;
  const todayKey = String(predictions.race_date || dateInput.value).replaceAll("-", "");
  const daily = deriveDailyRecords(performance);
  const storedToday = daily[todayKey] || {};
  const published = Array.isArray(predictions.rankings) ? predictions.rankings.length : 0;
  const evaluated = Number(storedToday.evaluated ?? storedToday.samples ?? 0);
  const hits = Number(storedToday.hits || 0);
  const pending = Math.max(0, published - evaluated);
  const state = !published ? "公開予想なし" : pending ? "結果待ち" : "集計済み";
  document.querySelector("#todayPublished").textContent = `${published}件`;
  document.querySelector("#todayEvaluated").textContent = `${evaluated}/${published}件`;
  document.querySelector("#todayHits").textContent = evaluated ? `${hits}件` : "判定前";
  document.querySelector("#todayRecordStatus").textContent = state;

  const today = {
    date: predictions.race_date || dateInput.value,
    published,
    evaluated,
    samples: evaluated,
    hits,
    hit_rate: evaluated ? hits / evaluated * 100 : 0,
    net_profit_yen: storedToday.net_profit_yen || 0,
    pending,
  };
  const rows = { ...daily, [todayKey]: today };
  document.querySelector("#dailyHistory").innerHTML = Object.entries(rows)
    .sort(([a], [b]) => b.localeCompare(a))
    .slice(0, 14)
    .map(([, item]) => {
      const itemPublished = Number(item.published || item.samples || 0);
      const itemEvaluated = Number(item.evaluated ?? item.samples ?? 0);
      const itemPending = Math.max(0, Number(item.pending ?? itemPublished - itemEvaluated));
      const status = itemPending ? "結果待ち" : "集計済み";
      const hitText = itemEvaluated ? `${Number(item.hits || 0)}件` : "--";
      const rateText = itemEvaluated ? `${Number(item.hit_rate || 0).toFixed(1)}%` : "--";
      const netText = itemEvaluated ? `${Number(item.net_profit_yen || 0).toLocaleString("ja-JP")}円` : "--";
      return `<div class="dailyRow" role="row"><span>${escapeHtml(item.date || "--")}</span><span>${itemPublished}件</span><span>${itemEvaluated}件</span><span>${hitText}</span><span>${rateText}</span><span>${netText}</span><span class="${itemPending ? "dailyPending" : "dailyComplete"}">${status}</span></div>`;
    }).join("");
}

function renderTodayVenuePerformance() {
  const container = document.querySelector("#venuePerformanceGrid");
  const thresholdNode = document.querySelector("#venueThresholds");
  if (!container || !thresholdNode) return;
  const performance = window.betakoPerformance || {};
  const predictionDate = window.betakoPredictions?.race_date;
  if (!predictionDate) {
    thresholdNode.textContent = "本日分の固定13点を照合中。未確定レースは母数に含めません。";
    container.innerHTML = `<article class="venuePerformanceCard"><span>結果待ち</span><h3>固定13点を確認中</h3><p>予想データの読み込み後に表示します。</p></article>`;
    return;
  }
  const dateKey = String(predictionDate).replaceAll("-", "");
  const evaluated = Object.values(performance.portfolio_evaluated || {})
    .filter((item) => String(item.key || "").startsWith(`${dateKey}-`) && item.strategy === "fixed13")
    .sort((a, b) => Number(a.race || 0) - Number(b.race || 0));
  const hits = evaluated.filter((item) => item.hit);
  thresholdNode.textContent = `固定13点：${evaluated.length}R照合・${hits.length}R的中｜各レース13点×100円｜${performance.updated_at || "更新時刻不明"}`;
  if (!hits.length) {
    container.innerHTML = `<article class="venuePerformanceCard"><span>結果待ち</span><h3>固定13点の的中はまだありません</h3><p>${evaluated.length ? `${evaluated.length}R照合済み` : "公式結果が確定したレースから自動照合します。"}</p></article>`;
    return;
  }
  const marketLabels = { single: "単勝", exacta: "2連単", quinella: "2連複", trio: "3連複", trifecta: "3連単" };
  container.innerHTML = hits.map((item) => {
    const winningTickets = (item.tickets || []).filter((ticket) => ticket.hit);
    const winningText = winningTickets.map((ticket) => `${marketLabels[ticket.bet_type] || ticket.bet_type} ${ticket.predicted}`).join("｜");
    return `<article class="venuePerformanceCard hot">
      <span>固定13点 的中</span>
      <h3>${escapeHtml(item.venue)} ${Number(item.race)}R</h3>
      <strong>${escapeHtml(winningText || `${Number(item.hit_count || 1)}点的中`)}</strong>
      <p>払戻 ${Number(item.payout_yen || 0).toLocaleString("ja-JP")}円｜投資1,300円｜収支 ${Number(item.profit_yen || 0) >= 0 ? "+" : ""}${Number(item.profit_yen || 0).toLocaleString("ja-JP")}円</p>
      <small>公式結果照合済み</small>
    </article>`;
  }).join("");
}

document.querySelector("#copyXPost").addEventListener("click", async () => {
  const top = window.betakoPredictions?.rankings?.[0];
  const status = document.querySelector("#copyStatus");
  if (!top) {
    status.textContent = "投稿できる予想データがありません。";
    return;
  }
  const post = `🌊水面ベタ子の厳選予想\n${top.venue} ${top.race}R\n期待度指数 ${Math.round(top.score)}\n本線候補 ${top.pick}\n一致度 ${Math.round(top.agreement)}%\n\n※検証中の分析情報です。的中・利益を保証しません。\nhttps://jcleanex-sudo.github.io/betako-free-site/`;
  try {
    await navigator.clipboard.writeText(post);
    status.textContent = "コピーしました。Xへ貼り付けられます。";
  } catch {
    status.textContent = "コピーできませんでした。ブラウザの許可を確認してください。";
  }
});

document.querySelector("#copyStaffShare").addEventListener("click", async () => {
  const rankings = window.betakoPredictions?.rankings || [];
  const longshots = window.betakoPredictions?.longshots || [];
  const checks = window.betakoExhibition?.race_date === dateInput.value
    ? (window.betakoExhibition?.longshots || [])
    : [];
  const status = document.querySelector("#staffShareStatus");
  if (!rankings.length) {
    status.textContent = "共有できる予想データがありません。";
    return;
  }
  const mainLines = rankings.slice(0, 3).map((item, index) => `${index + 1}. ${item.venue}${item.race}R ${item.pick}｜指数${Math.round(item.score)} ${item.label}`);
  const holeLines = longshots.slice(0, 3).map((item) => {
    const check = checks.find((candidate) => candidate.venue === item.venue && String(candidate.race) === String(item.race) && String(candidate.boat) === String(item.boat));
    return `${item.venue}${item.race}R ${item.boat}号艇 ${item.name}｜${check?.status || "WATCH"}`;
  });
  const shareText = `【水面ベタ子・本日の共有】\n\n本命ランキング\n${mainLines.join("\n")}\n\n穴党WATCH\n${holeLines.length ? holeLines.join("\n") : "候補なし"}\n\nUP=仮想検証候補／WATCH=見送り監視／DATA BLOCKED=データ不足\n※的中・利益を保証する情報ではありません。\nhttps://jcleanex-sudo.github.io/betako-free-site/`;
  try {
    await navigator.clipboard.writeText(shareText);
    status.textContent = "スタッフ共有文をコピーしました。LINEやメールへ貼り付けられます。";
  } catch {
    status.textContent = "コピーできませんでした。ブラウザのクリップボード許可を確認してください。";
  }
});

const refreshDataButton = document.querySelector("#refreshDataButton");
const refreshDataStatus = document.querySelector("#refreshDataStatus");

async function fetchFreshJson(path) {
  const relative = String(path).replace(/^data\//, "");
  const sources = String(path).startsWith("data/")
    ? [`${liveDataBase}/${relative}`, path]
    : [path];
  let lastError = null;
  for (const source of sources) {
    try {
      const response = await fetch(`${source}?ts=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`${source} HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error(`${path}: unavailable`);
}

function applyPerformancePayload(payload) {
  window.betakoPerformance = payload;
  renderDailyPerformance();
  renderTodayVenuePerformance();
  const summary = payload.summary || {};
  document.querySelector("#learningSamples").textContent = `${summary.samples || 0}件`;
  document.querySelector("#learningHit").textContent = `${Number(summary.hit_rate || 0).toFixed(1)}%`;
  document.querySelector("#learningNet").textContent = `${Number(summary.net_profit_yen || 0).toLocaleString("ja-JP")}円`;
  document.querySelector("#learningRisk").textContent = `${summary.profit_factor ?? "--"} / ${Number(summary.max_drawdown_yen || 0).toLocaleString("ja-JP")}円`;
  document.querySelector("#learningCi").textContent = summary.hit_rate_ci95 ? `${summary.hit_rate_ci95[0]}%—${summary.hit_rate_ci95[1]}%` : "集計開始待ち";
  const market = payload.market_summary || {};
  document.querySelector("#marketSamples").textContent = `${Number(market.samples || 0)}件`;
  document.querySelector("#marketPerformance").textContent = Number(market.samples || 0)
    ? `${Number(market.hit_rate || 0).toFixed(1)}% / ${Number(market.net_profit_yen || 0).toLocaleString("ja-JP")}円`
    : "集計開始待ち";
  const marketLabels = { single: "単勝", exacta: "2連単", quinella: "2連複", trio: "3連複", trifecta: "3連単" };
  document.querySelector("#marketByType").textContent = Object.entries(marketLabels)
    .map(([key, label]) => `${label}${Number(payload.market_by_type?.[key]?.samples || 0)}件`)
    .join("｜");
  const portfolio = payload.portfolio_summary || {};
  document.querySelector("#portfolioSamples").textContent = `${Number(portfolio.samples || 0)}件`;
  document.querySelector("#portfolioPerformance").textContent = Number(portfolio.samples || 0)
    ? `${Number(portfolio.hit_rate || 0).toFixed(1)}% / ${Number(portfolio.net_profit_yen || 0).toLocaleString("ja-JP")}円`
    : "集計開始待ち";
  const renderTier = (name, tier) => {
    const ci = tier.hit_rate_ci95 ? `${tier.hit_rate_ci95[0]}%—${tier.hit_rate_ci95[1]}%` : "--";
    document.querySelector(`#${name}Samples`).textContent = `${tier.samples || 0}件`;
    document.querySelector(`#${name}Metrics`).textContent = `純損益 ${Number(tier.net_profit_yen || 0).toLocaleString("ja-JP")}円｜PF ${tier.profit_factor ?? 0}｜DD ${Number(tier.max_drawdown_yen || 0).toLocaleString("ja-JP")}円｜95%CI ${ci}`;
  };
  renderTier("strict", payload.tiers?.strict || {});
  renderTier("experimental", payload.tiers?.experimental || {});
  const longshot = payload.longshot_summary || {};
  const longshotCi = longshot.hit_rate_ci95 ? `${longshot.hit_rate_ci95[0]}%—${longshot.hit_rate_ci95[1]}%` : "--";
  document.querySelector("#longshotSamples").textContent = `${longshot.samples || 0}件`;
  document.querySelector("#longshotMetrics").textContent = `純損益 ${Number(longshot.net_profit_yen || 0).toLocaleString("ja-JP")}円｜PF ${longshot.profit_factor ?? 0}｜最大DD ${Number(longshot.max_drawdown_yen || 0).toLocaleString("ja-JP")}円｜95%CI ${longshotCi}`;
}

function applyModelCalibration(payload) {
  window.betakoModelCalibration = payload;
  document.querySelector("#historicalSamples").textContent = `${Number(payload.samples || 0).toLocaleString("ja-JP")}件`;
  document.querySelector("#calibrationStatus").textContent = `${payload.status || "COLLECTING"}｜${payload.reason || "検証中"}`;
  const validation = payload.baseline_validation || {};
  document.querySelector("#heroModelVersion").textContent = payload.logic_transition || "現行モデル";
  document.querySelector("#heroAccuracy").textContent = Number(validation.top1_accuracy || 0).toFixed(1);
  document.querySelector("#heroValidationSamples").textContent = `検証 ${Number(validation.samples || 0).toLocaleString("ja-JP")}レース`;
  document.querySelector("#heroTrainingSamples").textContent = Number(payload.samples || 0).toLocaleString("ja-JP");
}

function applyExhibitionPayload(payload) {
  window.betakoExhibition = payload.race_date === dateInput.value
    ? payload
    : { race_date: payload.race_date || null, races: [], longshots: [] };
  renderLongshots(window.betakoPredictions?.longshots || []);
}

async function refreshAllData({ manual = false } = {}) {
  refreshDataButton.disabled = true;
  refreshDataButton.textContent = "↻ 取得中";
  refreshDataStatus.className = "";
  refreshDataStatus.textContent = manual ? "再取得中…" : "自動取得中…";

  const results = await Promise.allSettled([
    fetchFreshJson("data/predictions.json"),
    fetchFreshJson("data/performance.json"),
    fetchFreshJson("data/model_calibration.json"),
    fetchFreshJson("data/exhibition.json"),
    fetchFreshJson("data/runtime.json"),
  ]);
  const [predictions, performance, calibration, exhibition, runtime] = results;

  if (predictions.status === "fulfilled") renderRankings(predictions.value);
  else if (!window.betakoPredictions) renderRankings({ status: "DATA BLOCKED", message: "予想データを取得できませんでした。上の更新ボタンで再取得してください", rankings: [] });
  if (exhibition.status === "fulfilled") applyExhibitionPayload(exhibition.value);
  else if (!window.betakoExhibition) window.betakoExhibition = { races: [] };
  if (performance.status === "fulfilled") applyPerformancePayload(performance.value);
  if (calibration.status === "fulfilled") applyModelCalibration(calibration.value);
  if (runtime.status === "fulfilled") window.betakoRuntime = runtime.value;
  else if (!window.betakoRuntime) window.betakoRuntime = {};

  const succeeded = results.filter((result) => result.status === "fulfilled").length;
  refreshDataButton.disabled = false;
  refreshDataButton.textContent = "↻ 最新データ";
  if (succeeded === results.length) {
    refreshDataStatus.className = "success";
    refreshDataStatus.textContent = `${new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })} 更新完了`;
  } else {
    refreshDataStatus.className = "error";
    refreshDataStatus.textContent = succeeded
      ? `${succeeded}/${results.length}件取得・再試行可`
      : "通信失敗・再試行してください";
  }
}

refreshDataButton.addEventListener("click", () => { void refreshAllData({ manual: true }); });
window.addEventListener("offline", () => {
  refreshDataStatus.className = "error";
  refreshDataStatus.textContent = "オフラインです";
});
window.addEventListener("online", () => {
  refreshDataStatus.className = "";
  refreshDataStatus.textContent = "通信復帰・更新できます";
});

void refreshAllData();
