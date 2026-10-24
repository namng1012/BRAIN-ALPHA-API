# Toàn bộ FASTEXPR operators của WorldQuant BRAIN

Bản phân loại đầy đủ **84 REGULAR operator** mà platform publish, theo **kiểu data field** mà mỗi operator tiêu thụ. Đây là tài liệu đọc kèm bảng `cache/operators.csv` (sinh ra bởi `Functions/operators.py`).

Nguồn: `GET /operators`, đo trực tiếp ngày **2026-10-23**.

---

## 1. `/operators` là endpoint đặc biệt

| Đặc điểm | `/operators` | `/data-fields`, `/data-sets` |
| --- | --- | --- |
| Scope-scoped | ❌ không nhận `region` / `delay` / `universe` | ✅ bắt buộc |
| Payload | list phẳng, **không** có `{"results": [...]}` | có `results` + `count` |
| `scope` | **list** → cần `explode()` | không có |
| Có cache layer | không (payload nhỏ, đọc 1 lần) | có, theo scope |

Một operator publish thuộc nhiều scope: sau `explode("scope")` có **212 dòng / 103 operator distinct**.

| Scope | Số operator |
| --- | --- |
| `COMBO` | 101 |
| `REGULAR` | **84** ← bảng này |
| `SELECTION` | 27 |

`REGULAR` là scope dùng cho alpha expression thường. `SELECTION` là các operator dùng trong Selection expression (khác cú pháp), `COMBO` là operator ghép.

**Điểm vận hành:** `/operators` cần auth, nên tốn login. Bảng được cache thành **một file CSV duy nhất** ở `cache/operators.csv`; từ lần chạy thứ hai trở đi, file còn trên đĩa là không cần gọi platform nữa. Luồng xử lý 3 nhánh trong `main.py` xem §7.2.

---

## 2. Vì sao phải tự phân loại

Payload của `/operators` **không** chứa thông tin kiểu data field. Nó chỉ có:

```
name · category · scope · definition · description · documentation · level
```

Trong đó `category` là do platform grade (Arithmetic, Time Series, Logical, Group, Cross Sectional, Vector, Transformational) — nó phân loại theo **ý nghĩa toán học**, không phải theo **kiểu dữ liệu** mà operator chạm vào.

Hai điều suy ra được từ `category` là sai với mục đích dựng alpha:

- `if_else` được grade là `Logical`, nhưng nó là **value selector** (chọn giữa hai giá trị), không phải mask 0/1 → không thuộc nhóm BOOLEAN.
- `max` / `min` / `multiply` nằm trong `Arithmetic`, nhưng chúng nhận **số lượng field không cố định** → không phải unary/binary thông thường.

Vì vậy bảng dưới đây dùng **9 bucket riêng**, tách bạch khỏi `category` của platform.

---

## 3. Chín bucket và ý nghĩa

Các bucket đi theo **chiều data flow** mà một FASTEXPR đi qua. Thứ tự khai báo cũng là thứ tự dòng trong CSV — đọc file từ trên xuống là đi đúng đường đi của một biểu thức.

| Bucket | Ý nghĩa | Số |
| --- | --- | --- |
| `MATRIX_BINARY` | Nhận đúng **hai** matrix field → nơi hai field độc lập gặp nhau, biểu đạt được quan hệ pairwise | 9 |
| `MATRIX_UNARY` | Nhận **một** matrix field | 40 |
| `MATRIX_GENERATED` | Không nhận matrix field nào — tự sinh ra chuỗi đếm ngày (`ts_step`) | 1 |
| `VARIADIC` | Nhận số lượng matrix field **không cố định** | 3 |
| `SELECT` | Nhận matrix field, trong đó một field đóng vai trò **điều kiện** chứ không phải giá trị | 2 |
| `BOOLEAN` | Trả về **mask 0/1** thay vì giá trị | 10 |
| `VECTOR` | Tiêu thụ vector field và **giảm về matrix** | 7 |
| `GROUP` | Nhận matrix field **+** group field | 9 |
| `GROUPING` | Tiêu thụ hoặc sinh ra **grouping field**, không có matrix nào đi ra | 3 |

---

## 4. Luật phân loại — và những chỗ phải hard-code

Bốn luật đọc được trực tiếp từ payload:

| Luật | Cách suy ra |
| --- | --- |
| VECTOR | tên bắt đầu bằng `vec_` |
| GROUP | tên bắt đầu bằng `group_` **và** definition có nhắc tới `group` |
| BOOLEAN | `category == "Logical"` |
| VARIADIC | definition chứa `..` |

Ba luật còn lại **không** đọc được từ payload, phải suy ra riêng:

### 4.1 `bucket` và `densify` — hard-code theo tên

Hai operator này được xếp vào `GROUPING` vì typing của chúng chỉ được nói trong **prose description**, không nói trong definition. Không thể match theo từ khoá trong description một cách an toàn — ngày nào WorldQuant đổi cách diễn đạt là toàn bộ phân loại âm thầm sai.

### 4.2 `group_cartesian_product` — tự rơi ra

Đây là operator `group_` **duy nhất** không nhắc tới argument `group` (`group_cartesian_product(g1, g2)` — nó tự tạo ra group). Nên luật "GROUP nếu có chữ `group`" loại nó ra, và nó rơi vào `GROUPING` mà không cần hard-code.

### 4.3 SELECT — suy ra từ hình dạng argument

Một operator là SELECT khi **tất cả** argument của nó đều là data field, và có **từ 3 trở lên**.

Điểm dễ hiểu sai: platform dùng **hai** ký hiệu variadic khác nhau — `..` (hai chấm) và `...` (ba chấm). `multiply(x ,y, ... , filter=false), x * y` dùng ba chấm, nên luật "chứa `..`" mới bắt được `multiply` — vì `...` cũng chứa substring `..`.

| Operator | Definition | Vì sao |
| --- | --- | --- |
| `if_else` | `if_else(input1, input2, input 3)` | 3 data field, argument thứ nhất là điều kiện |
| `trade_when` | `trade_when(x, y, z)` | 3 data field, `x` là trigger |

Đã kiểm chứng trên catalog live: luật này chọn **đúng** `if_else` và `trade_when`, không chọn thêm operator nào.

### 4.4 Thứ tự quyết định

Một operator có thể thoả nhiều luật cùng lúc. Thứ tự trong `OperatorTable.bucket_of()` là:

```
GROUPING → GROUP → VECTOR → BOOLEAN → SELECT → VARIADIC → MATRIX_GENERATED → MATRIX_*
```

Hai chỗ thứ tự **có ý nghĩa**, đảo là sai:

- **SELECT trước BOOLEAN.** `if_else` là `Logical` (sẽ vào BOOLEAN nếu không loại) nhưng là value selector. Xếp SELECT trước thì `if_else` ra khỏi BOOLEAN, đúng như bảng.
- **VARIADIC trước MATRIX_*.** `max` / `min` / `multiply` có 2 argument data field (`x`, `y`) nên nếu đến bước MATRIX sẽ bị đếm là binary — sai, chúng nhận bao nhiêu field tuỳ ý.

### 4.5 Đếm matrix field — chỉ đếm argument data field

`DATA_ARGS = {x, y, z, input, input1, input2, input3}`

Các argument số và keyword (`d`, `k`, `lag`, `rettype`, `filter`, `std`) **không phải** matrix field:

| Operator | Definition | Số matrix field | Bucket |
| --- | --- | --- | --- |
| `ts_corr` | `ts_corr(x, y, d)` | 2 | MATRIX_BINARY |
| `ts_mean` | `ts_mean(x, d)` | 1 | MATRIX_UNARY |
| `ts_regression` | `ts_regression(y, x, d, lag = 0, rettype = 0)` | 2 | MATRIX_BINARY |
| `ts_backfill` | `ts_backfill(x,lookback = d, k=1)` | 1 | MATRIX_UNARY |

### 4.6 `ts_step` — operator không nhận data field

`ts_step(1)` không nhận matrix field nào: nó là **bộ đếm ngày**. Không phải unary transform nên **không** được xếp vào MATRIX_UNARY.

Argument của `ts_step` là **giá trị đầu** của chuỗi đếm, không phải bước nhảy:

| Call | Chuỗi trả về |
| --- | --- |
| `ts_step(1)` | 1, 2, 3, 4, … |
| `ts_step(2)` | 2, 3, 4, 5, … |

Cả hai đều **tăng 1 mỗi ngày** — argument chỉ dịch toàn bộ chuỗi. Vì vậy `ts_step(1)` và `ts_step(2)` **không** tạo ra chuỗi cách nhau 2 ngày; muốn lấy thay đổi sau 2 ngày thì dùng `ts_delta(x, 2)`.

`ts_step` thường được dùng làm biến độc lập `x` trong `ts_regression(returns, ts_step(1), 60, rettype=0)` — hồi quy returns theo trục thời gian trong cửa sổ 60 ngày.

---

## 5. Bảng đầy đủ

Cột **Platform category** là `category` do platform grade. Cột **Level** là `level` của platform: `ALL` nghĩa là operator dùng được ở mọi cấp độ; `-` nghĩa là payload trả `null` — platform **chưa grade** operator đó (18/84 operator, không phải dữ liệu thiếu).

### MATRIX_BINARY (9)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `add` | `add(x, y, filter = false), x + y` | Arithmetic | ALL |
| `divide` | `divide(x, y), x / y` | Arithmetic | ALL |
| `power` | `power(x, y)` | Arithmetic | ALL |
| `signed_power` | `signed_power(x, y)` | Arithmetic | ALL |
| `subtract` | `subtract(x, y, filter=false), x - y` | Arithmetic | ALL |
| `ts_corr` | `ts_corr(x, y, d)` | Time Series | ALL |
| `ts_covariance` | `ts_covariance(y, x, d)` | Time Series | ALL |
| `ts_regression` | `ts_regression(y, x, d, lag = 0, rettype = 0)` | Time Series | ALL |
| `vector_neut` | `vector_neut(x, y)` | Cross Sectional | - |

### MATRIX_UNARY (40)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `abs` | `abs(x)` | Arithmetic | ALL |
| `days_from_last_change` | `days_from_last_change(x)` | Time Series | ALL |
| `hump` | `hump(x, hump = 0.01)` | Time Series | ALL |
| `inverse` | `inverse(x)` | Arithmetic | ALL |
| `kth_element` | `kth_element(x, d, k, ignore=“NaN”)` | Time Series | ALL |
| `last_diff_value` | `last_diff_value(x, d)` | Time Series | ALL |
| `log` | `log(x)` | Arithmetic | ALL |
| `normalize` | `normalize(x, useStd = false, limit = 0.0)` | Cross Sectional | ALL |
| `pasteurize` | `pasteurize(x)` | Arithmetic | - |
| `quantile` | `quantile(x, driver = gaussian, sigma = 1.0)` | Cross Sectional | ALL |
| `rank` | `rank(x, rate=2)` | Cross Sectional | ALL |
| `reverse` | `reverse(x)` | Arithmetic | ALL |
| `scale` | `scale(x, scale=1, longscale=1, shortscale=1)` | Cross Sectional | ALL |
| `sign` | `sign(x)` | Arithmetic | ALL |
| `sqrt` | `sqrt(x)` | Arithmetic | ALL |
| `tail` | `tail(x, lower = 0, upper = 0, newval = 0)` | Transformational | - |
| `ts_arg_max` | `ts_arg_max(x, d)` | Time Series | ALL |
| `ts_arg_min` | `ts_arg_min(x, d)` | Time Series | ALL |
| `ts_av_diff` | `ts_av_diff(x, d)` | Time Series | ALL |
| `ts_backfill` | `ts_backfill(x,lookback = d, k=1)` | Time Series | ALL |
| `ts_count_nans` | `ts_count_nans(x ,d)` | Time Series | ALL |
| `ts_decay_linear` | `ts_decay_linear(x, d, dense = false)` | Time Series | ALL |
| `ts_delay` | `ts_delay(x, d)` | Time Series | ALL |
| `ts_delta` | `ts_delta(x, d)` | Time Series | ALL |
| `ts_ir` | `ts_ir(x, d)` | Time Series | - |
| `ts_kurtosis` | `ts_kurtosis(x, d)` | Time Series | - |
| `ts_max_diff` | `ts_max_diff(x, d)` | Time Series | - |
| `ts_mean` | `ts_mean(x, d)` | Time Series | ALL |
| `ts_product` | `ts_product(x, d)` | Time Series | ALL |
| `ts_quantile` | `ts_quantile(x,d, driver="gaussian" )` | Time Series | ALL |
| `ts_rank` | `ts_rank(x, d, constant = 0)` | Time Series | ALL |
| `ts_returns` | `ts_returns (x, d, mode = 1)` | Time Series | - |
| `ts_scale` | `ts_scale(x, d, constant = 0)` | Time Series | ALL |
| `ts_std_dev` | `ts_std_dev(x, d)` | Time Series | ALL |
| `ts_sum` | `ts_sum(x, d)` | Time Series | ALL |
| `ts_target_tvr_decay` | `ts_target_tvr_decay(x, lambda_min=0, lambda_max=1, target_tvr=0.1)` | Time Series | - |
| `ts_target_tvr_hump` | `ts_target_tvr_hump(x, lambda_min=0, lambda_max=1, target_tvr=0.1)` | Time Series | - |
| `ts_zscore` | `ts_zscore(x, d)` | Time Series | ALL |
| `winsorize` | `winsorize(x, std=4)` | Cross Sectional | ALL |
| `zscore` | `zscore(x)` | Cross Sectional | ALL |

### MATRIX_GENERATED (1)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `ts_step` | `ts_step(1)` | Time Series | ALL |

### VARIADIC (3)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `max` | `max(x, y, ..)` | Arithmetic | ALL |
| `min` | `min(x, y ..)` | Arithmetic | ALL |
| `multiply` | `multiply(x ,y, ... , filter=false), x * y` | Arithmetic | ALL |

### SELECT (2)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `if_else` | `if_else(input1, input2, input 3)` | Logical | ALL |
| `trade_when` | `trade_when(x, y, z)` | Transformational | ALL |

### BOOLEAN (10)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `and` | `and(input1, input2)` | Logical | ALL |
| `equal` | `input1 == input2` | Logical | ALL |
| `greater` | `input1 > input2` | Logical | ALL |
| `greater_equal` | `input1 >= input2` | Logical | ALL |
| `is_nan` | `is_nan(input)` | Logical | ALL |
| `less` | `input1 < input2` | Logical | ALL |
| `less_equal` | `input1 <= input2` | Logical | ALL |
| `not` | `not(x)` | Logical | ALL |
| `not_equal` | `input1!= input2` | Logical | ALL |
| `or` | `or(input1, input2)` | Logical | ALL |

### VECTOR (7)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `vec_avg` | `vec_avg(x)` | Vector | ALL |
| `vec_count` | `vec_count(x)` | Vector | - |
| `vec_max` | `vec_max(x)` | Vector | - |
| `vec_min` | `vec_min(x)` | Vector | - |
| `vec_range` | `vec_range(x)` | Vector | - |
| `vec_stddev` | `vec_stddev(x)` | Vector | - |
| `vec_sum` | `vec_sum(x)` | Vector | ALL |

### GROUP (9)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `group_backfill` | `group_backfill(x, group, d, std = 4.0)` | Group | ALL |
| `group_count` | `group_count(x, group)` | Group | - |
| `group_mean` | `group_mean(x, weight, group)` | Group | ALL |
| `group_neutralize` | `group_neutralize(x, group)` | Group | ALL |
| `group_rank` | `group_rank(x, group)` | Group | ALL |
| `group_scale` | `group_scale(x, group)` | Group | ALL |
| `group_std_dev` | `group_std_dev(x, group)` | Group | - |
| `group_sum` | `group_sum(x, group)` | Group | - |
| `group_zscore` | `group_zscore(x, group)` | Group | ALL |

### GROUPING (3)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `bucket` | `bucket(rank(x), range=“0, 1, 0.1”, skipBoth=False, NaNGroup=False) or bucket(rank(x), buckets = “2,5,6,7,10”, skipBoth=False, NaNGroup=False)` | Transformational | ALL |
| `densify` | `densify(x)` | Arithmetic | ALL |
| `group_cartesian_product` | `group_cartesian_product(g1, g2)` | Group | - |

---

## 6. Đối chiếu: bucket của ta vs category của platform

| Platform category | n | Bucket phân bố |
| --- | --- | --- |
| Time Series | 30 | MATRIX_UNARY 26 · MATRIX_BINARY 3 · MATRIX_GENERATED 1 |
| Arithmetic | 16 | MATRIX_UNARY 7 · MATRIX_BINARY 5 · VARIADIC 3 · GROUPING 1 (`densify`) |
| Logical | 11 | BOOLEAN 10 · SELECT 1 (`if_else`) |
| Group | 10 | GROUP 9 · GROUPING 1 (`group_cartesian_product`) |
| Cross Sectional | 7 | MATRIX_UNARY 6 · MATRIX_BINARY 1 (`vector_neut`) |
| Vector | 7 | VECTOR 7 |
| Transformational | 3 | GROUPING 1 (`bucket`) · SELECT 1 (`trade_when`) · MATRIX_UNARY 1 (`tail`) |

**Điểm đáng chú ý:** `category` của platform là **hữu ích để đọc** nhưng **không đủ để dựng alpha** — cùng một category trải trên nhiều bucket với ý nghĩa khác nhau (`Arithmetic` có cả unary, binary, variadic lẫn grouping).

---

## 7. Cách sinh lại bảng

```bash
uv run main.py
```

- Lần đầu: `GET /operators` → phân loại → ghi `cache/operators.csv`.
- Từ lần sau: file đã có trên đĩa → **không gọi platform, không tốn login**.
- Xoá `cache/operators.csv` → lần chạy sau sẽ fetch lại (cần `LOGIN_ALLOW = True`).

Cấu trúc CSV:

| Cột | Nguồn |
| --- | --- |
| `name` | `name` của payload |
| `category` | bucket do `OperatorTable.bucket_of()` suy ra |
| `expression` | `definition`, đã collapse whitespace (vì `bucket` ship nhiều dòng) |
| `description` | `description` của payload |

`cache/operators.csv` nằm trong `.gitignore` — nó là artifact runtime, tái sinh được từ platform.

### 7.1 API

Toàn bộ logic nằm trong class `OperatorTable` (`Functions/operators.py`):

| Thành phần | Kiểu | Việc |
| --- | --- | --- |
| `OperatorTable(data, path=OPERATORS_CSV_PATH)` | instance | Giữ session và đường dẫn đích |
| `.fetch()` | instance | GET `/operators`, phân loại, ghi CSV → trả về `DataFrame` |
| `.load(path=OPERATORS_CSV_PATH)` | staticmethod | Đọc CSV từ đĩa → trả về `DataFrame`, `category` là ordered categorical |
| `.arg_names(definition)` | staticmethod | Tên đối số top-level của call đầu tiên |
| `.bucket_of(name, definition, category, args)` | staticmethod | Bucket của một operator |

`arg_names` và `bucket_of` là `staticmethod` vì chúng là quy tắc thuần tuý — không phụ thuộc session hay đường dẫn. `load` cũng vậy: đọc từ đĩa không cần session.

### 7.2 Thứ tự xử lý trong `main.py`

Sau khi login, `main.py` xử lý `/operators` **trước** catalog:

| `cache/operators.csv` | `LOGIN_ALLOW` | Hành động |
| --- | --- | --- |
| Có | bất kỳ | `load()` — không gọi platform, không tốn login |
| Không | `True` | `fetch()` — dùng session vừa mở, ghi lại CSV |
| Không | `False` | Báo lỗi và dừng — không có gì để load, cũng không được phép fetch |

---

## 8. Giới hạn đã biết

| Vấn đề | Trạng thái |
| --- | --- |
| `OperatorTable.arg_names()` chỉ parse **call đầu tiên** trong definition | Nested call (`bucket(rank(x), ...)`) không đóng góp argument của riêng nó → kết quả là **cận dưới** của arity thật. Không ảnh hưởng 84 operator hiện tại vì `bucket` / `densify` đã hard-code. |
| Definition của operator so sánh (`equal`, `less`, …) là **không có ngoặc** | `OperatorTable.arg_names()` trả về rỗng → chúng không thể là SELECT. Đúng như mong muốn (chúng là BOOLEAN), nhưng là hệ quả chứ không phải thiết kế. |
| Bảng không còn hiệu lực khi platform đổi operator | Không có timestamp. Xoá `cache/operators.csv` để fetch lại. |
| `COMBO` và `SELECTION` scope chưa được phân loại | Tài liệu này chỉ phủ `REGULAR`. |
