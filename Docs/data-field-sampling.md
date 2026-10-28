# Lấy mẫu ngẫu nhiên Data Field

> **TRẠNG THÁI: ĐÃ TRIỂN KHAI.** §1–§2 là số đo trên API thật. §3–§8 mô tả code đang chạy. §9 liệt kê phần còn mở — những quyết định nghiên cứu **chưa** có trong code và không nên coi là đã chốt.

Ngữ cảnh: [data-description.md](data-description.md) mô tả cấu trúc catalog của BRAIN. Tài liệu này trả lời câu hỏi tiếp theo: **làm sao lấy được vài data field một cách ngẫu nhiên, có kiểm soát, từ tập ~76 000 field?**

Phạm vi: **chỉ về data**. Chưa đụng tới cách dựng alpha expression hay cách simulate.

---

## 1. Số đo nền (đo trên API thật, scope `EQUITY / USA / delay 1 / TOP3000`)


| Phép đo                           | Kết quả                                                    |
| --------------------------------- | ---------------------------------------------------------- |
| Số field trong 1 GET không filter | **75 926** (`count` khớp `len(results)`, 75 926 id unique) |
| Payload / thời gian               | 41.4 MB / 5.5 s                                            |
| RAM peak khi parse                | ~322 MB                                                    |
| Số dataset                        | 286 (274 tên khác nhau → có dataset trùng tên)             |
| Category / subcategory            | 16 / 41                                                    |
| Id prefix distinct                | 1 278                                                      |




### 1.1 Ràng buộc API (đã dò, tất cả đều trả lỗi rõ ràng)


| Query                                     | Kết quả                                                               |
| ----------------------------------------- | --------------------------------------------------------------------- |
| `/data-fields?<scope>` (không `limit`)    | `200`, ra trọn 75 926 records, `count` = 75 926                       |
| `/data-sets?<scope>` (không `limit`)      | `200`, 286 records, 0.41 MB                                           |
| `?limit=50`                               | `200`, nhưng `count` bị **cap 10 000** (không phải số thật)           |
| `?limit=75`                               | `400 "Invalid query: pagination limit too high."`                     |
| `?limit=1&offset=9990`                    | `400 "Invalid offset. Please use filters to narrow down the result."` |
| `?search=news&limit=50&offset=50`         | `200`, nhưng `search` có cap `offset + limit ≤ 100`                   |
| có filter mà **không** `limit`            | `400 "Invalid query"`                                                 |
| `?type=MATRIX&limit=50&offset=20000`      | `400` — cửa sổ filter chỉ 10 000 item                                 |
| `?sort=`, `?order=`, `?random=`, `?seed=` | `400 "Invalid query"` — server **không** hỗ trợ sort/random           |




### 1.2 Bẫy filter âm thầm — nguy hiểm nhất

Theo `OPTIONS /data-fields`, filter hợp lệ về mặt schema là `dataset.id`, `category.id`, `subcategory.id`… Nhưng thực tế server chỉ thực sự lọc với key **phẳng**:


| Query                                 | `count` | 50 record trả về                                | Có lọc?         |
| ------------------------------------- | ------- | ----------------------------------------------- | --------------- |
| `&category=model`                     | 10 000  | 50/50 `category=model`                          | ✅               |
| `&category=fundamental`               | 10 000  | 50/50 `category=fundamental`                    | ✅               |
| `&category=pv`                        | 10 000  | 50/50 `category=pv`                             | ✅               |
| `&subcategory=model-valuation-models` | 886     | 5/5 đúng subcategory                            | ✅               |
| `&dataset=model109`                   | 544     | 50/50 `dataset=model109`                        | ✅               |
| `&type=MATRIX`                        | 10 000  | 50/50 `type=MATRIX`                             | ✅               |
| `&type=VECTOR`                        | 10 000  | 50/50 `type=VECTOR`                             | ✅               |
| `&category.id=model`                  | 10 000  | trộn `model`/`fundamental`/`earnings`/`analyst` | ❌ **bị bỏ qua** |
| `&dataset.id=model109`                | 544     | đúng (riêng `dataset.id` lại chạy)              | ✅               |
| `&category.name=Model`                | 10 000  | trộn lẫn                                        | ❌ **bị bỏ qua** |


**Hệ quả:** code ghi `category.id=…` sẽ chạy trơn tru, trả HTTP 200, nhưng lấy sai tập dữ liệu — kiểu bug im lặng tệ nhất. Mọi filter phải dùng key phẳng, và **phải verify bằng cách kiểm tra giá trị trong record trả về**, không tin `count`.

### 1.3 Hệ quả kiến trúc

Vì (i) không có sort/random phía server, (ii) filter bị giới hạn cửa sổ 10 000, (iii) `count` bị cap khi có `limit` — **không thể enumerate hết một tập lọc lớn qua API**.

⇒ Quyết định kiến trúc số 1: **tải 1 lần toàn bộ scope (không filter), cache xuống đĩa, mọi lọc và lấy mẫu thực hiện local.** Pipeline hiện tại chọn cách này — xem §3.

---



## 2. Chiều thật của frame



### 2.1 `region` / `delay` mới là chiều lọc thật

Đo trực tiếp trên tập id:


| So sánh                            | Kích thước       | Intersection | Jaccard   |
| ---------------------------------- | ---------------- | ------------ | --------- |
| `USA/1/TOP3000` vs `USA/1/TOP500`  | 75 926 vs 75 926 | **75 926**   | **1.000** |
| `USA/1/TOP3000` vs `USA/0/TOP3000` | 75 926 vs 16 636 | 13 547       | 0.152     |
| `USA/1/TOP3000` vs `EUR/1/TOP2500` | 75 926 vs 35 225 | 21 419       | 0.239     |


- `delay` cắt rất mạnh: **62 379 field (82 %) chỉ tồn tại ở delay 1**, không có ở delay 0.
- `region` gần như tách rời: overlap 21 419 chủ yếu là nhóm `model` / `pv` dùng chung.

⇒ **Frame hiệu dụng là 16 cặp** `(region, delay)`**, không phải 44 scope.** `universe` quyết định *backtest chạy trên tập instrument nào*.

### 2.2 `universe` *không* hoàn toàn bỏ qua — đo lại trên cache

Các universe của cùng `(region, delay)` trả về **cùng một** `catalog_frame_id` — hash nội dung các field trước khi lọc coverage — **trừ một ngoại lệ đo được**:


| Scope            | `catalog_total` | `catalog_frame_id` |
| ---------------- | --------------- | ------------------ |
| `USA_1_TOP3000`  | 75 926          | `c7cc3b2e`         |
| `USA_1_TOP1000`  | 75 926          | `c7cc3b2e`         |
| `USA_1_TOP2000`  | 75 926          | `c7cc3b2e`         |
| `USA_1_TOP500`   | 75 926          | `c7cc3b2e`         |
| `USA_1_TOP200`   | 75 926          | `c7cc3b2e`         |
| `USA_1_TOPSP500` | **74 769**      | `d411bf99`         |


`TOPSP500` (super-sector, không phải cap của instrument count) có ít field hơn 1 157 và tập id của nó là **tập con thật** của `TOP3000`: 35 866 MATRIX eligible trong `TOPSP500`, 36 854 ở `TOP3000`, intersection đúng bằng 35 866, phần chỉ có ở `TOP3000` là 988, phần chỉ có ở `TOPSP500` là **0**.

**Kết luận đã sửa so với bản tài liệu cũ:** "universe không lọc gì" chỉ đúng với các cap dựa trên số lượng instrument, **không** đúng với `TOPSP500`. Không nên suy rẛng rộng rằng mọi universe trong một `(region, delay)` chia sẻ tập id.

### 2.3 Còn cần kiểm tra

Với `delay = 0` (non-delayed), danh sách field là *tập con* của `delay = 1` hay bản khác nhau về nội dung? Đo được: `USA/0 − USA/1` = 3 089 field → **có** field chỉ tồn tại ở delay 0.

---



## 3. Pipeline (đã triển khai)

```
[1] FETCH        GET /data-fields?<scope> + /data-sets?<scope>   (không limit)
                 1 session phục vụ mọi scope; 2 request / scope
[2] MERGE        ghép dataset-only columns vào /data-fields bằng datasetid
[3] FILTER       coverage > MIN_COVERAGE và dateCoverage > MIN_COVERAGE
                 → bỏ trước khi tách theo type
[4] SNAPSHOT     1 .npz / (scope, field type), chunked
[5] SAMPLE       rng = default_rng(seed); choice(n_rows, replace=False)
[6] OUTPUT       fieldid + frame_id đủ để replay
```

Chỉ stage 5 là random; stage 1–4 deterministic. Toàn bộ chi phí nằm ở stage 1.

### 3.1 Ba tầng class (`Functions/data.py`)


| Tầng      | Class            | Trách nhiệm                                                                  |
| --------- | ---------------- | ---------------------------------------------------------------------------- |
| Transport | `BrainAPI`       | session, rate limit 1 req/s, `OPTIONS /simulations` để enumerate scope       |
| Catalog   | `BrainData`      | flatten nested JSON thành frame phẳng; endpoint `/data-sets`, `/data-fields` |
| Pipeline  | `CatalogBuilder` | fetch → lọc → cache → sample. **Không sở hữu session.**                      |


`CatalogBuilder` nhận `BrainData` qua tham số thay vì kế thừa, vì platform giới hạn login (5/phút, 25/ngày) và class này phải dựng được với `data=None` cho đường offline.

### 3.2 Scope định nghĩa tĩnh

`config/scopes.yaml` là **snapshot** của `OPTIONS /simulations` (41 scope). Một scope mà platform đã bỏ sẽ làm request catalog fail chứ không bị bỏ qua âm thầm — đây là hành vi cố ý.

### 3.3 Vì sao lọc trước, tách sau

`fetch_scope` lọc coverage **trước** khi tách theo `type`, nên **mỗi archive chỉ chứa row đã eligible**. Đổi thứ tự sẽ khiến archive chứa field không đủ dùng, và `sample_field_ids` sẽ phải lọc lại lúc sample.

Hệ quả cần nói rõ: `sample_field_ids` **không kiểm tra ngưỡng lần nữa**. Archive ghi bởi `fetch_scope` thì mọi row đều hợp lệ. `ScopeCache.eligible_positions` vẫn tồn tại và vẫn đúng về mặt toán học, nhưng pipeline hiện tại không gọi nó.

---



## 4. Mô tả dữ liệu field (đã đo)

**Key presence trên 75 926 record:**

```
id 75926 · description 75926 · dataset 75926 · category 75926 · subcategory 75926
region 75926 · delay 75926 · universe 75926 · type 75926 · coverage 75926
userCount 75926 · alphaCount 75926 · pyramidMultiplier 75926 · themes 75926
dateCreated 75926 · dateCoverage 72667          ← thiếu 3 259 record (4.3 %)
```

`type`**:** MATRIX 57 356 · VECTOR 16 514 · GROUP 2 041 · SYMBOL 8 · UNIVERSE 7

`category`**:** model 18 971 · analyst 17 215 · pv 12 825 · fundamental 11 041 · other 9 203 · news 2 548 · sentiment 1 207 · risk 941 · option 619 · earnings 588 · socialmedia 232 · insiders 185 · macro 153 · shortinterest 110 · institutions 86 · imbalance 2

**Category × type:**


| category      | n      | MATRIX | VECTOR | GROUP | SYM | UNIV |
| ------------- | ------ | ------ | ------ | ----- | --- | ---- |
| model         | 18 971 | 16 517 | 2 449  | 1     | 4   | —    |
| analyst       | 17 215 | 11 184 | 6 031  | —     | —   | —    |
| pv            | 12 825 | 11 357 | 617    | 840   | 4   | 7    |
| fundamental   | 11 041 | 7 993  | 3 048  | —     | —   | —    |
| other         | 9 203  | 6 238  | 1 765  | 1 200 | —   | —    |
| news          | 2 548  | 637    | 1 911  | —     | —   | —    |
| sentiment     | 1 207  | 1 065  | 142    | —     | —   | —    |
| socialmedia   | 232    | 111    | 121    | —     | —   | —    |
| risk          | 941    | 920    | 21     | —     | —   | —    |
| option        | 619    | 619    | —      | —     | —   | —    |
| earnings      | 588    | 357    | 231    | —     | —   | —    |
| insiders      | 185    | 118    | 67     | —     | —   | —    |
| macro         | 153    | 105    | 48     | —     | —   | —    |
| shortinterest | 110    | 79     | 31     | —     | —   | —    |
| institutions  | 86     | 54     | 32     | —     | —   | —    |
| imbalance     | 2      | 2      | —      | —     | —   | —    |


`coverage`**:** min 0.0 · p10 0.50 · median 0.894 · p90 1.0 · max 1.0
→ `coverage == 0`: **82 field** (chết) · `< 0.5`: 5 565 · `≥ 0.95`: 30 291

`dateCreated`**:** 2022-05 → 2026-04. Đáng chú ý: **22 736 field tạo trong 2026-03**, 4 042 trong 2026-04 → catalog có dòng chảy mạnh, không phải tập tĩnh.

`id`**:** 100 % khớp `[a-z0-9_]`, độ dài 3–95 (median 29), 75 926 id unique. Không cần sanitize.

`userCount` **/** `alphaCount`**:** **25 549 field (33.6 %) có cả hai bằng 0** — chưa ai từng dùng. Số này **bằng nhau tuyệt đối** giữa hai cột (không field nào user>0 mà alpha=0) → có vẻ server dùng chung một cờ "đã dùng".

---



## 5. Eligibility — quyết định đã code

`CatalogBuilder(min_coverage)` lọc bằng một ngưỡng duy nhất, áp cho **cả hai** cột:

```python
eligible = (fields["coverage"] > min_coverage) & (fields["dateCoverage"] > min_coverage)
```


| Tiêu chí                 | Dữ liệu                        | Code hiện tại                           | Ghi chú                                   |
| ------------------------ | ------------------------------ | --------------------------------------- | ----------------------------------------- |
| `coverage`               | p10 = 0.50                     | `> MIN_COVERAGE`                        | `main.py` đặt `MIN_COVERAGE = 0.7`        |
| `dateCoverage`           | thiếu 4.3 %                    | `> MIN_COVERAGE`                        | NaN fail so sánh → tự động bị loại        |
| `type`                   | xem §4                         | tách 3 archive: MATRIX / VECTOR / GROUP | **không** lọc bỏ type nào                 |
| `userCount`/`alphaCount` | 25 549 field = 0               | **không lọc**                           | xem §6                                    |
| `dateCreated`            | 2026-03/04 có 26 778 field mới | không lọc                               | data-snooping risk, ghi lại chứ không lọc |
| `id`                     | 100 % sạch                     | không lọc                               | —                                         |


**Ngưỡng dùng** `>` **chứ không phải** `>=`**.** Với `MIN_COVERAGE = 0.7`, đây là ngưỡng nghiêm hơn đề xuất `≥ 0.5` của tài liệu cũ. Chênh lệch này là quyết định nghiên cứu, chưa có lý do sinh học — xem §9.

**Ba type được cache đều nhau.** Bản tài liệu cũ đề xuất MATRIX-only với lý do "VECTOR cần chính sách aggregate riêng". Code hiện tại lưu cả ba. Đây là lựa chọn *giữ lựa chọn*: pipeline không quyết type nào hợp lệ, việc đó để cho tầng alpha.

### 5.1 Số eligible thực tế trong cache

Đọc từ `cache/` ngày 2026-10-23, `MIN_COVERAGE = 0.7`, tổng 41 scope:


| Type   | Eligible rows (41 scope) |
| ------ | ------------------------ |
| MATRIX | 460 153                  |
| VECTOR | 139 925                  |
| GROUP  | 39 274                   |


Vài scope đơn lẻ, để thấy độ lệch giữa scope:


| Scope             | catalog_total | MATRIX eligible | VECTOR | GROUP |
| ----------------- | ------------- | --------------- | ------ | ----- |
| `USA_1_TOPSP500`  | 74 769        | 35 866          | 9 167  | 1 670 |
| `ASI_1_MINVOL10M` | 23 512        | 8 161           | 3 119  | 1 413 |


Mỗi archive giữ `catalog_total` (số trước khi lọc) và `catalog_frame_id` (hash tập field trước khi lọc), nên vẫn truy được filter đã loại bao nhiêu.

---



## 6. Bias hai chiều của "field chưa ai dùng" — quyết định nghiên cứu, chưa chốt

25 549 field có `userCount = alphaCount = 0`. **Code hiện tại giữ tất cả.**

- **Giữ** → không gian khám phá tối đa; tránh chọn field *đã biết là tốt* → selection bias theo hướng ngược (có thể thiên về field *tệ*).
- **Bỏ** → field đã từng được compile & backtest thành công → tỉ lệ lỗi thấp hơn, **nhưng** field được dùng nhiều thường là field tốt → bias *tăng* khả năng thành công (giống survivorship bias).

Không có lựa chọn nào "đúng" — phải nêu rõ trong paper và báo cáo cả hai chế độ nếu chạy.

---



## 7. Reproducibility



### 7.1 `frame_id` chứ không chỉ seed

Catalog là mục tiêu động (4 042 field mới trong 2026-04). Cùng `seed = 42` ở tuần sau sẽ ra bộ khác.

```
frame_id = sha256("\n".join(sorted(field_ids)))[:8]
```

Cache lưu **hai** hash khác nhau, và phân biệt này quan trọng:


| Hash               | Hash cái gì                              | Ví dụ `USA_1_TOPSP500`                                   |
| ------------------ | ---------------------------------------- | -------------------------------------------------------- |
| `catalog_frame_id` | toàn bộ field **trước** khi lọc coverage | `d411bf99`                                               |
| `frame_id`         | field **đã lọc** trong riêng archive đó  | MATRIX `d08d2f41` · VECTOR `fb679e43` · GROUP `f55798bc` |


Hai scope có cùng `catalog_frame_id` nghĩa là cùng tập field; archive MATRIX và VECTOR của một scope có `frame_id` khác nhau là bình thường vì tập id khác nhau.

### 7.2 Seed

`sample_field_ids(seed=None)` lấy entropy từ OS CSPRNG (`os.urandom(8)`), không gắn vào hằng số cố định. Seed thực tế được in ra cùng kết quả để replay bit-exact. **Cùng seed trên hai snapshot khác sẽ cho field khác** — đó là hành vi đúng, vì seed chỉ có nghĩa khi đi kèm `frame_id`.

### 7.3 Draw trả về metadata đầy đủ

`sample_field_ids` trả **một DataFrame, một dòng cho mỗi field được bốc**, mang **toàn bộ 19 cột** mà archive giữ: `fieldid`, `type`, `field_description`, `categoryid`, `categoryname`, `subcategoryid`, `subcategoryname`, `datasetid`, `datasetname`, `dataset_description`, `coverage`, `dateCoverage`, `dataset_valueScore`, `pyramidMultiplier`, `region`, `delay`, `universe`, `dateCreated`, `dataset_dateUpdated`. Thứ tự dòng là thứ tự bốc.

Áp dụng cho cả ba field type (`MATRIX`, `VECTOR`, `GROUP`) — không có ngoại lệ nào.

Trước đây hàm trả `list[str]` (chỉ `fieldid`) và bỏ phần metadata vốn đã nằm trên đĩa. Metadata đó là đầu vào cho tầng heuristic sau này.

**Chi phí đo được** (`USA_1_TOP3000`, archive MATRIX, 36 854 dòng):

| Cách đọc | Thời gian | Memory |
| --- | --- | --- |
| `fieldid` only (cách cũ) | 0.016 s | 2.9 MB |
| sample n=6, đủ 19 cột | 0.173 s | — |
| toàn bộ 19 cột, toàn archive | 0.332 s | 69 MB |

Đọc metadata cho vài dòng gần như miễn phí so với trước: mỗi cột là một member riêng của `.npz`, nên `np.load` phải decompress **cả cột** bất kể lấy bao nhiêu dòng. Đọc cột `field_description` (text dài) cho 6 dòng tốn gần bằng đọc 19 cột cho 36 854 dòng.

---



## 8. Phân phối mẫu: 4 phương án (chưa chốt)

**Hiện tượng lệch — đã đo:**


| Mức tập trung                                    | Kết quả                                   |
| ------------------------------------------------ | ----------------------------------------- |
| Dataset lớn nhất (`pv87` — "Aggregated dataset") | 6 666 field = **8.8 %**                   |
| Top 5 dataset                                    | 22.6 %                                    |
| Top 10 dataset                                   | 35.0 %                                    |
| Top 20 dataset                                   | 52.3 %                                    |
| Top 50 dataset                                   | 77.0 %                                    |
| Top 100 dataset                                  | 92.3 %                                    |
| HHI theo dataset                                 | 0.0216 → **hiệu dụng 46.3 / 286** dataset |
| HHI theo category                                | 0.1799 → **hiệu dụng 5.56 / 16** category |


**Bẫy family.** 1 278 id prefix, nhưng top 5 prefix đã chiếm 12 972 field: `pv87` 6 666 · `anl15` 2 538 · `fnd28` 2 209 · `anl10` 2 148 · `mdl264` 2 038. Field cùng prefix là **biến thể của cùng một khái niệm** (`anl10`/`anl15` = analyst forecast các kỳ khác nhau; `pv87` = 6 666 field cùng họ Price Volume).

Nếu uniform trên field, 3 field có thể ra 3 thành viên cùng họ → thực chất chỉ **1 feature độc lập**, không phải 3. Đây là lỗi thiết kế reviewer rất dễ chỉ ra, nên phải xử lý tường minh chứ không hy vọng nó hiếm xảy ra.


|                                     | Cách làm                                              | Đặc tính                                                                                                                             | Khi nào dùng                                 |
| ----------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| **A. Uniform field**                | `choice` trên N id eligible                           | Đơn giản; nhưng **Model + Analyst ≈ 47 %** → thực chất là *Model-heavy baseline*; P(cả 3 cùng dataset) ≤ 0.19 % (bound: max p × HHI) | null baseline trung thực — **luôn nên chạy** |
| **B. Stratified theo category**     | 16 nhóm, mỗi nhóm 1 field                             | Ép đa dạng ngữ nghĩa                                                                                                                 | baseline có kiểm soát                        |
| **C. Hai tầng: dataset → field**    | chọn dataset uniform (286) rồi field uniform trong đó | Mỗi dataset đóng góp 1 dataset; frame phẳng hơn A nhiều                                                                              | trả lời "dataset nào đáng khai thác"         |
| **D. Cluster-aware (1 per family)** | gom theo id prefix, mỗi family 1 field                | Đảm bảo 3 feature **thực sự khác nhau**                                                                                              | khi claim "3 independent features"           |


**Code hiện tại chỉ làm A** — `choice(n_rows, replace=False)` trên row của archive. B, C, D chưa có. Đề xuất vẫn là chạy **A (null) + D (có kiểm soát)** song song và luôn báo cáo phân phối category/dataset của các draw. Không thể gọi A là "random feature baseline" mà không nói rõ nó thiên về Model/Analyst.

---



## 9. Chi phí vận hành


| Việc                                        | Quy mô                            |
| ------------------------------------------- | --------------------------------- |
| Tải 1 scope lớn                             | 41 MB / 5.5 s                     |
| Tải 1 scope nhỏ (`USA/0/TOP3000`)           | 8.9 MB                            |
| Tải 16 cặp `(region, delay)`                | ~150–250 MB, ~2–3 phút            |
| Toàn bộ 41 scope trong `config/scopes.yaml` | 2 request / scope = 82 request    |
| Rate limit                                  | 1 req/s → **không phải nút thắt** |
| RAM lúc parse                               | ~322 MB peak (đo thật)            |


Sau khi cache một lần, mọi lần sample chỉ đọc local → gần như tức thì.

Cache format là **chunked** `.npz`, không phải parquet: `pyproject.toml` không có `pyarrow`, và npz cho phép đọc từng block + từng cột. Đổi lại phải giải nén toàn bộ member khi sample.

---



## 10. Quyết định còn mở — CHƯA CHỐT


| #   | Câu hỏi                                                            | Hiện trạng trong code                                                                                                                                                                          |
| --- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Ngưỡng `coverage` bao nhiêu?                                       | `MIN_COVERAGE = 0.7`, dùng `>` cho cả `coverage` lẫn `dateCoverage`. Tài liệu cũ đề xuất `≥ 0.5` cho `coverage` và loại riêng record thiếu `dateCoverage`. **Chưa có lý do sinh học cho 0.7.** |
| 2   | Phương án lấy mẫu?                                                 | Chỉ A (§8). B / C / D chưa có.                                                                                                                                                                 |
| 3   | `type` nào được phép làm alpha input?                              | Cache cả 3. Không có policy type nào ở tầng data. GROUP không phải alpha input nhưng vẫn được lưu.                                                                                             |
| 4   | Field `userCount = alphaCount = 0`?                                | Giữ (§6). Chưa quyết.                                                                                                                                                                          |
| 5   | `MIN_COVERAGE` là 1 số hay tách riêng `coverage` / `dateCoverage`? | Đang dùng chung 1 số. Tác giả có thể muốn `dateCoverage` nghiêm hơn vì nó đo độ sâu lịch sử chứ không phải độ phủ.                                                                             |
| 6   | Bao nhiêu draw để ước lượng phân phối?                             | `main.py` hiện sample 2 field mỗi type, 1 scope. Chỉ là smoke test, chưa phải nghiên cứu phân phối.                                                                                            |
| 7   | Cache cũ hơn `CATALOG_MAX_AGE_SECONDS` thì sao?                    | `refetch_stale` quyết định tải lại hay pin. Mặc định `True`. Xem `Functions/cache.py`.                                                                                                         |


---



## 11. Việc cần kiểm tra thêm

- [ ] Ngưỡng 0.7 có làm mất field dùng được không — so sánh tỉ lệ eligible ở 0.5 / 0.6 / 0.7 / 0.8, xem có nhóm nào bị cắt đột ngột.
- [ ] Mối quan hệ giữa `coverage` và `dateCoverage` (hiện `dateCoverage` thiếu 4.3 % — các record thiếu có tập trung ở category nào không?)
- [ ] 41 subcategory: có subcategory nào "rác" (chứa field không liên quan) không? Ví dụ `other-aiml-data` có 7 800 field — cần xem mẫu để biết đây là dữ liệu gì.
- [ ] Kiểm tra `themes` — có bao nhiêu theme, phân bố ra sao, dùng được làm nhóm ngữ nghĩa thay `category` không?
- [ ] `delay 0` vs `delay 1`: có field nào chỉ tồn tại ở delay 0 không? (đo: `USA/0 − USA/1` = 3 089 field → có). Nội dung có khác nhau không, hay chỉ là tập con?
- [ ] Các universe khác `TOPSP500` có universe nào khác lọc không? §2.2 mới chỉ dò `TOPSP500`.

---



## 12. Ghi chú lịch sử

- Số đo §1, §4, §8 lấy từ API thật ngày **2026-10-21**, scope `EQUITY / USA / delay 1 / TOP3000` trừ khi ghi rõ khác. Số eligible §5.1 đọc từ `cache/` ngày **2026-10-23**.
- Bản đầu tiên của tài liệu này (`random-field-pipeline-proposal.md`) là **ý tưởng + số đo kiểm chứng giả định**, đã bị thay thế sau khi phần lớn ý tưởng được code. Kết luận đã sửa: "universe không lọc gì" — xem §2.2.
- Phần mở rộng (expression, simulation) **chưa đề cập** — cố ý, để tách bạch vấn đề data với vấn đề alpha.

