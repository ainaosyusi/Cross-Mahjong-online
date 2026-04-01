const API_BASE = "https://mj-api.kyoten-hub.com";

// ========== Navigation ==========
document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    const page = link.dataset.page;
    showPage(page);
    // モバイルメニュー閉じる
    document.querySelector(".nav-mobile").classList.remove("open");
  });
});

document.querySelector(".hamburger").addEventListener("click", () => {
  document.querySelector(".nav-mobile").classList.toggle("open");
});

function showPage(page) {
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  document.getElementById(`page-${page}`).classList.add("active");
  document.querySelectorAll(".nav-link").forEach((l) => {
    l.classList.toggle("active", l.dataset.page === page);
  });
  window.scrollTo(0, 0);
}

// ========== Ranking ==========
let currentPeriod = "all";

document.querySelectorAll(".period-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".period-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    currentPeriod = tab.dataset.period;
    loadRanking();
  });
});

async function loadRanking() {
  const el = document.getElementById("ranking-content");
  el.innerHTML = '<div class="loading-state">読み込み中...</div>';

  try {
    const res = await fetch(`${API_BASE}/api/ranking`);
    const data = await res.json();

    if (!data.length) {
      el.innerHTML = '<div class="no-data">まだデータがありません</div>';
      return;
    }

    const medals = ["🥇", "🥈", "🥉"];
    let html =
      '<table class="ranking-table"><tr><th>#</th><th>プレイヤー</th><th>対戦数</th><th>平均順位</th><th>トップ率</th><th>連対率</th></tr>';

    data.forEach((r, i) => {
      const cls = i < 3 ? ` class="rank-${i + 1}"` : "";
      const rank = medals[i] || i + 1;
      html += `<tr>
        <td${cls}>${rank}</td>
        <td>${r.display_name}</td>
        <td>${r.game_count}</td>
        <td>${r.avg_rank}</td>
        <td>${r.top_rate}%</td>
        <td>${r.rentai_rate}%</td>
      </tr>`;
    });

    html += "</table>";
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="no-data">データの取得に失敗しました</div>';
  }
}

// ========== History ==========
async function loadHistory() {
  const el = document.getElementById("history-content");
  el.innerHTML = '<div class="loading-state">読み込み中...</div>';

  try {
    const res = await fetch(`${API_BASE}/api/recent`);
    const data = await res.json();

    if (!data.length) {
      el.innerHTML = '<div class="no-data">まだデータがありません</div>';
      return;
    }

    let html = "";
    data.forEach((m) => {
      const date = m.finished_at
        ? new Date(m.finished_at).toLocaleString("ja-JP", {
            month: "numeric",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })
        : "";

      html += `<div class="match-card">
        <div class="match-header">
          <span class="match-date">${date}</span>
          <span class="match-type-badge">${m.match_type}人戦</span>
        </div>
        <div class="match-players">`;

      m.players.forEach((p) => {
        const cls = p.rank <= 3 ? ` rank-${p.rank}` : "";
        html += `<span class="match-player${cls}">${p.rank}位: ${p.name}</span>`;
      });

      html += "</div></div>";
    });

    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="no-data">データの取得に失敗しました</div>';
  }
}

// ========== Init ==========
loadRanking();
loadHistory();
