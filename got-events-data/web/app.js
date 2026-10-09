// Gothenburg Events dashboard: reads ../events.csv written by 1-etl_data.ipynb

const DATA_URL = "../events.csv";

// Category colours: neon set ordered so neighbours stay distinguishable
// (checked for colour-blind separation on the dark background).
const CATEGORIES = [
  "Concert", "Theatre & shows", "Sports", "Festival", "Exhibition",
  "Market", "Family", "Tours", "Food & drink", "Other",
];
const CAT_COLOR = {
  "Concert": "#0a9fc2",
  "Theatre & shows": "#4a6cf7",
  "Sports": "#d62fb4",
  "Festival": "#c98500",
  "Exhibition": "#13a07a",
  "Market": "#e0622a",
  "Family": "#a24cf0",
  "Tours": "#f0507d",
  "Food & drink": "#8a8aa3",
  "Other": "#8a8aa3",
};

// Heat ramp, low -> high: cyan, blue, violet, magenta
const HEAT = ["#00e5ff", "#3fa9f5", "#3b4cf0", "#7a1af0", "#c21af0", "#ff00ff"];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const state = {
  year: new Date().getFullYear(),   // number or "all"
  month: null,                      // 1-12 or null
  cats: new Set(CATEGORIES),
  venue: "",
  estimated: true,
  free: false,
  search: "",
  mapMode: "venues",
};

let ALL = [];
let map, venueLayer, heatLayer;
let timelineChart, categoryChart;

// ---------------------------------------------------------------- helpers

const $ = (id) => document.getElementById(id);
const fmt = (n) => n.toLocaleString("en-GB");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// Interpolate along the HEAT ramp, t in [0, 1]
function heatColor(t) {
  t = Math.max(0, Math.min(1, t));
  const pos = t * (HEAT.length - 1);
  const i = Math.min(Math.floor(pos), HEAT.length - 2);
  const f = pos - i;
  const a = hexToRgb(HEAT[i]), b = hexToRgb(HEAT[i + 1]);
  const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${c.join(",")})`;
}

const heatGradientCss = `linear-gradient(90deg, ${HEAT.join(", ")})`;

function formatDate(d) {
  const date = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  const hasTime = d.getHours() || d.getMinutes();
  return hasTime ? `${date} · ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : date;
}

const editionKey = (r) => `${r.id}|${r.year}`;

// ---------------------------------------------------------------- filtering

// `skip` lets a view ignore its own dimension (e.g. the year heat map ignores the year filter)
function applyFilters(rows, skip = {}) {
  const q = state.search.trim().toLowerCase();
  return rows.filter((r) =>
    (state.estimated || r.source === "API") &&
    (skip.year || state.year === "all" || r.year === state.year) &&
    (skip.month || state.month === null || r.month === state.month) &&
    state.cats.has(r.category) &&
    (!state.venue || r.venue === state.venue) &&
    (!state.free || r.free) &&
    (skip.search || !q || r.name.toLowerCase().includes(q) || r.venue.toLowerCase().includes(q))
  );
}

// ---------------------------------------------------------------- load

Papa.parse(DATA_URL, {
  download: true,
  header: true,
  skipEmptyLines: true,
  complete: ({ data }) => {
    ALL = data
      .map((r) => {
        const start = new Date(r.start.replace(" ", "T"));
        return {
          id: r.event_id,
          name: r.name,
          start,
          year: start.getFullYear(),
          month: start.getMonth() + 1,
          category: CATEGORIES.includes(r.category) ? r.category : "Other",
          type: r.event_type,
          venue: r.venue || "Unknown",
          lat: +r.lat,
          lon: +r.lon,
          free: r.free === "True",
          source: r.source || "API",
          link: r.link,
        };
      })
      .filter((r) => !isNaN(r.start) && r.lat && r.lon)
      .sort((a, b) => a.start - b.start);

    const years = [...new Set(ALL.map((r) => r.year))];
    if (!years.includes(state.year)) state.year = Math.max(...years);

    initControls();
    initMap();
    initCharts();
    render();
    $("loading").classList.add("hidden");
    // Re-measure chart labels once the web font has loaded
    document.fonts.ready.then(() => { timelineChart.update(); categoryChart.update(); });
  },
  error: (err) => {
    $("loading").textContent = `Could not load ${DATA_URL}: ${err}. Run 1-etl_data.ipynb first.`;
  },
});

fetch(DATA_URL, { method: "HEAD" }).then((res) => {
  const lm = res.headers.get("Last-Modified");
  if (lm) $("fetched").textContent = `Data fetched ${new Date(lm).toLocaleString("en-GB")}`;
});

// ---------------------------------------------------------------- controls

function initControls() {
  const venues = [...new Set(ALL.map((r) => r.venue))].sort((a, b) => a.localeCompare(b));
  $("venue-list").innerHTML = venues.map((v) => `<option value="${esc(v)}">`).join("");

  $("venue-input").addEventListener("change", (e) => {
    const v = e.target.value.trim();
    state.venue = venues.includes(v) ? v : "";
    if (!state.venue) e.target.value = "";
    render();
  });

  $("est-toggle").addEventListener("change", (e) => { state.estimated = e.target.checked; render(); });
  $("free-toggle").addEventListener("change", (e) => { state.free = e.target.checked; render(); });

  let t;
  $("search").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.search = e.target.value; render(); }, 150);
  });

  $("reset").addEventListener("click", () => {
    Object.assign(state, {
      year: new Date().getFullYear(), month: null, cats: new Set(CATEGORIES),
      venue: "", estimated: true, free: false, search: "",
    });
    $("venue-input").value = "";
    $("search").value = "";
    $("est-toggle").checked = true;
    $("free-toggle").checked = false;
    render();
  });

  $("map-mode").addEventListener("click", (e) => {
    const mode = e.target.dataset.mode;
    if (!mode) return;
    state.mapMode = mode;
    [...$("map-mode").children].forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    renderMap(applyFilters(ALL));
  });
}

function renderYearChips() {
  const visible = ALL.filter((r) => state.estimated || r.source === "API");
  const years = [...new Set(visible.map((r) => r.year))].sort();
  const apiYears = new Set(ALL.filter((r) => r.source === "API").map((r) => r.year));
  if (state.year !== "all" && !years.includes(state.year)) state.year = "all";

  $("year-chips").innerHTML =
    `<button class="chip ${state.year === "all" ? "on" : ""}" data-year="all">All years</button>` +
    years.map((y) => `
      <button class="chip ${state.year === y ? "on" : ""}" data-year="${y}">
        ${y}${apiYears.has(y) ? "" : '<span class="est">est.</span>'}
      </button>`).join("");

  $("year-chips").onclick = (e) => {
    const b = e.target.closest("[data-year]");
    if (!b) return;
    state.year = b.dataset.year === "all" ? "all" : +b.dataset.year;
    state.month = null;
    render();
  };
}

function renderCategoryChips() {
  const all = state.cats.size === CATEGORIES.length;
  $("cat-chips").innerHTML =
    `<button class="chip ${all ? "on" : ""}" data-cat="__all">All</button>` +
    CATEGORIES.map((c) => `
      <button class="chip ${!all && state.cats.has(c) ? "on" : ""}" data-cat="${esc(c)}" style="--c:${CAT_COLOR[c]}">
        <span class="dot"></span>${esc(c)}
      </button>`).join("");

  $("cat-chips").onclick = (e) => {
    const b = e.target.closest("[data-cat]");
    if (!b) return;
    const c = b.dataset.cat;
    if (c === "__all") state.cats = new Set(CATEGORIES);
    else if (state.cats.size === CATEGORIES.length) state.cats = new Set([c]);   // first click focuses
    else {
      state.cats.has(c) ? state.cats.delete(c) : state.cats.add(c);
      if (!state.cats.size) state.cats = new Set(CATEGORIES);
    }
    render();
  };
}

function renderActiveFilters() {
  const pills = [];
  if (state.month) pills.push(["month", `${MONTHS[state.month - 1]} ${state.year}`]);
  if (state.venue) pills.push(["venue", state.venue]);
  if (state.search) pills.push(["search", `“${state.search}”`]);
  $("active-filters").innerHTML = pills
    .map(([k, label]) => `<span class="pill" data-k="${k}">${esc(label)}</span>`).join("");
  $("active-filters").onclick = (e) => {
    const k = e.target.dataset.k;
    if (!k) return;
    if (k === "month") state.month = null;
    if (k === "venue") { state.venue = ""; $("venue-input").value = ""; }
    if (k === "search") { state.search = ""; $("search").value = ""; }
    render();
  };
}

// ---------------------------------------------------------------- KPIs

function renderKPIs(rows) {
  const editions = new Set(rows.map(editionKey));
  const venues = new Set(rows.map((r) => r.venue));
  const free = new Set(rows.filter((r) => r.free).map(editionKey));
  const est = rows.filter((r) => r.source !== "API").length;
  const scope = state.year === "all" ? "all years" : state.year;

  const cards = [
    ["Events", fmt(editions.size), scope],
    ["Event dates", fmt(rows.length), est ? `${fmt(est)} estimated` : "all from the API"],
    ["Locations", fmt(venues.size), "venues with events"],
    ["Free events", fmt(free.size), editions.size ? `${Math.round(100 * free.size / editions.size)}% of events` : ""],
  ];
  $("kpis").innerHTML = cards.map(([l, v, n]) => `
    <div class="kpi"><div class="k-label">${l}</div><div class="k-value">${v}</div><div class="k-note">${esc(n)}</div></div>
  `).join("");
}

// ---------------------------------------------------------------- map

function initMap() {
  map = L.map("map", { preferCanvas: true, zoomControl: true }).setView([57.705, 11.97], 12);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 16, className: "base-tiles", attribution: "Tiles © Esri, HERE, Garmin, © OpenStreetMap contributors" }
  ).addTo(map);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 16, opacity: 0.6 }
  ).addTo(map);
  venueLayer = L.layerGroup().addTo(map);
}

function venueStats(rows) {
  const by = new Map();
  for (const r of rows) {
    let v = by.get(r.venue);
    if (!v) by.set(r.venue, v = { venue: r.venue, lat: r.lat, lon: r.lon, dates: 0, editions: new Set(), cats: {} });
    v.dates++;
    v.editions.add(editionKey(r));
    v.cats[r.category] = (v.cats[r.category] || 0) + 1;
  }
  for (const v of by.values()) {
    v.main = Object.entries(v.cats).sort((a, b) => b[1] - a[1])[0][0];
  }
  return [...by.values()].sort((a, b) => b.dates - a.dates);
}

function renderMap(rows) {
  venueLayer.clearLayers();
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }

  const stats = venueStats(rows);
  const max = stats.length ? stats[0].dates : 1;

  if (state.mapMode === "heat") {
    const pts = stats.map((v) => [v.lat, v.lon, Math.sqrt(v.dates / max)]);
    heatLayer = L.heatLayer(pts, {
      radius: 28, blur: 22, maxZoom: 14, minOpacity: 0.3, max: 1,
      gradient: { 0.15: HEAT[0], 0.35: HEAT[1], 0.55: HEAT[2], 0.75: HEAT[3], 0.9: HEAT[4], 1: HEAT[5] },
    }).addTo(map);
    $("map-legend").innerHTML =
      `Density of event dates <span>fewer</span><span class="bar" style="background:${heatGradientCss}"></span><span>more</span>`;
    return;
  }

  // stats is sorted big -> small, so small dots are drawn last and sit on top
  for (const v of stats) {
    const color = CAT_COLOR[v.main];
    const cats = Object.entries(v.cats).sort((a, b) => b[1] - a[1])
      .map(([c, n]) => `<span style="color:${CAT_COLOR[c]}">●</span> ${esc(c)} ${n}`).join("<br>");
    L.circleMarker([v.lat, v.lon], {
      radius: 4 + 22 * Math.sqrt(v.dates / max),
      color, weight: 1.5, fillColor: color, fillOpacity: 0.45,
    })
      .bindTooltip(
        `<b>${esc(v.venue)}</b><br>${fmt(v.editions.size)} events · ${fmt(v.dates)} dates<br>${cats}`,
        { direction: "top", sticky: true }
      )
      .on("click", () => {
        state.venue = state.venue === v.venue ? "" : v.venue;
        $("venue-input").value = state.venue;
        render();
      })
      .addTo(venueLayer);
  }

  const present = CATEGORIES.filter((c) => stats.some((v) => v.main === c));
  $("map-legend").innerHTML =
    `<span>Colour = main category · size = event dates · click a dot to filter</span>` +
    present.map((c) => `<span><i class="sw" style="background:${CAT_COLOR[c]}"></i>${esc(c)}</span>`).join("");
}

// ---------------------------------------------------------------- charts

function initCharts() {
  Chart.defaults.color = "#9a9ab5";
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.borderColor = "#1c1c30";
  Chart.defaults.plugins.tooltip.backgroundColor = "#0c0c16";
  Chart.defaults.plugins.tooltip.borderColor = "#3a3a5c";
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 10;

  timelineChart = new Chart($("timeline"), {
    type: "bar",
    data: { labels: [], datasets: [] },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "Event dates" } },
      },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true } },
        tooltip: { filter: (item) => item.raw > 0 },
      },
      onClick: (_, els) => {
        if (!els.length || state.year === "all") return;
        const m = els[0].index + 1;
        state.month = state.month === m ? null : m;
        render();
      },
    },
  });

  categoryChart = new Chart($("categories"), {
    type: "bar",
    data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderRadius: 4 }] },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      layout: { padding: { left: 4 } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#1c1c30" } }, y: { grid: { display: false } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${fmt(c.raw)} events` } } },
      onClick: (_, els) => {
        if (!els.length) return;
        const c = categoryChart.data.labels[els[0].index];
        state.cats = state.cats.size === 1 && state.cats.has(c) ? new Set(CATEGORIES) : new Set([c]);
        render();
      },
    },
  });
}

function renderTimeline() {
  // Follows every filter except month; with "All years" it shows one bar per year
  const rows = applyFilters(ALL, { month: true });
  const allYears = state.year === "all";
  const labels = allYears ? [...new Set(rows.map((r) => r.year))].sort() : MONTHS;
  const bucket = (r) => allYears ? labels.indexOf(r.year) : r.month - 1;

  const datasets = CATEGORIES.filter((c) => rows.some((r) => r.category === c)).map((c) => {
    const data = labels.map(() => 0);
    rows.filter((r) => r.category === c).forEach((r) => data[bucket(r)]++);
    return {
      label: c, data,
      backgroundColor: CAT_COLOR[c],
      borderColor: "#0c0c16", borderWidth: 1, borderRadius: 3, borderSkipped: false,
      pointStyle: "circle",
    };
  });

  timelineChart.data.labels = labels;
  timelineChart.data.datasets = datasets;
  timelineChart.update();

  $("timeline-title").textContent = allYears
    ? "Event dates per year, by category"
    : `Event dates per month in ${state.year}, by category${state.month ? "" : " · click a month to filter"}`;
}

function renderCategories(rows) {
  const counts = CATEGORIES.map((c) => new Set(rows.filter((r) => r.category === c).map(editionKey)).size);
  const order = CATEGORIES.map((c, i) => [c, counts[i]]).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  categoryChart.data.labels = order.map(([c]) => c);
  categoryChart.data.datasets[0].data = order.map(([, n]) => n);
  categoryChart.data.datasets[0].backgroundColor = order.map(([c]) => CAT_COLOR[c]);
  categoryChart.update();
}

// Year x month grid; ignores the year/month filters so it shows the whole calendar
function renderCalendar() {
  const rows = applyFilters(ALL, { year: true, month: true });
  const apiYears = new Set(ALL.filter((r) => r.source === "API").map((r) => r.year));
  const years = [...new Set(rows.map((r) => r.year))].sort();
  const counts = {};
  rows.forEach((r) => { const k = `${r.year}-${r.month}`; counts[k] = (counts[k] || 0) + 1; });
  const max = Math.max(1, ...Object.values(counts));

  let html = `<div></div>` + MONTHS.map((m) => `<div class="h">${m}</div>`).join("");
  for (const y of years) {
    html += `<div class="y">${y}${apiYears.has(y) ? "" : "<small>est.</small>"}</div>`;
    for (let m = 1; m <= 12; m++) {
      const n = counts[`${y}-${m}`] || 0;
      const t = Math.sqrt(n / max);
      const sel = state.year === y && state.month === m;
      const style = n ? `background:${heatColor(t)};color:${t < 0.35 ? "#05050a" : "#fff"}` : "";
      html += `<div class="cell ${n ? "" : "zero"} ${sel ? "sel" : ""}" data-y="${y}" data-m="${m}" style="${style}"
        title="${MONTHS[m - 1]} ${y}: ${n} event dates">${n || ""}</div>`;
    }
  }
  const el = $("calendar");
  el.style.gridTemplateColumns = `auto repeat(12, minmax(34px, 1fr))`;
  el.innerHTML = years.length ? html : `<p class="note">No events match the filters.</p>`;
  el.onclick = (e) => {
    const c = e.target.closest(".cell");
    if (!c || c.classList.contains("zero")) return;
    const y = +c.dataset.y, m = +c.dataset.m;
    if (state.year === y && state.month === m) state.month = null;
    else { state.year = y; state.month = m; }
    render();
  };

  $("ramp").innerHTML =
    `<span>fewer</span><span class="bar" style="background:${heatGradientCss}"></span><span>more event dates</span>`;
}

function renderTopVenues(rows) {
  const top = venueStats(rows).slice(0, 10);
  const max = top.length ? top[0].dates : 1;
  $("top-venues").innerHTML = top.map((v) => {
    const segs = CATEGORIES.filter((c) => v.cats[c])
      .map((c) => `<i style="width:${(100 * v.cats[c] / max).toFixed(2)}%;background:${CAT_COLOR[c]}" title="${esc(c)}: ${v.cats[c]}"></i>`)
      .join("");
    return `<li data-v="${esc(v.venue)}">
      <div class="v-top"><span class="v-name">${esc(v.venue)}</span><span class="v-n">${fmt(v.dates)}</span></div>
      <div class="v-bar">${segs}</div></li>`;
  }).join("") || `<p class="note">No events match the filters.</p>`;

  $("top-venues").onclick = (e) => {
    const li = e.target.closest("[data-v]");
    if (!li) return;
    const v = li.dataset.v;
    state.venue = state.venue === v ? "" : v;
    $("venue-input").value = state.venue;
    render();
  };
}

function renderSchedule(rows) {
  const LIMIT = 300;
  $("schedule").innerHTML = rows.slice(0, LIMIT).map((r) => `
    <tr class="${r.source === "API" ? "" : "estimated"}">
      <td class="date">${formatDate(r.start)}</td>
      <td>${esc(r.name)}</td>
      <td><span class="cat"><i style="background:${CAT_COLOR[r.category]}"></i>${esc(r.category)}</span></td>
      <td>${esc(r.type)}</td>
      <td>${esc(r.venue)}</td>
      <td>${r.free ? "Yes" : ""}</td>
      <td class="${r.source === "API" ? "" : "est"}">${r.source === "API" ? "API" : "Estimated"}</td>
      <td>${r.link ? `<a href="${esc(r.link)}" target="_blank" rel="noopener">More info ↗</a>` : ""}</td>
    </tr>`).join("");
  $("table-note").textContent = rows.length > LIMIT
    ? `Showing the first ${LIMIT} of ${fmt(rows.length)} event dates. Narrow the filters to see more.`
    : `${fmt(rows.length)} event dates.`;
}

// ---------------------------------------------------------------- render

function render() {
  renderYearChips();
  renderCategoryChips();
  renderActiveFilters();

  const rows = applyFilters(ALL);
  renderKPIs(rows);
  renderMap(rows);
  renderTimeline();
  renderCalendar();
  renderCategories(rows);
  renderTopVenues(rows);
  renderSchedule(rows);
}
