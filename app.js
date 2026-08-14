const venues = ["桐生","戸田","江戸川","平和島","多摩川","浜名湖","蒲郡","常滑","津","三国","びわこ","住之江","尼崎","鳴門","丸亀","児島","宮島","徳山","下関","若松","芦屋","福岡","唐津","大村"];
const venueSelect = document.querySelector("#venue");
const raceSelect = document.querySelector("#race");
const dateInput = document.querySelector("#raceDate");
const pendingRefreshes = new Set();
let latestManualPrediction = null;

function exhibitionMatchesPrediction(exhibition = window.betakoExhibition, predictions = window.betakoPredictions) {
  const quality = window.betakoQuality;
  return Boolean(
    quality?.status === "PASS"
    && quality.race_date === dateInput.value
    && quality.prediction_updated_at === predictions?.updated_at
    && exhibition?.race_date
    && exhibition.race_date === dateInput.value
    && predictions?.race_date === dateInput.value
    && exhibition.prediction_updated_at
    && exhibition.prediction_updated_at === predictions.updated_at
  );
}

venueSelect.replaceChildren(new Option("公式開催場を確認中", ""));
venueSelect.disabled = true;
for (let race = 1; race <= 12; race += 1) raceSelect.add(new Option(`${race}R`, String(race)));
dateInput.value = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });

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
          venue_id: String(venues.indexOf(venue) + 1).padStart(2, "0"),
          fetched_races: fetchedRaces,
          reference_rate: referenceRate,
          complete: fetchedRaces === 12,
        };
      });
  const current = venueSelect.value;
  venueSelect.replaceChildren(...official.map((item) => new Option(
    `${item.venue_id} ${item.venue}${item.complete === false ? `（${item.fetched_races}/12R）` : ""}`,
    item.venue,
  )));
  const available = payload.status === "OK" && official.length > 0 && official.every((item) => item.complete !== false);
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

  const strict = Number(match.score) >= 75 && Number(match.agreement) >= 75 && Number(match.data_rate) >= 95;
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

function renderPendingFormation(target) {
  target.classList.add("singleFormation");
  const card = document.createElement("div");
  card.className = "formationCard pendingFormation";
  card.innerHTML = `<div class="formationHeader"><b>DATA CHECK</b><em>確認中</em></div><div class="formationColumns">${["1着", "2着", "3着"].map((label) => `<section><small>${label}</small><div class="pendingChoice">取得中</div></section>`).join("")}</div>`;
  target.replaceChildren(card);
}

function ticketText(ticket) {
  return typeof ticket === "string" ? ticket : ticket?.pick || "--";
}

function formationPointCount(first, second, third) {
  let points = 0;
  first.forEach((a) => second.forEach((b) => third.forEach((c) => {
    if (a !== b && a !== c && b !== c) points += 1;
  })));
  return points;
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
  const fixedLines = [
    `${date} ${payload.venue}${payload.race}R`,
    ...formationCopyLines("本線", payload.main),
    ...formationCopyLines("押さえ", payload.cover),
    "※検証中・的中利益保証なし",
  ];
  const maxJapaneseCharacters = 140;
  const developmentPrefix = "展開:";
  const reserved = Array.from(fixedLines.join("\n")).length + developmentPrefix.length + 1;
  const development = Array.from(payload.development || "").slice(0, Math.max(0, maxJapaneseCharacters - reserved)).join("");
  return [fixedLines[0], `${developmentPrefix}${development}`, ...fixedLines.slice(1)].join("\n");
}

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

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
    const response = await fetch(`${api.replace(/\/$/, "")}/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ venue_id: venueId, race, race_date: raceDate }),
    });
    if (!response.ok) throw new Error(`refresh ${response.status}`);

    for (let attempt = 0; attempt < 24; attempt += 1) {
      await delay(10000);
      const exhibitionResponse = await fetch(`data/exhibition.json?ts=${Date.now()}`, { cache: "no-store" });
      if (!exhibitionResponse.ok) continue;
      const payload = await exhibitionResponse.json();
      if (payload.race_date !== raceDate || payload.prediction_updated_at !== window.betakoPredictions?.updated_at) continue;
      const refreshed = payload.races?.find((item) => item.venue_id === venueId && String(item.race) === String(race));
      if (refreshed && (refreshed.fetched_at !== previousFetchedAt || payload.updated_at !== previousUpdatedAt)) {
        window.betakoExhibition = payload;
        renderLongshots(window.betakoPredictions?.longshots || []);
        document.querySelector("#predictionForm").requestSubmit();
        return;
      }
    }
    badge.textContent = "展示前・更新待ち";
    detail.textContent = "更新処理は受付済みです。少し待ってから、もう一度このレースを選んでください。";
  } catch {
    badge.textContent = "展示前";
    detail.textContent = "更新を開始できませんでした。朝の予想を表示し、購入は見送り対象にします。";
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

document.querySelector("#predictionForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const venue = venueSelect.value;
  const venueIndex = venues.indexOf(venue) + 1;
  document.querySelector("#venueCode").textContent = String(venueIndex).padStart(2, "0");
  const predictionDate = window.betakoPredictions?.race_date;
  const dateMatches = !predictionDate || predictionDate === dateInput.value;
  const match = dateMatches
    ? (window.betakoPredictions?.all_races || window.betakoPredictions?.rankings || []).find((item) => item.venue === venue && String(item.race) === raceSelect.value)
    : null;
  const finalMode = document.querySelector("#predictionType").value === "展示後AI最終予想";
  const exhibitionDateMatches = exhibitionMatchesPrediction();
  const finalData = exhibitionDateMatches
    ? window.betakoExhibition?.races?.find((item) => item.venue === venue && String(item.race) === raceSelect.value)
    : null;
  const finalReady = finalMode && finalData?.status === "FINAL";
  renderExhibitionTimes(finalData, finalMode);
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
  const referenceBlocked = Boolean(match) && Number(match.data_rate) < 100;
  const morningSkip = !match
    || match.label !== "厳格候補"
    || Number(match.score) < 75
    || Number(match.agreement) < 75
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
  document.querySelector("#mainLabel").textContent = referenceBlocked
    ? "本線・データ確認中"
    : skipTarget
    ? "参考買い目6点（見送り）"
    : betPlan.ranked_by_edge ? "期待値上位6点" : "本線候補6点";
  document.querySelector("#coverLabel").textContent = referenceBlocked ? "押さえ・データ確認中" : "押さえ6点";
  if (referenceBlocked) {
    renderPendingFormation(document.querySelector("#mainPicks"));
    renderPendingFormation(document.querySelector("#coverPicks"));
  } else {
    renderFormation(document.querySelector("#mainPicks"), betPlan.main);
    renderFormation(document.querySelector("#coverPicks"), betPlan.cover);
  }
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
      ? `期待値最上位 ${finalData.best_value_pick || finalData.final_pick}｜3連単オッズ ${value?.odds ? `${value.odds}倍` : "未公開"}｜net edge ${value?.net_edge == null ? "--" : `${value.net_edge}%`}｜残り ${liveRemaining == null ? "--" : `${Math.max(0, liveRemaining).toFixed(0)}分`}｜判定 ${valueStatus}`
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
    ? `WAIT：${finalData?.message || "展示データが未取得です。朝予想を維持します。"}｜締切 ${value?.deadline || "未取得"}｜期待値判定 ${valueStatus}：${valueMessage || "3連単オッズ未公開"}`
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
    detail: document.querySelector("#predictionDetail").textContent,
    invalidConditions: document.querySelector("#invalidConditions").textContent,
  };
  document.querySelector("#manualCopyStatus").textContent = "";
  document.querySelector("#selectionResult").hidden = false;
  if (finalMode && !finalReady && match) {
    void refreshSelectedRace({
      venueId: String(venueIndex).padStart(2, "0"),
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function renderLongshots(longshots) {
  const longshotGrid = document.querySelector("#longshotGrid");
  const checks = exhibitionMatchesPrediction()
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
  const completeRaceCount = (payload.all_races || []).filter((item) => Number(item.data_rate) >= 100).length;
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
  const coverageReady = payload.status === "OK" && collectionRate >= 100 && !stalePrediction;
  if (!coverageReady) {
    rankings = [];
    longshots = [];
  } else {
    rankings = rankings.filter((item) => Number(item.data_rate) >= 100);
    longshots = longshots.filter((item) => (payload.all_races || []).some(
      (race) => race.venue === item.venue && Number(race.race) === Number(item.race) && Number(race.data_rate) >= 100,
    ));
  }
  window.betakoPredictions = { ...payload, rankings, longshots };
  renderDailyPerformance();
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
  const checks = exhibitionMatchesPrediction()
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

Promise.all([
  fetch(`data/predictions.json?ts=${Date.now()}`, { cache: "no-store" }),
  fetch(`data/exhibition.json?ts=${Date.now()}`, { cache: "no-store" }),
  fetch(`data/quality.json?ts=${Date.now()}`, { cache: "no-store" }),
])
  .then(async (responses) => {
    if (responses.some((response) => !response.ok)) throw new Error("dataset fetch failed");
    const [predictions, exhibition, quality] = await Promise.all(responses.map((response) => response.json()));
    const coherent = quality.status === "PASS"
      && quality.race_date === predictions.race_date
      && quality.prediction_updated_at === predictions.updated_at
      && exhibition.race_date === predictions.race_date
      && exhibition.prediction_updated_at === predictions.updated_at;
    if (!coherent) throw new Error("dataset version mismatch");
    window.betakoQuality = quality;
    window.betakoExhibition = exhibition;
    renderRankings(predictions);
  })
  .catch(() => {
    window.betakoQuality = { status: "DATA BLOCKED" };
    window.betakoExhibition = { races: [], longshots: [] };
    renderRankings({ status: "DATA BLOCKED", message: "検証済みデータを準備中です。全レースの表示枠は維持したまま自動再取得します。", rankings: [], all_races: [] });
  });

fetch(`data/performance.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((payload) => {
    window.betakoPerformance = payload;
    renderDailyPerformance();
    const summary = payload.summary || {};
    document.querySelector("#learningSamples").textContent = `${summary.samples || 0}件`;
    document.querySelector("#learningHit").textContent = `${Number(summary.hit_rate || 0).toFixed(1)}%`;
    document.querySelector("#learningNet").textContent = `${Number(summary.net_profit_yen || 0).toLocaleString("ja-JP")}円`;
    document.querySelector("#learningRisk").textContent = `${summary.profit_factor ?? "--"} / ${Number(summary.max_drawdown_yen || 0).toLocaleString("ja-JP")}円`;
    document.querySelector("#learningCi").textContent = summary.hit_rate_ci95 ? `${summary.hit_rate_ci95[0]}%—${summary.hit_rate_ci95[1]}%` : "集計開始待ち";
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
  })
  .catch(() => {});

fetch(`data/model_calibration.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((payload) => {
    document.querySelector("#historicalSamples").textContent = `${Number(payload.samples || 0).toLocaleString("ja-JP")}件`;
    document.querySelector("#calibrationStatus").textContent = `${payload.status || "COLLECTING"}｜${payload.reason || "検証中"}`;
  })
  .catch(() => {});

fetch(`data/runtime.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((payload) => { window.betakoRuntime = payload; })
  .catch(() => { window.betakoRuntime = {}; });
