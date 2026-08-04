const venues = ["桐生","戸田","江戸川","平和島","多摩川","浜名湖","蒲郡","常滑","津","三国","びわこ","住之江","尼崎","鳴門","丸亀","児島","宮島","徳山","下関","若松","芦屋","福岡","唐津","大村"];
const venueSelect = document.querySelector("#venue");
const raceSelect = document.querySelector("#race");
const dateInput = document.querySelector("#raceDate");
const pendingRefreshes = new Set();

venues.forEach((venue, index) => venueSelect.add(new Option(`${String(index + 1).padStart(2, "0")} ${venue}`, venue)));
for (let race = 1; race <= 12; race += 1) raceSelect.add(new Option(`${race}R`, String(race)));
venueSelect.value = "大村";
dateInput.value = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });

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

function renderFormation(target, tickets) {
  if (!tickets.length) {
    target.textContent = "--";
    return;
  }
  const labels = ["1着", "2着", "3着"];
  target.replaceChildren(...tickets.map((ticket) => {
    const pick = typeof ticket === "string" ? ticket : ticket?.pick || "--";
    const boats = pick.split("-");
    const row = document.createElement("div");
    row.className = "formationRow";
    labels.forEach((label, index) => {
      const position = document.createElement("span");
      const caption = document.createElement("small");
      const boat = document.createElement("b");
      caption.textContent = label;
      boat.textContent = boats[index] || "--";
      position.append(caption, boat);
      row.append(position);
    });
    if (typeof ticket !== "string" && ticket?.net_edge != null) {
      const edge = document.createElement("em");
      edge.textContent = `edge ${ticket.net_edge >= 0 ? "+" : ""}${Number(ticket.net_edge).toFixed(1)}%`;
      row.append(edge);
    }
    return row;
  }));
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
  const finalData = window.betakoExhibition?.races?.find((item) => item.venue === venue && String(item.race) === raceSelect.value);
  const finalReady = finalMode && finalData?.status === "FINAL";
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
  const morningSkip = !match
    || match.label !== "厳格候補"
    || Number(match.score) < 75
    || Number(match.agreement) < 75
    || Number(match.data_rate) < 95;
  const skipTarget = finalMode ? !finalReady || valueStatus !== "UP" : morningSkip;
  const decisionBadge = document.querySelector("#decisionBadge");
  decisionBadge.hidden = !skipTarget;
  decisionBadge.textContent = "見送り対象";
  const candidatePlan = buildBetPlan(match?.contenders, finalReady ? finalData.final_pick : match?.pick);
  const betPlan = finalMode && finalData?.ticket_plan ? finalData.ticket_plan : candidatePlan;
  document.querySelector("#mainLabel").textContent = betPlan.ranked_by_edge ? "期待値上位6点" : "本線候補6点";
  renderFormation(document.querySelector("#mainPicks"), betPlan.main);
  renderFormation(document.querySelector("#coverPicks"), betPlan.cover);
  document.querySelector("#selectionText").textContent = finalReady
    ? `${venue} ${raceSelect.value}R・展示後指数 ${Math.round(finalData.final_score)}（FINAL）`
    : match
      ? `${venue} ${raceSelect.value}R・期待度指数 ${Math.round(match.score)}（${finalMode ? finalData?.status || "WAIT" : match.label}）`
    : `${dateInput.value}・${venue} ${raceSelect.value}R・DATA BLOCKED`;
  document.querySelector("#predictionDetail").textContent = finalReady
    ? `期待値最上位 ${finalData.best_value_pick || finalData.final_pick}｜3連単オッズ ${value?.odds ? `${value.odds}倍` : "未公開"}｜net edge ${value?.net_edge == null ? "--" : `${value.net_edge}%`}｜残り ${liveRemaining == null ? "--" : `${Math.max(0, liveRemaining).toFixed(0)}分`}｜判定 ${valueStatus}`
    : match
      ? `本線候補 ${match.pick}｜相対1着推定 ${Math.round(match.estimated_probability)}%｜一致度 ${Math.round(match.agreement)}%｜データ取得率 ${Math.round(match.data_rate)}%`
    : dateMatches
      ? "公式データを取得できなかったレースです。DATA BLOCKEDとして見送ります。"
      : "選択日の予想データはありません。本日の日付を選択してください。";
  const reasons = document.querySelector("#predictionReasons");
  const displayedReasons = finalReady ? finalData.reasons : (match?.reasons || []);
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function renderLongshots(longshots) {
  const longshotGrid = document.querySelector("#longshotGrid");
  const checks = window.betakoExhibition?.longshots || [];
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
  const grid = document.querySelector("#rankingGrid");
  const status = document.querySelector("#dataStatus");
  const updated = document.querySelector("#dataUpdated");
  const rankings = Array.isArray(payload.rankings) ? payload.rankings : [];
  const longshots = Array.isArray(payload.longshots) ? payload.longshots : [];
  status.textContent = payload.status === "OK" ? "公式データ反映" : "DATA BLOCKED";
  updated.textContent = payload.updated_at ? `${payload.updated_at} 更新` : "更新時刻不明";

  if (!rankings.length) {
    grid.innerHTML = `<article class="rankCard gold"><div class="rankTop"><span class="rankNumber">--</span><span class="candidate">見送り</span></div><h3>公開できる候補なし</h3><div class="index"><span>状態</span><strong>--</strong></div><div class="pick"><span>理由</span><b>${escapeHtml(payload.message || "データ不足")}</b></div><div class="meter"><i style="width:0"></i></div></article>`;
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
  const checks = window.betakoExhibition?.longshots || [];
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

fetch(`data/predictions.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(renderRankings)
  .catch(() => renderRankings({ status: "DATA BLOCKED", message: "予想データを取得できませんでした", rankings: [] }));

fetch(`data/performance.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((payload) => {
    const summary = payload.summary || {};
    document.querySelector("#learningSamples").textContent = `${summary.samples || 0}件`;
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

fetch(`data/exhibition.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((payload) => {
    window.betakoExhibition = payload;
    renderLongshots(window.betakoPredictions?.longshots || []);
  })
  .catch(() => { window.betakoExhibition = { races: [] }; });

fetch(`data/runtime.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((payload) => { window.betakoRuntime = payload; })
  .catch(() => { window.betakoRuntime = {}; });
