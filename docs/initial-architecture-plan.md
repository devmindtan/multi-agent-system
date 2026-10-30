# SYSTEM ARCHITECTURE SPECIFICATION: HYBRID LOCAL/CLOUD MULTI-AGENT RUNTIME

---

## 1. System Overview & Objectives

Hệ thống **Hybrid Multi-Agent** được thiết kế để điều phối công việc phát triển phần mềm theo mô hình tự động hóa phân tầng:

* **Tối ưu chi phí:** Sử dụng mô hình cục bộ (Local LLM qua Ollama/vLLM) cho các tác vụ lặp, quét file, sinh boilerplate, linting và unit test ($0 token cost).
* **Đảm bảo chất lượng kiến trúc:** Hỗ trợ kết nối Cloud LLM (Claude/GPT qua LiteLLM/OpenRouter) cho khâu lập kế hoạch (Planning) và review logic khi cần.
* **Độc lập dự án:** Agent hoạt động trên bất kỳ codebase nào thông qua việc tiêm ngữ cảnh động (`project_context.md`) và CLI Tools chuẩn hóa.
* **Kiểm soát vòng lặp:** Sử dụng State Machine có giới hạn recursion, lưu checkpoint và ngắt khi gặp lỗi lặp.

---

## 2. Architecture & Workflow

```
                                  +-----------------------------+
                                  |     User Task / Prompt      |
                                  +--------------+--------------+
                                                 |
                                                 v
                                  +-----------------------------+
                                  |     Context Loader Node     |
                                  |  (Loads project_context.md  |
                                  |   & repository tree)        |
                                  +--------------+--------------+
                                                 |
                                                 v
                                  +-----------------------------+
                                  |      Planner Agent          |
                                  | (Breakdown task into steps) |
                                  +--------------+--------------+
                                                 |
                       +-------------------------+-------------------------+
                       |                                                   ^
                       v                                                   | (Fail - retry <= 3)
         +-----------------------------+                                   |
         |      Executor Agent         |                                   |
         |  (Call Tools, Write Code)   |                                   |
         +--------------+--------------+                                   |
                        |                                                  |
                        v                                                  |
         +-----------------------------+                                   |
         |   Deterministic Verifier    |                                   |
         |   (Run Linter / Test CLI)   +--- [Exit code != 0, retry] -------+
         +--------------+--------------+
                        | (Exit code == 0)
                        v
         +-----------------------------+
         |     Reviewer / QC Agent     +--- [Changes rejected] ------------+
         +--------------+--------------+
                        | (Approved)
                        v
         +-----------------------------+
         |       Output & Report       |
         +-----------------------------+

```

---

## 3. Tech Stack

* **Language & Runtime:** Python 3.11+
* **Orchestration Framework:** LangGraph (StateGraph)
* **Model Inference Layer:** LiteLLM (Universal proxy hỗ trợ đồng thời Ollama, vLLM, Anthropic, OpenAI)
* **Local Serving Engine:** Ollama (Recommended models: `qwen2.5-coder:7b-instruct`, `qwen2.5-coder:14b-instruct`)
* **State Management:** SQLite / In-Memory checkpointer
* **Schema Validation:** Pydantic v2

---

## 4. Directory Structure

```text
multi-agent-system/
├── config/
│   ├── settings.yaml          # Model configurations, local endpoints, timeouts
│   └── tools.yaml             # Whitelisted commands and path restrictions
├── core/
│   ├── __init__.py
│   ├── state.py               # Pydantic models & Graph state definition
│   ├── engine.py              # LangGraph orchestration graph construction
│   └── llm_gateway.py         # LiteLLM router wrapper
├── agents/
│   ├── __init__.py
│   ├── base.py                # Abstract Base Agent
│   ├── context_loader.py      # Scans repo and injects project rules
│   ├── planner.py             # High-level task decomposer
│   ├── executor.py            # Code generation & tool invocation
│   └── reviewer.py            # Final acceptance check
├── tools/
│   ├── __init__.py
│   ├── fs_tools.py            # read_file, write_file, patch_file, list_files
│   └── bash_tools.py          # run_command, run_linter, run_tests
├── main.py                    # CLI Entry point
├── requirements.txt
└── README.md

```

---

## 5. Core Data Models (`core/state.py`)

```python
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

class SubTask(BaseModel):
    id: int
    description: str
    target_files: List[str]
    verification_command: Optional[str] = None
    status: str = Field(default="pending", pattern="^(pending|in_progress|completed|failed)$")

class ExecutionArtifact(BaseModel):
    task_id: int
    files_created: List[str] = Field(default_factory=list)
    files_modified: List[str] = Field(default_factory=list)
    command_outputs: List[Dict[str, Any]] = Field(default_factory=list)
    error_log: Optional[str] = None

class AgentGraphState(TypedDict):
    project_root: str
    user_prompt: str
    project_context: str
    plan: List[SubTask]
    current_task_index: int
    retry_count: int
    max_retries: int
    artifacts: List[ExecutionArtifact]
    is_completed: bool
    final_summary: str

```

---

## 6. Detailed Agent Specifications & Prompts

### 6.1. Context Loader (`agents/context_loader.py`)

* **Role:** Khởi tạo ngữ cảnh ban đầu.
* **Actions:**
1. Đọc file `project_context.md` (hoặc `.agent-rules`) tại `project_root`. Nếu không tồn tại, khởi tạo context mặc định.
2. Quét cấu trúc thư mục dạng tree (bỏ qua `node_modules`, `.git`, `__pycache__`, `venv`).
3. Ghép vào trường `project_context` trong state.



### 6.2. Planner Agent (`agents/planner.py`)

* **Target Model:** Local `qwen2.5-coder:14b` hoặc Cloud Model (qua config).
* **System Prompt:**

```text
You are the Technical Lead Planner.
Analyze the user request, repository structure, and project guidelines.
Break the task down into a sequential list of minimal, atomic, verifiable subtasks.
Do not write complete implementation code here. Focus on precise file paths and validation checks.

Output MUST strictly follow the JSON schema:
{
  "tasks": [
    {
      "id": 1,
      "description": "Clear step description",
      "target_files": ["path/to/file"],
      "verification_command": "npm test path/to/test or pytest"
    }
  ]
}

```

### 6.3. Executor Agent (`agents/executor.py`)

* **Target Model:** Local `qwen2.5-coder:7b-instruct` hoặc `qwen2.5-coder:14b-instruct`.
* **System Prompt:**

```text
You are an expert Software Engineer implementing a single subtask.
You have access to file manipulation and execution tools.

Rules:
1. Focus ONLY on the current subtask.
2. Read files before editing them.
3. Write clean, idiomatic code adhering to project_context rules.
4. Execute verification commands if provided.
5. If a command fails, inspect stdout/stderr and fix the issue immediately.

```

* **Tool Calling Flow:**
* `read_file` -> inspect code.
* `write_file` / `patch_file` -> apply diffs.
* Call `run_command` -> execute test/lint.



### 6.4. Reviewer / Verifier Node (`agents/reviewer.py` + Deterministic Check)

* **First Phase (Deterministic):**
* Chạy `verification_command` từ task definition thông qua sub-process CLI.
* Nếu exit code $\neq 0$: Tự động tăng `retry_count`, gắn `error_log` vào artifact, chuyển state quay lại `executor`.


* **Second Phase (LLM Review):**
* Kiểm tra diff cuối cùng với checklist ban đầu của Planner.
* Trả về status: `APPROVE` hoặc `REJECT (with reason)`.



---

## 7. Concrete Tool Interfaces (`tools/`)

### File Management (`tools/fs_tools.py`)

```python
import os

def read_file(project_root: str, relative_path: str) -> str:
    safe_path = os.path.abspath(os.path.join(project_root, relative_path))
    if not safe_path.startswith(os.path.abspath(project_root)):
        raise PermissionError("Access outside project root is forbidden.")
    with open(safe_path, "r", encoding="utf-8") as f:
        return f.read()

def write_file(project_root: str, relative_path: str, content: str) -> str:
    safe_path = os.path.abspath(os.path.join(project_root, relative_path))
    if not safe_path.startswith(os.path.abspath(project_root)):
        raise PermissionError("Access outside project root is forbidden.")
    os.makedirs(os.path.dirname(safe_path), exist_ok=True)
    with open(safe_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote {len(content)} characters to {relative_path}"

```

### Command Execution (`tools/bash_tools.py`)

```python
import subprocess
import shlex
from typing import Dict, Any

def run_command(project_root: str, command: str, timeout: int = 60) -> Dict[str, Any]:
    # Restrict dangerous commands
    forbidden_tokens = ["rm -rf /", ":(){ :|:& };:", "dd if="]
    if any(token in command for token in forbidden_tokens):
        return {"exit_code": -1, "stdout": "", "stderr": "Command rejected: dangerous operation detected."}

    try:
        process = subprocess.run(
            shlex.split(command),
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "exit_code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout} seconds."}

```

---

## 8. StateGraph Definition (`core/engine.py`)

Codex cần cài đặt workflow theo cấu trúc LangGraph sau:

```python
from langgraph.graph import StateGraph, END
from core.state import AgentGraphState

def build_graph():
    workflow = StateGraph(AgentGraphState)

    # Add Nodes
    workflow.add_node("load_context", context_loader_node)
    workflow.add_node("plan_task", planner_node)
    workflow.add_node("execute_subtask", executor_node)
    workflow.add_node("verify_execution", verifier_node)
    workflow.add_node("reviewer", reviewer_node)

    # Define Edges
    workflow.set_entry_point("load_context")
    workflow.add_edge("load_context", "plan_task")
    workflow.add_edge("plan_task", "execute_subtask")
    workflow.add_edge("execute_subtask", "verify_execution")

    def route_verification(state: AgentGraphState):
        current_artifact = state["artifacts"][-1] if state["artifacts"] else None
        
        # Check if current task execution failed
        if current_artifact and current_artifact.error_log:
            if state["retry_count"] < state["max_retries"]:
                return "execute_subtask"  # Retry current subtask
            return "reviewer"            # Escalate failure
            
        # Check if more tasks remain
        if state["current_task_index"] + 1 < len(state["plan"]):
            state["current_task_index"] += 1
            state["retry_count"] = 0
            return "execute_subtask"

        return "reviewer"

    workflow.add_conditional_edges(
        "verify_execution",
        route_verification,
        {
            "execute_subtask": "execute_subtask",
            "reviewer": "reviewer"
        }
    )

    workflow.add_edge("reviewer", END)
    return workflow.compile()

```

---

## 9. Configuration Template (`config/settings.yaml`)

```yaml
system:
  max_retries_per_task: 3
  default_timeout_seconds: 90
  enforce_json_mode: true

models:
  planner:
    provider: "ollama"
    model_name: "qwen2.5-coder:14b"
    api_base: "http://localhost:11434"
    temperature: 0.1
  executor:
    provider: "ollama"
    model_name: "qwen2.5-coder:7b-instruct"
    api_base: "http://localhost:11434"
    temperature: 0.2
  reviewer:
    provider: "ollama"
    model_name: "qwen2.5-coder:7b-instruct"
    api_base: "http://localhost:11434"
    temperature: 0.0

cloud_fallback:
  enabled: false
  provider: "anthropic"
  model_name: "claude-3-5-sonnet-20241022"
  api_key_env: "ANTHROPIC_API_KEY"

```

---

## 10. Implementation Instructions for Codex

1. **Phase 1: Environment & State Setup**
* Khởi tạo file `requirements.txt`: `langgraph`, `langchain-core`, `litellm`, `pydantic`, `pyyaml`.
* Cài đặt file `core/state.py` theo đúng cấu trúc Pydantic đã định nghĩa tại Mục 5.


2. **Phase 2: Tooling & Security Sandboxing**
* Cài đặt `tools/fs_tools.py` và `tools/bash_tools.py`.
* Đảm bảo mọi thao tác file đều chặn path traversal (`os.path.abspath` kiểm tra tiền tố `project_root`).


3. **Phase 3: LLM Gateway**
* Tạo wrapper `core/llm_gateway.py` sử dụng hàm `litellm.completion`.
* Cấu hình hỗ trợ cờ `response_format={"type": "json_object"}` để đảm bảo tính ổn định của JSON đầu ra từ local models.


4. **Phase 4: Node Logic & Edge Routing**
* Viết logic cho từng node trong `agents/`.
* Cài đặt Graph tại `core/engine.py` và kết nối vòng lặp sửa lỗi tự động (`route_verification`).


5. **Phase 5: CLI Entry Point**
* Trong `main.py`, sử dụng `argparse` nhận 2 tham số: `--project-dir` (bắt buộc) và `--task` (bắt buộc).
* Khởi tạo state ban đầu, chạy Graph và in kết quả/diff trực quan ra terminal.s