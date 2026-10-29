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

Tài liệu này gồm ba phần: **§1–§7** mô tả bảng phân loại 84 operator (sinh từ `/operators`), **§8** mô tả phần dựng FASTEXPR từ operator đó (`MatrixBinary`, `MatrixUnary`, `Vector`, `Group` + sampler), và **§10** chốt trạng thái giai đoạn 1 (expression cơ bản) làm đầu vào cho giai đoạn 2.

---

## 2. Vì sao phải tự phân loại

Payload của `/operators` **không** chứa thông tin kiểu data field. Nó chỉ có:

```
name · category · scope · definition · description · documentation · level
```

Trong đó `category` là do platform grade (Arithmetic, Time Series, Logical, Group, Cross Sectional, Vector, Transformational) — nó phân loại theo **ý nghĩa toán học**, không phải theo **kiểu dữ liệu** mà operator chạm vào.

Hai điều suy ra được từ `category` là sai với mục đích dựng alpha:

- `if_else` được grade là `Logical`, nhưng nó là **value selector** (chọn giữa hai giá trị), không phải mask 0/1 → không thuộc nhóm BOOLEAN.
- `max` / `min` nằm trong `Arithmetic`, nhưng chúng nhận **số lượng field không cố định** → không phải unary/binary thông thường.

Vì vậy bảng dưới đây dùng **9 bucket riêng**, tách bạch khỏi `category` của platform.

---

## 3. Chín bucket và ý nghĩa

Các bucket đi theo **chiều data flow** mà một FASTEXPR đi qua. Thứ tự khai báo cũng là thứ tự dòng trong CSV — đọc file từ trên xuống là đi đúng đường đi của một biểu thức.

| Bucket | Ý nghĩa | Số |
| --- | --- | --- |
| `MATRIX_BINARY` | Nhận đúng **hai** matrix field → nơi hai field độc lập gặp nhau, biểu đạt được quan hệ pairwise | 10 |
| `MATRIX_UNARY` | Nhận **một** matrix field | 40 |
| `MATRIX_GENERATED` | Không nhận matrix field nào — tự sinh ra chuỗi đếm ngày (`ts_step`) | 1 |
| `VARIADIC` | Nhận số lượng matrix field **không cố định** | 2 |
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
| VARIADIC | definition chứa `..` **nhưng không** chứa `...` |

Ba luật còn lại **không** đọc được từ payload, phải suy ra riêng:

### 4.1 `bucket` và `densify` — hard-code theo tên

Hai operator này được xếp vào `GROUPING` vì typing của chúng chỉ được nói trong **prose description**, không nói trong definition. Không thể match theo từ khoá trong description một cách an toàn — ngày nào WorldQuant đổi cách diễn đạt là toàn bộ phân loại âm thầm sai.

### 4.2 `group_cartesian_product` — tự rơi ra

Đây là operator `group_` **duy nhất** không nhắc tới argument `group` (`group_cartesian_product(g1, g2)` — nó tự tạo ra group). Nên luật "GROUP nếu có chữ `group`" loại nó ra, và nó rơi vào `GROUPING` mà không cần hard-code.

### 4.3 SELECT — suy ra từ hình dạng argument

Một operator là SELECT khi **tất cả** argument của nó đều là data field, và có **từ 3 trở lên**.

Điểm dễ hiểu sai: platform dùng **hai** ký hiệu variadic khác nhau — `..` (hai chấm) và `...` (ba chấm). Luật VARIADIC chỉ bắt `..`, nên `multiply` — vốn dùng ba chấm — **không** rơi vào VARIADIC.

| Operator | Definition | Ký hiệu | Bucket |
| --- | --- | --- | --- |
| `max` | `max(x, y, ..)` | `..` hai chấm | VARIADIC |
| `min` | `min(x, y ..)` | `..` hai chấm | VARIADIC |
| `multiply` | `multiply(x ,y, ... , filter=false), x * y` | `...` ba chấm | MATRIX_BINARY |

`multiply` nhận hai matrix field (`x`, `y`) nên được đếm như `add` và `subtract`: đây là điểm nhất quán giữa **hình thức** (ký hiệu platform dùng) và **typing** (số field thực sự tiêu thụ).

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
- **VARIADIC trước MATRIX_*.** `max` / `min` có 2 argument data field (`x`, `y`) nên nếu đến bước MATRIX sẽ bị đếm là binary — sai, chúng nhận bao nhiêu field tuỳ ý. `multiply` không dính luật này vì nó dùng ký hiệu ba chấm, nên nó đi xuống bước MATRIX và ra MATRIX_BINARY.

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

### MATRIX_BINARY (10)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `add` | `add(x, y, filter = false), x + y` | Arithmetic | ALL |
| `divide` | `divide(x, y), x / y` | Arithmetic | ALL |
| `multiply` | `multiply(x ,y, ... , filter=false), x * y` | Arithmetic | ALL |
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

### VARIADIC (2)

| Operator | Expression | Platform category | Level |
| --- | --- | --- | --- |
| `max` | `max(x, y, ..)` | Arithmetic | ALL |
| `min` | `min(x, y ..)` | Arithmetic | ALL |

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
| Arithmetic | 16 | MATRIX_UNARY 7 · MATRIX_BINARY 6 · VARIADIC 2 · GROUPING 1 (`densify`) |
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

Phần **dựng expression** nằm ở class khác trong cùng file: `MatrixBinary` (bucket `MATRIX_BINARY`) — xem §8.

### 7.2 Thứ tự xử lý trong `main.py`

Sau khi login, `main.py` xử lý `/operators` **trước** catalog:

| `cache/operators.csv` | `LOGIN_ALLOW` | Hành động |
| --- | --- | --- |
| Có | bất kỳ | `load()` — không gọi platform, không tốn login |
| Không | `True` | `fetch()` — dùng session vừa mở, ghi lại CSV |
| Không | `False` | Báo lỗi và dừng — không có gì để load, cũng không được phép fetch |

---

## 8. Sinh expression từ operator: `MatrixBinary`, `MatrixUnary`, `Vector`, `Group`

Bảng ở §5 cho biết **operator nào** tồn tại. Các class trong `Functions/operators.py` là phần **dựng expression** từ operator đó: với mỗi operator trong bucket tương ứng, chúng dựng một lời gọi FASTEXPR hoàn chỉnh với field thật và các tham số được rút ra ngẫu nhiên (hoặc nhận trực tiếp để reproduce).

File này có **bốn** class dựng expression, cộng hai sampler:

| Class | Việc |
| --- | --- |
| `MatrixBinary` | 10 operator của bucket `MATRIX_BINARY` **+ `if_else`** (bucket `SELECT`) — xem §8.1–§8.3 |
| `MatrixUnary` | 40 operator của bucket `MATRIX_UNARY` **+ `trade_when`** (bucket `SELECT`) — xem §8.6 |
| `Vector` | 7 operator của bucket `VECTOR`, không có tham số rút — xem §8.7 |
| `Group` | 9 operator của bucket `GROUP`, kèm 5 chế độ dựng group — xem §8.7 |
| `IntegerSampler`, `FloatSampler` | Rút tham số số ngẫu nhiên (window `d`, `lag`, `rettype`, `std`, v.v.) — xem §8.4–§8.5 |

`if_else` và `trade_when` là hai operator duy nhất của bucket `SELECT`; chúng nằm trong class matrix vì builder của chúng chỉ nhận field matrix. Hệ quả: `profile["category"]` của chúng là `MATRIX_BINARY` / `MATRIX_UNARY`, **không** phải `SELECT` như bảng §5 (xem §10.3).

### 8.1 Return type: tuple `(expression, profile)`

Tất cả builders return **tuple** `(str, OperatorProfile)`:

```python
expression, profile = MatrixBinary.get("ts_corr", "field_a", "field_b")
# expression = 'ts_corr(field_a, field_b, 114)'
# profile = {"category": "MATRIX_BINARY", "name": "ts_corr", "config": {"d": 114}}
```

- **`expression`** (str): FASTEXPR hoàn chỉnh, ready-to-submit lên BRAIN API.
- **`profile`** (OperatorProfile): metadata chứa `category`, `name`, và `config` — dùng để audit trail và reproduce bit-exact.

**`OperatorProfile` structure:**

```python
OperatorProfile = TypedDict(
    "OperatorProfile",
    {
        "category": str,
        "name": str,
        "config": dict[str, int | bool | float | str],
        "implicit": list[dict[str, str]],
    },
)
```

| Key | Kiểu | Nghĩa |
| --- | --- | --- |
| `category` | `str` | Bucket của operator (e.g. `MATRIX_BINARY`, `MATRIX_UNARY`) |
| `name` | `str` | Tên operator theo đúng cách platform viết |
| `config` | `dict[str, int \| bool \| float \| str]` | Tất cả tham số **được rút ngẫu nhiên** hoặc **truyền vào** — đủ để reproduce bit-exact expression |
| `implicit` | `list[dict[str, str]]` | Các operator call mà operator này **kéo theo sẵn** — không có `config` vì tham số cố định bởi definition của platform |

**Operator kéo theo (`implicit`):** một số operator của platform tự chứa lời gọi operator khác trong definition của nó. Những lời gọi đó **không** xuất hiện trong `get()` nên phải khai báo tường minh:

| Operator | Kéo theo |
| --- | --- |
| `group_*` mode 2 | `densify` |
| `group_*` mode 3 | `densify`, `bucket`, `rank` |
| `group_*` mode 4, 5 | `densify`, `group_cartesian_product`, `bucket`, `rank` |
| `group_backfill` | `ts_rank` (ngoài các operator theo mode) |
| `group_mean` weight mode 5 | `ts_step` (ngoài các operator theo mode) |
| `if_else` | `ts_rank` (mỗi operand chưa được rank); thêm `ts_sum` khi `mode=1` |
| `trade_when` | `ts_rank`, `ts_zscore`, `abs` |
| `tail` | `ts_rank` |
| `winsorize` | `ts_rank` |
| `sqrt` | `if_else`, `sign`, `sqrt`, `abs` |

Ví dụ:

```python
expression, profile = MatrixBinary.ts_regression("field_a", "field_b")
# expression = 'ts_regression(field_b, field_a, 70, lag=0, rettype=1)'
# profile = {"category": "MATRIX_BINARY", "name": "ts_regression", "config": {"d": 70, "lag": 0, "rettype": 1}, "implicit": []}
```

### 8.2 Reproducibility: signature nhận parameters như optional arguments

Tất cả builders hỗ trợ **hai chế độ**:

**1. Random sampling (default)** — không truyền parameters:
```python
expr, profile = MatrixBinary.ts_corr("field_a", "field_b")
# expr = 'ts_corr(field_a, field_b, 114)'
# profile = {"category": "MATRIX_BINARY", "name": "ts_corr", "config": {"d": 114}}
```

**2. Bit-exact replay** — truyền parameters từ `config` để reproduce:
```python
expr2, _ = MatrixBinary.ts_corr("field_a", "field_b", d=114)
# expr2 = 'ts_corr(field_a, field_b, 114)'  # giống hệt expr
```

**Pattern:** mọi parameter trong `config` xuất hiện trong signature như optional argument (`d=None`, `lag=None`, `rettype=None`). Builder chỉ sample khi parameter là `None`:

```python
def ts_corr(x: str, y: str, d: int | None = None, *, distribution="balanced"):
    if d is None:
        d = IntegerSampler.sample(WINDOW_DAYS, None, WINDOW_STREAM, distribution)
    return _profile("ts_corr", {"d": d}, f"ts_corr({x}, {y}, {d})")
```

**`config` của từng operator bucket:**

| Bucket | Operators | Sampled parameters |
| --- | --- | --- |
| `MATRIX_BINARY` | `add`, `divide`, `multiply`, `power`, `signed_power`, `subtract`, `vector_neut` | Không có (expression deterministic) |
| | `ts_corr`, `ts_covariance` | `d` (window) |
| | `ts_regression` | `d` (window), `lag`, `rettype` |
| | `if_else` (bucket `SELECT`) | `s1`, `s2` (float), `dx`, `dy` (window, chỉ khi operand được bọc `ts_rank`), `mode` (0/1), `dz` (window `ts_sum`, chỉ khi `mode=1`) |
| `MATRIX_UNARY` | `abs_`, `inverse`, `log`, `pasteurize`, `reverse`, `sign`, `sqrt`, `zscore`, `days_from_last_change` | Không có |
| | 23 ts_* operators | `d` (window), một số có `mode`, `driver`, `dense`, `k` |
| | `hump` | `hump` (float) |
| | `kth_element` | `d`, `k` |
| | `last_diff_value` | `d` |
| | `normalize` | `use_std` (bool), `limit` (float) |
| | `quantile` | `driver`, `sigma` (float) |
| | `rank` | `rate` (float) |
| | `scale` | `book_size`, `long_scale` (float), `short_scale` (float) |
| | `tail` | `d`, `lower` (float), `upper` (float), `newval` (float) |
| | `ts_target_tvr_decay`, `ts_target_tvr_hump` | `lambda_min` (float), `lambda_max` (float), `target_tvr` (float) |
| | `winsorize` | `std` (float), `window` |
| | `trade_when` (bucket `SELECT`) | `t1`, `t2` (float), `d1`, `d2` (window) |

`config` chỉ chứa tham số **được sample hoặc truyền vào** — đủ để tái tạo bit-exact expression. Tham số cố định của operator (ví dụ `filter=true` của `add`/`multiply`/`subtract`) **không** nằm trong `config` vì chúng không đổi.

### 8.3 Thứ tự field: `x, y` hay `y, x`

Platform đặt tên tham số **không nhất quán** giữa các operator: `ts_corr(x, y, d)` nhưng `ts_covariance(y, x, d)` và `ts_regression(y, x, d, …)`.

Builders trong `MatrixBinary` xử lý thứ tự đúng theo platform:

| Operator | Thứ tự tham số field |
| --- | --- |
| `ts_corr` | `(x, y, d)` |
| `ts_covariance`, `ts_regression` | `(y, x, d, ...)` |

Đây là lý do class tách `get()` (dispatch theo tên) khỏi từng builder (mỗi builder biết thứ tự riêng của nó).

### 8.4 Rút tham số số: uniform và balanced

Các tham số ngẫu nhiên (`d`, `lag`, `rettype`, `std`, `hump`, v.v.) được rút từ `IntegerSampler.sample()` hoặc `FloatSampler.sample()`. Mỗi tham số nằm trên một **entropy stream riêng** nên thêm tham số mới không làm đổi giá trị của tham số cũ.

**Streams trong `MatrixBinary`:**

| Tham số | Stream | Khoảng | Distribution default | Áp dụng |
| --- | --- | --- | --- | --- |
| `d` | `WINDOW_STREAM = 1` | `WINDOW_DAYS = (1, 252)` | `"balanced"` | `ts_corr`, `ts_covariance`, `ts_regression` |
| `rettype` | `RETTYPE_STREAM = 2` | `(0, 9)` | `"uniform"` | `ts_regression` |
| `lag` | `LAG_STREAM = 3` | `(0, 5)` | `"uniform"` | `ts_regression` |
| `s1`, `s2` | 1, 2 | `(1.0, 2.0)` | theo `distribution` | `if_else` |
| `dx`, `dy` | 3, 4 | `(60, 252)` | theo `distribution` | `if_else` (xem dưới) |
| `mode` | 5 | `(0, 1)` | `"uniform"` | `if_else` |
| `dz` | 6 | `(10, 52)` | theo `distribution` | `if_else`, chỉ khi `mode=1` |

`if_else` dùng stream số thẳng trong hàm (1 đến 6), không dùng hằng `*_STREAM` của class, nên số 3 của `dx` trùng số của `LAG_STREAM`. Không xung đột vì `if_else` luôn gọi với `seed=None`; nếu sau này truyền seed cố định thì phải đổi thành hằng riêng.

**`if_else` bọc `ts_rank` quanh operand.** Operand `x` (hoặc `y`) chưa bắt đầu bằng `ts_rank(`, `rank(`, `scale(`, `ts_scale(` thì được bọc `ts_rank(·, dx)` (hoặc `dy`), với `dx`, `dy` rút **độc lập** từ `[60, 252]`. Operand đã là rank operator thì giữ nguyên và **không** có `dx`/`dy` trong `config`. Trước đây window này là hằng 252, nên alpha `if_else` cũ không sinh lại giống hệt.

**`if_else` có hai `mode`.** `mode` rút đều từ `{0, 1}` và luôn nằm trong `config`.
- `mode=0`: `if_else(s1 * _x > s2 * _y, _x, _y)`, như trước.
- `mode=1`: `ts_sum(if_else(s1 * _x > s2 * _y, 1, 0), dz)`, với `dz` rút từ `[10, 52]`. Chỉ trả 0/1 thì tín hiệu nghèo, nên chỉ báo được cộng dồn qua `dz` ngày. `ts_sum` được ghi vào `implicit` của profile.

Hệ quả với alpha cũ: `if_else` mới có thêm khoá `mode` trong `config`, nên profile cũ (không có `mode`) khi `replicate` sẽ rút lại `mode` ngẫu nhiên thay vì phát lại `mode=0`.

**Distribution modes:**

- **`"uniform"`**: mọi giá trị trong khoảng có xác suất bằng nhau.
- **`"balanced"`**: khoảng được chia thành **5 quintile buckets theo tỉ lệ** `(5/252, 22/252, 66/252, 126/252)` của kích thước khoảng, mỗi bucket được chọn với xác suất 20%, rồi một giá trị bên trong bucket đó được chọn đều.

Với `WINDOW_DAYS = (1, 252)`, 5 buckets là: `1-5`, `6-22`, `23-66`, `67-126`, `127-252`.

**Convention:**
- **Window parameters** (`d` trong time-series operators) dùng `"balanced"` — tránh sample quá nhiều window ngắn (1-5 ngày) hoặc quá dài (200+ ngày).
- **Enum parameters** (`lag`, `rettype`, `mode`) dùng `"uniform"` — chúng là discrete choices, không phải horizons.
- **Float parameters** (`std`, `sigma`, `rate`, `hump`, `limit`) dùng `FloatSampler` với `"uniform"` hoặc `"balanced"` tuỳ ý nghĩa parameter.

Verified: tất cả `IntegerSampler.sample(WINDOW_DAYS, ...)` trong codebase đều dùng `distribution="balanced"`.

### 8.5 Bit-exact và replay từ seed

`IntegerSampler.sample` nhận `seed` và `stream`; `(seed, stream, value_range, distribution)` cố định ⇒ ra **cùng một số**, bit-exact. `seed=None` lấy entropy mới từ CSPRNG của OS mỗi lần gọi.

**Replay từ config (recommended):**
```python
# Lần 1: sample random
expr, profile = MatrixBinary.ts_regression("field_a", "field_b")
# profile = {"category": "MATRIX_BINARY", "name": "ts_regression", "config": {"d": 70, "lag": 2, "rettype": 1}}

# Lần 2: replay bit-exact từ config
expr2, _ = MatrixBinary.ts_regression("field_a", "field_b", d=70, lag=2, rettype=1)
# expr2 == expr (bit-exact)
```

**Replay từ seed (legacy, ít dùng):**
```python
# Khi muốn nhiều operators dùng chung một window
expr1, _ = MatrixBinary.ts_corr("a", "b", seed=42)        # d=114
expr2, _ = MatrixBinary.ts_covariance("a", "b", seed=42)  # d=114
expr3, _ = MatrixBinary.ts_regression("a", "b", seed=42)  # d=114, lag=3, rettype=7
```

Lưu ý: `seed` replay chỉ cố định được **stream 1** (window `d`) — các streams khác (`lag`, `rettype`) vẫn random. Để cố định tất cả, phải truyền tất cả parameters vào signature.

**`replicate(profile, ...)` — replay từ profile, một hàm cho mỗi class.** Thay vì tự trải `config` ra keyword argument, mỗi class có `replicate` nhận chính `OperatorProfile` và toán hạng, rồi gọi lại builder với đúng `config` đã ghi:

| Class | Signature | Ghi chú |
| --- | --- | --- |
| `MatrixBinary` | `replicate(profile, x, y)` | gọi `getattr(MatrixBinary, name)(x, y, **config)` |
| `MatrixUnary` | `replicate(profile, x)` | đổi tên khoá `config` về tên tham số builder qua `CONFIG_PARAMETER`; bỏ `ignore` của `kth_element`; `abs` gọi `abs_` |
| `Vector` | `replicate(profile, x)` | không có tham số rút |
| `Group` | `replicate(profile, x, group)` | đổi `"True"/"False"` về 0/1, `std` về `float` |
| `Variadic` | `replicate(profile, operands)` | giữ nguyên thứ tự operand |

`MatrixUnary.CONFIG_PARAMETER` tồn tại vì `config` ghi một số tham số theo tên platform (`useStd`, `lookback`, `scale`, `longscale`, `shortscale`) trong khi builder dùng `use_std`, `d`, `book_size`, `long_scale`, `short_scale`. `kth_element` ghi `ignore` nhưng đó là hàm của `k`, builder tự suy ra nên `replicate` không truyền.

`Group` mode 3, 4, 5 rút `bucket_range` (`[min, max, step]`) ngẫu nhiên. Trước đây nó **không** nằm trong `config`, nên replay ra text khác. Nay mọi `group_*` ghi `bucket_range` vào `config` khi `mode >= 3` (mode 1 và 2 không render nó). Expression sinh ra không đổi: snapshot 260 expression Group trước và sau sửa giống hệt.

Replay cả một expression nhiều tầng từ profile của `ExpressionBuilder`: xem `Docs/expression-builder.md` §6.

### 8.6 `MatrixUnary` — 40 operators nhận 1 field

Class `MatrixUnary` xử lý bucket `MATRIX_UNARY` (40 operators). Pattern giống hệt `MatrixBinary`:

**Signature:**
```python
MatrixUnary.get(name: str, x: str, *, distribution: Literal["uniform", "balanced"] = "uniform") -> tuple[str, OperatorProfile]
```

**Example:**
```python
# Random sampling
expr, profile = MatrixUnary.ts_mean("close")
# expr = 'ts_mean(close, 96)'
# profile = {"category": "MATRIX_UNARY", "name": "ts_mean", "config": {"d": 96}}

# Bit-exact replay
expr2, _ = MatrixUnary.ts_mean("close", d=96)
# expr2 == expr
```

**31 operators có sampled parameters**, ví dụ:
- `ts_mean(x, d)` — signature: `ts_mean(x: str, d: int | None = None, *, distribution="balanced")`
- `normalize(x, useStd, limit)` — signature: `normalize(x: str, use_std: bool | None = None, limit: float | None = None, *, distribution="uniform")`
- `scale(x, bookSize, longscale, shortscale)` — signature: `scale(x: str, book_size: int | None = None, long_scale: float | None = None, short_scale: float | None = None, *, distribution="uniform")`

**9 operators không có parameters** (deterministic):
`abs_`, `days_from_last_change`, `inverse`, `log`, `pasteurize`, `reverse`, `sign`, `sqrt`, `zscore`

**`trade_when` (bucket `SELECT`, nằm trong `MatrixUnary`).** Một field `x`, dựng:

```
trade_when(ts_rank(x, d1) > t1, x, abs(ts_zscore(x, d2)) < t2)
```

Signature: `trade_when(x, t1=None, t2=None, d1=None, d2=None, *, distribution="balanced")`. `t1`, `t2` rút từ `[0, 0.1]`; `d1`, `d2` rút độc lập từ `[60, 252]`; cả bốn theo `distribution`. `config = {"t1", "t2", "d1", "d2"}`. Range `[60, 252]` do user chọn, **khác** `WINDOW_DAYS = (1, 252)` của các `ts_*` còn lại.

### 8.7 `Vector` và `Group`

**`Vector`** (7 operator `vec_*`): `Vector.get(name, x)`, không tham số rút, `config` luôn rỗng. Tên lạ thì `get` raise `ValueError`.

**`Group`** (9 operator `group_*`): `Group.get(name, x, group, *, ...)`. Ngoài tham số riêng từng operator (`d`, `std`, `window` cho `group_backfill`; `weight_mode` cho `group_mean`), mọi operator có `mode` rút đều từ `{1..5}` quyết định cách dựng group:

| `mode` | Group truyền vào operator |
| --- | --- |
| 1 | `group` nguyên gốc |
| 2 | `densify(group)` |
| 3 | `densify(bucket(rank(x), range=…, skipBoth=…, NaNGroup=…))` |
| 4 | `densify(group_cartesian_product(bucket(rank(x), …), group))` |
| 5 | **cùng chuỗi với mode 4** (xem §10.3) |

`bucket` nhận `range='min, max, step'` rút từ `BUCKET_MIN_RANGE`, `BUCKET_MAX_RANGE`, `BUCKET_STEP_RANGE`, cộng hai cờ `skipBoth`, `NaNGroup` rút `{0, 1}`. Với `mode >= 3`, `config` ghi thêm `bucket_range = [min, max, step]`; `skip_both` và `nan_group` được ghi dạng chuỗi `"True"`/`"False"`. `group_backfill` bọc `x` bằng `ts_rank(x, window)` trước khi dùng.

---

## 9. Giới hạn đã biết

| Vấn đề | Trạng thái |
| --- | --- |
| `OperatorTable.arg_names()` chỉ parse **call đầu tiên** trong definition | Nested call (`bucket(rank(x), ...)`) không đóng góp argument của riêng nó → kết quả là **cận dưới** của arity thật. Không ảnh hưởng 84 operator hiện tại vì `bucket` / `densify` đã hard-code. |
| Definition của operator so sánh (`equal`, `less`, …) là **không có ngoặc** | `OperatorTable.arg_names()` trả về rỗng → chúng không thể là SELECT. Đúng như mong muốn (chúng là BOOLEAN), nhưng là hệ quả chứ không phải thiết kế. |
| Bảng không còn hiệu lực khi platform đổi operator | Không có timestamp. Xoá `cache/operators.csv` để fetch lại. |
| `COMBO` và `SELECTION` scope chưa được phân loại | Tài liệu này chỉ phủ `REGULAR`. |
| 3 bucket chưa có builder (14 operator) | `MATRIX_GENERATED` (1), `BOOLEAN` (10), `GROUPING` (3) — xem §10.2. |
| `Group` mode 4 và mode 5 sinh **cùng một chuỗi** | Chưa sửa, xem §10.3. |

---

## 10. Giai đoạn 1 đã chốt, đầu vào cho giai đoạn 2

Giai đoạn 1 là dựng **expression cơ bản**: mỗi operator có builder trả `(expression, profile)`, tham số rút ngẫu nhiên khi để `None` và replay được từ `config`. Trạng thái chốt ngày **2026-10-26**.

### 10.1 Đã có builder: 70 / 84 operator

| Class | Bucket | Số operator |
| --- | --- | --- |
| `MatrixBinary` | `MATRIX_BINARY` 10 + `SELECT` 1 (`if_else`) | 11 |
| `MatrixUnary` | `MATRIX_UNARY` 40 + `SELECT` 1 (`trade_when`) | 41 |
| `Vector` | `VECTOR` | 7 |
| `Group` | `GROUP` | 9 |
| `Variadic` | `VARIADIC` | 2 |
| | **Tổng** | **70** |

Cách kiểm: chạy từng tên operator của CSV qua `get()` của class tương ứng; tên nào `get()` từ chối (`KeyError`/`ValueError`) thì tính là chưa có builder. `main.py` in một ví dụ cho mỗi builder (`if_else` trong vòng binary, `trade_when` trong vòng unary).

### 10.2 Chưa có builder: 14 operator

| Bucket | Số | Operator |
| --- | --- | --- |
| `MATRIX_GENERATED` | 1 | `ts_step` |
| `BOOLEAN` | 10 | `and`, `equal`, `greater`, `greater_equal`, `is_nan`, `less`, `less_equal`, `not`, `not_equal`, `or` |
| `GROUPING` | 3 | `bucket`, `densify`, `group_cartesian_product` |

Bucket `BOOLEAN` không có builder vì phần lớn operator trong đó là **so sánh infix** (`input1 > input2`), không phải function call: `OPERATOR_CALL` trong `main.py` chỉ match `name(`, nên một expression có điều kiện boolean sẽ bị đếm thiếu trong ngân sách operator. Cần sửa bộ đếm trước khi viết builder cho nhóm này.

`bucket`, `densify`, `group_cartesian_product` đã xuất hiện **bên trong** expression do `Group` dựng (mode 2 đến 5), nhưng chưa có builder độc lập.

### 10.3 Điểm lệch cần biết trước khi sang giai đoạn 2

| # | Điểm lệch | Trạng thái |
| --- | --- | --- |
| 1 | `Group` mode 4 và mode 5 sinh **cùng một chuỗi** `densify(group_cartesian_product(bucket(...), group))`. Đã chạy trên 4 operator và đọc mã cả 9: mode 5 chỉ đổi chỗ đặt `densify`, kết quả giống mode 4. Hệ quả: `mode` rút đều `{1..5}` nhưng chỉ có 4 dạng expression khác nhau, dạng này chiếm 40% thay vì 20%. | **Chưa sửa.** Chưa rõ mode 5 định dựng gì khác; chờ quyết định. |
| 2 | `profile["category"]` của `if_else`, `trade_when` là `MATRIX_BINARY`, `MATRIX_UNARY`, trong khi bảng §5 xếp chúng vào `SELECT`. | Chưa sửa. |
| 3 | `if_else` (`dx`, `dy`) và `trade_when` (`d1`, `d2`) rút window từ `[60, 252]` viết thẳng trong hàm, khác `WINDOW_DAYS = (1, 252)` của các `ts_*`. | Theo yêu cầu user, chưa có hằng chung. |
| 4 | `OperatorProfile.config` khai báo `dict[str, int \| bool]` nhưng thực tế chứa cả `float` và `str`. | Chưa sửa. |

### 10.4 Profile của một expression

`ExpressionBuilder.build` trả tuple `(expression, profile)`. Profile mô tả **toàn bộ** expression, dựng bằng cách đi trên cây đã build chứ không parse text render.

```python
{
  "expression": "...",
  "operator_count": 13,
  "data": {
    "fields": [ {metadata catalog đầy đủ của từng field, cộng "type"} ],
    "group":  {metadata catalog đầy đủ của GROUP field, hoặc null}
  },
  "levels": {
    "leaf": { "<tên operator>": [ {profile của lần gọi}, ... ] },
    "join": { ... },
    "post": { ... }
  },
  "counts": {
    "operators_per_level": {"leaf": 6, "join": 2, "post": 1},
    "operators_per_category": {"MATRIX_UNARY": 3, "GROUP": 1, ...},
    "n_data_fields": 3,
    "n_distinct_operators": 5
  },
  "tree": { "level": ..., "operators": [...], "children": [...] }
}
```

**`tree`:** cây operator mà `ExpressionBuilder.replicate` đọc để dựng lại expression. `levels` chỉ gom operator theo tên nên không nói được operator nào bọc operator nào; `tree` giữ thông tin đó. Chi tiết ở `Docs/expression-builder.md` §5.4 và §6.

**Ba tầng (`levels`):**

| Tầng | Nội dung |
| --- | --- |
| `leaf` | Operator bọc **một field** — `vec_*` của field VECTOR, rồi 0..2 wrapper `MATRIX_UNARY` / `GROUP` |
| `join` | Operator **ghép** các node — `MATRIX_BINARY`, `VARIADIC`, và operator kéo theo của chúng |
| `post` | Operator phủ **lên cây đã join** — transform của giá trị đã kết hợp |

**`data`:** `fields` là các field làm lá của expression, mỗi field kèm **19 cột metadata** từ catalog (`fieldid`, `type`, `field_description`, `categoryid`, `coverage`, `dateCoverage`, `dataset_valueScore`, `pyramidMultiplier`, …). `group` là field GROUP mà mọi operator `group_*` dùng để gom nhóm.

**Hai điểm cần biết khi đọc profile:**

1. **Số lần gọi trong profile ≠ số lần xuất hiện trong text.** Một số operator render lại argument của nó (`group_*` mode 3/4/5 nhúng `x` vào `bucket(rank(x))`; `trade_when` render 3 lần; `if_else` render operand 2 lần), nên text đếm *rendered occurrence* còn profile đếm *logical call*. Invariant đúng để verify profile là **coverage hai chiều theo tên operator**, không phải theo số lần.

2. **`rank` của scale-fix không có trong `levels`.** Khi join dùng operator scale-sensitive (`add`, `subtract`, `multiply`, `signed_power`, `max`, `min`), generator bọc mỗi operand trong `rank(x)` để chúng cùng scale. Đó là **scaffolding bắt buộc để hai operand cùng scale**, không phải lựa chọn của generator, nên nó không được ghi vào `levels`. Nếu có, nó sẽ chiếm ~40% lượt operator và làm mờ phần thông tin còn lại. Nó chỉ xuất hiện trong `tree` dưới dạng node `level = "rank"` không có operator, để `replicate` đặt lại đúng chỗ.

### 10.5 Giai đoạn 2

Phạm vi giai đoạn 2 chưa được ghi ở file nào trong repo. Mục này để trống đến khi user chốt.
