(function () {
    const state = {
        config: null,
        editor: null,
        terminal: null,
        fitAddon: null,
        currentEnv: "python",
        storageKey: "quantumm:ide-state",
        isRunning: false,
    };

    function readConfig() {
        const node = document.getElementById("environment-config");
        if (!node) return {};
        try {
            return JSON.parse(node.textContent);
        } catch {
            return {};
        }
    }

    function savedState() {
        try {
            return JSON.parse(localStorage.getItem(state.storageKey) || "{}");
        } catch {
            return {};
        }
    }

    function persistState() {
        const payload = {
            env_key: state.currentEnv,
            code: getCurrentPayload(),
            notebook_path: savedState().notebook_path || "/files/dataset.csv",
            saved_at: new Date().toISOString(),
        };
        localStorage.setItem(state.storageKey, JSON.stringify(payload));
        const indicator = document.querySelector("[data-save-state]");
        if (indicator) indicator.textContent = "All changes saved";
    }

    function initTerminal() {
        const target = document.getElementById("qt-terminal");
        if (!target || !window.Terminal) return;
        state.terminal = new Terminal({
            cursorBlink: true,
            convertEol: true,
            theme: { background: "#020617", foreground: "#d7e2ee", cursor: "#00ff41" },
            fontFamily: "Roboto Mono, ui-monospace, monospace",
            fontSize: 13,
        });
        if (window.FitAddon) {
            state.fitAddon = new FitAddon.FitAddon();
            state.terminal.loadAddon(state.fitAddon);
        }
        state.terminal.open(target);
        fitTerminal();
        writeTerminal("Quantum Environment Gateway ready.");
        window.addEventListener("resize", fitTerminal);
    }

    function fitTerminal() {
        if (state.fitAddon) state.fitAddon.fit();
    }

    function writeTerminal(message) {
        if (!state.terminal) return;
        const text = typeof message === "string" ? message : JSON.stringify(message);
        const highlighted = text
            .replace(/Success/g, "\x1b[32mSuccess\x1b[0m")
            .replace(/Vulnerable/g, "\x1b[33mVulnerable\x1b[0m")
            .replace(/Error|error/g, "\x1b[31mError\x1b[0m");
        state.terminal.writeln(highlighted);
        fitTerminal();
    }

    function setLoading(active) {
        const loader = document.querySelector("[data-loading]");
        if (loader) loader.classList.toggle("active", Boolean(active));
    }

    async function loadEnvironment(envKey) {
        state.currentEnv = normalizeEnv(envKey);
        setLoading(true);
        const pane = document.querySelector("[data-ide-pane]");
        const label = document.querySelector("[data-env-label]");
        if (!pane) return;
        pane.innerHTML = '<div class="qt-loading active" data-loading>Loading environment...</div>';

        const configUrl = `/api/v1/environments/${state.currentEnv}/?lesson=${encodeURIComponent(state.config.lesson_id || "")}&block=${encodeURIComponent(state.config.block_id || "")}`;
        try {
            const response = await fetch(configUrl);
            if (response.ok) state.config = await response.json();
        } catch {
            writeTerminal("Error: environment config endpoint unavailable; using embedded defaults.");
        }

        if (label) label.textContent = state.config.label || state.currentEnv;

        if (state.currentEnv === "python") {
            renderPython(pane);
        } else if (state.currentEnv === "jupyter") {
            renderIframe(pane, state.config.iframe_url || "/static/jupyter/lab/index.html", "");
            preloadJupyterFiles();
        } else if (state.currentEnv === "wokwi") {
            renderIframe(pane, state.config.iframe_url || "https://wokwi.com/projects/new/arduino-uno?embed=1", "clipboard-write; serial");
        } else if (state.currentEnv === "cyber") {
            renderCyber(pane);
        }

        setLoading(false);
        persistState();
    }

    function normalizeEnv(envKey) {
        const aliases = {
            python_sandbox: "python",
            advanced_python_engine: "python",
            jupyter_notebook: "jupyter",
            circuit: "wokwi",
            circuit_simulator: "wokwi",
            wokwi: "wokwi",
            security_terminal: "cyber",
        };
        return aliases[envKey] || envKey || "python";
    }

    function renderPython(pane) {
        const saved = savedState();
        const code = saved.code || state.config.student_code || "print('Hello from Quantum TechHub')";
        pane.innerHTML = '<div class="qt-python-editor" data-python-editor><div id="monaco-editor" style="height:100%;width:100%;"></div></div>';
        if (window.require) {
            window.require.config({ paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.50.0/min/vs" } });
            window.require(["vs/editor/editor.main"], function () {
                state.editor = monaco.editor.create(document.getElementById("monaco-editor"), {
                    value: code,
                    language: "python",
                    theme: "vs-dark",
                    minimap: { enabled: false },
                    automaticLayout: true,
                    fontFamily: "Roboto Mono, monospace",
                    scrollBeyondLastLine: false,
                    padding: { top: 12, bottom: 12 },
                });
                state.editor.onDidChangeModelContent(() => {
                    resizePythonEditor();
                    persistState();
                });
                state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => execute());
                resizePythonEditor();
            });
        } else {
            pane.innerHTML = `<div class="qt-python-editor" data-python-editor><textarea data-fallback-editor spellcheck="false" style="width:100%;height:100%;background:#050816;color:#d7e2ee;border:0;padding:12px;font-family:Roboto Mono,monospace">${code}</textarea></div>`;
            const fallback = pane.querySelector("[data-fallback-editor]");
            fallback.addEventListener("input", () => {
                resizePythonEditor();
                persistState();
            });
            fallback.addEventListener("keydown", (event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                    event.preventDefault();
                    execute();
                }
            });
            resizePythonEditor();
        }
    }

    function resizePythonEditor() {
        const container = document.querySelector("[data-python-editor]");
        if (!container) return;
        const code = getCurrentPayload();
        const lineCount = Math.max(1, code.split("\n").length);
        const targetHeight = Math.min(620, Math.max(220, (lineCount * 22) + 48));
        container.style.height = `${targetHeight}px`;
        const ideRoot = document.getElementById("qt-ide");
        if (ideRoot) ideRoot.style.setProperty("--qt-editor-height", `${targetHeight}px`);
        if (state.editor && typeof state.editor.layout === "function") {
            state.editor.layout({ width: container.clientWidth, height: targetHeight });
        }
        if (window.parent !== window) {
            window.parent.postMessage({
                type: "quantumm:ide-resize",
                block_id: state.config.block_id,
                height: targetHeight + 260,
            }, window.location.origin);
        }
    }

    function renderIframe(pane, src, allow) {
        const iframe = document.createElement("iframe");
        iframe.src = src;
        iframe.allow = allow || "";
        iframe.title = state.config.label || "Environment";
        pane.innerHTML = "";
        pane.appendChild(iframe);
    }

    function preloadJupyterFiles() {
        const config = state.config.lab_config || {};
        (config.files || []).forEach((file) => {
            localStorage.setItem(`dataset:${file.path || "dataset.csv"}`, file.content || "");
        });
        writeTerminal("Success: JupyterLite file pre-loader staged dataset.csv.");
    }

    function renderCyber(pane) {
        const tools = state.config.tools || [];
        pane.innerHTML = `
            <div style="height:100%;display:grid;grid-template-columns:240px 1fr;background:#0a0e14">
                <aside style="border-right:1px solid #1f2a37;padding:14px;overflow:auto">
                    <div style="color:#00ff41;font-weight:700;margin-bottom:12px">Security Tools</div>
                    ${tools.map((tool) => `<button type="button" data-cyber-command="${escapeAttr(tool.command)}" style="display:block;width:100%;margin-bottom:8px;background:#111827;color:#d7e2ee;border:1px solid #1f2a37;border-radius:6px;padding:9px;text-align:left;font-family:inherit">${tool.name}</button>`).join("")}
                </aside>
                <main style="padding:18px;color:#718096">Use the tool list or type sample commands into the pinned terminal.</main>
            </div>`;
        pane.querySelectorAll("[data-cyber-command]").forEach((button) => {
            button.addEventListener("click", () => {
                const command = button.getAttribute("data-cyber-command");
                writeTerminal(`$ ${command}`);
                execute(command);
            });
        });
    }

    function escapeAttr(value) {
        return String(value || "").replace(/"/g, "&quot;");
    }

    function getCurrentPayload() {
        if (state.editor && typeof state.editor.getValue === "function") return state.editor.getValue();
        const fallback = document.querySelector("[data-fallback-editor]");
        if (fallback) return fallback.value;
        return savedState().code || state.config.student_code || "";
    }

    async function execute(payloadOverride) {
        if (state.isRunning) return;
        const payload = payloadOverride || getCurrentPayload();
        if (!payload.trim()) {
            writeTerminal("Error: write some Python code before running it.");
            return;
        }
        state.isRunning = true;
        const runButton = document.querySelector("[data-run]");
        if (runButton) {
            runButton.disabled = true;
            runButton.textContent = "Running...";
        }
        writeTerminal(`$ run ${state.currentEnv}`);
        try {
            const response = await fetch("/api/v1/execute/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify({
                    env_key: state.currentEnv,
                    payload,
                    metadata: {
                        lesson_id: state.config.lesson_id,
                        block_id: state.config.block_id,
                    },
                }),
            });
            const responseText = await response.text();
            let data;
            try {
                data = JSON.parse(responseText);
            } catch {
                throw new Error(`The server returned ${response.status}: ${responseText || "no response body"}`);
            }
            writeTerminal(data.output || data.status || `Execution failed (${response.status}).`);
            if (data.logs) writeTerminal(data.logs);
        } catch (error) {
            writeTerminal(`Error: ${error.message}`);
        } finally {
            state.isRunning = false;
            if (runButton) {
                runButton.disabled = false;
                runButton.textContent = "Run / Simulate";
            }
        }
    }

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(";").shift();
        return "";
    }

    function bindControls() {
        const select = document.querySelector("[data-env-select]");
        if (select) {
            select.value = state.currentEnv;
            select.addEventListener("change", () => loadEnvironment(select.value));
        }
        const run = document.querySelector("[data-run]");
        if (run) run.addEventListener("click", () => execute());
        const focus = document.querySelector("[data-focus-toggle]");
        if (focus) focus.addEventListener("click", () => document.getElementById("qt-ide").classList.toggle("focus-mode"));
        const fullscreen = document.querySelector("[data-fullscreen-toggle]");
        if (fullscreen) fullscreen.addEventListener("click", () => {
            const root = document.getElementById("qt-ide");
            if (!document.fullscreenElement && root.requestFullscreen) root.requestFullscreen();
            else if (document.exitFullscreen) document.exitFullscreen();
        });
        const clear = document.querySelector("[data-clear-terminal]");
        if (clear) clear.addEventListener("click", () => {
            if (state.terminal) state.terminal.clear();
            writeTerminal("Lab reset.");
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        state.config = readConfig();
        state.currentEnv = normalizeEnv(state.config.env_key || savedState().env_key || "python");
        initTerminal();
        bindControls();
        loadEnvironment(state.currentEnv);
        setInterval(persistState, 10000);
    });

    window.loadEnvironment = loadEnvironment;
})();
