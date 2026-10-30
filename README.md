# Local Parallel Multi-Agent Runtime

Python runtime điều phối một quy trình phát triển phần mềm gồm: nạp context,
lập kế hoạch DAG, chạy worker song song, kiểm thử xác định và review chất lượng.
Toàn bộ model chạy cục bộ qua Ollama/vLLM; runtime chủ động từ chối provider hoặc
endpoint cloud.

- [Hướng dẫn sử dụng đầy đủ](docs/USAGE.md)
- [Bản kế hoạch kiến trúc ban đầu](docs/initial-architecture-plan.md)
- [Kế hoạch hoàn thiện multi-agent song song](docs/full-implementation-plan.md)

## Yêu cầu

- Python 3.11+
- Ollama đang chạy tại `http://localhost:11434`
- Các model trong `config/settings.yaml` đã được pull

## Cài đặt

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:7b-instruct
```

Chỉnh model, concurrency và timeout trong `config/settings.yaml`; chỉnh allowlist
lệnh trong `config/tools.yaml`; chỉnh vai trò/prompt trong `config/agents.yaml`
và `prompts/`.

## Sử dụng

Runtime và project đích nên được clone thành hai thư mục riêng. Runtime chỉ sửa
thư mục được truyền qua `--project-dir`.

```bash
.venv/bin/python main.py \
  --project-dir /absolute/path/to/project \
  --task "Thêm endpoint health check và unit test" \
  --max-parallel 4 --verbose
```

Trong project đích, có thể tạo `project_context.md` hoặc `.agent-rules` để mô tả
quy ước kiến trúc, lệnh test và giới hạn thay đổi. CLI in trạng thái từng subtask,
các file đã chạm, `git status`/`git diff` (nếu project dùng Git) và kết quả review
cuối cùng; exit code là `0` khi được duyệt.

Xem [docs/USAGE.md](docs/USAGE.md) để biết toàn bộ quy trình từ clone, chuẩn bị
project, viết rules, chạy task, kiểm tra diff đến commit kết quả.

## An toàn

- Mọi file path được resolve và kiểm tra nằm trong project root.
- Lệnh chạy bằng argument list (`shell=False`) và executable phải có trong allowlist.
- Mỗi task và mỗi vòng review đều có retry budget; graph có recursion limit.
- Tool không cung cấp thao tác xóa file.
- Coding worker dùng Git worktree riêng; chỉ patch đã verify và review mới được áp.
- Event và checkpoint lưu cục bộ trong `.runtime/state.db`.

## Kiểm thử

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Các test kiểm tra DAG/concurrency, Git worktree integration, vòng đời file, path
traversal và command allowlist.
