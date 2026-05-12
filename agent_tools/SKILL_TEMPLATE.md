---
name: zerosync-copilot
description: 
  Enables remote server operations. The local workspace is live-synced to the remote server. Use this skill for all server-side interactions.
---

# ZeroSync Remote Copilot Instructions

**Architecture:** If you are reading this skill, the user has successfully mounted the current local workspace to the remote server. Any local file edits you make are instantly pushed to the server. However, files generated *on the server* do NOT sync back automatically.

## Current Environment
- Remote Host: **{HOSTNAME}**
- Remote Dir: `{REMOTE_DIR}`
- Docker: **{DOCKER_STATUS}**

## Required Tools
**MANDATE: ABANDON default local shell execution. You MUST use the following scripts to interact with the server.**

- **Remote Execution**: `python {SCRIPTS_DIR}/shell_execute.py "<command>"`
  *Role*: Replaces your local terminal. Injects commands into the remote server's live terminal. 
  *Warning*: For long-running tasks (e.g., training, large installs), you MUST run them in the background: `python {SCRIPTS_DIR}/shell_execute.py "nohup <your_command> > output.log 2>&1 &"`
- **Pull Files**: `python {SCRIPTS_DIR}/safe_pull.py "<remote_path>"`
  *Role*: Downloads server-generated files (logs, weights, outputs) to your local workspace so you can analyze them. Supports both absolute paths and relative paths (relative to workspace root).
- **Environment Profiler**: `python {SCRIPTS_DIR}/env_profiler.py`
  *Role*: Retrieves a highly compressed, structured summary of the remote system.
- **Web Service Launcher**: `python {SCRIPTS_DIR}/port_forward.py <port> ["<command>"]`
  *Role*: Safely starts a web UI in the background and instantly creates a local access URL. 
  *Usage*: Pass the expected port and your start command (e.g., `python port_forward.py 7860 "gradio app.py"`). If the service is already running, omit the command.

## Critical Rules
1. **Code Modification (THINK LOCAL)**: Every local file corresponds exactly to a file on the server. DO NOT waste time probing the server to verify file existence before editing. Just use your standard local tools to modify the local files directly. The changes will magically sync. NEVER use remote shell commands (like `sed` or `echo`) to edit files.
2. **Command Execution (THINK REMOTE)**: NEVER run builds, tests, or project scripts locally. ALWAYS use `shell_execute.py` to run them on the server.
3. **Reading Results**: If your remote command generates a new file on the server, you MUST use `safe_pull.py` to bring it to your local workspace BEFORE attempting to read or analyze it.
4. **Web Services**: NEVER run web servers (e.g., TensorBoard, Gradio) via `shell_execute.py` as it blocks the channel. You MUST use the `port_forward.py` tool to start them and expose the URL in one atomic step.
5. **Skill Initialization**: Immediately upon activating this skill, you MUST execute `env_profiler.py` and STOP all actions IMMEDIATELY after the tool returns its output. Your task is complete once the environment profile is displayed; you MUST wait for the user's next explicit instruction before taking any further action.