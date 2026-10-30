# Hybrid Local/Cloud Multi-Agent Runtime

Python runtime điều phối một quy trình phát triển phần mềm gồm: nạp context,
lập kế hoạch, thực thi bằng tool, kiểm thử xác định và review chất lượng. Model
được gọi qua LiteLLM nên có thể dùng Ollama cục bộ hoặc cloud fallback.

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

Chỉnh model, timeout và fallback trong `config/settings.yaml`. Chỉnh allowlist
lệnh trong `config/tools.yaml`. Cloud fallback chỉ được dùng khi bật `enabled`
và biến môi trường API key tương ứng đã tồn tại.

## Sử dụng

```bash
.venv/bin/python main.py \
  --project-dir /absolute/path/to/project \
  --task "Thêm endpoint health check và unit test"
```

Trong project đích, có thể tạo `project_context.md` hoặc `.agent-rules` để mô tả
quy ước kiến trúc, lệnh test và giới hạn thay đổi. CLI in trạng thái từng subtask,
các file đã chạm, `git status`/`git diff` (nếu project dùng Git) và kết quả review
cuối cùng; exit code là `0` khi được duyệt.

## An toàn

- Mọi file path được resolve và kiểm tra nằm trong project root.
- Lệnh chạy bằng argument list (`shell=False`) và executable phải có trong allowlist.
- Mỗi task và mỗi vòng review đều có retry budget; graph có recursion limit.
- Tool không cung cấp thao tác xóa file.

## Kiểm thử

```bash
python3 -m unittest discover -s tests -v
```

Các test hiện tại kiểm tra vòng đời file, path traversal, lỗi prefix path và
command allowlist.
