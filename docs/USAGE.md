# Hướng dẫn sử dụng end-to-end

Runtime này là một công cụ độc lập. Không cần copy mã nguồn runtime vào từng dự
án. Cách dễ quản lý nhất là đặt runtime và các project đích cạnh nhau:

```text
workspace/
├── multi-agent-system/     # runtime điều phối agent
└── my-application/         # project mà agent sẽ sửa
```

## 1. Cài runtime một lần

Clone repo runtime, tạo môi trường Python và cài dependency:

```bash
mkdir -p ~/workspace
cd ~/workspace
git clone <URL_CUA_MULTI_AGENT_SYSTEM> multi-agent-system
cd multi-agent-system
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Dùng model local qua Ollama

Cài và khởi động Ollama theo hệ điều hành, sau đó pull các model mặc định:

```bash
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:7b-instruct
ollama list
```

Runtime mặc định kết nối `http://localhost:11434`. Có thể đổi model, endpoint,
temperature và timeout trong `config/settings.yaml`.

Runtime chạy ở chế độ `local_only`. Provider phải là `ollama` hoặc `vllm` và
endpoint phải là loopback (`localhost`, `127.0.0.1` hoặc `::1`). Không cần API key
và không có cloud fallback.

## 2. Clone và chuẩn bị project đích

Clone project cần làm việc ở một thư mục khác:

```bash
cd ~/workspace
git clone <URL_CUA_PROJECT> my-application
cd my-application
git switch -c agent/add-health-check
git status --short
```

Nên bắt đầu từ working tree sạch. Agent không tự commit và không tự push; mọi
thay đổi chỉ nằm trong working tree để người dùng review.

Cài dependency của chính project đích trước. Ví dụ với Python:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Hoặc với Node.js:

```bash
npm install
```

Nếu project dùng lệnh chưa có trong `multi-agent-system/config/tools.yaml`, thêm
executable đó vào `commands.allowed_executables` trước khi chạy.

## 3. Khai báo quy ước project

Tại root của project đích, nên tạo `project_context.md`. Runtime cũng nhận
`.agent-rules`, nhưng nếu cả hai tồn tại thì `project_context.md` được ưu tiên.

Ví dụ:

```markdown
# Project context

- Backend dùng Python 3.12, FastAPI và SQLAlchemy 2.
- Source code nằm trong `src/`; test nằm trong `tests/`.
- Không sửa migration cũ. Migration mới đặt trong `migrations/versions/`.
- Mọi endpoint mới phải có unit test.
- Chạy test: `pytest -q`.
- Chạy lint: `ruff check .`.
- Không thay đổi public API ngoài phạm vi task.
```

File này nên được commit vào project nếu quy tắc áp dụng cho cả đội. Nếu không có
file rules, runtime vẫn quét cây thư mục và dùng các quy tắc an toàn mặc định.

## 4. Chạy một task

Đứng tại repo runtime và truyền đường dẫn tuyệt đối của project đích:

```bash
cd ~/workspace/multi-agent-system
.venv/bin/python main.py \
  --project-dir ~/workspace/my-application \
  --task "Thêm endpoint GET /health trả về status và version; bổ sung unit test" \
  --max-parallel 4 --verbose
```

Nên mô tả một outcome rõ ràng trong mỗi lần chạy: hành vi cần có, phạm vi được
phép sửa và tiêu chí kiểm thử. Task quá lớn nên chia thành nhiều lần chạy để diff
dễ review và model local làm việc ổn định hơn.

Luồng xử lý thực tế:

1. `Context Loader` đọc rules và quét cấu trúc project.
2. `Supervisor` tạo DAG có dependency và write scope.
3. Scheduler fan-out các task độc lập; mỗi writer dùng Git worktree riêng.
4. Worker sửa file, chạy verification và retry trong budget.
5. Integrator cherry-pick kết quả đã đạt vào integration worktree.
6. Reviewer đối chiếu request, DAG và artifact; feedback có thể tạo vòng sửa lại.
7. Patch cuối được áp vào working tree chính và CLI in báo cáo.

Tiến trình/checkpoint được lưu trong `.runtime/state.db`. Xem lại một run:

```bash
.venv/bin/python inspect_run.py <RUN_ID>
```

Nếu process dừng giữa run, tiếp tục từ SQLite checkpoint:

```bash
.venv/bin/python main.py --resume <RUN_ID>
```

CLI trả exit code `0` khi reviewer duyệt và `1` khi task thất bại hoặc bị từ chối.

## 5. Review và nhận thay đổi

Sau khi runtime kết thúc, quay về project đích:

```bash
cd ~/workspace/my-application
git status --short
git diff
pytest -q
```

Thay `pytest -q` bằng bộ lint/test chuẩn của project. Nếu kết quả đạt yêu cầu,
commit theo workflow thông thường của đội:

```bash
git add <cac-file-da-review>
git commit -m "feat: add health endpoint"
git push -u origin agent/add-health-check
```

Agent không sở hữu bước review cuối, commit hoặc push. Người dùng quyết định giữ,
chỉnh thêm hay bỏ thay đổi dựa trên diff và test thực tế.

## 6. Ví dụ cấu hình theo project

Nếu một project cần timeout hoặc model khác, copy settings thay vì sửa cấu hình
chung:

```bash
cp config/settings.yaml config/settings.my-application.yaml
```

Chỉnh file copy rồi chạy:

```bash
.venv/bin/python main.py \
  --settings config/settings.my-application.yaml \
  --project-dir ~/workspace/my-application \
  --task "Sửa lỗi phân trang và thêm regression test"
```

Không trỏ cấu hình local-only tới endpoint bên ngoài.

## 7. Job lặp lại

Đăng ký job và gọi bằng cron hoặc systemd timer:

```bash
.venv/bin/python jobs.py add --id nightly-tests \
  --project-dir ~/workspace/my-application \
  --task "Chạy test, sửa regression có thể tái hiện và bổ sung test" \
  --schedule "0 2 * * *"

.venv/bin/python jobs.py run --id nightly-tests
```

Khóa `(job_id, scheduled_for)` trong SQLite ngăn cùng một lịch chạy hai lần.

## 8. Xử lý lỗi thường gặp

- `LiteLLM is not installed`: chạy `.venv/bin/pip install -r requirements.txt`
  trong repo runtime.
- Không kết nối được Ollama: kiểm tra Ollama đang chạy, `ollama list`, endpoint và
  tên model trong `config/settings.yaml`.
- `executable ... is not allowed`: bổ sung executable hợp lệ vào
  `config/tools.yaml`; không bật rộng các shell như `sh` hoặc `bash`.
- Verification lặp lại: chạy chính command đó bằng tay trong project đích, kiểm
  tra dependency và cập nhật `project_context.md` để chỉ rõ lệnh đúng.
- Context quá lớn: giảm `context_max_depth`/`context_max_files`, hoặc bổ sung thư
  mục generated vào `filesystem.ignored_directories`.
- Working tree đã có thay đổi: commit hoặc stash trước; worktree isolation yêu cầu
  project Git sạch.

## 9. Cập nhật runtime

Khi muốn lấy phiên bản mới của công cụ:

```bash
cd ~/workspace/multi-agent-system
git pull
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Project đích không cần thay đổi khi runtime được cập nhật.
