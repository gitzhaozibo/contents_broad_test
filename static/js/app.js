// 社内ポータル フロントエンド（フレームワーク不使用・ES モジュール）

// ---------------------------------------------------------------------------
// 定数・状態
// ---------------------------------------------------------------------------
const BASE = "/app01";
const FOLDERS = ["manuals/", "videos/", "release_notes/", "announcements/"];
const PAGE_SIZE = 50;
const DELETE_UNDO_MS = 5000;
const NOTE_CATEGORIES = {
  release: "リリース",
  update: "アップデート",
  news: "ニュース",
};

let currentPrefix = "manuals/";
let allFiles = [];
let sortKey = "last_modified";
let sortDir = -1;
let currentPage = 1;
let allNotes = [];
let currentCategory = "release";
const pendingDeletes = new Map();

// ---------------------------------------------------------------------------
// DOM 要素（モジュール読み込みは DOM 構築後なので取得済みで固定できる）
// ---------------------------------------------------------------------------
const userLabel = document.getElementById("user");
const adminTabBtn = document.getElementById("adminTabBtn");
const foldersBox = document.getElementById("folders");
const announceNotice = document.getElementById("announceNotice");
const searchInput = document.getElementById("search");
const fileCountLabel = document.getElementById("fileCount");
const fileBody = document.getElementById("fileBody");
const emptyState = document.getElementById("emptyState");
const pager = document.getElementById("pager");
const pageInfo = document.getElementById("pageInfo");
const prevPageBtn = document.getElementById("prevPage");
const nextPageBtn = document.getElementById("nextPage");
const releaseNotesBox = document.getElementById("releaseNotes");
const uploadsBox = document.getElementById("uploads");
const toastsBox = document.getElementById("toasts");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const filePickBtn = document.getElementById("filePick");
const selDeleteBtn = document.getElementById("selDelete");

// ---------------------------------------------------------------------------
// 汎用ヘルパー
// ---------------------------------------------------------------------------
function api(path, opts) {
  return fetch(`${BASE}/api${path}`, opts);
}

function fmtSize(bytes) {
  if (bytes == null || bytes === "") return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = bytes;
  for (let i = 0; i < units.length; i++) {
    v /= 1024;
    if (v < 1024 || i === units.length - 1)
      return `${v.toFixed(1)} ${units[i]}`;
  }
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function baseName(name) {
  return name.startsWith(currentPrefix)
    ? name.slice(currentPrefix.length)
    : name;
}

function contentUrl(name) {
  return `${BASE}/content/${name.split("/").map(encodeURIComponent).join("/")}`;
}

function toast(msg, type = "info", actionLabel, onAction, duration = 4000) {
  const box = document.createElement("div");
  box.className = `toast ${type}`;
  const span = document.createElement("span");
  span.textContent = msg;
  box.appendChild(span);
  if (actionLabel) {
    const btn = document.createElement("button");
    btn.textContent = actionLabel;
    btn.addEventListener("click", () => {
      onAction();
      box.remove();
    });
    box.appendChild(btn);
  }
  toastsBox.appendChild(box);
  setTimeout(() => box.remove(), duration);
}

// ---------------------------------------------------------------------------
// タブ切り替え
// ---------------------------------------------------------------------------
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => {
    document
      .querySelectorAll("nav button")
      .forEach((x) => x.classList.remove("active"));
    document
      .querySelectorAll(".tab")
      .forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    document.getElementById(b.dataset.tab).classList.add("active");
    if (b.dataset.tab === "admin") loadFiles();
    if (b.dataset.tab === "announce") loadReleaseNotes();
  }),
);

// ---------------------------------------------------------------------------
// お知らせタブ
// ---------------------------------------------------------------------------
document.querySelectorAll("#noteTabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document
      .querySelectorAll("#noteTabs button")
      .forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    currentCategory = b.dataset.cat;
    renderNotes();
  }),
);

function noteTitle(note) {
  return note.name
    .split("/")
    .pop()
    .replace(/\.txt$/i, "")
    .replace(/^(update_|news_)/i, "");
}

function noteBadge(category) {
  const badge = document.createElement("span");
  badge.className = "note-badge";
  badge.textContent = NOTE_CATEGORIES[category];
  return badge;
}

function renderReleaseNote(note) {
  const article = document.createElement("article");
  article.className = "release-note";
  const title = document.createElement("h3");
  title.textContent = noteTitle(note);
  const time = document.createElement("time");
  time.dateTime = note.last_modified || "";
  time.textContent = fmtDate(note.last_modified);
  const content = document.createElement("pre");
  content.textContent = note.content;
  article.append(noteBadge("release"), title, time, content);
  return article;
}

function renderUpdateNote(note) {
  const article = document.createElement("article");
  article.className = "update-note";
  const head = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = noteTitle(note);
  const time = document.createElement("time");
  time.dateTime = note.last_modified || "";
  time.textContent = fmtDate(note.last_modified);
  head.append(noteBadge("update"), document.createTextNode(" "), title, time);
  const content = document.createElement("p");
  content.textContent = note.content;
  article.append(head, content);
  return article;
}

function renderNewsNote(note) {
  const article = document.createElement("article");
  article.className = "news-note";
  const time = document.createElement("time");
  time.dateTime = note.last_modified || "";
  time.textContent = fmtDate(note.last_modified);
  const title = document.createElement("h3");
  const lines = (note.content || "").split("\n");
  title.textContent = lines[0] || noteTitle(note);
  const content = document.createElement("p");
  content.textContent = lines.slice(1).join("\n").trim();
  article.append(noteBadge("news"), time, title, content);
  return article;
}

const NOTE_RENDERERS = {
  release: renderReleaseNote,
  update: renderUpdateNote,
  news: renderNewsNote,
};

function renderNotes() {
  releaseNotesBox.replaceChildren();
  const notes = allNotes.filter(
    (n) => (n.category || "release") === currentCategory,
  );
  if (!notes.length) {
    releaseNotesBox.textContent = `現在、${NOTE_CATEGORIES[currentCategory]}のお知らせはありません。`;
    return;
  }
  notes.forEach((note) =>
    releaseNotesBox.appendChild(NOTE_RENDERERS[currentCategory](note)),
  );
}

async function loadReleaseNotes() {
  releaseNotesBox.textContent = "読み込み中...";
  try {
    const r = await api("/release-notes");
    if (!r.ok) throw new Error(`release-notes: ${r.status}`);
    allNotes = (await r.json()).release_notes || [];
    renderNotes();
  } catch {
    releaseNotesBox.textContent = "お知らせを読み込めませんでした。";
  }
}

// ---------------------------------------------------------------------------
// 管理タブ: ファイル一覧
// ---------------------------------------------------------------------------
async function loadFiles() {
  announceNotice.style.display =
    currentPrefix === "announcements/" ? "block" : "none";
  try {
    const r = await api(
      `/admin/files?prefix=${encodeURIComponent(currentPrefix)}`,
    );
    if (!r.ok) return;
    allFiles = (await r.json()).files || [];
  } catch {
    toast("ファイル一覧を取得できませんでした", "error");
    return;
  }
  currentPage = 1;
  render();
}

function render() {
  const q = searchInput.value.toLowerCase();
  const files = allFiles
    .filter((f) => !pendingDeletes.has(f.name))
    .filter((f) => f.name.toLowerCase().includes(q))
    .sort((a, b) => {
      let va = a[sortKey];
      let vb = b[sortKey];
      if (sortKey === "name") {
        va = (va || "").toLowerCase();
        vb = (vb || "").toLowerCase();
      }
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
    });

  const pages = Math.max(1, Math.ceil(files.length / PAGE_SIZE));
  if (currentPage > pages) currentPage = pages;
  const pageFiles = files.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  );

  fileBody.replaceChildren();
  pageFiles.forEach((f) => {
    const tr = document.createElement("tr");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = f.name;
    const tdCb = document.createElement("td");
    tdCb.appendChild(cb);
    const tdName = document.createElement("td");
    const link = document.createElement("a");
    link.href = contentUrl(f.name);
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = baseName(f.name);
    link.title = f.name;
    tdName.appendChild(link);
    const tdSize = document.createElement("td");
    tdSize.textContent = fmtSize(f.size);
    const tdMod = document.createElement("td");
    tdMod.textContent = fmtDate(f.last_modified);
    const btn = document.createElement("button");
    btn.className = "act danger";
    btn.textContent = "削除";
    btn.addEventListener("click", () => scheduleDelete([f.name]));
    const tdAct = document.createElement("td");
    tdAct.appendChild(btn);
    tr.append(tdCb, tdName, tdSize, tdMod, tdAct);
    fileBody.appendChild(tr);
  });

  emptyState.style.display = files.length ? "none" : "block";
  fileCountLabel.textContent = files.length ? `${files.length} 件` : "";

  pager.style.display = pages > 1 ? "flex" : "none";
  pageInfo.textContent = `${currentPage} / ${pages}`;
  prevPageBtn.disabled = currentPage <= 1;
  nextPageBtn.disabled = currentPage >= pages;

  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.querySelector(".arrow").textContent =
      th.dataset.sort === sortKey ? (sortDir === 1 ? "▲" : "▼") : "";
  });
}

searchInput.addEventListener("input", () => {
  currentPage = 1;
  render();
});

document.querySelectorAll("th[data-sort]").forEach((th) =>
  th.addEventListener("click", () => {
    if (sortKey === th.dataset.sort) {
      sortDir = -sortDir;
    } else {
      sortKey = th.dataset.sort;
      sortDir = th.dataset.sort === "name" ? 1 : -1;
    }
    render();
  }),
);

prevPageBtn.addEventListener("click", () => {
  currentPage--;
  render();
});
nextPageBtn.addEventListener("click", () => {
  currentPage++;
  render();
});

// ---------------------------------------------------------------------------
// 管理タブ: 削除（5 秒間の「元に戻す」猶予付き）
// ---------------------------------------------------------------------------
function scheduleDelete(names) {
  if (!names.length) return;
  names.forEach((n) => {
    const timer = setTimeout(async () => {
      pendingDeletes.delete(n);
      try {
        const r = await api("/admin/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: n }),
        });
        if (!r.ok) throw new Error(`delete: ${r.status}`);
      } catch {
        toast(`削除に失敗しました: ${baseName(n)}`, "error");
        loadFiles();
      }
    }, DELETE_UNDO_MS);
    pendingDeletes.set(n, timer);
  });
  render();
  toast(
    `${names.length} 件を削除しました`,
    "success",
    "元に戻す",
    () => {
      names.forEach((n) => {
        clearTimeout(pendingDeletes.get(n));
        pendingDeletes.delete(n);
      });
      render();
    },
    DELETE_UNDO_MS,
  );
}

selDeleteBtn.addEventListener("click", () => {
  const names = [...fileBody.querySelectorAll("input:checked")].map(
    (c) => c.value,
  );
  scheduleDelete(names);
});

// ---------------------------------------------------------------------------
// 管理タブ: アップロード
// ---------------------------------------------------------------------------
function createProgress(name) {
  const wrap = document.createElement("div");
  wrap.className = "progress";
  const label = document.createElement("span");
  label.textContent = name;
  const track = document.createElement("div");
  track.className = "track";
  const fill = document.createElement("div");
  fill.className = "fill";
  track.appendChild(fill);
  wrap.append(label, track);
  uploadsBox.appendChild(wrap);
  return {
    set: (r) => {
      fill.style.width = `${Math.round(r * 100)}%`;
    },
    remove: () => wrap.remove(),
  };
}

// fetch には送信進捗イベントがないため、進捗バー表示に XMLHttpRequest を使う。
function uploadOne(name, file) {
  const bar = createProgress(name);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", `${BASE}/api/admin/upload?name=${encodeURIComponent(name)}`);
  xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
  xhr.upload.addEventListener("progress", (e) => {
    if (e.lengthComputable) bar.set(e.loaded / e.total);
  });
  xhr.addEventListener("load", () => {
    bar.remove();
    if (xhr.status >= 200 && xhr.status < 300) {
      toast(`アップロード完了: ${file.name}`, "success");
      loadFiles();
    } else {
      toast(`アップロードに失敗しました: ${file.name}`, "error");
    }
  });
  xhr.addEventListener("error", () => {
    bar.remove();
    toast(`アップロードに失敗しました: ${file.name}`, "error");
  });
  xhr.send(file);
}

function uploadFiles(fileList) {
  const existing = new Set(allFiles.map((f) => f.name));
  for (const file of fileList) {
    const name = currentPrefix + file.name;
    if (
      existing.has(name) &&
      !confirm(`同名ファイルが存在します。上書きしますか: ${name}`)
    )
      continue;
    uploadOne(name, file);
  }
}

dropzone.addEventListener("dragover", (e) => e.preventDefault());
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadFiles(e.dataTransfer.files);
});
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});
filePickBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  uploadFiles(fileInput.files);
  fileInput.value = "";
});

// ---------------------------------------------------------------------------
// 初期化
// ---------------------------------------------------------------------------
async function init() {
  try {
    const r = await api("/me");
    const me = await r.json();
    userLabel.textContent = me.name ? `  ${me.name}` : "";
    if (me.is_admin) adminTabBtn.style.display = "";
  } catch {
    // /api/me が取れなくても閲覧系は使えるため、匿名表示のまま続行する
  }
  FOLDERS.forEach((f) => {
    const btn = document.createElement("button");
    btn.textContent = f;
    if (f === currentPrefix) btn.classList.add("active");
    btn.addEventListener("click", () => {
      currentPrefix = f;
      document
        .querySelectorAll(".folders button")
        .forEach((x) => x.classList.remove("active"));
      btn.classList.add("active");
      loadFiles();
    });
    foldersBox.appendChild(btn);
  });
}

init();
