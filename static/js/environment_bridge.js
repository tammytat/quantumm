class EnvironmentBridge {
    constructor(options = {}) {
        this.envKey = options.envKey || this.readEnvKey();
        this.lessonId = options.lessonId || this.readLessonId();
        this.blockId = options.blockId || this.readBlockId();
        this.studentCode = options.studentCode || "";
        this.csrfToken = options.csrfToken || this.readCsrfToken();
        this.environmentConfig = this.readEnvironmentConfig();
        this.targets = {
            jupyterFrame: document.querySelector("[data-jupyterlite-frame]"),
            circuitFrame: document.querySelector("[data-circuit-frame]"),
            fileInput: document.querySelector("[data-dataset-input]"),
            datasetList: document.querySelector("[data-dataset-list]"),
            runButton: document.querySelector("[data-env-run]"),
            flashButton: document.querySelector("[data-flash-hardware]"),
            terminal: document.querySelector("[data-env-terminal]"),
        };
    }

    readEnvKey() {
        const node = document.querySelector("[data-env-key]");
        return node ? node.getAttribute("data-env-key") : "";
    }

    readCsrfToken() {
        const input = document.querySelector("input[name='csrfmiddlewaretoken']");
        return input ? input.value : "";
    }

    readLessonId() {
        const node = document.querySelector("[data-lesson-id]");
        return node ? node.getAttribute("data-lesson-id") : "";
    }

    readBlockId() {
        const node = document.querySelector("[data-block-id]");
        return node ? node.getAttribute("data-block-id") : "";
    }

    readEnvironmentConfig() {
        const node = document.getElementById("environment-config");
        if (!node) return {};
        try {
            return JSON.parse(node.textContent || "{}");
        } catch {
            return {};
        }
    }

    init() {
        if (this.envKey === "jupyter" || this.envKey === "jupyter_notebook") {
            this.injectJupyterLite();
            this.bindDatasetUploads();
            this.syncPersistedDatasets();
        }

        if (['circuit', 'circuit_simulator', 'arduino_flasher', 'robotics'].includes(this.envKey)) {
            this.bindCircuitRunner();
            this.bindHardwareFlash();
        }

        window.addEventListener("message", (event) => this.handleMessage(event));
    }

    setStudentCode(code) {
        this.studentCode = code || "";
    }

    injectJupyterLite() {
        const frame = this.targets.jupyterFrame;
        if (!frame) return;

        const iframeUrl = this.environmentConfig.iframe_url || "/static/jupyter/lab/index.html";
        const params = new URLSearchParams({
            lesson: this.lessonId,
            block: this.blockId,
        });
        frame.src = `${iframeUrl}?${params.toString()}`;
        this.writeTerminal("JupyterLite workspace loaded. Datasets dropped here stay in the browser.");
    }

    bindDatasetUploads() {
        const input = this.targets.fileInput;
        const saveAllButton = document.querySelector("[data-save-all-datasets]");
        if (!input) return;

        input.addEventListener("change", async () => {
            const files = Array.from(input.files || []);
            if (!files.length) return;

            const manifest = [];
            for (const file of files) {
                const text = await file.text();
                localStorage.setItem(`dataset:${file.name}`, text);
                manifest.push({ name: file.name, size: file.size, type: file.type || "text/csv" });

                // Auto-upload the file to server staging so backend execution can access it
                await this.saveDatasetToServer(file.name, text);
            }

            this.renderDatasets();
            this.postToJupyter({
                type: "quantumm:datasets-loaded",
                datasets: manifest,
            });
            this.writeTerminal(`Loaded ${manifest.length} dataset file(s) into the browser sandbox.`);
        });

        if (saveAllButton) {
            saveAllButton.addEventListener("click", async () => {
                const keys = Object.keys(localStorage).filter((key) => key.startsWith("dataset:"));
                if (!keys.length) {
                    this.writeTerminal("No uploaded datasets to save to server.");
                    return;
                }
                let savedCount = 0;
                const manifest = [];
                for (const key of keys) {
                    const name = key.replace("dataset:", "");
                    const content = localStorage.getItem(key);
                    if (!content) continue;
                    const result = await this.saveDatasetToServer(name, content);
                    if (result) {
                        savedCount += 1;
                        manifest.push({ name, size: content.length, type: "text/csv" });
                    }
                }
                this.writeTerminal(`Saved ${savedCount} dataset file(s) to server storage.`);
                this.renderDatasets();
                if (manifest.length) {
                    this.postToJupyter({
                        type: "quantumm:datasets-loaded",
                        datasets: manifest,
                    });
                }
            });
        }

        this.renderDatasets();
    }

    async saveDatasetToServer(name, content) {
        try {
            const res = await fetch("/api/v1/upload-dataset/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": this.csrfToken,
                },
                body: JSON.stringify({
                    name: name,
                    content: content,
                    lesson_id: this.lessonId,
                    block_id: this.blockId,
                }),
            });
            const json = await res.json();
            if (json && json.status === "success") {
                this.writeTerminal(`Saved ${name} to server as ${json.server_path}`);
                return true;
            }
            this.writeTerminal(`Save failed for ${name}: ${json && json.message ? json.message : res.statusText}`);
        } catch (err) {
            this.writeTerminal(`Save error for ${name}: ${err.message}`);
        }
        return false;
    }

    syncPersistedDatasets() {
        const datasetKeys = Object.keys(localStorage).filter((key) => key.startsWith("dataset:"));
        if (!datasetKeys.length) return;

        const manifest = datasetKeys.map((key) => {
            const name = key.replace("dataset:", "");
            const content = localStorage.getItem(key) || "";
            return { name, size: content.length, type: "text/csv" };
        });

        if (manifest.length) {
            this.postToJupyter({
                type: "quantumm:datasets-loaded",
                datasets: manifest,
            });
            this.writeTerminal(`Restored ${manifest.length} saved dataset file(s) to the notebook.`);
        }
    }

    renderDatasets() {
        const list = this.targets.datasetList;
        if (!list) return;

        const datasetKeys = Object.keys(localStorage).filter((key) => key.startsWith("dataset:"));
        if (!datasetKeys.length) {
            list.innerHTML = '<div class="text-muted small">No datasets uploaded yet.</div>';
            return;
        }

        list.innerHTML = "";
        datasetKeys.forEach((key) => {
            const name = key.replace("dataset:", "");
            const row = document.createElement("div");
            const label = document.createElement("span");
            const removeBtn = document.createElement("button");
            const saveBtn = document.createElement("button");

            row.className = "dataset-row d-flex align-items-center gap-2";
            label.textContent = name;

            removeBtn.type = "button";
            removeBtn.textContent = "x";
            removeBtn.title = `Remove ${name}`;
            removeBtn.addEventListener("click", () => {
                localStorage.removeItem(`dataset:${name}`);
                this.renderDatasets();
            });

            saveBtn.type = "button";
            saveBtn.textContent = "Save to server";
            saveBtn.title = `Save ${name} to server storage for code execution`;
            saveBtn.addEventListener("click", async () => {
                const content = localStorage.getItem(`dataset:${name}`) || "";
                try {
                    const res = await fetch("/api/v1/upload-dataset/", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": this.csrfToken,
                        },
                        body: JSON.stringify({ name: name, content: content }),
                    });
                    const json = await res.json();
                    if (json && json.status === "success") {
                        this.writeTerminal(`Saved ${name} to server as ${json.server_path}`);
                    } else {
                        this.writeTerminal(`Failed to save ${name}: ${json && json.message ? json.message : res.statusText}`);
                    }
                } catch (err) {
                    this.writeTerminal(`Save failed: ${err.message}`);
                }
            });

            row.append(label, saveBtn, removeBtn);
            list.appendChild(row);
        });
    }

    postToJupyter(payload) {
        const frame = this.targets.jupyterFrame;
        if (frame && frame.contentWindow) {
            frame.contentWindow.postMessage(payload, window.location.origin);
        }
    }

    bindCircuitRunner() {
        if (!this.targets.runButton) return;

        this.targets.runButton.addEventListener("click", () => {
            const code = this.readStudentCodeFromParent();
            this.loadCircuitCode(code);
        });
    }

    readStudentCodeFromParent() {
        if (this.studentCode) return this.studentCode;
        const parentEditor = window.parent && window.parent.QuantummEditors && window.parent.QuantummEditors[this.blockId];
        if (parentEditor && typeof parentEditor.getValue === "function") {
            return parentEditor.getValue();
        }
        const textarea = document.querySelector("[data-student-code]");
        return textarea ? textarea.value : "";
    }

    loadCircuitCode(code) {
        const frame = this.targets.circuitFrame;
        const payload = {
            type: "quantumm:load-code",
            env_key: this.envKey,
            block_id: this.blockId,
            student_code: code || "",
        };
        const targetOrigin = ['circuit', 'circuit_simulator', 'arduino_flasher', 'robotics'].includes(this.envKey)
            ? 'https://wokwi.com'
            : window.location.origin;

        if (frame && frame.contentWindow) {
            frame.contentWindow.postMessage(payload, targetOrigin);
            this.writeTerminal("Sent current code to the circuit simulator.");
        }

        fetch("/api/validate-code/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": this.csrfToken,
            },
            body: JSON.stringify({
                code: code || "",
                env_type: "arduino",
                token: this.lessonId,
            }),
        })
            .then((response) => response.json())
            .then((result) => this.writeTerminal(result.output || result.message || "Simulation request complete."))
            .catch(() => this.writeTerminal("Simulation bridge could not reach the validation endpoint."));
    }

    async bindHardwareFlash() {
        if (!this.targets.flashButton) return;

        if (!("serial" in navigator)) {
            this.targets.flashButton.disabled = true;
            this.targets.flashButton.title = "Web Serial is available in Chrome and Edge over HTTPS or localhost.";
            return;
        }

        this.targets.flashButton.addEventListener("click", async () => {
            try {
                const port = await navigator.serial.requestPort();
                await port.open({ baudRate: 115200 });
                const writer = port.writable.getWriter();
                const code = new TextEncoder().encode(this.readStudentCodeFromParent());
                await writer.write(code);
                writer.releaseLock();
                await port.close();
                this.writeTerminal("Code sent over Web Serial to the connected board.");
            } catch (error) {
                this.writeTerminal(`Hardware flash cancelled or failed: ${error.message}`);
            }
        });
    }

    handleMessage(event) {
        if (event.origin !== window.location.origin && event.origin !== "https://wokwi.com") return;
        const data = event.data || {};

        if (data.type === "quantumm:run-code") {
            this.loadCircuitCode(data.student_code || this.studentCode);
        }

        if (data.type === "JUPYTER_CODE_SUBMISSION") {
            this.writeTerminal("Notebook submitted code for validation.");
        }
    }

    writeTerminal(message) {
        const terminal = this.targets.terminal;
        if (!terminal) return;
        const line = document.createElement("div");
        line.textContent = `$ ${message}`;
        terminal.appendChild(line);
        terminal.scrollTop = terminal.scrollHeight;
    }
}

window.EnvironmentBridge = EnvironmentBridge;
