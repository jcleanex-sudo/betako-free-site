const venues = ["桐生","戸田","江戸川","平和島","多摩川","浜名湖","蒲郡","常滑","津","三国","びわこ","住之江","尼崎","鳴門","丸亀","児島","宮島","徳山","下関","若松","芦屋","福岡","唐津","大村"];
const venueSelect = document.querySelector("#venue");
const raceSelect = document.querySelector("#race");
const dateInput = document.querySelector("#raceDate");

venues.forEach((venue, index) => venueSelect.add(new Option(`${String(index + 1).padStart(2, "0")} ${venue}`, venue)));
for (let race = 1; race <= 12; race += 1) raceSelect.add(new Option(`${race}R`, String(race)));
venueSelect.value = "大村";
dateInput.value = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });

document.querySelector("#predictionForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const venue = venueSelect.value;
  const venueIndex = venues.indexOf(venue) + 1;
  document.querySelector("#venueCode").textContent = String(venueIndex).padStart(2, "0");
  const match = window.betakoPredictions?.rankings?.find((item) => item.venue === venue && String(item.race) === raceSelect.value);
  const finalMode = document.querySelector("#predictionType").value === "展示後AI最終予想";
  const finalData = window.betakoExhibition?.races?.find((item) => item.venue === venue && String(item.race) === raceSelect.value);
  const finalReady = finalMode && finalData?.status === "FINAL";
  const value = finalData?.value;
  document.querySelector("#selectionText").textContent = finalReady
    ? `${venue} ${raceSelect.value}R・展示後指数 ${Math.round(finalData.final_score)}（FINAL）`
    : match
      ? `${venue} ${raceSelect.value}R・期待度指数 ${Math.round(match.score)}（${finalMode ? finalData?.status || "WAIT" : match.label}）`
    : `${dateInput.value}・${venue} ${raceSelect.value}R・DATA BLOCKED`;
  document.querySelector("#predictionDetail").textContent = finalReady
    ? `展示後本線 ${finalData.final_pick}｜3連単オッズ ${value?.odds ? `${value.odds}倍` : "未公開"}｜net edge ${value?.net_edge == null ? "--" : `${value.net_edge}%`}｜判定 ${value?.status || "DATA BLOCKED"}`
    : match
      ? `本線候補 ${match.pick}｜相対1着推定 ${Math.round(match.estimated_probability)}%｜一致度 ${Math.round(match.agreement)}%｜データ取得率 ${Math.round(match.data_rate)}%`
    : "現在の公開ランキングにこのレースはありません。根拠不足のため見送ります。";
  const reasons = document.querySelector("#predictionReasons");
  const displayedReasons = finalReady ? finalData.reasons : (match?.reasons || []);
  reasons.replaceChildren(...displayedReasons.map((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    return item;
  }));
  document.querySelector("#invalidConditions").textContent = finalReady
    ? `期待値判定：${value?.message || "オッズ未公開のため判定なし"}｜無効条件：オッズ急変、展示データ欠損、公式情報取得失敗`
    : finalMode && !finalReady
    ? `WAIT：${finalData?.message || "展示データが未取得です。朝予想を維持します。"}`
    : match
      ? `無効条件：${(match.invalid_conditions || []).join("／")}`
    : "見送り条件：ランキング対象外、データ不足、公式情報の取得失敗";
  document.querySelector("#selectionResult").hidden = false;
});

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function renderRankings(payload) {
  window.betakoPredictions = payload;
  const grid = document.querySelector("#rankingGrid");
  const status = document.querySelector("#dataStatus");
  const updated = document.querySelector("#dataUpdated");
  const rankings = Array.isArray(payload.rankings) ? payload.rankings : [];
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
    return `<article class="rankCard ${tone}">
      <div class="rankTop"><span class="rankNumber">${String(index + 1).padStart(2, "0")}</span><span class="candidate">${escapeHtml(item.label)}</span></div>
      <h3>${escapeHtml(item.venue)} <small>${escapeHtml(item.race)}R</small></h3>
      <div class="index"><span>期待度指数</span><strong>${Number(item.score).toFixed(0)}</strong></div>
      <div class="pick"><span>本線候補</span><b>${escapeHtml(item.pick)}</b></div>
      <p class="rankLead">軸：${escapeHtml(lead ? `${lead.boat}号艇 ${lead.name}（${lead.class}）` : "データ確認中")}</p>
      <div class="meter"><i style="width:${Math.max(0, Math.min(100, Number(item.score)))}%"></i></div>
      <p class="disclaimer">一致度 ${Number(item.agreement).toFixed(0)}%・データ取得率 ${Number(item.data_rate).toFixed(0)}%</p>
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
  })
  .catch(() => {});

fetch(`data/exhibition.json?ts=${Date.now()}`, { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((payload) => { window.betakoExhibition = payload; })
  .catch(() => { window.betakoExhibition = { races: [] }; });
