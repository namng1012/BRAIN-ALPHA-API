# `ace_lib.py` — thư viện điều khiển WorldQuant BRAIN API

**Nguồn:** `ACE_API__Gold_/ace_lib.py` (1422 dòng, reference code, chỉ đọc — xem `.cursor/rules/16-reference-code-readonly.mdc`).

Tài liệu này ghi lại **toàn bộ hiểu biết** về file: mục đích từng hàm, luồng điều khiển, hợp đồng API, và những điểm phải biết trước khi dùng làm nguồn tham khảo cho code mới.

---

## 1. Tổng quan

`ace_lib.py` là client HTTP cho WorldQuant BRAIN API. Nó lo 4 việc:

1. **Quản lý session** — đăng nhập, xử lý biometric auth, theo dõi hạn token, đăng nhập lại.
2. **Mô tả alpha** — dựng payload simulation (REGULAR hoặc SUPER).
3. **Chạy simulation** — gửi, chờ, thu kết quả; chạy song song nhiều alpha.
4. **Đánh giá alpha** — lấy IS stats, PnL, yearly stats, kiểm tra submission, self-correlation, prod-correlation.

### 1.1 Hằng số và kiểu dữ liệu module

| Tên | Giá trị | Ý nghĩa |
| --- | --- | --- |
| `DEV` | `False` | Khi `True`, logger ghi file `ace.log` ở mức `DEBUG` |
| `_UNSET` | `object()` | Sentinel phân biệt "không truyền" với "truyền `None`" (xoá thuộc tính) |
| `Category` | `Optional[Literal[...]]` | 8 category alpha hợp lệ: `PRICE_REVERSION`, `PRICE_MOMENTUM`, `VOLUME`, `FUNDAMENTAL`, `ANALYST`, `PRICE_VOLUME`, `RELATION`, `SENTIMENT` |
| `DEFAULT_CONFIG` | dict 8 khoá tất cả `False` | Cấu hình mặc định cho `get_specified_alpha_stats`: không lấy PnL, không lấy stats, không lưu file, không check correlation |
| `brain_api_url` | env `BRAIN_API_URL` hoặc `https://api.worldquantbrain.com` | Base URL của platform |
| `logger` | `setup_logger()` | Logger tên `"ace"`, format `%(asctime)s - %(name)s - %(levelname)s - %(message)s` |

### 1.2 Phụ thuộc ngoài

`requests`, `pandas`, `tqdm`, và `helpful_functions` (cùng folder): `expand_dict_columns`, `save_pnl`, `save_simulation_result`, `save_yearly_stats`.

`helpful_functions.py` gồm 4 hàm:

| Hàm | Việc |
| --- | --- |
| `expand_dict_columns(data)` | Tách các cột chứa dict thành nhiều cột, đặt tên `{col}_{key}` |
| `save_simulation_result(result)` | Ghi JSON kết quả simulation vào `simulation_results/{alpha_id}_{region}` |
| `save_pnl(pnl_df, alpha_id, region)` | Ghi CSV PnL vào `alphas_pnl/{alpha_id}_{region}.csv` |
| `save_yearly_stats(yearly_stats, alpha_id, region)` | Ghi CSV yearly stats vào `yearly_stats/{alpha_id}_{region}.csv` |

---

## 2. `class SingleSession(requests.Session)` — dòng 42

Session HTTP singleton, mở rộng `requests.Session`. Ba lý do cho mẫu singleton:

- Cookie và token của BRAIN gắn vào session, nên phải dùng **một** session cho cả run.
- `ThreadPool` chạy song song các request; `requests.Session` không thread-safe nếu mỗi thread tạo session riêng, và việc đăng nhập lại giữa chừng sẽ phá session của các thread khác.
- `__init__` chạy một lần duy nhất (`_initialized`), còn `__new__` giữ singleton (`_instance`).

Ba lock phục vụ ba mục đích khác nhau:

| Lock | Bảo vệ |
| --- | --- |
| `_lock` | Việc tạo instance (`__new__`) — double-checked locking |
| `_relogin_lock` | Việc đăng nhập lại, để hai thread không cùng lúc đăng nhập lại |
| `_initialized` | Không chạy lại `requests.Session.__init__` |

### 2.1 `__new__(cls, *args, **kwargs)` — dòng 48

**Mục đích:** trả về instance duy nhất của `SingleSession`, tạo nó nếu chưa có.

Cơ chế double-checked locking: kiểm tra `_instance` ở ngoài lock (đường nhanh, không phải chờ), nếu `None` thì mới vào `_lock` và kiểm tra lại (trường hợp hai thread cùng tới lúc đầu). Nếu không có lock này, hai thread có thể cùng tạo instance và một session bị mất.

### 2.2 `__init__(self, *args, **kwargs)` — dòng 55

**Mục đích:** khởi tạo `requests.Session` đúng một lần.

`_initialized` chặn việc `__init__` chạy lại: `SingleSession()` được gọi nhiều lần trong run (mỗi lần `start_session`), và `requests.Session.__init__` sẽ reset lại adapters và cookies nếu chạy lại — tức là xoá session đã đăng nhập.

### 2.3 `get_relogin_lock(self)` — dòng 60

**Mục đích:** trả về `_relogin_lock` để `check_session_and_relogin` dùng.

Đây là cách duy nhất để `check_session_and_relogin` (hàm top-level) điều phối được với các thread khác, vì `threading.Lock` không thể truy cập từ ngoài class mà không phá encapsulation.

---

## 3. Hằng số và cấu hình

### 3.1 `setup_logger() -> logging.Logger` — dòng 64

**Mục đích:** tạo và trả về logger ghi ra console (và file `ace.log` nếu `DEV=True`).

Cấu hình:
- Tên logger `"ace"`.
- Mức `DEBUG` nếu `DEV` không còn là `False`, ngược lại `INFO`.
- Console handler ở cùng mức.
- File handler luôn ở `DEBUG`, ghi vào `ace.log` ở thư mục hiện tại — dù `DEV=False`, file vẫn ghi mọi thứ ở mức DEBUG.
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`.

Gọi một lần ở import: `logger = setup_logger()` (dòng 97).

**Điểm cần biết:** `setup_logger` gọi `logger.addHandler` mỗi lần chạy. Nếu hàm được gọi lại (ví dụ trong test hoặc reload module), handler sẽ nhân bản và mỗi dòng log bị in nhiều lần. Trong file này nó chỉ chạy một lên nên không xảy ra.

### 3.2 `DEFAULT_CONFIG` — dòng 100

Dict 8 khoá tất cả `False`: `get_pnl`, `get_stats`, `save_pnl_file`, `save_stats_file`, `save_result_file`, `check_submission`, `check_self_corr`, `check_prod_corr`.

Đây là cấu hình mặc định cho `simulate_alpha_list` và `simulate_alpha_list_multi`. Nghĩa là mặc định **không** tải PnL, **không** kiểm tra correlation. Mỗi request tới platform đều tốn quota, nên việc bật các khoá này là quyết định có chủ ý.

---

## 4. Xác thực và session

### 4.1 `get_credentials() -> tuple[str, str]` — dòng 114

**Mục đích:** lấy email và mật khẩu platform, ưu tiên đọc từ file trên đĩa, nếu không có thì hỏi người dùng rồi lưu lại.

Thứ tự ưu tiên:
1. Biến môi trường `BRAIN_CREDENTIAL_EMAIL` và `BRAIN_CREDENTIAL_PASSWORD` — chỉ dùng khi file không tồn tại.
2. File `~/secrets/platform-brain.json`. Đọc khi file tồn tại **và** kích thước > 2 byte (một file JSON rỗng `{}` bị coi như không có).
3. Nếu không có file: tạo thư mục `~/secrets`, lấy credential từ biến môi trường nếu có, ngược lại `input()` cho email và `getpass.getpass()` cho mật khẩu, rồi ghi file.

Trả về `(data["email"], data["password"])`.

**Điểm cần biết:**
- Ghi file không đặt quyền hạn chế; file chứa mật khẩu dạng rõ.
- `json.JSONDecodeError` nếu file tồn tại nhưng JSON hỏng — exception này được docstring nêu nhưng code không bắt, nên nó lan ra.
- Hàm đọc file **mỗi lần** `start_session` gọi, không cache trong bộ nhớ.

### 4.2 `start_session() -> SingleSession` — dòng 151

**Mục đích:** đăng nhập vào BRAIN, trả về session đã xác thực.

Luồng:
1. `s = SingleSession()` — lấy singleton.
2. `s.auth = get_credentials()`.
3. `POST {base}/authentication`.
4. Nếu status 401 **và** header `WWW-Authenticate` bằng `persona`: platform yêu cầu biometric. In URL cho người dùng, chờ `input()`, rồi `POST` lại URL đó trong vòng lặp cho tới khi trả 201.
5. Nếu 401 theo kiểu khác (sai email/mật khẩu): ghi đè file credential bằng `{}` (để lần sau hỏi lại) rồi **đệ quy** gọi lại `start_session()`.

**Điểm cần biết:**
- Bước biometric chặn ở `input()`, nên script không chạy tự động được nếu tài khoản cần Persona.
- Nhánh sai mật khẩu gọi đệ quy không giới hạn. Nếu credential sai vĩnh viễn, đây là vòng lặp vô hạn chỉ bị chặn bởi người dùng bấm Ctrl-C.
- `r.json()` trong `logger.debug` được gọi **trước** khi kiểm tra status code. Nếu response không phải JSON, `r.json()` ném exception và hàm chết trước khi kịp xử lý 401.

### 4.3 `check_session_timeout(s) -> int` — dòng 197

**Mục đích:** trả về **số giây còn lại** của token hiện tại, hoặc `0` nếu hết hạn hoặc lỗi.

Cách tính: `GET /authentication`, đọc `json()["token"]["expiry"]`. Bất kỳ exception nào (`try/except Exception`) đều trả `0`.

**Điểm cần biết:** hàm trả về **giá trị expiry của platform** chứ không phải số giây còn lại do client tính. Ý nghĩa thực tế của nó trong `check_session_and_relogin` là "còn hạn hay không"; con số 2000 là ngưỡng, không phải đơn vị thời gian còn lại theo nghĩa thông thường.

### 4.4 `check_session_and_relogin(s) -> SingleSession` — dòng 311

**Mục đích:** đảm bảo session còn dùng được trước khi gọi API; nếu không thì đăng nhập lại.

Luồng:
1. Vào `s.get_relogin_lock()` — mọi thread chờ ở đây, nên chỉ một thread đăng nhập lại tại một thời điểm.
2. Nếu `check_session_timeout(s) < 2000` → thử `start_session()`. Nếu lỗi, `logger.info` rồi `time.sleep(100)` và thử lại.
3. Trả về session (mới nếu đã đăng nhập lại).

**Điểm cần biết:**
- `start_session()` trả về **cùng một singleton** (vì `SingleSession` là singleton), nên `s = start_session()` thực chất chỉ đổi lại `auth` và cookies trên cùng object. Việc gán lại `s` gần như là no-op về mặt object.
- Vì `s` là singleton, sau khi đăng nhập lại, các thread khác đang chờ ở lock cũng tự động dùng session đã làm mới.
- Ngưỡng 2000 là hằng viết cứng trong hàm.

---

## 5. Mô tả alpha

### 5.1 `generate_alpha(...) -> dict` — dòng 217

**Mục đích:** dựng payload simulation cho một alpha.

Tham số và mặc định:

| Tham số | Mặc định | Ghi chú |
| --- | --- | --- |
| `regular` | `None` | FASTEXPR của alpha thường |
| `selection`, `combo` | `None` | Chỉ dùng cho SUPER alpha |
| `alpha_type` | `"REGULAR"` | `"REGULAR"` hoặc `"SUPER"` |
| `region` | `"USA"` | |
| `universe` | `"TOP3000"` | |
| `delay` | `1` | `Literal[0, 1]` |
| `decay` | `0` | |
| `neutralization` | `"INDUSTRY"` | |
| `truncation` | `0.08` | |
| `pasteurization` | `"ON"` | |
| `test_period` | `"P0Y0M0D"` | ISO-8601 duration |
| `unit_handling` | `"VERIFY"` | |
| `nan_handling` | `"OFF"` | |
| `max_trade` | `"ON"`/`"OFF"` | |
| `selection_handling` | `"POSITIVE"` | Chỉ SUPER |
| `selection_limit` | `100` | Chỉ SUPER |
| `visualization` | `False` | |
| `simulation_mode` | `"FULL"` | `"FULL"` hoặc `"QUICK"` |

Payload luôn chứa `settings` với `instrumentType: "EQUITY"` và `language: "FASTEXPR"`.

- `alpha_type == "REGULAR"`: `{type, settings, regular}`.
- `alpha_type == "SUPER"`: `{type, settings + selectionHandling + selectionLimit, combo, selection}`.
- Giá trị khác: `logger.error` và trả `{}` (dict rỗng, **không** raise).

**Điểm cần biết:**
- Docstring nói "Raises: ValueError" nhưng code **không** raise; nó trả `{}`. Lời gọi sai sẽ âm thầm đi tiếp với payload rỗng.
- `settings` không có khoá `universe` cho SUPER? Có — `universe` nằm trong `settings` chung.
- `instrumentType` cố định `"EQUITY"`, không tham số hoá.

### 5.2 `DEFAULT_CONFIG` liên quan

Xem §3.2.

---

## 6. Chạy simulation

### 6.1 `start_simulation(s, simulate_data) -> requests.Response` — dòng 341

**Mục đích:** `POST /simulations` với payload, trả response thô.

Hàm này **không** kiểm tra status code và **không** xử lý rate limit — việc đó nằm ở `simulation_progress` / `multisimulation_progress`.

`simulate_data` nhận `Union[list[dict], dict]`: một dict cho simulation đơn, một list cho multi-simulation (platform nhận list để chạy một lệnh nhiều alpha).

### 6.2 `simulation_progress(s, simulate_response) -> dict` — dòng 359

**Mục đích:** theo dõi một simulation đến khi xong, trả `{"completed": bool, "result": dict}`.

Luồng:
1. Status không 2xx → `logger.warning`, trả `{"completed": False, "result": {}}`.
2. Lấy URL tiến độ từ header `Location`.
3. Vòng lặp poll `GET`:
   - Status không 2xx → ngủ 30 giây, tăng `retry_count`. Tối đa 2 lần retry thì coi như lỗi (`error_flag = True`, thoát vòng lặp).
   - Header `Retry-After` bằng 0 (hoặc vắng mặt) → server đã trả kết quả cuối. Nếu `status` là `"ERROR"` thì `error_flag = True`. Thoát vòng lặp.
   - Ngủ `float(Retry-After)` giây rồi poll lại.
4. Nếu lỗi → `logger.error`, trả `{"completed": False, "result": {}}`.
5. Đọc `alpha` từ JSON. Nếu bằng 0 → `logger.warning`, coi như thất bại.
6. Gọi `get_simulation_result_json(s, alpha)`; nếu kết quả rỗng → `{"completed": False, "result": {}}`.
7. Ngược lại trả `{"completed": True, "result": <dict alpha>}`.

**Điểm cần biết:**
- Cơ chế "xong" dựa vào header `Retry-After` **bằng 0**. Đây là quy ước riêng của platform, không phải HTTP chuẩn.
- `simulation_progress_response` được dùng **ngoài** vòng lặp ở bước 4 và 5. Nếu vòng lặp không chạy đúng một vòng (ví dụ exception trước đó), biến này có thể chưa được gán — nhưng bước 1 đã return sớm nên về thực tế vòng lặp luôn chạy ít nhất một lần.
- `retry_count` không reset giữa các lần lỗi liên tiếp.

### 6.3 `get_simulation_result_json(s, alpha_id) -> dict` — dòng 422

**Mục đích:** lấy JSON đầy đủ của một alpha từ `GET /alphas/{alpha_id}`.

Luồng: poll `GET` cho tới khi response **không** có header `retry-after`, ngủ theo giá trị header nếu có. Rồi `result.json()` trong `try/except`; nếu lỗi thì `logger.error` và trả `{}`.

**Điểm cần biết:**
- Dòng 448 (`return s.get(...).json()`) là **code chết**: mọi nhánh đều đã return trước đó.
- Vòng poll ở đây không có điều kiện dừng khi server lỗi — chỉ dừng khi header `retry-after` vắng mặt.

### 6.4 `multisimulation_progress(s, simulate_response) -> dict` — dòng 452

**Mục đích:** theo dõi một multi-simulation (một request, nhiều alpha con) đến khi xong.

Luồng:
1. Status không 2xx → `{"completed": False, "result": {}}`.
2. Poll URL từ header `Location`, tương tự `simulation_progress` **nhưng không có giới hạn retry**: status không 2xx chỉ ngủ 30 giây rồi poll lại, không đếm số lần retry.
3. Đọc `children` từ JSON (danh sách id simulation con).
4. Nếu lỗi: nếu `children` rỗng thì báo lỗi chung; ngược lại `GET /simulations/{child}` cho từng con để log chi tiết rồi trả `{"completed": False, "result": {}}`.
5. Nếu `children` rỗng → coi như thất bại.
6. Với từng child: `GET /simulations/{child}`, đọc `alpha`; nếu bằng 0 thì **dừng luôn** và trả thất bại (một con lỗi làm hỏng cả batch).
7. Với mỗi alpha con, gọi `get_simulation_result_json` và gom vào list.
8. Trả `{"completed": True, "result": [list các dict alpha]}`.

**Điểm cần biết:**
- Một alpha con lỗi làm toàn bộ batch thất bại, kể cả các con đã thành công.
- Không có giới hạn retry như `simulation_progress`.
- Ở bước 4, khi `children` không rỗng, vòng lặp `for child in children` chỉ log, không `break`.

### 6.5 `simulate_single_alpha(s, simulate_data) -> dict` — dòng 865

**Mục đích:** chạy một alpha và trả `{"alpha_id": str|None, "simulate_data": dict}`.

Luồng: `check_session_and_relogin` → `start_simulation` → `simulation_progress`. Nếu không completed → `alpha_id = None`. Ngược lại `alpha_id = result["id"]`.

**Điểm cần biết:** docstring nói hàm "sets alpha properties upon completion" nhưng code **không** gọi `set_alpha_properties`. Trong `simulate_multi_alpha` dòng 741, lệnh gọi đó cũng đã bị comment out.

### 6.6 `simulate_multi_alpha(s, simulate_data_list) -> list[dict]` — dòng 696

**Mục đích:** chạy một **list** alpha bằng multi-simulation (một request chứa nhiều alpha).

Luồng:
1. `check_session_and_relogin`.
2. Nếu list chỉ có 1 phần tử → gọi `simulate_single_alpha` và bọc trong list.
3. `start_simulation(s, simulate_data_list)` — gửi cả list.
4. `multisimulation_progress`.
5. Nếu không completed → trả list với `alpha_id = None` cho mỗi phần tử.
6. Ngược lại dựng list từ kết quả, với `simulate_data` rút gọn còn `{type, settings, regular: x["regular"]["code"]}`.

**Điểm cần biết:**
- Dòng 741 (`set_alpha_properties`) bị comment out — xem §6.5.
- `simulate_data` trả về bị **rút gọn**: chỉ giữ `regular` dạng code, mất `combo`/`selection` nếu là SUPER alpha.

### 6.7 `simulate_alpha_list(s, alpha_list, limit_of_concurrent_simulations=3, simulation_config=DEFAULT_CONFIG) -> list` — dòng 902

**Mục đích:** chạy nhiều alpha **đồng thời**, mỗi alpha một simulation riêng.

Luồng:
1. Kiểm tra `limit_of_concurrent_simulations` trong `1..8`; nếu ngoài khoảng thì `logger.warning` và đặt lại về 3.
2. `ThreadPool(limit_of_concurrent_simulations)` + `pool.imap_unordered(partial(simulate_single_alpha, s), alpha_list)`, kèm thanh `tqdm`.
3. ThreadPool(3) chạy `get_specified_alpha_stats` cho từng kết quả.
4. `_delete_duplicates_from_result`.

**Điểm cần biết:**
- `imap_unordered` nên thứ tự kết quả **không** khớp thứ tự input.
- ThreadPool thứ hai cố định 3, không theo tham số.
- `func(x)` ở dòng 937 là closure cục bộ dùng `s` đã capture.

### 6.8 `simulate_alpha_list_multi(s, alpha_list, limit_of_concurrent_simulations=3, limit_of_multi_simulations=10, simulation_config=DEFAULT_CONFIG) -> list` — dòng 947

**Mục đích:** chạy nhiều alpha bằng multi-simulation: chia list thành batch, mỗi batch là một request.

Luồng:
1. Kiểm tra `limit_of_multi_simulations` trong `2..10` (ngoài khoảng → đặt 10) và `limit_of_concurrent_simulations` trong `1..8` (ngoài khoảng → đặt 3).
2. Nếu có bất kỳ alpha nào `type == "SUPER"` → `logger.warning` và **rơi về** `simulate_alpha_list` với `limit_of_concurrent_simulations=3` (bỏ qua tham số người dùng truyền).
3. Chia `alpha_list` thành batch kích thước `limit_of_multi_simulations`.
4. `ThreadPool` chạy `simulate_multi_alpha` trên từng batch, có `tqdm`.
5. Flatten kết quả, rồi `ThreadPool(3)` chạy `get_specified_alpha_stats`.
6. `_delete_duplicates_from_result`.

**Điểm cần biết:**
- Multi-simulation **không** hỗ trợ SUPER alpha — đây là giới hạn của platform, code chỉ ghi log rồi chuyển sang đường chạy đơn.
- Khi rơi về `simulate_alpha_list`, tham số `limit_of_concurrent_simulations` của người dùng bị thay bằng 3.

### 6.9 `_delete_duplicates_from_result(result: list) -> list` — dòng 1009

**Mục đích:** loại các alpha trùng `alpha_id`, giữ lần xuất hiện đầu.

Các entry có `alpha_id is None` (alpha thất bại) được giữ **tất cả**, không bị loại.

---

## 7. Đánh giá alpha

### 7.1 `get_specified_alpha_stats(...) -> dict` — dòng 744

**Mục đích:** hàm trung tâm của phần đánh giá: gom mọi thống kê của một alpha vào một dict.

Tham số (mặc định lấy từ `DEFAULT_CONFIG`, tất cả `False`):
`get_pnl`, `get_stats`, `save_pnl_file`, `save_stats_file`, `save_result_file`, `check_submission`, `check_self_corr`, `check_prod_corr`.

Luồng:
1. `check_session_and_relogin`.
2. Nếu `alpha_id is None` → trả dict với mọi giá trị `None` (`is_stats`, `pnl`, `stats`, `is_tests`, `train`, `test`).
3. `get_simulation_result_json(s, alpha_id)`.
4. `is_stats` = DataFrame một dòng từ `result["is"]` bỏ khoá `checks`, gắn `alpha_id`.
5. `train = result["train"]`, `test = result["test"]`.
6. `get_pnl` → `get_alpha_pnl`; nếu `save_pnl_file` thì `save_pnl(pnl, alpha_id, region)`.
7. `get_stats` → `get_alpha_yearly_stats`; nếu `save_stats_file` thì `save_yearly_stats(...)`.
8. `save_result_file` → `save_simulation_result(result)`.
9. `is_tests` = DataFrame từ `result["is"]["checks"]`.
10. `check_submission` → `is_tests = get_check_submission(...)` và **return sớm** (bỏ qua self/prod corr).
11. `check_self_corr` (và không `check_submission`) → `check_self_corr_test`, nối vào `is_tests` bằng `pd.concat` + `drop_duplicates(subset=["test"], keep="last")`.
12. `check_prod_corr` (và không `check_submission`) → tương tự với `check_prod_corr_test`.
13. Trả dict 7 khoá: `alpha_id`, `simulate_data`, `is_stats`, `pnl`, `stats`, `is_tests`, `train`, `test`.

**Điểm cần biết:**
- `region` được lấy từ `result["settings"]["region"]` ở bước 4, **bên trong** `try/except`. Nếu exception xảy ra, `region` **không** được gán, và bước 6/7 sẽ ném `UnboundLocalError` khi `save_pnl_file` hoặc `save_stats_file` bật. Ngoài ra `is_stats` được dựng lại ở bước 5, nên `try/except` ở bước 4 gần như vô nghĩa.
- `check_submission` bị ưu tiên hơn self/prod corr: nếu bật, hai test kia không chạy.
- `is_tests` dùng `drop_duplicates(subset=["test"], keep="last")` — test self/prod corr ghi đè test cùng tên đến từ `result["is"]["checks"]`.

### 7.2 `get_prod_corr(s, alpha_id) -> pd.DataFrame` — dòng 514

**Mục đích:** lấy dữ liệu correlation với alpha production của BRAIN.

Endpoint: `GET /alphas/{alpha_id}/correlations/prod`. Poll theo header `retry-after`.

Nếu `records` rỗng → `logger.warning` và trả DataFrame rỗng.

Ngược lại: cột lấy từ `schema.properties[].name`, dựng DataFrame từ `records`, gắn `alpha_id`, rồi thêm hai cột `alpha_max_prod_corr` và `alpha_min_prod_corr` lấy từ `max` và `min` của response.

### 7.3 `check_prod_corr_test(s, alpha_id, threshold=0.7) -> pd.DataFrame` — dòng 546

**Mục đích:** kiểm tra correlation production có vượt ngưỡng không.

Giá trị kiểm tra: `prod_corr_df[prod_corr_df.alphas > 0]["max"].max()` — chỉ các alpha production có `alphas > 0` (tức là alpha đang chạy thật, không phải alpha đã bị loại).

Kết quả `PASS` nếu `value <= threshold`, ngược lại `FAIL`. Nếu không lấy được dữ liệu (`DataFrame` rỗng) → `result = "NONE"`, `value = None`.

Trả DataFrame một dòng với cột `test`, `result`, `limit`, `value`, `alpha_id`.

**Điểm cần biết:**
- Dùng `<=` (không phải `<`) — khác với self-correlation.
- Trường hợp rỗng trả `"NONE"`, **không** phải `"FAIL"`. Nghĩa là "không biết", không phải "sai".

### 7.4 `get_self_corr(s, alpha_id) -> pd.DataFrame` — dòng 587

**Mục đích:** lấy dữ liệu self-correlation (correlation với chính các alpha đã submit của cùng user).

Endpoint: `GET /alphas/{alpha_id}/correlations/self`. Poll theo `retry-after`.

Nếu `records` rỗng → warning + DataFrame rỗng. Cột lấy từ `schema.properties[].name`, gắn `alpha_id`, thêm `alpha_max_self_corr` và `alpha_min_self_corr`.

### 7.5 `check_self_corr_test(s, alpha_id, threshold=0.7) -> pd.DataFrame` — dòng 625

**Mục đích:** kiểm tra self-correlation có vượt ngưỡng không.

Giá trị kiểm tra: `self_corr_df["correlation"].max()` — cột literal `correlation`, khác với prod corr dùng `["max"]`.

Kết quả `PASS` nếu `value < threshold` (dùng `<` nghiêm, khác prod corr dùng `<=`), ngược lại `FAIL`.

Nếu không lấy được dữ liệu → `"PASS"` với `value = 0`. Tức là **thiếu dữ liệu thì coi như đạt**, trong khi prod corr thiếu dữ liệu thì coi là `"NONE"`. Đây là bất đối xứng có chủ ý trong reference code.

### 7.6 `get_check_submission(s, alpha_id) -> pd.DataFrame` — dòng 666

**Mục đích:** lấy kết quả các kiểm tra trước khi submit của một alpha.

Endpoint: `GET /alphas/{alpha_id}/check`. Poll theo `retry-after`.

Nếu `result.json().get("is", 0) == 0` → warning + DataFrame rỗng. Ngược lại DataFrame từ `result.json()["is"]["checks"]`, gắn `alpha_id`.

### 7.7 `_get_alpha_pnl(s, alpha_id, pnl_type="pnl") -> pd.DataFrame` — dòng 1089

**Mục đích:** lấy PnL. `pnl_type` là `"pnl"` (cumulative) hoặc `"daily-pnl"`.

Endpoint: `GET /alphas/{alpha_id}/recordsets/{pnl_type}`. Poll theo `retry-after`.

Nếu `records` rỗng → DataFrame rỗng. Ngược lại: cột từ `schema.properties[].name`, cột `date` được parse bằng `pd.to_datetime(..., format="%Y-%m-%d")` và đặt làm index, gắn `alpha_id`.

**Điểm cần biết:** format cố định `"%Y-%m-%d"` — nếu platform đổi định dạng ngày, `to_datetime` raise.

### 7.8 `get_alpha_pnl(s, alpha_id) -> pd.DataFrame` — dòng 1124

**Mục đích:** wrapper công khai của `_get_alpha_pnl` với `pnl_type="pnl"`.

### 7.9 `get_alpha_yearly_stats(s, alpha_id) -> pd.DataFrame` — dòng 1139

**Mục đích:** lấy thống kê theo năm của một alpha.

Endpoint: `GET /alphas/{alpha_id}/recordsets/yearly-stats`. Poll theo `retry-after`.

Nếu `records` rỗng → DataFrame rỗng. Ngược lại: cột từ `schema.properties[].name`, gắn `alpha_id`.

### 7.10 `performance_comparison(s, alpha_id, team_id=None, competition=None) -> dict` — dòng 1383

**Mục đích:** lấy so sánh hiệu năng trước/sau của một alpha so với team hoặc competition.

Đường dẫn phụ chọn theo thứ tự ưu tiên:
1. `competition` khác `None` → `competitions/{competition}`
2. ngược lại `team_id` khác `None` → `teams/{team_id}`
3. ngược lại → `users/self`

Endpoint đầy đủ: `GET /{part_url}/alphas/{alpha_id}/before-and-after-performance`. Poll theo `retry-after`.

Nếu `stats` rỗng hoặc status khác 200 → `logger.warning` và trả `{}`. Ngược lại trả JSON.

---

## 8. Truy vấn catalog

### 8.1 `get_datasets(s, instrument_type="EQUITY", region="USA", delay=1, universe="TOP3000", theme=None) -> pd.DataFrame` — dòng 1204

**Mục đích:** lấy danh sách dataset của một scope.

Endpoint: `GET /data-sets?instrumentType=&region=&delay=&universe=`.

Tham số `theme` có ba trạng thái:
- `True` → thêm `&theme=true`, chỉ dataset thuộc theme.
- `False` → thêm `&theme=false`, chỉ dataset **không** thuộc theme.
- `None` → không thêm tham số, lấy tất cả.

Sau khi nhận JSON: `pd.DataFrame(result.json()["results"])` rồi `expand_dict_columns` để tách các cột chứa dict thành cột phẳng.

**Điểm cần biết:** đây là **một trong hai chỗ** trong file dùng tham số `theme` với nghĩa "lọc theo theme" (chỗ kia là `sample_field_ids` của dự án hiện tại, không thuộc file này).

### 8.2 `get_datafields(s, instrument_type="EQUITY", region="USA", delay=1, universe="TOP3000", search="") -> pd.DataFrame` — dòng 1245

**Mục đích:** lấy danh sách data field của một scope, tuỳ chọn lọc theo từ khoá.

Hai nhánh:
- `search` rỗng → `GET /data-fields?...` không có phân trang.
- `search` khác rỗng → `GET /data-fields?...&limit=50&search={search}&offset=0`. **`limit=50` là cố định** — chỉ 50 kết quả đầu được lấy, không có cơ chế phân trang tiếp.

Kết quả: `pd.DataFrame(results)` + `expand_dict_columns`.

**Điểm cần biết:**
- `search` được nối thẳng vào URL **không** encode.
- Với `search` rỗng, endpoint trả về toàn bộ field của scope (hàng chục nghìn ở `USA_1_TOP3000`).
- Nhánh `search` rỗng **không** kiểm tra `_check_rate_limit` trước khi request, nhưng có gọi sau.

### 8.3 `get_operators(s) -> pd.DataFrame` — dòng 1298

**Mục đích:** lấy bảng operator của platform.

Endpoint: `GET /operators`. Kết quả được `explode('scope')` để mỗi scope của operator thành một dòng riêng, rồi `reset_index(drop=True)`.

**Điểm cần biết:**
- Không gọi `_check_rate_limit`.
- `explode` trên cột `scope` yêu cầu cột đó tồn tại và chứa list; nếu response đổi hình dạng thì raise.
- Endpoint `/operators` không scope-scoped: một request lấy toàn bộ bảng. Đây là điểm khớp với cách dự án hiện tại cache `/operators` thành một file CSV duy nhất.

### 8.4 `get_instrument_type_region_delay(s) -> pd.DataFrame` — dòng 1317

**Mục đích:** lấy **tất cả** tổ hợp hợp lệ của instrument type / region / delay / universe / neutralization từ `OPTIONS /simulations`.

Luồng:
1. Đọc `actions.POST.settings.children` của `OPTIONS /simulations`.
2. Chọn các khoá có `type == 'choice'`.
3. Tách theo label: `Instrument type`, `Region`, `Universe`, `Delay`, `Neutralization`.
4. Vòng lặp 3 tầng: instrument type → region → delay. Mỗi dòng chứa `InstrumentType`, `Region`, `Delay`, `Universe` (danh sách), `Neutralization` (danh sách).
5. Sort theo `InstrumentType`, `Region`, `Delay` **descending**, `reset_index(drop=True)`.

**Điểm cần biết:**
- Đây chính là nguồn mà `config/scopes.yaml` của dự án hiện tại được sinh ra (41 scope hợp lệ).
- Hàm trả về **một dòng cho mỗi (instrumentType, region, delay)**, với `Universe` là **danh sách** các universe hợp lệ của region đó — chứ không phải một dòng cho mỗi scope đầy đủ. Muốn có scope đầy đủ phải tự cross product.
- Không gọi `_check_rate_limit`.
- Sort `ascending=False` khiến thứ tự output không trực giác (USA trước GLB, v.v.).

---

## 9. Tiện ích HTTP

### 9.1 `_check_rate_limit(response) -> None` — dòng 1166

**Mục đích:** ngủ theo header rate-limit để không vượt quota của platform.

Bốn header đọc: `x-ratelimit-limit-minute`, `x-ratelimit-remaining-minute`, `x-ratelimit-limit-second`, `x-ratelimit-remaining-second`.

Hành vi:
- Thiếu header → `logger.warning` và **return** (không ngủ).
- Header không parse được thành int → `logger.warning` và **return**.
- `remaining_second < 1` → ngủ 1 giây.
- `remaining_minute <= 1` → `logger.info` và ngủ 60 giây.

**Điểm cần biết:**
- Hàm chỉ được gọi ở `get_datasets` và `get_datafields`. Các endpoint khác (`/simulations`, `/alphas`, `/operators`, `/authentication`) **không** kiểm tra rate limit.
- Nếu header thiếu, hàm báo warning nhưng **không ngủ** — tức là coi như không có giới hạn.
- `parsed["limit_minute"]` chỉ dùng để log.

---

## 10. Bảng tóm tắt

| Dòng | Tên | Loại | Mục đích |
| --- | --- | --- | --- |
| 42 | `SingleSession` | class | Session HTTP singleton, thread-safe cho việc đăng nhập lại |
| 48 | `__new__` | method | Tạo singleton với double-checked locking |
| 55 | `__init__` | method | Khởi tạo `requests.Session` đúng một lần |
| 60 | `get_relogin_lock` | method | Trả lock điều phối đăng nhập lại |
| 64 | `setup_logger` | func | Tạo logger console + file `ace.log` |
| 114 | `get_credentials` | func | Đọc/hỏi/lưu email + password |
| 151 | `start_session` | func | Đăng nhập, xử lý Persona biometric |
| 197 | `check_session_timeout` | func | Số giây còn lại của token, 0 nếu lỗi |
| 217 | `generate_alpha` | func | Dựng payload simulation (REGULAR/SUPER) |
| 311 | `check_session_and_relogin` | func | Đảm bảo token còn hạn, đăng nhập lại nếu cần |
| 341 | `start_simulation` | func | `POST /simulations` |
| 359 | `simulation_progress` | func | Poll một simulation đến khi xong |
| 422 | `get_simulation_result_json` | func | `GET /alphas/{id}` |
| 452 | `multisimulation_progress` | func | Poll một multi-simulation và gom kết quả con |
| 514 | `get_prod_corr` | func | Correlation với alpha production |
| 546 | `check_prod_corr_test` | func | Kiểm tra prod correlation (ngưỡng 0.7) |
| 587 | `get_self_corr` | func | Self-correlation |
| 625 | `check_self_corr_test` | func | Kiểm tra self correlation (ngưỡng 0.7) |
| 666 | `get_check_submission` | func | Kết quả check trước khi submit |
| 696 | `simulate_multi_alpha` | func | Chạy một list alpha bằng multi-simulation |
| 744 | `get_specified_alpha_stats` | func | Gom mọi thống kê của một alpha |
| 865 | `simulate_single_alpha` | func | Chạy một alpha |
| 902 | `simulate_alpha_list` | func | Chạy nhiều alpha song song, mỗi cái một request |
| 947 | `simulate_alpha_list_multi` | func | Chạy nhiều alpha theo batch multi-simulation |
| 937, 999 | `func` | nested | Closure gọi `get_specified_alpha_stats` |
| 1009 | `_delete_duplicates_from_result` | func | Loại alpha trùng `alpha_id` |
| 1031 | `set_alpha_properties` | func | `PATCH /alphas/{id}` đổi tên/màu/category/mô tả/tag |
| 1089 | `_get_alpha_pnl` | func | Lấy PnL (`pnl` hoặc `daily-pnl`) |
| 1124 | `get_alpha_pnl` | func | Lấy cumulative PnL |
| 1139 | `get_alpha_yearly_stats` | func | Thống kê theo năm |
| 1166 | `_check_rate_limit` | func | Ngủ theo header rate-limit |
| 1204 | `get_datasets` | func | `GET /data-sets` cho một scope |
| 1245 | `get_datafields` | func | `GET /data-fields` cho một scope |
| 1298 | `get_operators` | func | `GET /operators`, explode scope |
| 1317 | `get_instrument_type_region_delay` | func | Enumerate scope hợp lệ từ `OPTIONS /simulations` |
| 1383 | `performance_comparison` | func | So sánh hiệu năng trước/sau |

**Tổng: 36 `def`** — 31 hàm top-level, 3 method của `SingleSession`, 2 nested `func`.

---

## 11. Những điểm cần biết trước khi dùng làm tham khảo

### 11.1 Đây là reference code, không phải code của dự án

Folder `ACE_API__Gold_/` là **mẫu tham khảo** từ WorldQuant BRAIN Alpha Creation Engine. Theo rule 16 của workspace, file trong folder này **chỉ được đọc**: không sửa, không copy nguyên khối vào code dự án. Khi cần dùng, phải viết lại từ nguồn gốc (paper, docs chính thức của platform) và cite.

### 11.2 Quy ước API quan sát được

| Quy ước | Chi tiết |
| --- | --- |
| Hết hạn token | `GET /authentication` → `json["token"]["expiry"]`; ngưỡng đăng nhập lại 2000 |
| Xong simulation | Header `Retry-After` bằng 0, **không** phải status code |
| Rate limit | Header `x-ratelimit-remaining-second` và `-minute` |
| Schema response | `schema.properties[].name` là danh sách tên cột; `records` là các dòng |
| Check trước submit | `GET /alphas/{id}/check` → `json["is"]["checks"]` |
| Enumerate scope | `OPTIONS /simulations` → `actions.POST.settings.children` |
| Biometric | `WWW-Authenticate: persona` + header `Location` |

### 11.3 Bất đối xứng và điểm lệch đã ghi nhận (trong reference code)

| # | Điểm lệch | Ảnh hưởng |
| --- | --- | --- |
| 1 | `check_prod_corr_test` dùng `value <= threshold`, `check_self_corr_test` dùng `value < threshold` | Alpha có correlation đúng bằng ngưỡng: prod PASS, self FAIL |
| 2 | Thiếu dữ liệu: prod corr → `"NONE"`, self corr → `"PASS"` với `value = 0` | Self corr thiếu dữ liệu bị coi là đạt |
| 3 | `generate_alpha` docstring nói raise `ValueError`, code trả `{}` | Payload rỗng đi tiếp xuống pipeline |
| 4 | `get_specified_alpha_stats` lấy `region` trong `try/except` rồi dùng ngoài khối | `UnboundLocalError` nếu exception và bật `save_pnl_file` |
| 5 | `start_session` gọi `r.json()` trước khi kiểm tra status | Response không phải JSON làm chết hàm |
| 6 | `start_session` sai mật khẩu → đệ quy không giới hạn | Vòng lặp vô hạn nếu credential sai vĩnh viễn |
| 7 | `multisimulation_progress`: một alpha con lỗi làm hỏng cả batch | Mất kết quả của các con đã thành công |
| 8 | `multisimulation_progress` không giới hạn retry, khác `simulation_progress` (2 lần) | Có thể poll vô hạn |
| 9 | `simulate_multi_alpha` bỏ `simulate_data` (chỉ giữ `regular`) | Mất `combo`/`selection` của SUPER alpha |
| 10 | `set_alpha_properties` bị gọi ở đâu đó thì bị comment out (dòng 741) | Alpha không được đặt tên/category sau khi mô phỏng |
| 11 | `get_datafields` với `search` dùng `limit=50` cố định | Chỉ 50 kết quả đầu, không phân trang |
| 12 | `search` nối thẳng vào URL không encode | Chuỗi đặc biệt làm sai URL |
| 13 | `_check_rate_limit` chỉ gọi ở 2 endpoint | Các endpoint nặng (`/simulations`) không kiểm tra quota |
| 14 | `setup_logger` thêm handler mỗi lần gọi | Log nhân bản nếu gọi lại hàm |
| 15 | `get_simulation_result_json` có dòng return code chết (448) | Vô hại nhưng gây nhiễu khi đọc |

### 11.4 Điểm khác biệt so với code của dự án hiện tại

| Khía cạnh | `ace_lib.py` (reference) | Dự án hiện tại |
| --- | --- | --- |
| Số lần đăng nhập | `start_session()` gọi trực tiếp, không đếm | `Functions/login.py` theo dõi quota 5/phút, 25/ngày |
| Cache catalog | Không có; mọi lần gọi đều là request | `Functions/cache.py` lưu `.npz` theo (scope, field type) |
| Rate limit | Chỉ 2 endpoint dùng `_check_rate_limit` | `Functions/data.py` ngủ theo `X-RateLimit-Remaining-Second` ở mọi GET |
| Operator table | `get_operators` gọi API mỗi lần | `OperatorTable` cache thành một CSV |
| Scope | `get_instrument_type_region_delay` trả (region, delay) + list universe | `config/scopes.yaml` chứa 41 scope đầy đủ, đã flatten |
| Theme | `get_datasets` có tham số `theme` (bool) | `THEME` là list `categoryid`, áp cho MATRIX/VECTOR/GROUP |
| Chạy alpha | `simulate_alpha_list` / `_multi` | Chưa có trong dự án |

---

## 12. Cách dùng tham khảo

```python
from ace_lib import (
    SingleSession, start_session, check_session_and_relogin,
    generate_alpha, simulate_alpha_list, get_specified_alpha_stats,
)

s = start_session()
alpha_data = generate_alpha(
    regular="ts_delta(close, 5)",
    region="USA", universe="TOP3000", delay=1,
)
result = simulate_alpha_list(s, [alpha_data], simulation_config={"get_pnl": True})
```

Luồng điển hình:

```
start_session
    → generate_alpha           (dựng payload)
    → simulate_alpha_list      (chạy song song, có tqdm)
        → simulate_single_alpha
            → check_session_and_relogin
            → start_simulation      (POST /simulations)
            → simulation_progress   (poll theo Retry-After)
            → get_simulation_result_json
        → get_specified_alpha_stats   (ThreadPool 3)
            → get_simulation_result_json
            → get_alpha_pnl / get_alpha_yearly_stats   (tuỳ config)
            → check_self_corr_test / check_prod_corr_test (tuỳ config)
        → _delete_duplicates_from_result
```
