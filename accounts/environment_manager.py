import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from django.conf import settings
from django.urls import reverse


@dataclass(frozen=True)
class EnvironmentRuntime:
    key: str
    protocol: str
    label: str
    template: str


class SandboxUnavailable(RuntimeError):
    """Raised when no usable sandbox backend is configured."""


class SandboxRunner:
    """Builds the command that executes a Python file inside a container.

    Supports two backends so the project runs both on Linux servers (plain
    Docker) and on Windows development machines (Docker reached through WSL):

      * ``docker`` — invokes the docker binary directly.
      * ``wsl``    — invokes ``wsl [-d <distro>] -- docker ...`` so Docker
                     Desktop / dockerd running inside WSL is used.
      * ``none``   — execution is blocked entirely.

    In all container modes learner code is run with no network, dropped
    capabilities, a read-only mount, memory/CPU/PID limits and a
    non-privileged user.
    """

    def __init__(self):
        self.backend = getattr(settings, "SANDBOX_BACKEND", "docker") or "docker"
        self.docker_bin = getattr(settings, "SANDBOX_DOCKER_BIN", "") or ""
        self.wsl_distro = getattr(settings, "SANDBOX_WSL_DISTRO", "") or ""
        self.image = getattr(settings, "SANDBOX_IMAGE", "quantumm/python-ds:3.12")

    # -- availability ---------------------------------------------------------
    def _resolve_binary(self, name):
        """Find the executable, honouring an explicit override path."""
        if self.docker_bin:
            return self.docker_bin
        return shutil.which(name)

    def is_available(self):
        if self.backend == "none":
            return False
        if self.backend == "wsl":
            return self._resolve_binary("wsl") is not None
        return self._resolve_binary("docker") is not None

    # -- command construction -------------------------------------------------
    def _docker_args(self, work_dir, inner_command):
        """Relative / translated volume mount, per backend."""
        if self.backend == "wsl":
            # Inside WSL the Windows temp path must be translated. We mount the
            # directory as-is and let WSL map it; Docker Desktop handles the
            # path translation for \\wsl$ shares.
            return [
                "run", "--rm",
                "--network", "none",
                "--memory", "256m",
                "--cpus", "1",
                "--pids-limit", "64",
                "--read-only",
                "--tmpfs", "/tmp:rw,size=64m",
                "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL",
                "--user", "65534:65534",
                "-v", f"{work_dir}:/workspace:ro",
                "-w", "/workspace",
                self.image,
                *inner_command,
            ]
        return [
            "run", "--rm",
            "--network", "none",
            "--memory", "256m",
            "--cpus", "1",
            "--pids-limit", "64",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--user", "65534:65534",
            "-v", f"{work_dir}:/workspace:ro",
            "-w", "/workspace",
            self.image,
            *inner_command,
        ]

    def build_command(self, work_dir):
        """Return the full argv list to run __student_code__.py in work_dir."""
        inner = ["python", "-I", "-u", "__student_code__.py"]
        if self.backend == "wsl":
            wsl_bin = self._resolve_binary("wsl")
            prefix = [wsl_bin]
            if self.wsl_distro:
                prefix += ["-d", self.wsl_distro]
            prefix += ["--", "docker"]
            return prefix + self._docker_args(work_dir, inner)
        docker_bin = self._resolve_binary("docker")
        return [docker_bin] + self._docker_args(work_dir, inner)


class EnvironmentManager:
    """Central registry and execution gateway for LMS runtimes."""

    SANDBOX_IMAGE = "quantumm/python-ds:3.12"
    DEFAULT_PYTHON_IMAGE = "python:3.12-alpine"
    DATA_SCIENCE_PACKAGES = [
        "pandas",
        "numpy",
        "scipy",
        "scikit-learn",
        "matplotlib",
        "seaborn",
        "statsmodels",
    ]
    MAX_STAGED_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file
    MAX_TOTAL_STAGED_SIZE = 50 * 1024 * 1024  # 50 MB total staged files
    # Public Microsoft "Sales & Marketing" sample report used as a fallback so
    # the Power BI environment renders something meaningful out of the box.
    DEFAULT_POWERBI_REPORT_URL = "https://playground.powerbi.com/sampleReportEmbed"

    REGISTRY = {
        "python": EnvironmentRuntime("python", "docker-exec", "Python Sandbox", "environments/base_ide.html"),
        "python_sandbox": EnvironmentRuntime("python_sandbox", "docker-exec", "Python Sandbox", "environments/base_ide.html"),
        "advanced_python_engine": EnvironmentRuntime("advanced_python_engine", "docker-exec", "Advanced Python", "environments/base_ide.html"),
        "jupyter": EnvironmentRuntime("jupyter", "jupyterlite", "JupyterLite", "environments/base_ide.html"),
        "jupyter_notebook": EnvironmentRuntime("jupyter_notebook", "jupyterlite", "JupyterLite", "environments/base_ide.html"),
        "wokwi": EnvironmentRuntime("wokwi", "iframe", "Wokwi Circuit Simulator", "environments/base_ide.html"),
        "robotics": EnvironmentRuntime("robotics", "iframe", "Robotics Simulator", "environments/robotics.html"),
        "circuit": EnvironmentRuntime("circuit", "iframe", "Wokwi Circuit Simulator", "environments/base_ide.html"),
        "circuit_simulator": EnvironmentRuntime("circuit_simulator", "iframe", "Wokwi Circuit Simulator", "environments/base_ide.html"),
        "arduino_flasher": EnvironmentRuntime("arduino_flasher", "web-serial", "Arduino Hardware Bridge", "environments/base_ide.html"),
        "cyber": EnvironmentRuntime("cyber", "terminal", "Cyber Security Lab (Simulated)", "environments/base_ide.html"),
        "security_terminal": EnvironmentRuntime("security_terminal", "terminal", "Cyber Security Lab (Simulated)", "environments/base_ide.html"),
        # --- Office utilities (browser-side tooling: SheetJS / reveal.js / Office viewer) ---
        "office_utility_excel": EnvironmentRuntime("office_utility_excel", "office", "Excel Analyzer", "environments/excel.html"),
        "office_utility_powerpoint": EnvironmentRuntime("office_utility_powerpoint", "office", "PowerPoint Preview", "environments/ppt.html"),
        "office_utility": EnvironmentRuntime("office_utility", "office", "Universal Office Suite", "environments/office.html"),
        # --- Power BI (embedded report iframe) ---
        "powerbi": EnvironmentRuntime("powerbi", "powerbi", "Power BI Report", "environments/powerbi.html"),
    }

    @classmethod
    def normalize_key(cls, env_key):
        aliases = {
            "wokwi": "wokwi",
            "robotics": "wokwi",
            "circuit": "wokwi",
            "circuit_simulator": "wokwi",
            "python_sandbox": "python",
            "advanced_python_engine": "python",
            "jupyter_notebook": "jupyter",
            "security_terminal": "cyber",
            # Office utilities keep their own canonical key so they never
            # silently degrade into the Python sandbox.
            "office_utility_excel": "office_utility_excel",
            "office_utility_powerpoint": "office_utility_powerpoint",
            "office_utility": "office_utility",
            "powerbi": "powerbi",
        }
        return aliases.get(env_key, env_key or "python")

    @classmethod
    def get_runtime(cls, env_key):
        key = env_key or "python"
        return cls.REGISTRY.get(key) or cls.REGISTRY.get(cls.normalize_key(key)) or cls.REGISTRY["python"]

    @classmethod
    def build_environment(cls, request, env_key, metadata=None):
        metadata = metadata or {}
        runtime = cls.get_runtime(env_key)
        canonical_key = cls.normalize_key(runtime.key)
        config = {
            "env_key": runtime.key,
            "canonical_key": canonical_key,
            "protocol": runtime.protocol,
            "label": runtime.label,
            "execute_url": reverse("execute_environment"),
            "lesson_id": metadata.get("lesson_id", ""),
            "block_id": metadata.get("block_id", ""),
            "student_code": metadata.get("student_code", ""),
            "files": metadata.get("files", []),
        }

        if canonical_key == "wokwi":
            config["iframe_url"] = cls.build_wokwi_url(metadata.get("diagram"), runtime.key)
            config["allow"] = "clipboard-write"
        elif canonical_key == "jupyter":
            config["iframe_url"] = metadata.get("jupyter_url") or "/static/jupyter/lab/index.html"
            config["lab_config"] = cls.build_jupyter_config(metadata.get("files"))
        elif canonical_key == "cyber":
            config["websocket_url"] = metadata.get("websocket_url") or "/ws/environments/cyber/"
            # This environment is an in-browser SIMULATION. The commands run no
            # real security tooling and never touch a network; it exists to teach
            # command syntax and workflow. `simulated` is surfaced to the UI so
            # students are never misled into thinking it is a live lab.
            config["simulated"] = True
            config["notice"] = (
                "Simulated security lab: commands are illustrative and run no real "
                "scanning or exploitation tooling."
            )
            config["tools"] = [
                {"name": "Nmap", "command": "nmap -sV 192.168.1.10"},
                {"name": "Wireshark", "command": "tshark -i eth0 -c 5"},
                {"name": "Metasploit", "command": "msfconsole -q"},
                {"name": "Burp Suite", "command": "burpsuite --project-file lab.burp"},
            ]
        elif canonical_key in ("office_utility_excel", "office_utility_powerpoint", "office_utility"):
            # Office utilities render entirely in the browser (SheetJS / reveal.js
            # / the hosted Office viewer). The server only supplies the mode and
            # an optional document URL.
            config["office_mode"] = canonical_key.replace("office_utility", "").strip("_") or "general"
            config["document_url"] = metadata.get("document_url", "")
        elif canonical_key == "powerbi":
            # Power BI reports render in an embedded iframe. Provide a default
            # public sample report; instructors can override per lesson.
            config["report_url"] = metadata.get("report_url") or cls.DEFAULT_POWERBI_REPORT_URL
            config["allow"] = "fullscreen"

        return config

    @classmethod
    def build_wokwi_url(cls, diagram=None, env_key="wokwi"):
        if diagram:
            diagram_payload = diagram
        elif env_key == "robotics":
            diagram_payload = {
                "version": 1,
                "author": "Quantum TechHub",
                "editor": "wokwi",
                "parts": [
                    {"type": "wokwi-arduino-uno", "id": "uno", "top": 50, "left": 120, "attrs": {}},
                    {"type": "wokwi-servo", "id": "servo1", "top": 220, "left": 80, "attrs": {"pin": "9"}},
                    {"type": "wokwi-servo", "id": "servo2", "top": 220, "left": 160, "attrs": {"pin": "10"}},
                ],
                "connections": [
                    {"from": {"id": "uno", "pin": "9"}, "to": {"id": "servo1", "pin": "signal"}},
                    {"from": {"id": "uno", "pin": "10"}, "to": {"id": "servo2", "pin": "signal"}},
                ],
            }
        else:
            diagram_payload = {
                "version": 1,
                "author": "Quantum TechHub",
                "editor": "wokwi",
                "parts": [{"type": "wokwi-arduino-uno", "id": "uno", "top": 0, "left": 0, "attrs": {}}],
                "connections": [],
            }
        encoded = base64.urlsafe_b64encode(json.dumps(diagram_payload).encode("utf-8")).decode("ascii")
        return f"https://wokwi.com/projects/new/arduino-uno?embed=1&diagram={encoded}"

    @classmethod
    def build_jupyter_config(cls, files=None):
        return {
            "appUrl": "/static/jupyter/lab/index.html",
            "enableUpload": True,
            "showFileBrowser": True,
            "files": files or [
                {
                    "path": "files/dataset.csv",
                    "content": "name,score\nAda,98\nGrace,95\nKatherine,99\n",
                    "type": "text/csv",
                }
            ],
        }

    @classmethod
    def execute(cls, env_key, payload="", metadata=None):
        canonical_key = cls.normalize_key(env_key)
        if canonical_key == "python":
            return cls.execute_python(payload, files=(metadata or {}).get("files"))
        if canonical_key == "wokwi":
            return cls.execute_wokwi(payload, metadata)
        if canonical_key == "jupyter":
            return {
                "status": "success",
                "output": "JupyterLite execution runs inside the browser. Files/config were prepared.",
                "logs": cls.build_jupyter_config((metadata or {}).get("files")),
            }
        if canonical_key == "cyber":
            return cls.execute_cyber(payload)
        if canonical_key in ("office_utility_excel", "office_utility_powerpoint", "office_utility"):
            return cls.execute_office(canonical_key, payload, metadata)
        if canonical_key == "powerbi":
            return cls.execute_powerbi(payload, metadata)
        return {"status": "error", "output": f"Unknown environment: {env_key}", "logs": ""}

    @classmethod
    def _stage_files(cls, work_dir, files):
        total_bytes = 0
        seen_basename = set()
        for file_entry in files or []:
            filename = file_entry.get("path") or file_entry.get("name")
            if not filename:
                continue
            normalized = os.path.normpath(filename).lstrip("/\\")
            if normalized.startswith("..") or os.path.isabs(normalized):
                continue
            basename = os.path.basename(normalized)
            if not basename or basename == "__student_code__.py":
                continue
            if basename in seen_basename:
                continue
            content = file_entry.get("content", "")
            if isinstance(content, str):
                content_bytes = content.encode("utf-8")
            else:
                content_bytes = content
            if len(content_bytes) > cls.MAX_STAGED_FILE_SIZE:
                continue
            if total_bytes + len(content_bytes) > cls.MAX_TOTAL_STAGED_SIZE:
                continue
            destination = os.path.join(work_dir, basename)
            try:
                with open(destination, "wb") as f:
                    f.write(content_bytes)
                total_bytes += len(content_bytes)
                seen_basename.add(basename)
            except OSError:
                continue

    @classmethod
    def execute_python(cls, code, files=None):
        files = files or []
        runner = SandboxRunner()
        with tempfile.TemporaryDirectory() as work_dir:
            cls._stage_files(work_dir, files)
            code_file_path = os.path.join(work_dir, "__student_code__.py")
            with open(code_file_path, "w", encoding="utf-8") as code_file:
                code_file.write(code or "")

            if runner.is_available():
                try:
                    command = runner.build_command(work_dir)
                    process = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                    if process.returncode != 0:
                        stderr = process.stderr or ""
                        if "No such image" in stderr or "Unable to find image" in stderr:
                            return {
                                "status": "error",
                                "output": (
                                    f"Sandbox image {runner.image} not found. "
                                    f"Build it with: docker build -f Dockerfile.python-ds -t {runner.image} ."
                                ),
                                "logs": stderr,
                            }
                        return {
                            "status": "error",
                            "output": stderr or process.stdout,
                            "logs": f"Sandbox ({runner.backend}) exited with code {process.returncode}",
                        }
                    return {
                        "status": "success",
                        "output": process.stdout,
                        "logs": f"Sandbox ({runner.backend}) {runner.image} executed successfully.",
                    }
                except subprocess.TimeoutExpired:
                    return {
                        "status": "error",
                        "output": "❌ Execution timed out after 20 seconds. The sandbox process was terminated.",
                        "logs": "Sandbox timeout",
                    }
                except Exception as exc:
                    return {
                        "status": "error",
                        "output": f"Sandbox execution failed: {str(exc)}",
                        "logs": f"Sandbox ({runner.backend}) could not start.",
                    }

            # No sandbox available. Only fall back to host execution when the
            # operator has EXPLICITLY opted in (default: blocked). This keeps
            # learner code off the application host in every normal deployment.
            if not getattr(settings, "ALLOW_UNSANDBOXED_LOCAL_EXECUTION", False):
                return {
                    "status": "error",
                    "output": (
                        "The code sandbox is unavailable. Install Docker (or enable the "
                        "WSL backend) to run code. Host execution is disabled for safety."
                    ),
                    "logs": f"Sandbox backend '{runner.backend}' unavailable and host fallback disabled.",
                }

            try:
                process = subprocess.run(
                    [sys.executable, "-I", "-u", code_file_path],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    cwd=work_dir,
                )
                if process.returncode == 0:
                    is_noted = "with staged files" if files else "without staged files"
                    return {
                        "status": "success",
                        "output": process.stdout,
                        "logs": f"⚠️ UNSANDBOXED host fallback executed successfully {is_noted}.",
                    }
                return {"status": "error", "output": process.stderr or process.stdout, "logs": f"Host fallback exited with code {process.returncode}"}
            except subprocess.TimeoutExpired:
                return {
                    "status": "error",
                    "output": "❌ Execution timed out after 20 seconds. The sandbox process was terminated.",
                    "logs": "Host fallback timeout",
                }
            except Exception as exc:
                return {"status": "error", "output": f"Host execution failed: {str(exc)}", "logs": "Host fallback failed."}

    @classmethod
    def execute_wokwi(cls, code, metadata=None):
        return {
            "status": "success",
            "output": "Circuit payload prepared for Wokwi simulation.",
            "logs": {
                "iframe_url": cls.build_wokwi_url((metadata or {}).get("diagram")),
                "code_length": len(code or ""),
            },
        }

    @classmethod
    def execute_cyber(cls, command):
        """Return a SIMULATED response for the security lab terminal.

        This is intentionally a teaching aid, NOT a real terminal. No command is
        executed, no tooling is installed, and no network is touched. Outputs are
        canned strings so learners can practise command syntax and workflow. The
        ``[simulated]`` prefix is included in every response so the UI can make
        clear that nothing real happened.
        """
        clean_command = (command or "").strip()
        if not clean_command:
            return {"status": "error", "output": "No terminal command received.", "logs": ""}
        sample_outputs = {
            "nmap": "Success: Host 192.168.1.10 is up. Open ports: 22/tcp, 80/tcp.",
            "tshark": "Success: Captured 5 packets from lab interface.",
            "msfconsole": "Vulnerable: training target exposes an intentionally weak service.",
            "burpsuite": "Success: Proxy project initialized for the lab target.",
        }
        for prefix, output in sample_outputs.items():
            if clean_command.startswith(prefix):
                return {
                    "status": "success",
                    "simulated": True,
                    "output": f"[simulated] {output}\n(No real tooling was run.)",
                    "logs": f"Simulated cyber tool: {prefix}",
                }
        return {
            "status": "success",
            "simulated": True,
            "output": f"$ {clean_command}\n[simulated] Command accepted by the lab gateway. No real command was executed.",
            "logs": "Simulated cyber terminal fallback.",
        }

    @classmethod
    def execute_office(cls, canonical_key, payload="", metadata=None):
        """Office utilities execute in the browser, not in the Python sandbox.

        Excel/SheetJS, PowerPoint/reveal.js and the hosted Office viewer all run
        client-side, so the server simply acknowledges the payload and reports
        which mode the front-end should render. This deliberately does NOT route
        to ``execute_python`` — that was the old bug where Excel lessons silently
        became Python lessons.
        """
        mode = canonical_key.replace("office_utility", "").strip("_") or "general"
        labels = {
            "excel": "Excel analyzer",
            "powerpoint": "PowerPoint preview",
            "general": "Office suite",
        }
        return {
            "status": "success",
            "output": f"{labels.get(mode, 'Office utility')} ready. Rendering in the browser.",
            "logs": {
                "office_mode": mode,
                "document_url": (metadata or {}).get("document_url", ""),
                "payload_length": len(payload or ""),
            },
        }

    @classmethod
    def execute_powerbi(cls, payload="", metadata=None):
        """Power BI reports render in an embedded iframe (no server execution).

        The server just confirms the report target so the front-end can mount
        the embed. This keeps Power BI lessons off the Python sandbox path.
        """
        report_url = (metadata or {}).get("report_url") or cls.DEFAULT_POWERBI_REPORT_URL
        return {
            "status": "success",
            "output": "Power BI report ready. Rendering embedded report in the browser.",
            "logs": {
                "report_url": report_url,
                "payload_length": len(payload or ""),
            },
        }
