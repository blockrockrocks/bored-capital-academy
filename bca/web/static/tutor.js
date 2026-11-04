(() => {
  const chat = document.getElementById("chat");
  const form = document.getElementById("ask");
  const q = document.getElementById("q");
  const send = document.getElementById("send");

  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // Minimal, safe formatting: escape everything, then allow **bold**, `code`, bullet lists and paragraphs.
  function fmt(text) {
    const blocks = esc(text).split(/\n{2,}/);
    return blocks.map((b) => {
      const lines = b.split("\n");
      const inline = (l) => l.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
      if (lines.every((l) => /^\s*([-*•]|\d+\.)\s+/.test(l))) {
        return "<ul>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*([-*•]|\d+\.)\s+/, "")) + "</li>").join("") + "</ul>";
      }
      return "<p>" + lines.map(inline).join("<br>") + "</p>";
    }).join("");
  }
  function add(cls, html) {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    d.innerHTML = html;
    chat.appendChild(d);
    d.scrollIntoView({ behavior: "smooth", block: "end" });
    return d;
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = q.value.trim();
    if (!text) return;
    add("user", fmt(text));
    q.value = "";
    send.disabled = true;
    const wait = add("tutor thinking", "<p>Thinking…</p>");
    try {
      const r = await fetch("/api/tutor", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text }) });
      const data = await r.json();
      wait.remove();
      if (!r.ok) add("error", esc(data.error || "Something went wrong."));
      else add("tutor", fmt(data.reply));
    } catch {
      wait.remove();
      add("error", "Network error. Please try again.");
    } finally {
      send.disabled = false;
      q.focus();
    }
  });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  document.getElementById("reset").addEventListener("click", async () => {
    await fetch("/api/tutor/reset", { method: "POST" });
    chat.querySelectorAll(".msg:not(:first-child)").forEach((m) => m.remove());
  });
})();
