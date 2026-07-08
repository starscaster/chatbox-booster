// Chatbox Booster Management UI
(function() {
  "use strict";

  const token = new URLSearchParams(location.search).get("token") || "";
  const headers = { "Authorization": "Bearer " + token, "Content-Type": "application/json" };

  async function api(path, method, body) {
    const opts = { method: method || "GET", headers };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch("/api/" + path, opts);
    if (!res.ok) throw new Error("API error: " + res.status);
    return res.json();
  }

  // Tab switching
  document.querySelectorAll(".nav-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll(".nav-btn").forEach(function(b) { b.classList.remove("active"); });
      document.querySelectorAll(".tab-content").forEach(function(t) { t.classList.remove("active"); });
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
  });

  // Plugins tab
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

        let statusBadge;
        if (p.load_error) {
          statusBadge = '<span class="badge badge-err">Error</span>';
        } else if (!p.deps_met) {
          statusBadge = '<span class="badge badge-warn">Missing deps</span>';
        } else if (p.loaded) {
          statusBadge = '<span class="badge badge-ok">Loaded</span>';
        } else if (p.enabled) {
          statusBadge = '<span class="badge badge-warn">Not loaded</span>';
        } else {
          statusBadge = '<span class="badge badge-dim">Disabled</span>';
        }

        let toolBadge = "";
        if (p.tool_count > 0) {
          toolBadge = '<span class="badge badge-dim">' + p.tool_count + " tool" + (p.tool_count > 1 ? "s" : "") + "</span>";
        }

        let sourceBadge = '<span class="badge badge-dim">' + p.source + "</span>";

        meta.innerHTML = statusBadge + toolBadge + sourceBadge;
        if (p.load_error) {
          meta.innerHTML += '<div style="color:var(--red);margin-top:4px">' + p.load_error + "</div>";
        }
        if (p.missing_required && p.missing_required.length > 0) {
          meta.innerHTML += '<div style="color:var(--yellow);margin-top:4px">Missing: ' + p.missing_required.join(", ") + "</div>";
          const installBtn = document.createElement("button");
          installBtn.className = "btn-install";
          installBtn.textContent = "Install Dependencies";
          installBtn.addEventListener("click", async function(e) {
            e.stopPropagation();
            installBtn.disabled = true;
            installBtn.textContent = "Installing...";
            try {
              const result = await api("plugins/" + p.name + "/install-deps", "POST", {});
              if (result.ok) {
                installBtn.textContent = "Installed!";
                setTimeout(function() { loadPlugins(); }, 1000);
              } else {
                installBtn.textContent = "Failed";
                installBtn.disabled = false;
                alert("Install failed: " + (result.error || "unknown error"));
              }
            } catch (err) {
              installBtn.textContent = "Error";
              installBtn.disabled = false;
              alert("Install error: " + err.message);
            }
          });
          meta.appendChild(installBtn);
        }
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
      document.getElementById("plugin-list").innerHTML = '<div style="color:var(--red)">Failed to load: ' + e.message + "</div>";
    }
  }

  // Config tab
  let configData = {};
  async function loadConfig() {
    try {
      configData = await api("config");
      renderConfig(configData);
    } catch (e) {
      document.getElementById("config-editor").innerHTML = '<div style="color:var(--red)">Failed to load config</div>';
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
          input.value = val === null ? "" : (Array.isArray(val) ? val.join(", ") : String(val));
          input.dataset.key = fullKey;
          input.dataset.isArray = Array.isArray(val);
          input.dataset.isBool = typeof val === "boolean";
          input.dataset.isNumber = typeof val === "number";
          row.appendChild(label);
          row.appendChild(input);
          section.appendChild(row);
        }
      });
      return section;
    }

    Object.keys(data).forEach(function(key) {
     if (key === "plugins") return; // handled by plugins tab
     if (key === "runtime") return; // handled by Python Environment tab
      if (key === "quality") return; // regex arrays not safe for comma-join editing
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
    injectApiTestButtons(container);
  }

  function injectApiTestButtons(container) {
    var sections = container.querySelectorAll(".config-section");
    sections.forEach(function(section) {
      var h3 = section.querySelector("h3");
      if (!h3) return;
      var type = h3.textContent.trim().toLowerCase();
      if (type !== "rerank" && type !== "ai_eval" && type !== "serper") return;

      var btn = document.createElement("button");
      btn.className = "btn-secondary";
      btn.textContent = "Test";
      btn.style.marginTop = "8px";

      var resultEl = document.createElement("pre");
      resultEl.style.display = "none";
      resultEl.className = "test-result";

      section.appendChild(btn);
      section.appendChild(resultEl);

      btn.addEventListener("click", async function() {
        var inputs = section.querySelectorAll("input[data-key]");
        var keyPrefix = "api." + type + ".";
        var config = {};
        inputs.forEach(function(input) {
          var key = input.dataset.key;
          if (key && key.startsWith(keyPrefix)) {
            config[key.substring(keyPrefix.length)] = input.value;
          }
        });

        btn.disabled = true;
        btn.textContent = "Testing...";
        resultEl.style.display = "block";
        resultEl.className = "test-result";
        resultEl.innerHTML = '<div class="test-spinner">Testing...</div>';

        try {
          var result = await api("test-api", "POST", { type: type, config: config });
          if (result.ok) {
            var html = '<span class="test-icon-ok">&#10003;</span> ' + (result.message || "Connected");
            if (result.detail) {
              html += '<br><span style="font-size:11px;opacity:0.7">' + result.detail + '</span>';
            }
            resultEl.innerHTML = html;
            resultEl.className = "test-result test-result-ok";
          } else {
            var html = '<span class="test-icon-fail">&#10007;</span> ' + (result.message || "Test failed");
            if (result.detail) {
              html += '<br><span style="font-size:11px;opacity:0.7">' + result.detail + '</span>';
            }
            resultEl.innerHTML = html;
            resultEl.className = "test-result test-result-err";
          }
        } catch (e) {
          resultEl.innerHTML = '<span class="test-icon-fail">&#10007;</span> Request failed: ' + e.message;
          resultEl.className = "test-result test-result-err";
        }

        btn.disabled = false;
        btn.textContent = "Test";
      });
    });
  }

  document.getElementById("save-config").addEventListener("click", async function() {
    const inputs = document.querySelectorAll("#config-editor input");
    const changes = {};
    inputs.forEach(function(input) {
      const key = input.dataset.key;
      let val = input.value;
      if (input.dataset.isArray === "true") {
        val = val.split(",").map(function(s) { return s.trim(); }).filter(Boolean);
      } else if (input.dataset.isBool === "true") {
        val = val === "true" || val === "True";
      } else if (input.dataset.isNumber === "true") {
        val = parseFloat(val);
      }
      changes[key] = val;
    });
    try {
      await api("config", "POST", changes);
      alert("Config saved!");
    } catch (e) {
      alert("Save failed: " + e.message);
    }
  });

  // Logs tab
  async function loadLogs() {
    try {
      const data = await api("logs");
      document.getElementById("log-view").textContent = data.logs.join("\n");
    } catch (e) {
      document.getElementById("log-view").textContent = "Failed to load logs";
    }
  }

  // MCP tab
  async function loadMcpConfig() {
    try {
      let url = "mcp-config";
      // previewPath is passed when called from Apply (not saved yet)
      if (arguments.length > 0 && arguments[0]) {
        url += "?preview=" + encodeURIComponent(arguments[0]);
      }
      const config = await api(url);
      document.getElementById("mcp-config").textContent = JSON.stringify(config, null, 2);
    } catch (e) {
      document.getElementById("mcp-config").textContent = "Failed to load";
    }
  }

  // Python Environment tab
  async function loadPythonEnv() {
    try {
      const env = await api("python-env");
      const detections = env.detections || [];
      const select = document.getElementById("python-path-select");
      const customInput = document.getElementById("python-path-custom");
      const currentBar = document.getElementById("python-env-current");
      const currentPathEl = document.getElementById("py-current-path");
      const configuredPathEl = document.getElementById("py-configured-path");

      // Show info bar with both paths
      currentBar.textContent = "Current: " + env.current;
      if (currentPathEl) currentPathEl.textContent = env.current;
      if (configuredPathEl) configuredPathEl.textContent = env.configured || "(same as current)";

      // Populate preset dropdown
      select.innerHTML = "";
      detections.forEach(function(d) {
        var opt = document.createElement("option");
        opt.value = d.path;
        opt.textContent = d.label + "  (" + d.path + ")";
        select.appendChild(opt);
      });

      // Fill custom input with configured value or current
      customInput.value = env.configured || env.current;

      // Mark which preset matches
      var activePath = env.configured || env.current;
      for (var i = 0; i < select.options.length; i++) {
        if (select.options[i].value === activePath) {
          select.selectedIndex = i;
          break;
        }
      }
    } catch (e) {
      document.getElementById("python-env-current").textContent = "Failed to detect Python environments";
    }
  }

  document.getElementById("python-apply-preset").addEventListener("click", function() {
    var select = document.getElementById("python-path-select");
    var path = select.value;
    document.getElementById("python-path-custom").value = path;
    showPythonStatus("Selected: " + select.value, "info");
    loadMcpConfig(path);
  });

  document.getElementById("python-save").addEventListener("click", async function() {
    var path = document.getElementById("python-path-custom").value.trim();
    if (!path) {
      showPythonStatus("Path cannot be empty", "error");
      return;
    }
    try {
      await api("config", "POST", { "runtime.python_path": path });
      showPythonStatus("Saved to config.json. Use this in your AI client.", "ok");
      loadMcpConfig();
      loadPythonEnv();
      loadConfig();
    } catch (e) {
      showPythonStatus("Save failed: " + e.message, "error");
    }
  });

  document.getElementById("python-reset").addEventListener("click", async function() {
    try {
      await api("config", "POST", { "runtime.python_path": "" });
      var env = await api("python-env");
      document.getElementById("python-path-custom").value = env.current;
     showPythonStatus("Reset. MCP server will use the current interpreter.", "ok");
     loadMcpConfig();
     loadPythonEnv();
     loadConfig();
   } catch (e) {
     showPythonStatus("Reset failed: " + e.message, "error");
    }
  });

  document.getElementById("python-test-btn").addEventListener("click", async function() {
    var path = document.getElementById("python-path-custom").value.trim();
    if (!path) {
      showPythonStatus("Enter a Python path first", "error");
      return;
    }
    var resultEl = document.getElementById("python-test-result");
    resultEl.style.display = "block";
    resultEl.className = "test-result";
    resultEl.innerHTML = '<div class="test-spinner">Testing...</div>';
    try {
      var result = await api("python-env/test", "POST", { "path": path });
      if (result.ok) {
        var html = '<div class="test-line test-ver"><span class="test-icon-ok">&#10003;</span> Version: ' + (result.version || "?") + '</div>';
        html += '<div class="test-line"><span class="test-icon-ok">&#10003;</span> Path: ' + result.python_exe + '</div>';
        var allOk = result.all_core_ok;
        var allReqOk = result.all_required_ok;
        var missingReq = result.missing_required || [];
        var hasWarn = result.has_warnings || false;
        var imports = result.core_imports || {};
        html += '<div class="test-section-title">Dependencies:</div>';
        var depList = [
          {n:"fastmcp",r:true,l:"Core: fastmcp"},
          {n:"aiohttp",r:true,l:"Core: aiohttp"},
          {n:"ddgs",r:true,l:"Search: ddgs"},
          {n:"requests",r:true,l:"Search: requests"},
          {n:"tiktoken",r:true,l:"Token: tiktoken"},
          {n:"curl_cffi",r:true,l:"Fetch: curl_cffi"},
          {n:"lxml",r:true,l:"Fetch: lxml"},
          {n:"pypdf",r:true,l:"PDF: pypdf"},
          {n:"patchright",r:false,l:"Browser: patchright"},
        ];
        depList.forEach(function(d) {
          var ok = imports[d.n] === true;
          var icon = ok ? "&#10003;" : "&#10007;";
          var cls = ok ? "test-icon-ok" : "test-icon-fail";
          html += '<div class="test-line"><span class="' + cls + '">' + icon + '</span> ' + d.l + (d.r ? "" : " (optional)") + '</div>';
        });
        if (allReqOk && !hasWarn) {
          html += '<div class="test-summary test-summary-ok">All dependencies satisfied.</div>';
        } else if (allReqOk && hasWarn) {
          html += '<div class="test-summary test-summary-ok">All required OK (optional: patchright missing).</div>';
        } else {
          html += '<div class="test-summary test-summary-fail">Missing: ' + missingReq.join(", ") + '</div>';
          html += '<button id="python-install-deps-btn" class="btn-primary" style="margin-top:8px">Install Dependencies into Target</button>';
        }
        resultEl.innerHTML = html;
        resultEl.className = "test-result " + (allReqOk ? "test-result-ok" : "test-result-warn");
      } else {
        resultEl.innerHTML = '<div class="test-line test-err"><span class="test-icon-fail">&#10007;</span> ' + (result.error || "Test failed") + '</div>';
        resultEl.className = "test-result test-result-err";
      }
    } catch (e) {
      resultEl.innerHTML = '<div class="test-line test-err"><span class="test-icon-fail">&#10007;</span> Request failed: ' + e.message + '</div>';
      resultEl.className = "test-result test-result-err";
    }
  });

  function showPythonStatus(msg, type) {
    var el = document.getElementById("python-env-status");
    el.textContent = msg;
    el.className = "status-msg " + (type || "info");
    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(function() { el.textContent = ""; el.className = "status-msg"; }, 8000);
  }

  document.getElementById("copy-mcp").addEventListener("click", function() {
    const text = document.getElementById("mcp-config").textContent;
    navigator.clipboard.writeText(text).then(function() {
      alert("Copied!");
    });
  });

  // Restart banner
  async function checkRestartBanner() {
    try {
      const status = await api("status");
      if (status.needs_restart) {
        const info = status.needs_restart;
        const banner = document.createElement("div");
        banner.className = "restart-banner";
        const msg = document.createElement("span");
        msg.textContent = "Plugin '" + (info.plugin || "?") + "' was " + (info.action || "changed") + ". Changes will take effect on next MCP server start.";
        banner.appendChild(msg);
        const closeBtn = document.createElement("button");
        closeBtn.className = "close-btn";
        closeBtn.textContent = "\u00d7";
        closeBtn.addEventListener("click", function() { banner.remove(); });
        banner.appendChild(closeBtn);
        const app = document.getElementById("app");
        app.insertBefore(banner, app.firstChild.nextSibling);
      }
      // Show Python executable info
      if (status.python_exe) {
        const pyInfo = document.createElement("div");
        pyInfo.style.cssText = "font-size:11px;color:var(--text-dim);margin-bottom:12px;padding:6px 10px;background:var(--surface);border-radius:6px";
        pyInfo.textContent = "Python: " + status.python_exe;
        const app = document.getElementById("app");
        app.insertBefore(pyInfo, app.firstChild.nextSibling.nextSibling);
      }
    } catch (e) { /* non-critical */ }
  }

  // Initial load
  checkRestartBanner();
  loadPlugins();
  loadConfig();
  loadPythonEnv();
  loadMcpConfig();

  // Auto-refresh logs when on logs tab
  setInterval(function() {
    if (document.querySelector(".nav-btn[data-tab=logs]").classList.contains("active")) {
      loadLogs();
    }
  }, 3000);
})();
