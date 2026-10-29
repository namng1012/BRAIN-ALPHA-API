# `ExpressionBuilder`: sinh FASTEXPR nhiều tầng, profile và replicate

**Trạng thái: đã triển khai trong `main.py`.** Tài liệu này mô tả **bộ sinh** (cú pháp, ngân sách operator, cấu trúc, profile, replicate) và các phép đo tính đúng của nó. Nó **không** nói expression nào có alpha tốt: dự án chưa có local oracle để đo điều đó (xem `Docs/expression-search-experimental.md` §1).

Quy tắc xuyên suốt: **không đổi quy tắc của bất kỳ primitive operator nào** (`Functions/operators.py`). Mọi thứ ở đây nằm ở lớp ghép (composition layer) phía trên chúng.

## 1. Vai trò và API

`ExpressionBuilder(catalog, scope, theme, operator_limit, join_cost, post_wrappers)` gồm ba việc:

| Method | Việc |
| --- | --- |
| `draw_fields(n)` | Rút `n` field MATRIX/VECTOR khác nhau kèm metadata đầy đủ |
| `build(field_ids, field_types, max_wrappers=2, field_meta=None)` | Dựng một FASTEXPR từ các field đó, trả `(expression, profile)` |
| `ExpressionBuilder.replicate(profile)` | Dựng lại **đúng** expression từ profile, không rút gì thêm |

Luồng trong `main()`:

```python
expressions = ExpressionBuilder(
    builder, scope, THEME, OPERATOR_LIMIT, JOIN_COST, POST_WRAPPERS
)
field_types, field_ids, drawn = expressions.draw_fields(n)
expression, profile = expressions.build(field_ids, field_types, field_meta=drawn)
replicated = ExpressionBuilder.replicate(profile)   # == expression
```

`n = 1` hợp lệ: khi đó expression chỉ có tầng lá (không có join). `n = 0` raise `ValueError`.

## 2. Đầu vào: `draw_fields(n)`

- Mỗi slot rút ngẫu nhiên loại `MATRIX` hoặc `VECTOR` (`IntegerSampler.sample((0, 1))`). Hai loại được coi là **một pool**.
- Số field mỗi loại bị chặn bởi kích thước pool. Một pool dưới `MIN_POOL_SIZE` (MATRIX 1, VECTOR 3, GROUP 3) coi như rỗng; phần thiếu được chuyển sang loại còn field.
- Nếu cả MATRIX lẫn VECTOR đều rỗng thì `print` thông báo và dừng; `main()` bỏ qua giá trị `n` đó.
- Trả về `(field_types, field_ids, drawn)`. `drawn` là `pd.DataFrame` đủ 19 cột metadata, **theo đúng thứ tự draw** (xem `Docs/data-field-sampling.md` §7.3).
- id của MATRIX, VECTOR, GROUP đôi một không giao nhau (đã đo), nên các id trong một expression khác nhau.

**GROUP field** được rút **một lần trong `__init__`** (`group_frame`, `group_id`) và dùng cho mọi `group_*` của builder đó. Hệ quả: các expression sinh từ cùng một instance `ExpressionBuilder` dùng chung một GROUP field. Nếu pool GROUP dưới mức tối thiểu thì `group_id = None` và `group_*` bị tắt (ví dụ `USA_delay1_SP500` chỉ có 1 GROUP field).

## 3. Các tầng của một expression

```
Tầng 0  VECTOR field  -> vec_*(field)                      (chỉ field VECTOR)
Tầng 1  mỗi lá        -> 0..max_wrappers wrapper           (MATRIX_UNARY hoặc GROUP)
Tầng 2+ các node      -> xáo, ghép cặp/nhóm, join          (MATRIX_BINARY hoặc VARIADIC)
        lặp đến khi còn 1 node
Cuối    node gốc      -> 0..POST_WRAPPERS wrapper          (post-join)
```

### 3.1 Tầng lá (`_leaf`)

1. Field VECTOR đi qua một `vec_*` rút từ `VECTOR_POOL`. Field MATRIX giữ nguyên.
2. Rút số wrapper trong `0..max_wrappers` (mặc định 2). Mỗi wrapper là `Group` với xác suất 1/2 (khi có `group_id` và pool group), ngược lại là `MatrixUnary`.
3. Một wrapper làm số operator của lá vượt `allowance` (mục 4) thì **bị bỏ và vòng lặp dừng**.

Tầng lá chỉ bọc **từng field riêng lẻ**. Giá trị đã kết hợp của hai field trở lên không bao giờ tới một phép biến đổi ở tầng này; đó là lý do có post-join wrapper (mục 3.5).

### 3.2 Join round (`_join_round`)

Mỗi round:

- **Xáo** các node bằng Fisher-Yates, nên mỗi round ghép theo thứ tự khác.
- Duyệt từ đầu. Nếu `variadic_pool` không rỗng, còn ít nhất 3 node, và rút được xác suất `VARIADIC_PROBABILITY` (0.35), thì lấy `count` node (`3..min(VARIADIC_MAX_OPERANDS, remaining)`) và join bằng **một** lời gọi `max`/`min`.
- Ngược lại ghép cặp `(left, right)` bằng một operator `MatrixBinary`. Một node lẻ cuối round đi thẳng sang round sau.
- Operator binary rút **không hoàn lại trong cùng một round**: có một "bag" bắt đầu bằng cả `binary_pool`, mỗi lần pop một operator, hết thì nạp lại. Sang round sau bag **bắt đầu đầy lại**. Mục đích: không có hai operator giống nhau chồng sát nhau trong một round.
- Operator thuộc `NON_COMMUTATIVE` được hoán `left`/`right` với xác suất 1/2.

### 3.3 Scale-fix: `rank()` quanh operand

Nhiều join phụ thuộc độ lớn của operand: một field cỡ 1e9 sẽ lấn át field cỡ 1e-2. Với các join thuộc `SCALE_SENSITIVE` (`add`, `subtract`, `multiply`, `signed_power`, `max`, `min`), **mỗi operand được bọc `rank(x)` trước khi join**. `rank` cắt ngang (cross-sectional) đưa operand về `[0, 1]`.

- `ts_corr` thì scale-free, `if_else` đã tự rank-wrap operand, nên cả hai không bị bọc thêm.
- `ts_covariance`, `ts_regression`, `vector_neut` **chưa** được bọc: chúng phụ thuộc scale nhưng chưa được review. Đây là điểm còn mở.
- `rank` chèn thêm là `rank(x)` thuần, **không** có tham số `rate`, khác với `MatrixUnary.rank` (rate rút từ `{0,1,2}`).
- Với `max`/`min`, wrap theo **từng operand**, không phải một `rank` quanh cả lời gọi. Hai dạng không tương đương: `rank(max(a, b))` xếp hạng giá trị lớn nhất trên cross-section, còn `max(rank(a), rank(b))` lấy giá trị lớn hơn của hai giá trị đã xếp hạng.
- Mỗi join scale-sensitive tốn thêm 2 operator, nên `JOIN_COST = 3` (1 binary + 2 `rank`).

### 3.4 Variadic join (`_variadic_join`)

`max(a, b, c)` thay một chuỗi hai join nhị phân và chỉ tốn 1 operator cho lời gọi. Builder là `Variadic.get(name, operands)` trong `Functions/operators.py`. `VARIADIC_POOL` có 4 operator: `max`, `min`, và `add`, `multiply` (mô tả của platform trong `cache/operators.csv` ghi cả hai nhận "two or more inputs"). `subtract` và `divide` không vào: chúng là join nhị phân. Cả bốn operator variadic đều giao hoán. Dạng hai operand của `add`, `multiply` vẫn ở `MatrixBinary`. Chưa xác nhận trên simulation thật rằng platform chấp nhận lời gọi từ ba operand trở lên của `add` và `multiply`; căn cứ hiện tại chỉ là mô tả của platform. `VARIADIC_MAX_OPERANDS = 4` là lựa chọn ngân sách, không phải giới hạn platform (platform chỉ đòi ít nhất 2 operand).

### 3.5 Post-join wrapper (`_post_wrap`)

Sau khi cây join xong, áp thêm `0..POST_WRAPPERS` (2) wrapper lên node gốc. Wrapper thử từng cái: nếu kết quả làm `operator_count` vượt `operator_limit` thì dừng (không áp cái đó). Vì vậy post-wrap chỉ dùng phần ngân sách mà cây còn dư.

Đo trên generator (3000 mẫu mỗi cấu hình), mean operator count:

| Cấu hình | N=3 | N=6 | expression có transform trên join (N=3) |
| --- | --- | --- | --- |
| Binary only, không post-wrap | 14.2 | 28.7 | 56.3% |
| + variadic | 13.1 | 26.4 | n/a |
| + post-wrap | 20.5 | 34.4 | 85.7% |
| + cả hai | 20.0 | 32.2 | n/a |

Hai lever đối lập về ngân sách: post-wrap tiêu operator, variadic tiết kiệm operator.

## 4. Ngân sách operator

Platform giới hạn **64 operator** trong một FASTEXPR (`OPERATOR_LIMIT` trong `main()`, truyền vào builder thành `self.operator_limit`). Bộ đếm `operator_count` đếm trên **text đã render** bằng regex `\b[A-Za-z_][A-Za-z0-9_]*\s*\(`, nên:

- Lời gọi lồng nhau đều được đếm.
- Operator **lặp argument** nhân chi phí của cả cây con bên dưới. `REPEATING` gồm `sqrt` (4 lần), `trade_when` (3), `if_else` (2) và đa số `group_*` (2). Ví dụ `sqrt` lồng 3 tầng quanh một field tốn 5 + 4*25 = 105.
- Regex chỉ match **function call**. Toán tử infix (nhóm BOOLEAN) sẽ bị đếm thiếu; đó là lý do BOOLEAN chưa có builder.

### 4.1 Cấp phát và hạ cấp (`build`)

n lá cần ít nhất `n - 1` join, mỗi join tốn tối đa `JOIN_COST = 3`, và mỗi lá VECTOR tốn thêm đúng 1 `vec_*`. Sàn chính xác của level nghèo nhất (chỉ `add`, không wrapper) là `3 * (n - 1) + V` với V là số lá VECTOR. Nhưng V được draw ngẫu nhiên (n = 5 cho V từ 0 đến 5, trung bình 2.5), nên dùng V làm ngưỡng khiến cùng một `OPERATOR_LIMIT` lúc raise lúc không (n = 5, limit 14: raise 23/40 lần). Vì vậy ngưỡng dùng trường hợp xấu nhất V = n: `floor = JOIN_COST * (n - 1) + n = 4n - 3`, chỉ phụ thuộc n. Nếu `floor > operator_limit` thì `build` **raise `ValueError`** nêu `floor` và yêu cầu tăng `OPERATOR_LIMIT` hoặc draw ít field hơn. Trần cứng là `PLATFORM_OPERATOR_LIMIT = 64` (platform từ chối expression nhiều hơn): `OPERATOR_LIMIT > 64` làm constructor raise, và `floor > 64` làm `build` raise nêu số field tối đa `(64 + JOIN_COST) // (JOIN_COST + 1) = 16`. Đã kiểm worst case toàn VECTOR ở limit `4n - 3` với n = 1, 2, 3, 5, 8, 16: luôn vừa; n = 17 cho floor 65 nên raise. Nếu không level nào vừa (chỉ xảy ra khi `join_cost` thấp hơn chi phí thật của một join), `build` raise thay vì trả `None`. Đổi lại ngưỡng có thể cao hơn mức cần thiết khi draw ít VECTOR. Build không bao giờ bỏ field: mọi field truyền vào đều có trong expression. Công thức `POST_WRAPPERS * n` không đủ làm sàn (n = 22 cho 44, trong khi sàn thật có lúc 78). `POST_WRAPPERS` không nằm trong floor: `_post_wrap` bỏ wrapper làm vượt limit, nên post wrapper là best-effort (0/300 vi phạm ở mọi limit đã đo), và thay `JOIN_COST` bằng `POST_WRAPPERS + 1` chỉ khớp khi `POST_WRAPPERS = 2`.

Mỗi lá được cấp `allowance = max(1, (64 - 3*(n-1)) // n)` operator. `build` thử lần lượt các **level pool**, từ giàu đến nghèo (`self.levels`):

| Level | Binary | Unary | Group | Variadic |
| --- | --- | --- | --- | --- |
| 0 | `BINARY_POOL` | `UNARY_POOL` | `GROUP_POOL` | `add`, `max`, `min`, `multiply` |
| 1 | `BINARY_POOL` | `UNARY_POOL` | `GROUP_POOL` | không |
| 2 | bỏ operator `REPEATING` | bỏ `REPEATING` | bỏ `REPEATING` | không |
| 3 | chỉ `add` | `UNARY_POOL` | `GROUP_POOL` | không |
| 4 | chỉ `add` | không | không | không |

Với mỗi level: dựng cây; nếu `operator_count > 64` thì **chia đôi** `allowance` và dựng lại, đến khi `allowance == 1`; rồi sang level kế. Khi `operator_limit >= floor`, level 4 luôn vừa nên `build` luôn trả expression trong giới hạn với đủ n field.

Kết quả đo gần đây (scope `USA_1_TOP3000`, 60 mẫu mỗi n):

| n | số mẫu vượt 64 | operator count lớn nhất |
| --- | --- | --- |
| 1 | 0 | 46 |
| 2 | 0 | 45 |
| 3 | 0 | 63 |
| 6 | 0 | 64 |
| 12 | 0 | 64 |
| 18 | 0 | 64 |
| 20 | 0 | 64 |
| 22 | 2 (lần đo lại, 150 mẫu: 0) | 66 |

**Đã sửa (2026-10-29).** Trước đây ở n = 22 có khoảng 1% mẫu vượt 64 (tối đa 66) vì khi không level nào vừa, `build` trả cây nhỏ nhất đã thấy thay vì raise, và platform sẽ từ chối expression đó. Nguyên nhân đã xác minh: kiểm tra khả thi cũ chỉ tính `JOIN_COST`, không tính `vec_*` của lá VECTOR. Nay `build` kiểm `floor = 3(n-1) + n = 4n - 3` ngay từ đầu và raise nếu `operator_limit < floor`. Đo lại với draw thật (n = 1, 2, 5, 10; 15 mẫu mỗi n): ở `operator_limit = floor` expression luôn vừa, đủ n field, `replicate` khớp từng ký tự; ở `floor - 1` luôn raise.

## 5. Profile

`build` trả `(expression, profile)`. Profile mô tả **cái đã dựng**: nó được thu bằng cách đi trên cây (`_walk`), không parse text render.

```python
{
  "expression": "...",
  "operator_count": 13,
  "data":   {"fields": [...], "group": {...} | None},
  "levels": {"leaf": {...}, "join": {...}, "post": {...}},
  "counts": {...},
  "tree":   {...},
}
```

### 5.1 `data`

- `fields`: các field làm lá, mỗi field là một dict gồm **19 cột metadata** từ catalog (`fieldid`, `categoryid`, `coverage`, `dateCoverage`, `field_description`, ...) cộng khoá `type` (`MATRIX`/`VECTOR`). Nếu `field_meta=None` (hoặc field không có trong frame) thì `_field_metadata` chỉ trả `{"type": ...}`. Docstring của hàm nói "giữ id và type", nhưng code (`{**metadata, "type": ...}` với `metadata = {}`) **không** giữ `fieldid`; id vẫn tra được từ `tree` (node `leaf`). Đây là chênh lệch giữa docstring và code, chưa sửa.
- `group`: metadata đầy đủ của GROUP field mà mọi `group_*` dùng, hoặc `None`.

### 5.2 `levels`

`{"leaf" | "join" | "post": {tên operator: [profile của từng lần gọi]}}`. Mỗi phần tử là `OperatorProfile` (`category`, `name`, `config`, `implicit`; xem `Docs/all-operators.md` §8.1).

Operator **kéo theo** (`implicit`: `densify`, `bucket`, `group_cartesian_product`, `ts_rank` của `if_else`/`trade_when`/`winsorize`/`tail`, ...) được ghi vào **cùng level** với operator mang chúng, để tổng operator của một level khớp với cái level đó thực sự đưa vào expression.

### 5.3 `counts`

| Khoá | Nghĩa |
| --- | --- |
| `operators_per_level` | số lời gọi (cả implicit) ở `leaf`/`join`/`post` |
| `operators_per_category` | số lời gọi theo `category` |
| `n_data_fields` | số field làm lá |
| `n_distinct_operators` | tổng số tên operator khác nhau, đếm theo từng level |

### 5.4 `tree`

Cây operator, thứ mà `replicate` đọc. `levels` chỉ gom theo tên nên mất thông tin "ai bọc ai" và thứ tự toán hạng. Mỗi node:

```python
{
  "level": "leaf" | "join" | "post" | "rank",
  "operators": [OperatorProfile, ...],   # theo thứ tự áp dụng, trong ra ngoài
  "children": [node, ...],
  "field": {"fieldid": ..., "type": ...},   # chỉ có ở node "leaf"
}
```

Node `level = "rank"` là scaffolding của scale-fix (mục 3.3), `operators` rỗng. Ví dụ thật (n = 2, `USA_1_TOP3000`):

```
add(rank(group_zscore(default_risk_global_percentile, densify(energy_sector_pca_grouping_method4_2clusters))), rank(fnd23_annfv1a_smcq), filter=true)
```

```
post []
  join [add]
    rank []
      leaf [group_zscore {mode: 2, skip_both: "False", nan_group: "True"}]   default_risk_global_percentile
    rank []
      leaf []                                                                 fnd23_annfv1a_smcq
```

### 5.5 `rank` của scale-fix không nằm trong `levels`

Nó xuất hiện ở **mọi** join scale-sensitive, là scaffolding bắt buộc để hai operand cùng scale, không phải lựa chọn của generator. Ghi nó vào `levels` sẽ chiếm khoảng 40% lượt operator và làm mờ phần còn lại. Nó chỉ tồn tại dưới dạng node `rank` trong `tree`, để `replicate` đặt lại đúng chỗ.

### 5.6 Số lần gọi trong profile khác số lần xuất hiện trong text

Operator lặp argument (`group_*` mode 3/4/5 nhúng `x` vào `bucket(rank(x))`, `trade_when` render 3 lần, `if_else` render operand 2 lần) khiến text đếm **rendered occurrence**, profile đếm **logical call**. Invariant đúng để kiểm profile là **coverage hai chiều theo tên operator** (mọi operator trong text có trong profile và ngược lại, trừ `rank` của scale-fix), không phải so số lần. Đã kiểm: 250 mẫu, 0 vi phạm (trước khi có `implicit`, 87/100 mẫu lệch).

## 6. Replicate

`ExpressionBuilder.replicate(profile)` dựng lại expression **giống từng ký tự** từ `profile["tree"]`, không rút gì mới.

Thuật toán (`_replay`): đệ quy từ gốc.

- Node `rank`: `rank(<replay con>)`.
- Node `join`: lấy operator duy nhất của node, áp lên danh sách toán hạng là các con đã replay (`_apply`).
- Node `leaf`: bắt đầu từ `field.fieldid`, áp lần lượt từng operator trong `operators`.
- Node `post`: bắt đầu từ con duy nhất, áp lần lượt từng operator.

`_apply` chọn class theo `category`: `MATRIX_BINARY` -> `MatrixBinary.replicate`, `VARIADIC` -> `Variadic.replicate`, `VECTOR` -> `Vector.replicate`, `MATRIX_UNARY` -> `MatrixUnary.replicate`, còn lại (GROUP) -> `Group.replicate` kèm `group_id` lấy từ `profile["data"]["group"]["fieldid"]`.

### 6.1 Vì sao replay từ `config`, không từ seed

`Docs/all-operators.md` §8.5: replay từ seed chỉ cố định được stream 1 (window `d`), các stream khác vẫn ngẫu nhiên. `config` ghi đủ mọi tham số đã rút, nên truyền lại nó cho builder cho kết quả bit-exact. Parse lại text expression bị loại vì dễ sai với operator implicit và tham số lặp.

### 6.2 Các chỗ `config` không replay trực tiếp được (đã xử lý)

| # | Vấn đề | Xử lý |
| --- | --- | --- |
| 1 | `config` ghi tên platform (`useStd`, `lookback`, `scale`, `longscale`, `shortscale`) khác tên tham số builder (`use_std`, `d`, `book_size`, `long_scale`, `short_scale`) | `MatrixUnary.CONFIG_PARAMETER` ánh xạ lại |
| 2 | `kth_element` ghi `ignore` nhưng nó là hàm của `k`, builder tự suy ra | `MatrixUnary.replicate` bỏ `ignore` |
| 3 | `Group` mode 3-5 rút `bucket_range` ngẫu nhiên nhưng không ghi vào config, nên text khác sau replay | Mọi `group_*` ghi `bucket_range` vào config khi `mode >= 3` (mode 1-2 không render nó) |
| 4 | Cờ `skip_both`, `nan_group` ghi dạng `"True"/"False"`, `std` ghi dạng chuỗi 2 chữ số; builder nhận 0/1 và `float` | `Group.replicate` đổi ngược |
| 5 | Nhánh fallback của `build` trước đây truyền `tree=None` nên profile rỗng | Nay giữ cây nhỏ nhất làm fallback |

Thay đổi (3) làm `config` của `Group` đổi hình dạng (thêm `bucket_range`) nhưng **không đổi expression sinh ra**: snapshot 260 expression Group trước và sau sửa giống hệt.

### 6.3 Kết quả kiểm

- 2880 expression (n = 1..22) và 400 build sát limit: 0 mismatch, kể cả qua JSON round-trip.
- Lần chạy lại gần nhất: 480 expression (n = 1, 2, 3, 6, 12, 18, 20, 22, mỗi n 60 mẫu): 0 mismatch với profile gốc và 0 mismatch với profile đã qua `json.dumps`/`json.loads`.

### 6.4 Giới hạn

- Chỉ dùng được với profile có khoá `tree`. Profile từ code cũ thì không.
- Chỉ dựng lại **chuỗi expression**. Không dựng lại metadata hay `drawn`.
- Cần `data.group` nếu cây có `group_*`.
- Kiểm trên scope `USA_1_TOP3000` (chủ yếu). Scope có pool GROUP rỗng chưa kiểm replay riêng.
- `main()` hiện gọi `replicate(profile)` trực tiếp. Bước JSON round-trip chỉ nằm trong phép kiểm ở trên, không còn trong `main()`.
- Vì `profile` chứa kiểu numpy/Timestamp trong metadata, khi in hoặc lưu JSON cần `default=str`. `replicate` chỉ đọc `tree` và `data.group.fieldid` nên không bị ảnh hưởng.

## 7. Tính ngẫu nhiên và tái lập

- Mọi lần rút (`IntegerSampler.sample`) dùng entropy mới của OS. `ExpressionBuilder` **không** nhận seed, nên hai lần `build` với cùng field cho hai expression khác nhau. Đây là chủ ý: mỗi alpha sinh ra là một mẫu độc lập.
- Tái lập một expression cụ thể dùng **profile**, không dùng seed (mục 6).
- `draw_fields` cũng dùng entropy mới (`theme` chỉ giới hạn pool, không cố định mẫu).

## 8. Cấu hình hiện tại (hằng số trong `ExpressionBuilder`)

| Hằng số | Giá trị | Ý nghĩa |
| --- | --- | --- |
| `OPERATOR_LIMIT` | 64 | giới hạn operator của platform; đặt trong `main()` |
| `JOIN_COST` | 3 | 1 binary + 2 `rank` cho mỗi join; đặt trong `main()` |
| `VARIADIC_MAX_OPERANDS` | 4 | số operand tối đa của một `max`/`min` (chọn theo ngân sách) |
| `VARIADIC_PROBABILITY` | 0.35 | xác suất dùng variadic khi còn >= 3 node |
| `POST_WRAPPERS` | 2 | số wrapper tối đa trên cây đã join; đặt trong `main()` |
| `MIN_POOL_SIZE` | MATRIX 1, VECTOR 3, GROUP 3 | pool nhỏ hơn mức này coi như rỗng |
| `max_wrappers` (tham số `build`) | 2 | số wrapper tối đa mỗi lá |

Pool operator: `BINARY_POOL` (9), `UNARY_POOL` (40), `VECTOR_POOL` (7), `GROUP_POOL` (9), `VARIADIC_POOL` (4). `power` bị loại khỏi `BINARY_POOL` có chủ ý: cơ số âm với số mũ không nguyên làm simulation lỗi và tốn một slot. `divide` nằm trong `BINARY_POOL` (10 operator), builder render `divide(x, y + x + 0.0001)`, tức giá trị `x / (x + y + 0.0001)`: tỷ trọng của x trong x + y, không phải x / y. Viết infix nên `OPERATOR_CALL` không đếm thêm call nào; chưa xác nhận platform có đếm `+` infix là một operator hay không. `x` được render hai lần nên `divide` nằm trong `REPEATING`. `divide` không giao hoán nên nằm trong `NON_COMMUTATIVE` và có thể bị đảo operand; chưa nằm trong `SCALE_SENSITIVE`, nên không được rank-wrap.

Các hằng `VARIADIC_MAX_OPERANDS`, `VARIADIC_PROBABILITY`, `POST_WRAPPERS`, `max_wrappers` là **lựa chọn thiết kế chưa được tối ưu theo kết quả platform**. Không có bằng chứng hiện tại rằng giá trị nào tốt hơn.

## 9. Việc còn mở

- `ts_covariance`, `ts_regression`, `vector_neut` chưa được scale-fix.
- n >= 22 có thể vượt 64 operator (mục 4.1).
- BOOLEAN chưa có builder; cần sửa bộ đếm cho toán tử infix trước.
- Mode 4 và mode 5 của `Group` sinh cùng một chuỗi (`Docs/all-operators.md` §10.3).
- Chưa có local oracle nên chưa biết lever nào (post-wrap, variadic, scale-fix) cải thiện alpha thật.
- Phạm vi giai đoạn 2 chưa được chốt.
