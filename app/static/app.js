const $ = (id) => document.getElementById(id);
const STATUS = {
  queued: "En attente",
  writing: "Scénario",
  visuals: "Visuels",
  editing: "Montage",
  done: "Terminé",
  error: "Échec",
};

let currentId = null;
let pollTimer = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

async function loadConfig() {
  const config = await api("/api/config");
  const warnings = [];
  if (!config.anthropic_key) {
    warnings.push("ANTHROPIC_API_KEY n'est pas défini : Claude ne pourra pas écrire le scénario.");
  }
  if (!config.replicate) {
    for (const input of document.querySelectorAll('input[name="visual_mode"]')) {
      if (input.value !== "local") input.disabled = true;
    }
    warnings.push("Ajoutez REPLICATE_API_TOKEN dans .env pour débloquer les images et vidéos IA.");
  }
  if (warnings.length) {
    $("setup-warning").textContent = warnings.join(" ");
    $("setup-warning").hidden = false;
  }
}

function renderJob(job) {
  const title = job.screenplay?.title;
  $("job").hidden = false;
  $("job-title").textContent = title || "Fabrication en cours";
  $("job-status").textContent = STATUS[job.status] || job.status;
  $("job-status").className = `pill ${job.status}`;
  $("progress-bar").style.width = `${job.progress}%`;
  $("progress-bar").parentElement.setAttribute("aria-valuenow", Math.round(job.progress));
  $("job-message").textContent = job.message;

  $("job-error").hidden = !job.error;
  $("job-error").textContent = job.error || "";

  const warnings = $("job-warnings");
  warnings.replaceChildren(...job.warnings.map((w) => el("li", {}, w)));
  warnings.hidden = job.warnings.length === 0;

  if (job.screenplay) {
    $("script").hidden = false;
    $("logline").textContent = job.screenplay.logline;
    $("scenes").replaceChildren(
      ...job.screenplay.scenes.map((scene) => {
        const swatch = el("span", { class: "swatch", "aria-hidden": "true" });
        for (const color of scene.colors) {
          const chip = el("i");
          chip.style.background = color;
          swatch.append(chip);
        }
        return el(
          "li",
          {},
          el("div", { class: "heading" }, swatch, scene.heading),
          el("p", {}, scene.narration),
        );
      }),
    );
  } else {
    $("script").hidden = true;
  }

  const player = $("player");
  if (job.status === "done") {
    const src = `${job.video_url}?v=${job.finished_at}`;
    if ($("video").getAttribute("src") !== src) $("video").src = src;
    $("download").href = job.video_url;
    $("download-srt").hidden = !job.subtitles_url;
    if (job.subtitles_url) $("download-srt").href = job.subtitles_url;
    player.hidden = false;
  } else {
    player.hidden = true;
    $("video").removeAttribute("src");
  }
}

async function poll() {
  clearTimeout(pollTimer);
  if (!currentId) return;
  try {
    const job = await api(`/api/films/${currentId}`);
    renderJob(job);
    if (job.status === "done" || job.status === "error") {
      $("submit").disabled = false;
      loadHistory();
      return;
    }
  } catch (err) {
    $("job-message").textContent = `Connexion perdue : ${err.message}`;
  }
  pollTimer = setTimeout(poll, 1500);
}

function openJob(id) {
  currentId = id;
  poll();
  $("job").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadHistory() {
  const films = await api("/api/films");
  $("history-empty").hidden = films.length > 0;
  $("history").replaceChildren(
    ...films.map((film) => {
      const date = new Date(film.created_at * 1000).toLocaleString("fr-FR", {
        dateStyle: "short",
        timeStyle: "short",
      });
      const remove = el(
        "button",
        {
          class: "delete",
          type: "button",
          onclick: async (event) => {
            event.stopPropagation();
            if (!confirm("Supprimer ce film ?")) return;
            try {
              await api(`/api/films/${film.id}`, { method: "DELETE" });
              if (currentId === film.id) {
                currentId = null;
                $("job").hidden = true;
              }
              loadHistory();
            } catch (err) {
              alert(err.message);
            }
          },
        },
        "Supprimer",
      );
      const finished = film.status === "done" || film.status === "error";
      return el(
        "li",
        { onclick: () => openJob(film.id), tabindex: "0", onkeydown: (e) => e.key === "Enter" && openJob(film.id) },
        el("span", { class: "title" }, film.screenplay?.title || film.request.idea.slice(0, 60)),
        el("span", { class: "meta" }, el("span", {}, `${STATUS[film.status] || film.status} · ${date}`), finished ? remove : ""),
      );
    }),
  );
}

$("num_scenes").addEventListener("input", (e) => {
  $("scenes-out").textContent = e.target.value;
});

$("film-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const body = {
    idea: form.get("idea"),
    style: form.get("style"),
    language: form.get("language"),
    num_scenes: Number(form.get("num_scenes")),
    aspect: form.get("aspect"),
    visual_mode: form.get("visual_mode"),
    subtitles: $("subtitles").checked,
  };
  $("submit").disabled = true;
  try {
    const job = await api("/api/films", { method: "POST", body: JSON.stringify(body) });
    loadHistory();
    openJob(job.id);
  } catch (err) {
    $("submit").disabled = false;
    alert(`Impossible de lancer le film : ${err.message}`);
  }
});

loadConfig();
loadHistory();
