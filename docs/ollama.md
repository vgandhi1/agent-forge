# Running AgentForge with Ollama (local models)

AgentForge can run entirely on a local [Ollama](https://ollama.com) server — no Anthropic key, no
network calls leaving your machine. This guide covers install, the two common WSL/Windows topologies,
model choice, configuration, and troubleshooting.

> TL;DR
> ```bash
> export AGENTFORGE_LLM_PROVIDER=ollama
> export AGENTFORGE_OLLAMA_MODEL=qwen2.5-coder:7b
> # If Ollama is on the SAME machine/OS as AgentForge, defaults work:
> uv run python main.py --preset intake --goal "..."
> ```

---

## 1. Install Ollama

| OS | Install |
|----|---------|
| **Windows** | Download the installer from [ollama.com/download](https://ollama.com/download). Runs as a tray app + background service on `127.0.0.1:11434`. |
| **Linux / WSL** | `curl -fsSL https://ollama.com/install.sh \| sh` then `ollama serve` (or it runs as a systemd service). |
| **macOS** | Download the app from [ollama.com/download](https://ollama.com/download). |

Verify it serves:

```bash
curl http://127.0.0.1:11434/api/tags   # → JSON list of installed models
```

---

## 2. Pick a model (must support tool calling)

Every AgentForge agent acts through **tools** (`write_file`, `read_file`, review/escalation tools), so
the model **must support Ollama function calling**. Small instruct-only models (e.g. `llama3.2:3b`)
produce truncated or tool-less output and are not suitable for the full pipeline.

| Model | Size | Notes |
|-------|------|-------|
| `qwen2.5-coder:7b` | ~4.7 GB | **Recommended.** Strong code + reliable tool calls. |
| `llama3.1:8b` | ~4.9 GB | Solid general-purpose tool use. |
| `qwen2.5:14b` | ~9 GB | Stronger reasoning if you have the VRAM. |
| `mistral-nemo` | ~7 GB | Good tool calling, larger context. |

Pull one:

```bash
ollama pull qwen2.5-coder:7b
```

Per-role overrides are supported (e.g. a bigger model for the builder, a smaller one for the reviewer):

```bash
export AGENTFORGE_OLLAMA_MODEL=qwen2.5-coder:7b          # default for all roles
export AGENTFORGE_OLLAMA_MODEL_BACKEND=qwen2.5-coder:14b # heavier for the backend
export AGENTFORGE_OLLAMA_MODEL_REVIEWER=llama3.1:8b      # lighter for the reviewer
```

---

## 3. Topology: where does Ollama run?

### A. Ollama and AgentForge on the same machine/OS (simplest)

Includes: native Linux, macOS, or **Ollama installed inside WSL** alongside AgentForge. Default host
works, nothing else to set:

```bash
export AGENTFORGE_LLM_PROVIDER=ollama
export AGENTFORGE_OLLAMA_MODEL=qwen2.5-coder:7b
uv run python main.py --dry-run        # confirms host = http://127.0.0.1:11434
```

### B. Ollama on Windows, AgentForge in WSL2 (GPU on Windows)

This is the common gotcha. Inside WSL2, `127.0.0.1` is **WSL's own loopback**, not the Windows host —
so the default points at nothing and you get a connection error. Two ways to fix it.

#### B-1. Mirrored networking (cleanest — `127.0.0.1` just works)

On Windows, create/edit `C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Then from PowerShell:

```powershell
wsl --shutdown
```

Reopen WSL. Now WSL and Windows share `localhost`, so the **default config works** — no host IP, no
trust flag needed. (Requires a recent Windows 11 / WSL build.)

#### B-2. NAT networking (default) — point at the Windows host

**On Windows** — make Ollama listen on all interfaces (not just localhost), then restart it:

```powershell
setx OLLAMA_HOST "0.0.0.0:11434"
# Quit Ollama from the tray, then relaunch it.
```

Allow the port through Windows Firewall (admin PowerShell):

```powershell
New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow
```

**In WSL** — point at the Windows host IP and allow the private address (AgentForge rejects non-loopback
hosts unless you opt in):

```bash
export AGENTFORGE_LLM_PROVIDER=ollama
export AGENTFORGE_OLLAMA_HOST="http://$(ip route show default | awk '{print $3}'):11434"
export AGENTFORGE_OLLAMA_TRUST_LAN=1       # required: host IP is private/LAN
export AGENTFORGE_OLLAMA_MODEL=qwen2.5-coder:7b
```

`ip route show default` yields the WSL→Windows gateway (the Windows host) in NAT mode.

---

## 4. Test connectivity before running

Always confirm the endpoint first — this isolates network problems from AgentForge:

```bash
echo "$AGENTFORGE_OLLAMA_HOST"
curl "${AGENTFORGE_OLLAMA_HOST:-http://127.0.0.1:11434}/api/tags"
```

- JSON list of models → good, proceed.
- `Connection refused` / hang → Ollama isn't reachable: check it's running, `OLLAMA_HOST=0.0.0.0`
  applied (topology B), firewall, and the host IP.

Optional end-to-end check of chat + the model:

```bash
curl "${AGENTFORGE_OLLAMA_HOST:-http://127.0.0.1:11434}/api/chat" -d '{
  "model": "qwen2.5-coder:7b",
  "messages": [{"role": "user", "content": "say ok"}],
  "stream": false
}'
```

---

## 5. Run AgentForge

```bash
# Preview resolved config (provider, host, per-role models) — no API calls
uv run python main.py --dry-run

# Smallest real run
uv run python main.py --preset intake --goal "Capture requirements for habit streaks"

# Full pipeline
uv run python main.py --goal "Build the MVP of DailyEase"
```

Persist the settings instead of exporting each time — add them to `.env` in the repo root:

```bash
AGENTFORGE_LLM_PROVIDER=ollama
AGENTFORGE_OLLAMA_HOST=http://<windows-host-ip>:11434
AGENTFORGE_OLLAMA_TRUST_LAN=1
AGENTFORGE_OLLAMA_MODEL=qwen2.5-coder:7b
```

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `ollama unreachable at http://127.0.0.1:11434` | Topology B: WSL can't see Windows localhost. Use mirrored networking (B-1) or the host IP + `AGENTFORGE_OLLAMA_TRUST_LAN=1` (B-2). |
| `Connection refused` from `curl /api/tags` | Ollama not running, or not bound to `0.0.0.0` on Windows (`setx OLLAMA_HOST 0.0.0.0:11434`, then restart Ollama). |
| Connects locally but not from WSL | Windows Firewall blocking 11434 — add the inbound rule above. |
| `AGENTFORGE_OLLAMA_HOST` rejected / "host not allowed" | It's a private/LAN address; set `AGENTFORGE_OLLAMA_TRUST_LAN=1`. |
| `model "…" not found` | `ollama pull <model>` on the machine running Ollama. |
| Truncated files / no tool calls | Model too small or lacks tool support — switch to `qwen2.5-coder:7b` / `llama3.1:8b`. |
| Very slow | Large model without GPU. Use a smaller tag, or run Ollama where the GPU is and point AgentForge at it. |
| Timeouts on big builds | Expected for large local models; AgentForge retries. Consider per-role smaller models for `pm`/`reviewer`. |

See also: [USAGE.md](../USAGE.md) (all interfaces and flags) and the env-var table in
[agents_plan.md](../agents_plan.md).
