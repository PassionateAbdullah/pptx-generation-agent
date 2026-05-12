const form = document.querySelector("#generateForm");
const promptInput = document.querySelector("#prompt");
const slideCountInput = document.querySelector("#slideCount");
const generateButton = document.querySelector("#generateButton");
const statusPill = document.querySelector("#statusPill");
const activityLog = document.querySelector("#activityLog");
const preview = document.querySelector("#preview");
const outlineText = document.querySelector("#outlineText");
const notesText = document.querySelector("#notesText");
const sourcesList = document.querySelector("#sourcesList");
const downloadButton = document.querySelector("#downloadButton");
const htmlButton = document.querySelector("#htmlButton");

function setStatus(value) {
  statusPill.textContent = value;
}

function setLinks(downloadUrl, htmlUrl) {
  downloadButton.href = downloadUrl || "#";
  htmlButton.href = htmlUrl || "#";
  for (const link of [downloadButton, htmlButton]) {
    const enabled = link.href && !link.href.endsWith("#");
    link.classList.toggle("disabled", !enabled);
    link.setAttribute("aria-disabled", enabled ? "false" : "true");
  }
}

function setLog(items) {
  activityLog.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    activityLog.appendChild(li);
  }
}

function setSources(sources) {
  sourcesList.innerHTML = "";
  if (!sources.length) {
    sourcesList.innerHTML = '<div class="empty-state"><h2>No sources</h2><p>No research sources were returned.</p></div>';
    return;
  }
  for (const source of sources) {
    const item = document.createElement("article");
    item.className = "source-item";
    const title = document.createElement(source.url && !source.url.startsWith("local://") ? "a" : "strong");
    title.textContent = source.title || "Source";
    if (title.tagName === "A") {
      title.href = source.url;
      title.target = "_blank";
      title.rel = "noreferrer";
    }
    const snippet = document.createElement("p");
    snippet.textContent = source.snippet || source.url || "";
    item.append(title, snippet);
    sourcesList.appendChild(item);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("Running");
  generateButton.disabled = true;
  setLinks("", "");
  setLog([
    "Prompt accepted.",
    "Starting research and slide planning."
  ]);

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: promptInput.value,
        slide_count: Number(slideCountInput.value)
      })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Generation failed.");
    }

    preview.innerHTML = data.preview_html;
    outlineText.textContent = data.structure;
    notesText.textContent = data.slide_content;
    setSources(data.sources || []);
    setLog(data.logs || []);
    setLinks(data.download_url, data.html_url);
    setStatus("Ready");
  } catch (error) {
    setStatus("Error");
    setLog(["Generation failed.", error.message]);
  } finally {
    generateButton.disabled = false;
  }
});

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    const target = tab.dataset.tab;
    for (const item of document.querySelectorAll(".tab")) {
      item.classList.toggle("active", item === tab);
    }
    for (const panel of document.querySelectorAll(".tab-panel")) {
      panel.classList.toggle("active", panel.id === target);
    }
  });
}

