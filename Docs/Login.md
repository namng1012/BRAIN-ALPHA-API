# Đăng nhập WorldQuant BRAIN API

Ghi lại toàn bộ kỹ thuật đăng nhập vào BRAIN platform, dựa trên `Functions/login.py` hiện tại.

## 0. Cấu trúc code

```
Brain-Alpha-API/
├── main.py                    # entry point, gọi BrainLogin
├── Functions/
│   ├── __init__.py
│   └── login.py               # class BrainLogin — toàn bộ logic đăng nhập
└── .brain/                    # runtime state
    ├── session.json           # cache cookie (JWT)
    └── persona_url.txt        # link xác minh persona (tạm, xoá khi login OK)
```

`BrainLogin` là class có state (`base_url`, `state_dir`, các path), nên các method là **instance method** — không dùng global.

| Method | Việc |
|---|---|
| `credentials()` | đọc `[email, password]` từ `.env` |
| `check_login(s)` | số giây còn lại của session, `0` = chết |
| `save_session(s)` / `load_session()` | ghi/đọc cookie cache |
| `start_session(email, password)` | POST `/authentication` + xử lý persona |
| `get_session()` | entry point: cache còn sống → tái dùng, không thì login mới |
| `get_token(s)` | trả JWT (cookie `t`) |

## 1. Tổng quan

BRAIN không dùng API key. Auth dựa trên **session cookie** (JWT) + **Persona biometric verification**.

| Khái niệm | Giá trị |
|---|---|
| Base URL | `https://api.worldquantbrain.com` (override qua env `BRAIN_API_URL`) |
| Endpoint login | `POST /authentication` |
| Endpoint check | `GET /authentication` → `{"token": {"expiry": <unix ts>}}` |
| Endpoint persona | `POST /authentication/persona?inquiry=inq_XXX` |
| JWT | session cookie tên `t` |
| File cache | `.brain/session.json` |
| File link persona | `.brain/persona_url.txt` |

## 2. Luồng xác thực

```
POST /authentication
   │
   ├─ 200 ──────────────────────────► đã có JWT, trả cookie "t"
   │
   └─ 401 + WWW-Authenticate: persona
          │
          ├─ Location: /authentication/persona?inquiry=inq_XXX
          │     → in ra terminal + ghi vào .brain/persona_url.txt
          │
          └─ poll POST /authentication/persona?inquiry=inq_XXX
                 ├─ 201 ──► xác minh thành công, server set cookie "t"
                 └─ khác ─► chờ rồi thử lại
```

**Điểm mấu chốt:** `401` + header `WWW-Authenticate: persona` là tín hiệu bắt buộc phải xác minh sinh trắc học. Nếu `WWW-Authenticate` khác `persona` → sai email/password.

## 3. Persona là gì

Persona là dịch vụ xác minh danh tính của WorldQuant. Mỗi lần login là một **`inquiry`** (phiên xác minh) riêng với id dạng `inq_XXX`.

- Bắt buộc làm **thủ công trên trình duyệt**: chụp mặt / giọng nói, v.v.
- Không tự động hoá được — đây là bản chất bảo mật, không phải hạn chế kỹ thuật.
- Nhưng **phần chờ** (poll server) thì tự động hoá được.

## 4. Các kỹ thuật đã dùng

### 4.1 Poll server thay vì chờ Enter

Bản gốc (từ `ace_lib.py`) dùng `input()` để chờ người dùng bấm Enter, rồi mới hỏi server. Điều này buộc phải quay lại terminal.

Bản hiện tại poll tự động:

```python
deadline = time.monotonic() + PERSONA_TIMEOUT_SECONDS
while True:
    if s.post(inquiry_url).status_code == 201:
        break
    if time.monotonic() > deadline:
        print("\nBiometrics authentication timed out ...")
        return None
    time.sleep(PERSONA_POLL_INTERVAL_SECONDS)
```

- `PERSONA_POLL_INTERVAL_SECONDS = 5` — nhịp hỏi server
- `PERSONA_TIMEOUT_SECONDS = 600` — bỏ sau 10 phút
- Dùng `time.monotonic()` chứ không phải `time.time()`: monotonic không bị ảnh hưởng bởi đổi đồng hồ hệ thống (NTP sync, đổi múi giờ).

### 4.2 Link persona lưu ra file

Khi script chạy detached (nohup / systemd / cron) thì `print` có thể không hiện ra terminal đang nhìn. Nên link được ghi song song vào `.brain/persona_url.txt`:

```python
self.persona_url_path.write_text(inquiry_url + "\n")
print(..., flush=True)
```

`flush=True` ép flush buffer ngay để output không bị đẩy lên khi process kết thúc.

File được xoá khi login thành công (`self.persona_url_path.unlink(missing_ok=True)`) để không đọc nhầm link cũ.

### 4.3 Cache session để không login lại mỗi lần chạy

`.brain/session.json` lưu toàn bộ cookie (name/value/domain/path):

```python
json.dumps([{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in s.cookies])
```

Lần sau `load_session()` dựng lại `requests.Session` từ cookie cache.

### 4.4 Ngưỡng re-login trước khi session chết

`RELOGIN_THRESHOLD_SECONDS = 1000` (~17 phút): session còn sống ≥ ngưỡng này thì tái dùng, ngược lại login mới.

Logic: re-auth **trước khi** session chết, chứ không phải sau — để không bao giờ gặp session chết giữa lúc chạy (giống `ace_lib.check_session_and_relogin`).

`ace_lib.check_session_and_relogin` dùng 2000s. Ngưỡng của dự án là **1000s** — thấp hơn, để giảm số lần login (giới hạn 5 lần/phút và 25 lần/ngày) trong khi vẫn giữ ≥ 17 phút đệm cho một lần chạy.

`check_login()` bắt lỗi trả về `0` = coi như hết hạn → login lại.

### 4.5 `s.auth = (email, password)`

`requests` gửi HTTP Basic Auth header. Ở bước POST `/authentication` đầu tiên, server dùng header này để biết *ai* đang xin xác minh, rồi mới trả về `inquiry` tương ứng.

## 5. Credentials

`.env`:

```
BRAIN_CREDENTIALS=["email@example.com","password"]
```

Đọc bằng `json.loads(os.environ["BRAIN_CREDENTIALS"])` — dạng JSON array để password chứa ký tự đặc biệt (`"`, `,`) không vỡ.

> `.env` chứa credential thật → **không commit**. Folder `.brain/` cũng phải gitignore (chứa cookie + link xác minh).

## 6. Cách dùng thực tế

### 6.1 Chạy thường

```bash
uv run main.py
```

Cache còn sống → in `Reusing cached session, valid for <n>s`. Hết hạn → in link persona, chờ xác minh.

### 6.2 Case SSH: máy A chạy code, máy B xác minh

**Cách 1 — copy link trực tiếp:**
```bash
# trên A
ssh user@machine-A
cd ~/Brain-Alpha-API && uv run main.py
# copy link → mở trên trình duyệt máy B
```

**Cách 2 — chạy detached, đọc link từ file:**
```bash
# trên A
nohup uv run main.py > login.log 2>&1 &
sleep 5
cat .brain/persona_url.txt     # copy link này sang máy B
```

**Cách 3 — theo dõi log real-time:**
```bash
# trên B
ssh user@machine-A 'tail -f ~/Brain-Alpha-API/login.log'
```

Cả 3 cách đều chỉ cần **mở link trên máy B**; script tự hoàn tất sau khi xác minh.

## 7. Kiểm tra session đã sống chưa

```bash
uv run python -c "
from Functions.login import BrainLogin
login = BrainLogin()
s = login.load_session()
print(login.check_login(s), 'seconds left')
"
```

## 8. Lỗi thường gặp

| Triệu chứng | Nguyên nhân |
|---|---|
| `Incorrect email or password` | `401` mà `WWW-Authenticate` ≠ `persona` → sai credential |
| `Biometrics authentication timed out` | Xác minh persona chưa hoàn tất trong 10 phút |
| Persona từ chối | Ảnh/giọng không đạt chuẩn → làm lại inquiry mới |
| `401` khi gọi API dù cache còn "sống" | Session bị server revoke → xoá `.brain/session.json` rồi chạy lại |

## 9. Ghi chú lịch sử

- `Functions/login.py` là bản rút gọn từ `ACE_API__Gold_/ace_lib.py`: thay logic `input()` bằng poll + timeout, bổ sung cơ chế lưu link persona ra file cho môi trường SSH, và gom toàn bộ vào class `BrainLogin`.
- `main.py` chỉ còn là entry point mỏng.
