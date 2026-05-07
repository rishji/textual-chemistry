const data = window.VOW_DATA;

const fmt = new Intl.NumberFormat("en-US");
const weekdays = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
const weekdayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderStats() {
  const stats = [
    [fmt.format(data.totals.messages), "messages"],
    [fmt.format(data.totals.activeDays), "active days"],
    [`${data.totals.activePct}%`, "days with a text"],
    [fmt.format(data.totals.attachments), "attachments"]
  ];
  const grid = document.querySelector("#statsGrid");
  stats.forEach(([number, label]) => {
    const card = el("div", "stat");
    card.innerHTML = `<div><strong>${number}</strong><span>${label}</span></div>`;
    grid.appendChild(card);
  });
}

function renderMessageChart() {
  const series = data.months || data.years;
  const max = Math.max(...series.map((d) => d.messages));
  const chart = document.querySelector("#yearChart");
  series.forEach((item) => {
    const label = item.month || item.year;
    const isPeak = item.messages === max;
    const bar = el("div", `bar ${isPeak ? "highlight" : ""}`);
    bar.style.height = `${Math.max(22, (item.messages / max) * 260)}px`;
    bar.title = `${label} · ${fmt.format(item.messages)} messages`;
    bar.innerHTML = `<span>${label}<br>${fmt.format(item.messages)}</span>`;
    chart.appendChild(bar);
  });
}

function heatLevel(count) {
  if (count === 0) return 0;
  if (count < 40) return 1;
  if (count < 110) return 2;
  if (count < 185) return 3;
  if (count < 245) return 4;
  return 5;
}

function renderHeatmap() {
  const values = new Map(data.heatmap.map(([day, hour, count]) => [`${day}-${hour}`, count]));
  const heatmap = document.querySelector("#heatmap");
  const selection = document.querySelector("#heatSelection");

  heatmap.appendChild(el("div", "hm-label", ""));
  for (let hour = 0; hour < 24; hour += 1) {
    heatmap.appendChild(el("div", "hm-label", hour % 3 === 0 ? `${hour}` : ""));
  }

  for (let day = 0; day < 7; day += 1) {
    heatmap.appendChild(el("div", "hm-label", weekdays[day]));
    for (let hour = 0; hour < 24; hour += 1) {
      const count = values.get(`${day}-${hour}`) || 0;
      const cell = el("button", `cell level-${heatLevel(count)}`);
      cell.type = "button";
      cell.title = `${weekdayNames[day]} ${hour}:00 · ${count} messages`;
      cell.addEventListener("click", () => {
        document.querySelectorAll(".cell.selected").forEach((node) => node.classList.remove("selected"));
        cell.classList.add("selected");
        const average = data.weekdayAverages?.[day];
        const averageText = average ? ` · ${average} texts per ${weekdayNames[day]} on average` : "";
        selection.textContent = `${weekdayNames[day]} · ${hour}:00 — ${fmt.format(count)} messages all time${averageText}`;
      });
      heatmap.appendChild(cell);
    }
  }
}

function renderTerms() {
  const grid = document.querySelector("#termsGrid");
  data.terms.forEach(([term, count, note, unit = "messages"]) => {
    const card = el("div", "term-card");
    card.innerHTML = `<strong>${term}</strong><span>${fmt.format(count)} ${unit} · ${note}</span>`;
    grid.appendChild(card);
  });
}

function renderEmojis() {
  const grid = document.querySelector("#emojiGrid");
  data.emojis.forEach(([emoji, count, note], index) => {
    const card = el("div", `emoji-card ${emoji === "❤" ? "heart-card" : ""}`);
    card.style.borderStyle = index < 3 ? "solid" : "dashed";
    const noteHtml = note ? `<small>${note}</small>` : "";
    card.innerHTML = `<span class="emoji">${emoji}</span><strong>${fmt.format(count)}</strong><span>uses</span>${noteHtml}`;
    grid.appendChild(card);
  });
}

function renderOrigins() {
  const list = document.querySelector("#originList");
  data.origins.forEach((origin) => {
    const item = el("div", "origin");
    item.innerHTML = `<strong>${origin.topic}</strong><span>${origin.date} · ${origin.sender}</span><p>${origin.text}</p>`;
    list.appendChild(item);
  });
}

function renderCategories() {
  const list = document.querySelector("#categoryBars");
  const donut = document.querySelector("#categoryDonut");
  const total = data.categories.reduce((sum, item) => sum + item[1], 0);
  const colors = ["#5c765f", "#d8b277", "#bd735f", "#989991", "#7b917d"];
  let offset = 0;
  const stops = data.categories.map(([, count], index) => {
    const start = offset;
    offset += (count / total) * 100;
    return `${colors[index % colors.length]} ${start}% ${offset}%`;
  });
  donut.style.background = `conic-gradient(${stops.join(", ")})`;
  donut.innerHTML = `<span>${fmt.format(total)}<small>classified hits</small></span>`;

  data.categories.forEach(([name, count], index) => {
    const pct = Math.round((count / total) * 100);
    const row = el("div", "category");
    row.innerHTML = `<i style="background:${colors[index % colors.length]}"></i><strong>${name}</strong><span>${pct}%</span><em>${fmt.format(count)}</em>`;
    list.appendChild(row);
  });
}

function renderEras() {
  const list = document.querySelector("#eraList");
  data.eras.forEach(([label, range, evidence]) => {
    const item = el("div", "era");
    item.innerHTML = `<strong>${label}</strong><span>${range}</span><p>${evidence}</p>`;
    list.appendChild(item);
  });
}

function renderSnippets() {
  const grid = document.querySelector("#snippetGrid");
  data.snippets.forEach((snippet) => {
    const card = el("div", "snippet");
    card.innerHTML = `<strong>${snippet.sender} · ${snippet.date}</strong><p>${snippet.text}</p>`;
    grid.appendChild(card);
  });
}

renderStats();
renderMessageChart();
renderHeatmap();
renderTerms();
renderEmojis();
renderOrigins();
renderCategories();
renderEras();
renderSnippets();
