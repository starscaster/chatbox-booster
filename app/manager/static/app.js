(function() {
"use strict";

const token = new URLSearchParams(location.search).get("token") || "";
const baseHeaders = { "Authorization": "Bearer " + token, "Content-Type": "application/json" };
let chatConfig = null;
let messages = [];
let isStreaming = false;

// ===== API helper =====
async function api(path, method, body) {
  const opts = { method: method || "GET", headers: baseHeaders };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch("/api/" + path, opts);
  if (!res.ok) throw new Error("API error: " + res.status);
  return res.json();
}

// ===== Basic Markdown renderer =====
function renderMarkdown(text) {
  if (!text) return "";
  // Escape HTML first
  let html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // Code blocks
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, function(m, lang, code) {
    return '<pre><code>' + code.replace(/&amp;/g, "&") + '</code></pre>';
  });
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Bold and italic
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  // Lists
  html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
  html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, '<ul>$1</ul>');
  // Paragraphs and line breaks
  html = html.replace(/\n\n/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  return '<p>' + html + '</p>';
}

// ===== Chat =====
async function loadChatConfig() {
  try {
    chatConfig = await api("chat/config");
    document.getElementById("chat-api-url").value = chatConfig.api_url || "";
    document.getElementById("chat-api-key").value = chatConfig.api_key || "";
    document.getElementById("chat-model").value = chatConfig.model || "";
    document.getElementById("chat-sysprompt").value = chatConfig.system_prompt || "";
    document.getElementById("chat-temp").value = chatConfig.temperature ?? 0.6;
    document.getElementById("chat-maxtoks").value = chatConfig.max_tokens ?? 64000;
    // Show warning if no API key
    if (!chatConfig.has_api_key) {
      const msg = document.createElement("div");
      msg.className = "restart-banner";
      msg.innerHTML = '<span>API key not configured. Click the gear icon to set up chat.</span>';
      msg.querySelector("span").onclick = function() { toggleSettings(true); };
      document.getElementById("chat-messages").appendChild(msg);
    }
  } catch (e) { console.error("Config load failed:", e); }
}

async function sendMessage() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text || isStreaming) return;

  // Add user message to UI
  appendMessage("user", text);
  messages.push({ role: "user", content: text });

  input.value = "";
  input.style.height = "auto";
  isStreaming = true;
  document.getElementById("chat-send").disabled = true;

  // Create assistant message placeholder
  const msgDiv = document.createElement("div");
  msgDiv.className = "msg msg-assistant";
  const contentDiv = document.createElement("div");
  contentDiv.className = "msg-content";
  contentDiv.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
  msgDiv.appendChild(contentDiv);
  document.getElementById("chat-messages").appendChild(msgDiv);

  let accumulatedText = "";
  let toolBlocksContainer = null;

  try {
    const response = await fetch("/api/chat/message?token=" + encodeURIComponent(token), {
      method: "POST",
      headers: baseHeaders,
      body: JSON.stringify({ messages: messages }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            handleSSEEvent(data, contentDiv, msgDiv, (text) => {
              accumulatedText += text;
              contentDiv.innerHTML = renderMarkdown(accumulatedText);
              scrollChatToBottom();
            }, (toolData) => {
              if (!toolBlocksContainer) {
                toolBlocksContainer = document.createElement("div");
                msgDiv.insertBefore(toolBlocksContainer, contentDiv);
              }
              const block = createToolBlock(toolData);
              toolBlocksContainer.appendChild(block);
            }, (resultData) => {
              updateToolBlock(toolBlocksContainer, resultData);
            });
          } catch (e) { /* skip non-JSON */ }
        }
      }
    }

    // Save assistant response to history
    messages.push({ role: "assistant", content: accumulatedText });
    scrollChatToBottom();
  } catch (e) {
    contentDiv.innerHTML = '<span style="color: var(--red)">Error: ' + e.message + "</span>";
  } finally {
    isStreaming = false;
    document.getElementById("chat-send").disabled = false;
    input.focus();
  }
}

function handleSSEEvent(data, contentDiv, msgDiv, onContent, onToolCall, onToolResult) {
  switch (data.type) {
    case "content":
      onContent(data.text);
      break;
    case "tool_call":
      onToolCall(data);
      break;
    case "tool_result":
      onToolResult(data);
      break;
    case "error":
      contentDiv.innerHTML = '<span style="color: var(--red)">' + (data.error || "Unknown error") + "</span>";
      break;
  }
}

function createToolBlock(data) {
  const block = document.createElement("div");
  block.className = "tool-block";
  block.dataset.toolName = data.name;
  const header = document.createElement("div");
  header.className = "tool-header";
  header.innerHTML = '<span class="tool-icon"> "&#128295;"</span> <span class="tool-name">' + escapeHtml(data.name) + "</span>" +
    '<span class="tool-status">running...</span>';
  header.onclick = function() { block.classList.toggle("expanded"); };
  const body = document.createElement("div");
  body.className = "tool-body";
  body.textContent = "Arguments: " + JSON.stringify(data.arguments, null, 2);
  block.appendChild(header);
  block.appendChild(body);
  return block;
}

function updateToolBlock(container, data) {
  if (!container) return;
  const blocks = container.querySelectorAll(".tool-block");
  for (const block of blocks) {
    if (block.dataset.toolName === data.name && !block.dataset.resultSet) {
      block.dataset.resultSet = "1";
      block.querySelector(".tool-status").textContent = "done";
      const body = block.querySelector(".tool-body");
      body.textContent += "\n\nResult:\n" + (data.result || "");
      break;
    }
  }
}

function appendMessage(role, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = "msg msg-" + role;
  const contentDiv = document.createElement("div");
  contentDiv.className = "msg-content";
  if (role === "user") {
    contentDiv.textContent = text;
  } else {
    contentDiv.innerHTML = renderMarkdown(text);
  }
  msgDiv.appendChild(contentDiv);
  document.getElementById("chat-messages").appendChild(msgDiv);
  scrollChatToBottom();
}

function scrollChatToBottom() {
  const container = document.getElementById("chat-messages");
  container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ===== Input handling =====
const inputEl = document.getElementById("chat-input");
inputEl.addEventListener("input", function() {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 150) + "px";
});
inputEl.addEventListener("keydown", function(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
document.getElementById("chat-send").addEventListener("click", sendMessage);

// ===== Settings overlay =====
function toggleSettings(show) {
  const overlay = document.getElementById("settings-overlay");
  if (show) {
    overlay.classList.remove("hidden");
    loadPlugins();
    loadConfig();
    loadMcpConfig();
  } else {
    overlay.classList.add("hidden");
  }
}
document.getElementById("settings-btn").addEventListener("click", function() { toggleSettings(true); });
document.getElementById("settings-close").addEventListener("click", function() { toggleSettings(false); });
document.getElementById("settings-overlay").addEventListener("click", function(e) {
  if (e.target === this) toggleSettings(false);
});

// Settings tab switching
document.querySelectorAll(".settings-nav-btn").forEach(function(btn) {
  btn.addEventListener("click", function() {
    document.querySelectorAll(".settings-nav-btn").forEach(function(b) { b.classList.remove("active"); });
    document.querySelectorAll(".settings-tab").forEach(function(t) { t.classList.remove("active"); });
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// Save chat config
document.getElementById("save-chat-config").addEventListener("click", async function() {
  const changes = {};
  document.querySelectorAll("#tab-chat-config input, #tab-chat-config textarea").forEach(function(el) {
    const key = el.dataset.key;
    if (!key) return;
    let val = el.value;
    if (el.type === "number") val = parseFloat(val) || 0;
    changes[key] = val;
  });
  try {
    await api("config", "POST", changes);
    document.getElementById("chat-config-status").textContent = "Saved!";
    document.getElementById("chat-config-status").style.color = "var(--green)";
    setTimeout(function() {
      document.getElementById("chat-config-status").textContent = "";
    }, 2000);
    loadChatConfig();
  } catch (e) {
    document.getElementById("chat-config-status").textContent = "Save failed: " + e.message;
    document.getElementById("chat-config-status").style.color = "var(--red)";
  }
});

// ===== Plugins tab =====
async function loadPlugins() {
  try {
    const plugins = await api("plugins");
    const container = document.getElementById("plugin-list");
    container.innerHTML = "";
    plugins.forEach(function(p) {
      const card = document.createElement("div");
      card.className = "plugin-card";
      const info = document.createElement("div");
      info.className = "plugin-info";
      const name = document.createElement("div");
      name.className = "plugin-name";
      name.textContent = p.name + " v" + p.version;
      info.appendChild(name);
      const desc = document.createElement("div");
      desc.className = "plugin-desc";
      desc.textContent = p.description;
      info.appendChild(desc);
      const meta = document.createElement("div");
      meta.className = "plugin-meta";
      let badge;
      if (p.load_error) badge = '<span class="badge badge-err">Error</span>';
      else if (!p.deps_met) badge = '<span class="badge badge-warn">Missing deps</span>';
      else if (p.loaded) badge = '<span class="badge badge-ok">Loaded</span>';
      else if (p.enabled) badge = '<span class="badge badge-warn">Not loaded</span>';
      else badge = '<span class="badge badge-dim">Disabled</span>';
      let tc = "";
      if (p.tool_count > 0) tc = '<span class="badge badge-dim">' + p.tool_count + " tool" + (p.tool_count > 1 ? "s" : "") + "</span>";
      meta.innerHTML = badge + tc + '<span class="badge badge-dim">' + p.source + "</span>";
      if (p.load_error) meta.innerHTML += '<div style="color:var(--red);margin-top:4px">' + p.load_error + "</div>";
      info.appendChild(meta);
      card.appendChild(info);
      const toggle = document.createElement("div");
      toggle.className = "toggle" + (p.enabled ? " on" : "");
      toggle.addEventListener("click", async function() {
        try {
          await api("plugins/" + p.name + "/toggle", "POST", { enabled: !p.enabled });
          toggle.classList.toggle("on");
          loadPlugins();
        } catch (e) { alert("Failed: " + e.message); }
      });
      card.appendChild(toggle);
      container.appendChild(card);
    });
  } catch (e) {
    document.getElementById("plugin-list").innerHTML = '<div style="color:var(--red)">Failed to load</div>';
  }
}

// ===== Config tab =====
let configData = {};
async function loadConfig() {
  try {
    configData = await api("config");
    renderConfig(configData);
  } catch (e) {
    document.getElementById("config-editor").innerHTML = '<span style="color:var(--red)">Failed to load</span>';
  }
}
function renderConfig(data) {
  const container = document.getElementById("config-editor");
  container.innerHTML = "";
  function createSection(title, obj, prefix) {
    const section = document.createElement("div");
    section.className = "config-section";
    const h3 = document.createElement("h3");
    h3.textContent = title;
    section.appendChild(h3);
    Object.keys(obj).forEach(function(key) {
      if (key === "plugins" || key === "chat") return;
      const val = obj[key];
      const fullKey = prefix ? prefix + "." + key : key;
      if (val !== null && typeof val === "object" && !Array.isArray(val)) {
        section.appendChild(createSection(key, val, fullKey));
      } else {
        const row = document.createElement("div");
        row.className = "config-row";
        const label = document.createElement("label");
        label.textContent = key;
        const input = document.createElement("input");
        input.value = val === null ? "" : Array.isArray(val) ? val.join(", ") : String(val);
        input.dataset.key = fullKey;
        input.dataset.isArray = Array.isArray(val);
        input.dataset.isBool = typeof val === "boolean";
        row.appendChild(label);
        row.appendChild(input);
        section.appendChild(row);
      }
    });
    return section;
  }
  Object.keys(data).forEach(function(key) {
    if (key === "plugins" || key === "chat") return;
    const val = data[key];
    if (val !== null && typeof val === "object" && !Array.isArray(val)) {
      container.appendChild(createSection(key, val, key));
    } else {
      const row = document.createElement("div");
      row.className = "config-row";
      const label = document.createElement("label");
      label.textContent = key;
      const input = document.createElement("input");
      input.value = val === null ? "" : String(val);
      input.dataset.key = key;
      row.appendChild(label);
      row.appendChild(input);
      container.appendChild(row);
    }
  });
}
document.getElementById("save-config").addEventListener("click", async function() {
  const inputs = document.querySelectorAll("#config-editor input");
  const changes = {};
  inputs.forEach(function(input) {
    const key = input.dataset.key;
    let val = input.value;
    if (input.dataset.isArray === "true") val = val.split(",").map(function(s) { return s.trim(); }).filter(Boolean);
    else if (input.dataset.isBool === "true") val = val === "true";
    changes[key] = val;
  });
  try { await api("config", "POST", changes); alert("Config saved!"); }
  catch (e) { alert("Save failed: " + e.message); }
});

// ===== Logs tab =====
async function loadLogs() {
  try {
    const data = await api("logs");
    document.getElementById("log-view").textContent = data.logs.join("\n");
  } catch (e) { document.getElementById("log-view").textContent = "Failed"; }
}
setInterval(function() {
  if (!document.getElementById("settings-overlay").classList.contains("hidden") &&
      document.querySelector(".settings-nav-btn[data-tab=logs]") &&
      document.querySelector(".settings-nav-btn[data-tab=logs]").classList.contains("active")) {
    loadLogs();
  }
}, 3000);

// ===== MCP tab =====
async function loadMcpConfig() {
  try {
    const config = await api("mcp-config");
    document.getElementById("mcp-config").textContent = JSON.stringify(config, null, 2);
  } catch (e) { document.getElementById("mcp-config").textContent = "Failed"; }
}
document.getElementById("copy-mcp").addEventListener("click", function() {
  navigator.clipboard.writeText(document.getElementById("mcp-config").textContent).then(function() {
    alert("Copied!");
  });
});

// ===== Restart banner =====
async function checkRestartBanner() {
  try {
    const status = await api("status");
    if (status.needs_restart) {
      const info = status.needs_restart;
      const banner = document.createElement("div");
      banner.className = "restart-banner";
      const msg = document.createElement("span");
      msg.textContent = "Plugin '" + (info.plugin || "?") + "' was " + (info.action || "changed") + ". Restart MCP server to apply.";
      banner.appendChild(msg);
      const closeBtn = document.createElement("button");
      closeBtn.className = "close-btn";
      closeBtn.textContent = "\u00d7";
      closeBtn.onclick = function() { banner.remove(); };
      banner.appendChild(closeBtn);
      const chatMsg = document.getElementById("chat-messages");
      chatMsg.insertBefore(banner, chatMsg.firstChild);
    }
  } catch (e) {}
}

// ===== Init =====
checkRestartBanner();
loadChatConfig();
})();
