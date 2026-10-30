# Kế hoạch hoàn thiện hệ thống multi-agent song song

## 1. Mục tiêu

Nâng runtime hiện tại từ pipeline tuần tự thành một nền tảng điều phối có thể:

- Dùng model mạnh như Claude hoặc Codex làm Supervisor.
- Phân rã yêu cầu thành một DAG gồm các công việc độc lập và phụ thuộc.
- Chạy nhiều worker song song nhưng không ghi đè thay đổi của nhau.
- Dùng worker khác nhau theo loại việc: local LLM, Claude, Codex hoặc model cloud
  qua LiteLLM.
- Lặp lại một task khi verification thất bại, hoặc re-plan khi hướng làm sai.
- Chạy lại công việc định kỳ theo lịch mà không tạo run trùng.
- Stream toàn bộ tiến trình ra CLI và lưu audit log để xem lại.
- Cho phép người dùng phê duyệt plan, hành động rủi ro và bước merge cuối.

## 2. Quyết định kiến trúc cốt lõi

### 2.1. LangGraph là control plane chuẩn

Scheduler do Python/LangGraph quản lý mới là nguồn sự thật về task, dependency,
retry, budget, workspace và kết quả. Không giao toàn bộ quyền điều phối cho một
provider cụ thể.

Claude/Codex có thể đảm nhiệm hai vai trò:

1. `Supervisor`: tạo hoặc sửa DAG và lựa chọn worker phù hợp.
2. `Worker`: thực thi một task được giới hạn rõ ràng.

Provider-native multi-agent là chế độ tăng tốc tùy chọn, không phải kiến trúc duy
nhất. Lý do:

- API multi-agent của từng provider có lifecycle và giới hạn khác nhau.
- Cần chuyển đổi Claude, Codex và local model mà không đổi workflow.
- Scheduler phải kiểm soát xung đột file, budget, approval và audit đồng nhất.
- Tính năng managed agent của provider có thể đang beta hoặc thay đổi.

### 2.2. Model đề xuất, Python quyết định

Supervisor trả về structured output mô tả DAG. Python phải validate trước khi
chạy:

- Task ID duy nhất và dependency không tạo cycle.
- Mỗi task có input, output contract và acceptance criteria.
- Write scope không chồng lấn giữa các task chạy đồng thời.
- Command nằm trong allowlist.
- Số worker, token/cost budget và retry không vượt giới hạn.

Model không trực tiếp quyết định concurrency hoặc bỏ qua policy.

### 2.3. Song song theo dependency và write scope

Chỉ chạy song song khi task:

- Không phụ thuộc output chưa hoàn thành.
- Không cùng ghi vào một file hoặc cùng ownership boundary.
- Không sử dụng resource độc quyền giống nhau.
- Có thể tạo artifact độc lập để merge sau.

Task chỉ đọc có thể dùng chung snapshot. Task sửa code phải dùng Git worktree
riêng hoặc sandbox filesystem riêng.

## 3. Kiến trúc đích

```text
User / Schedule / API
          |
          v
 Intake + Context Snapshot
          |
          v
 Large-model Supervisor (Claude | Codex | configured model)
          |
          v
      Validated Task DAG
          |
          v
 Deterministic Scheduler + Budget + Policy
       /       |        \
      v        v         v
 Worker A   Worker B   Worker C       <- chạy song song
 worktree A worktree B read-only
      \        |         /
       v       v        v
       Result Collector
              |
              v
 Deterministic Verifier per task
       | fail          | pass
       v               v
 Retry / Re-plan   Integration Queue
                         |
                         v
              Conflict Resolver + Tests
                         |
                         v
                 Independent Reviewer
                         |
                         v
               Human Approval / Report
```

## 4. Danh mục agent

Không spawn tất cả agent cho mọi task. Scheduler chỉ tạo agent khi capability đó
cần thiết.

| Agent | Trách nhiệm | Quyền mặc định | Output |
|---|---|---|---|
| Supervisor | Phân rã DAG, chọn profile, re-plan | Đọc context, không sửa file | `TaskGraph` |
| Explorer | Tìm kiến trúc, symbol và dependency | Chỉ đọc | `ResearchArtifact` |
| Architect | Thiết kế interface và ownership | Chỉ đọc | `DesignDecision` |
| Implementer | Sửa code trong scope được cấp | Đọc/ghi worktree, command giới hạn | patch/commit |
| Test agent | Sinh/chạy test, phân tích failure | Ghi test scope, chạy command | `VerificationResult` |
| Reviewer | Review độc lập theo rubric | Chỉ đọc diff và artifact | approve/reject |
| Integrator | Áp patch/cherry-pick theo thứ tự | Ghi integration worktree | integrated commit |
| Conflict resolver | Xử lý conflict được giao | Chỉ file conflict | resolution patch |
| Reporter | Tổng hợp tiến trình và kết quả | Chỉ đọc event/artifact | final report |

Mỗi agent được định nghĩa ngoài source code:

```text
config/agents.yaml
prompts/supervisor.md
prompts/explorer.md
prompts/implementer.md
prompts/tester.md
prompts/reviewer.md
prompts/integrator.md
```

Một agent profile phải có:

```yaml
id: implementer_backend
role: implementer
provider_profile: codex_worker
instructions_file: prompts/implementer.md
allowed_tools: [read_file, patch_file, run_command]
write_globs: [src/backend/**, tests/backend/**]
max_turns: 20
timeout_seconds: 900
max_retries: 2
requires_approval: false
```

## 5. Data model mới

### `TaskSpec`

```text
id
title
description
kind: research | design | implement | test | review | integrate
dependencies[]
target_files[]
read_scope[]
write_scope[]
required_capabilities[]
preferred_worker_profile
acceptance_criteria[]
verification_commands[]
priority
max_attempts
timeout_seconds
status
```

### `TaskAttempt`

```text
attempt_id
task_id
worker_id
provider
model
workspace_id
started_at / finished_at
input_snapshot_hash
artifact_ids[]
command_results[]
token_usage / estimated_cost
failure_class
failure_message
```

### `RunState`

```text
run_id
thread_id
project_snapshot
task_graph
ready_queue
running_tasks
completed_tasks
failed_tasks
integration_queue
budgets
approval_requests
event_sequence
final_status
```

Các collection cập nhật từ node song song phải có reducer rõ ràng theo `task_id`,
không dùng list append mù hoặc last-write-wins.

## 6. Provider abstraction

Tạo interface thống nhất:

```python
class AgentBackend(Protocol):
    async def start(self, request: AgentRequest) -> AgentHandle: ...
    async def events(self, handle: AgentHandle) -> AsyncIterator[AgentEvent]: ...
    async def send(self, handle: AgentHandle, message: str) -> None: ...
    async def cancel(self, handle: AgentHandle) -> None: ...
    async def result(self, handle: AgentHandle) -> AgentResult: ...
```

Các adapter:

### `LiteLLMBackend`

- Dùng cho local Ollama và model API đơn giản.
- Runtime tự quản lý tool loop.
- Phù hợp task nhỏ, phân loại, boilerplate và reviewer rẻ.

### `ClaudeAgentBackend`

- Ưu tiên Claude Agent SDK khi cần coding harness chạy trong process của mình.
- Có thể bổ sung Claude Managed Agents cho session dài và dynamic workflows.
- Chuẩn hóa stream/session/thread của Claude thành `AgentEvent` nội bộ.
- Không để provider tự sửa working tree chính; cấp worktree riêng.

### `CodexBackend`

- Dùng Codex SDK cho start/resume/stream task programmatically, hoặc Agents API
  khi muốn managed Codex harness và native subagents.
- `codex exec` chỉ dùng làm fallback cho CI/job một lần.
- Chuẩn hóa session, subagent event, command và approval thành `AgentEvent`.
- Không xem Codex chỉ là tên model gọi qua LiteLLM; coding harness cần adapter
  lifecycle riêng.

### `MockBackend`

- Backend deterministic cho unit/integration test.
- Giả lập success, timeout, retry, conflict, cancellation và provider outage.

## 7. Task DAG và scheduler song song

Supervisor tạo `TaskGraph`. Scheduler thực hiện:

1. Validate schema và cycle.
2. Tính task sẵn sàng: mọi dependency đã `completed`.
3. Lock `write_scope` và resource cần thiết.
4. Chọn backend theo capability, policy, availability và budget.
5. Fan-out task bằng LangGraph `Send` hoặc parallel branches.
6. Giới hạn concurrency bằng semaphore toàn cục và theo provider.
7. Thu kết quả bằng reducer keyed theo task ID.
8. Release lock rồi mở khóa task phụ thuộc tiếp theo.

Scheduler config đề xuất:

```yaml
scheduler:
  max_parallel_tasks: 4
  max_parallel_writers: 2
  max_parallel_readers: 6
  provider_limits:
    claude: 2
    codex: 2
    ollama: 1
  stop_on_budget_exceeded: true
  stop_on_unresolved_conflict: true
```

Provider-native subagents vẫn phải bị chặn bởi một quota bên ngoài. Một task cha
không được âm thầm tạo số lượng subagent không giới hạn.

## 8. Workspace isolation và tích hợp code

Đây là điều kiện bắt buộc trước khi cho phép nhiều coding agent chạy song song.

### Read-only task

- Dùng cùng commit snapshot.
- Chỉ cấp read/list/search tools.
- Không cần worktree riêng.

### Write task

- Tạo branch và Git worktree: `runs/<run-id>/<task-id>`.
- Worker chỉ được ghi trong write scope của task.
- Worker tạo patch hoặc commit cục bộ, không push.
- Verifier chạy trong chính worktree đó.

### Integration

- Integrator áp commit/patch theo topological order.
- Sau mỗi integration batch, chạy smoke test.
- Nếu conflict: tạo `ConflictTask`, không cho model tự ý bỏ thay đổi.
- Sau khi tích hợp xong, chạy full verification và reviewer độc lập.
- Chỉ cập nhật working tree đích sau human approval hoặc policy cho phép.

Không cho nhiều agent cùng sửa trực tiếp một working tree, kể cả khi provider nói
rằng subagent có thể chia sẻ filesystem.

## 9. Retry, iteration và re-plan

Phân loại failure trước khi lặp:

| Failure | Xử lý |
|---|---|
| Rate limit/network | Retry cùng attempt với exponential backoff |
| Command/test failure có chẩn đoán | Tạo attempt mới, gửi failure context |
| Sai output schema | Repair JSON một lần, sau đó đổi model/escalate |
| Scope violation | Hủy attempt, không áp artifact |
| Conflict | Tạo ConflictTask cho integrator |
| Cách tiếp cận sai | Supervisor re-plan phần DAG chưa hoàn thành |
| Provider outage | Chuyển backend nếu policy cho phép |
| Budget/retry hết | Dừng an toàn và yêu cầu người dùng |

Giới hạn bắt buộc:

- `max_attempts` mỗi task.
- `max_replans` mỗi run.
- `max_graph_steps`.
- Token/cost/time budget theo run và provider.
- Phát hiện failure fingerprint lặp lại để không sửa cùng một lỗi vô hạn.

Mỗi attempt chỉ nhận context cần thiết: TaskSpec, dependency artifacts, file scope,
failure mới nhất và acceptance criteria. Không truyền toàn bộ lịch sử cho mọi
worker.

## 10. Công việc lặp lại theo lịch

Phân biệt hai loại lặp:

1. `Retry loop`: xảy ra trong một run do task chưa đạt.
2. `Scheduled job`: tạo run mới theo cron hoặc sự kiện repository.

Thêm bảng/job model:

```text
JobDefinition: job_id, project, task_template, schedule, policy, enabled
JobRun: job_run_id, job_id, scheduled_for, run_id, status, idempotency_key
```

Quy tắc:

- Unique key `(job_id, scheduled_for)` ngăn chạy trùng.
- Dùng lease có expiry để một job chỉ có một worker sở hữu.
- Không chạy job mới nếu job cũ còn hoạt động, trừ khi policy cho phép overlap.
- Mỗi scheduled run phải pin commit SHA đầu vào.
- Mặc định chỉ tạo branch/report; không tự merge hoặc push.

Giai đoạn đầu dùng scheduler nội bộ/cron gọi CLI. Khi cần nhiều máy mới chuyển
sang queue như Redis + worker service.

## 11. Observability

Tất cả backend phát event theo schema chung:

```text
run.created
plan.created / plan.revised
task.queued / task.started / task.completed / task.failed
agent.started / agent.message / agent.stopped
tool.started / tool.completed / tool.failed
command.started / command.completed
verification.completed
artifact.created
approval.requested / approval.resolved
integration.started / integration.conflict / integration.completed
run.completed / run.failed / run.cancelled
```

Ba output song song:

1. CLI streaming: tiến trình dễ đọc, `--verbose` để thấy tool/command.
2. Local audit: JSONL và SQLite, luôn bật, có `run_id` và sequence number.
3. LangSmith/provider tracing: tùy chọn, có redaction và opt-in rõ ràng.

CLI cần thêm:

```text
--supervisor claude|codex|litellm
--max-parallel N
--approve-plan
--approval-policy safe|balanced|strict
--stream
--verbose
--log-file PATH
--resume RUN_ID
--cancel RUN_ID
--dry-run
```

Không ghi secret, API key, nội dung `.env` hoặc file bị deny vào trace cloud.

## 12. Human-in-the-loop và an toàn

Các checkpoint đề xuất:

- Phê duyệt plan trước khi sửa file khi dùng `--approve-plan`.
- Phê duyệt lệnh ngoài safe allowlist.
- Phê duyệt network/write external system.
- Phê duyệt conflict resolution có thay đổi hành vi.
- Phê duyệt integration cuối.

Tool policy theo capability, không chỉ theo tên executable:

```text
filesystem.read
filesystem.write_scoped
command.test
command.build
command.package_install
network.read
git.commit_local
git.push              # mặc định deny
external.write        # mặc định deny
```

Command phải chạy trong sandbox/container hoặc worktree với timeout, output limit,
environment allowlist và process-tree termination.

## 13. Workflow LangGraph đích

```text
START
  -> intake
  -> snapshot_context
  -> supervisor_plan
  -> validate_plan
  -> optional_plan_approval
  -> schedule_ready
  -> [worker_task x N in parallel]
  -> collect_results
  -> verify_results
       -> retry_task -> schedule_ready
       -> replan -> supervisor_plan
       -> integrate
  -> integration_verify
       -> conflict_task -> schedule_ready
       -> reviewer
  -> optional_final_approval
  -> report
  -> END
```

Persistence dùng SQLite trong chế độ local và PostgreSQL khi chạy service. Mọi
side effect phải có idempotency key vì node có thể chạy lại sau resume.

## 14. Các phase triển khai

### Phase 0 — Chốt contract và baseline

- Viết ADR cho scheduler trung lập, provider adapter và Git worktree.
- Chụp baseline test của runtime hiện tại.
- Chốt event schema, TaskSpec và RunState trước khi sửa graph.

Nghiệm thu: schema validate được, có fixture DAG hợp lệ/cycle/conflict.

### Phase 1 — Externalize agent rules

- Tạo `config/agents.yaml` và thư mục `prompts/`.
- Loader validate profile, tool capability và prompt file.
- Thêm template rule cho project đích.

Nghiệm thu: đổi model/prompt/tool policy mà không sửa Python.

### Phase 2 — Event bus và streaming

- Thay `invoke()` bằng `stream()`/`astream()`.
- Tạo `EventSink`: console, JSONL, SQLite.
- Instrument model, tool, command, verifier và reviewer.
- Thêm run ID, correlation ID và redaction.

Nghiệm thu: nhìn thấy node/task/tool/retry theo thời gian thực và replay được log.

### Phase 3 — DAG scheduler song song

- Thay plan tuyến tính bằng `TaskGraph`.
- Implement ready queue, dependency resolution, reducers và semaphore.
- Fan-out bằng LangGraph dynamic `Send`.
- Dùng MockBackend để test concurrency deterministic.

Nghiệm thu: task độc lập chạy đồng thời; task phụ thuộc chỉ chạy sau dependency;
không vượt concurrency limit.

### Phase 4 — Workspace isolation

- Workspace manager tạo/thu hồi Git worktree.
- Lock read/write scope.
- Artifact store cho patch, commit, command output.
- Integration queue và conflict task.

Nghiệm thu: hai worker sửa hai scope độc lập và merge thành công; overlapping
scope không chạy đồng thời; conflict không làm mất code.

### Phase 5 — Provider backends

- Giữ LiteLLMBackend cho Ollama và model API thường.
- Tích hợp Claude Agent SDK trước, stream event và cancellation.
- Tích hợp Codex SDK hoặc Agents API, stream subagent/command/approval event.
- Capability discovery và fallback policy.

Nghiệm thu: cùng một TaskSpec chạy được trên mock, Ollama, Claude và Codex mà
scheduler không đổi.

### Phase 6 — Retry, re-plan và budgets

- Failure classifier và fingerprint.
- Retry/backoff, model escalation, partial re-plan.
- Token/cost/time/attempt budgets.
- Circuit breaker theo provider.

Nghiệm thu: không có vòng lặp vô hạn; outage chuyển provider đúng policy; budget
hết thì dừng với state có thể resume.

### Phase 7 — Human approval và persistence

- Interrupt/resume cho plan, command và integration approval.
- SQLite checkpointer và run registry.
- CLI `resume`, `cancel`, `inspect`.

Nghiệm thu: kill process giữa run rồi resume không lặp side effect đã hoàn tất.

### Phase 8 — Scheduled jobs

- Job definition, idempotency key và lease.
- CLI/service runner cho cron/event.
- Chính sách overlap và pinned commit SHA.

Nghiệm thu: cùng một lịch không tạo duplicate run; job lỗi không chặn job khác.

### Phase 9 — Evals và production hardening

- Bộ benchmark task nhỏ/vừa/lớn.
- Eval planner quality, success rate, retry count, conflict rate, latency, cost.
- Chaos test timeout, malformed output, provider outage và process crash.
- Security test traversal, symlink, command escape, secret redaction.
- Tài liệu vận hành, backup và cleanup worktree/artifact.

Nghiệm thu: đạt SLO nội bộ đã định nghĩa và có báo cáo regression giữa model.

## 15. Test matrix bắt buộc

- Unit: schema, DAG validation, lock, reducers, retry, budget, redaction.
- Graph: fan-out/fan-in, re-plan, interrupt/resume, recursion exhaustion.
- Workspace: branch/worktree lifecycle, patch, conflict, cleanup.
- Provider contract: fake stream cho Claude/Codex/LiteLLM.
- Integration: hai task song song sửa hai module và full test sau merge.
- Failure: timeout, cancellation, rate limit, invalid JSON, duplicate event.
- Security: traversal, symlink escape, forbidden command, leaked secret.
- E2E: clone fixture repo, plan, parallel implement, verify, review, report.

Không dùng provider thật trong unit test. Provider live test chạy riêng, có budget
và opt-in.

## 16. Definition of done

Hệ thống chỉ được coi là hoàn thiện khi:

- Supervisor có thể tạo DAG hợp lệ và re-plan phần chưa hoàn thành.
- Ít nhất hai coding worker chạy song song trong worktree cô lập.
- Claude và Codex đều có adapter programmatic, stream/cancel/result đầy đủ.
- Không có hai writer giữ lock scope chồng lấn.
- Retry và recurring job đều idempotent, có giới hạn rõ ràng.
- Run có thể pause/resume sau process restart.
- Người dùng quan sát được agent, task, tool, command, cost và artifact theo live
  stream và audit log.
- Reviewer độc lập không dùng cùng context mù với implementer.
- Không tự push/merge hoặc chạy hành động rủi ro khi chưa có policy/approval.
- Toàn bộ acceptance test và security test vượt qua.

## 17. Thứ tự MVP khuyến nghị

Không tích hợp Claude/Codex ngay từ đầu. Thứ tự giảm rủi ro:

1. Agent profiles và event stream.
2. Task DAG + MockBackend song song.
3. Git worktree isolation + integrator.
4. Retry/re-plan/budget.
5. Claude adapter.
6. Codex adapter.
7. Persistence + approval.
8. Scheduled jobs và production hardening.

Nếu scheduler và isolation chưa đúng, việc thêm model mạnh chỉ khiến lỗi xảy ra
nhanh hơn và tốn chi phí hơn.

## 18. Tài liệu tham chiếu chính thức

- OpenAI Agents API multi-agent:
  https://developers.openai.com/api/docs/guides/agents-api/multi-agent
- OpenAI agent orchestration/handoffs:
  https://developers.openai.com/api/docs/guides/agents/orchestration
- Codex integration layers:
  https://developers.openai.com/blog/codex-as-a-platform
- Claude multiagent orchestration:
  https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration
- Claude dynamic workflow cookbook:
  https://platform.claude.com/cookbook/claude-agent-sdk-08-dynamic-workflows
- LangGraph graph API, parallel branches và `Send`:
  https://langchain-ai.github.io/langgraph/how-tos/multi-agent-network/
