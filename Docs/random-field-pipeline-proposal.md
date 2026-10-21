# Đề xuất: Pipeline lấy mẫu ngẫu nhiên Data Field

> **TRẠNG THÁI: ĐỀ XUẤT — CHƯA ĐƯỢC CHỐT, CHƯA ĐƯỢC XÁC NHẬN.**
>
> Tài liệu này ghi lại **ý tưởng thiết kế** và các **số đo thực nghiệm** đã chạy để kiểm chứng các giả định của ý tưởng. Chưa có mã nguồn, chưa có kết quả lấy mẫu, chưa có quyết định nào được chốt. Mọi con số trong §1–§4 là **đo đạc trên API thật**; mọi lựa chọn trong §5–§9 là **đề xuất, còn đang mở**. Khi nào các quyết định ở §10 được chốt, phần đó mới trở thành thiết kế chính thức.

Ngữ cảnh: [data-description.md](data-description.md) mô tả cấu trúc catalog của BRAIN. Tài liệu này trả lời câu hỏi tiếp theo: **làm sao lấy được 3 data field một cách ngẫu nhiên, có kiểm soát, từ tập ~76 000 field?**

Phạm vi: **chỉ về data**. Chưa đụng tới cách dựng alpha expression hay cách simulate.

---

## 1. Số đo nền (đã verify, scope `EQUITY / USA / delay 1 / TOP3000`)

| Phép đo | Kết quả |
|---|---|
| Số field trong 1 GET không filter | **75 926** (`count` khớp `len(results)`, 75 926 id unique) |
| Payload / thời gian | 41.4 MB / 5.5 s |
| RAM peak khi parse | ~322 MB |
| Số dataset | 286 (274 tên khác nhau → có dataset trùng tên) |
| Category / subcategory | 16 / 41 |
| Id prefix distinct | 1 278 |

### 1.1 Ràng buộc API (đã dò, tất cả đều trả lỗi rõ ràng)

| Query | Kết quả |
|---|---|
| `/data-fields?<scope>` (không `limit`) | `200`, ra trọn 75 926 records, `count` = 75 926 |
| `/data-sets?<scope>` (không `limit`) | `200`, 286 records, 0.41 MB |
| `?limit=50` | `200`, nhưng `count` bị **cap 10 000** (không phải số thật) |
| `?limit=75` | `400 "Invalid query: pagination limit too high."` |
| `?limit=1&offset=9990` | `400 "Invalid offset. Please use filters to narrow down the result."` |
| `?search=news&limit=50&offset=50` | `200`, nhưng `search` có cap `offset + limit ≤ 100` |
| có filter mà **không** `limit` | `400 "Invalid query"` |
| `?type=MATRIX&limit=50&offset=20000` | `400` — cửa sổ filter chỉ 10 000 item |
| `?sort=`, `?order=`, `?random=`, `?seed=` | `400 "Invalid query"` — server **không** hỗ trợ sort/random |

### 1.2 Bẫy filter âm thầm — nguy hiểm nhất

Theo `OPTIONS /data-fields`, filter hợp lệ về mặt schema là `dataset.id`, `category.id`, `subcategory.id`… Nhưng thực tế server chỉ thực sự lọc với key **phẳng**:

| Query | `count` | 50 record trả về | Có lọc? |
|---|---|---|---|
| `&category=model` | 10 000 | 50/50 `category=model` | ✅ |
| `&category=fundamental` | 10 000 | 50/50 `category=fundamental` | ✅ |
| `&category=pv` | 10 000 | 50/50 `category=pv` | ✅ |
| `&subcategory=model-valuation-models` | 886 | 5/5 đúng subcategory | ✅ |
| `&dataset=model109` | 544 | 50/50 `dataset=model109` | ✅ |
| `&type=MATRIX` | 10 000 | 50/50 `type=MATRIX` | ✅ |
| `&type=VECTOR` | 10 000 | 50/50 `type=VECTOR` | ✅ |
| `&category.id=model` | 10 000 | trộn `model`/`fundamental`/`earnings`/`analyst` | ❌ **bị bỏ qua** |
| `&dataset.id=model109` | 544 | đúng (riêng `dataset.id` lại chạy) | ✅ |
| `&category.name=Model` | 10 000 | trộn lẫn | ❌ **bị bỏ qua** |

**Hệ quả:** code ghi `category.id=…` sẽ chạy trơn tru, trả HTTP 200, nhưng lấy sai tập dữ liệu — kiểu bug im lặng tệ nhất. Mọi filter phải dùng key phẳng, và **phải verify bằng cách kiểm tra giá trị trong record trả về**, không tin `count`.

### 1.3 Hệ quả kiến trúc

Vì (i) không có sort/random phía server, (ii) filter bị giới hạn cửa sổ 10 000, (iii) `count` bị cap khi có `limit` — **không thể enumerate hết một tập lọc lớn qua API**.

⇒ Quyết định kiến trúc số 1: **tải 1 lần toàn bộ scope (không filter), cache xuống đĩa, mọi lọc và lấy mẫu thực hiện local.**

---

## 2. Chiều thật của frame: `universe` không lọc gì, `region`/`delay` mới là thật

Đo trực tiếp trên tập id:

| So sánh | Kích thước | Intersection | Jaccard |
|---|---|---|---|
| `USA/1/TOP3000` vs `USA/1/TOP500` | 75 926 vs 75 926 | **75 926** | **1.000** |
| `USA/1/TOP3000` vs `USA/0/TOP3000` | 75 926 vs 16 636 | 13 547 | 0.152 |
| `USA/1/TOP3000` vs `EUR/1/TOP2500` | 75 926 vs 35 225 | 21 419 | 0.239 |
| Union 3 scope trên | 92 752 | — | — |

**`universe` không làm thay đổi tập field id** — cùng universe khác nhau trong cùng region+delay trả về *đúng* tập id giống nhau.

Ngược lại:
- `delay` cắt rất mạnh: **62 379 field (82 %) chỉ tồn tại ở delay 1**, không có ở delay 0.
- `region` gần như tách rời: overlap 21 419 chủ yếu là nhóm `model` / `pv` dùng chung.
- `ALL / delay 1 / LARGE` → **0 field** (scope tồn tại nhưng rỗng).

⇒ **Frame hiệu dụng là 16 cặp `(region, delay)`, không phải 44 scope.** `universe` chỉ quyết định *backtest chạy trên tập instrument nào*, không quyết định *field nào tồn tại*.

Cần kiểm tra thêm (chưa làm): với `delay = 0` (non-delayed), danh sách field có phải *tập con* của `delay = 1` không, hay là bản khác nhau về nội dung (đề xuất: coi mỗi `(region, delay)` là một frame riêng, gắn cặp này vào từng field).

---

## 3. Pipeline 6 stage (đề xuất)

```
[0] FRAME        chọn (region, delay) hoặc union các cặp
                 → frame = tập field id + metadata đầy đủ
[1] FETCH        GET /data-fields?<region>&<delay>      (không limit)
                 1 request / cặp, ~5–40 s, 9–41 MB
[2] NORMALIZE    flatten category / subcategory / dataset / themes
                 → 1 row / field, cột phẳng
[3] ELIGIBLE     lọc data-level theo §5
                 → bảng eligible, đánh số 1..N
[4] SNAPSHOT     cache theo content-hash của frame          (bắt buộc, §7)
[5] SAMPLE       rng = Random(seed); chọn k = 3
[6] OUTPUT       1 row / draw:
                 seed, draw_id, frame_id, field_id, dataset_id, dataset_name,
                 category, subcategory, type, coverage, date_coverage,
                 date_created, user_count, alpha_count, description
```

Chỉ stage 5 là random; stage 1–2 deterministic. Toàn bộ chi phí nằm ở stage 1.

---

## 4. Mô tả dữ liệu field (đã đo)

**Key presence trên 75 926 record:**

```
id 75926 · description 75926 · dataset 75926 · category 75926 · subcategory 75926
region 75926 · delay 75926 · universe 75926 · type 75926 · coverage 75926
userCount 75926 · alphaCount 75926 · pyramidMultiplier 75926 · themes 75926
dateCreated 75926 · dateCoverage 72667          ← thiếu 3 259 record (4.3 %)
```

**`type`:** MATRIX 57 356 · VECTOR 16 514 · GROUP 2 041 · SYMBOL 8 · UNIVERSE 7

**`category`:** model 18 971 · analyst 17 215 · pv 12 825 · fundamental 11 041 · other 9 203 · news 2 548 · sentiment 1 207 · risk 941 · option 619 · earnings 588 · socialmedia 232 · insiders 185 · macro 153 · shortinterest 110 · institutions 86 · imbalance 2

**Category × type** (cho thấy VECTOR tập trung ở đâu):

| category | n | MATRIX | VECTOR | GROUP | SYM | UNIV |
|---|---|---|---|---|---|---|
| model | 18 971 | 16 517 | 2 449 | 1 | 4 | — |
| analyst | 17 215 | 11 184 | 6 031 | — | — | — |
| pv | 12 825 | 11 357 | 617 | 840 | 4 | 7 |
| fundamental | 11 041 | 7 993 | 3 048 | — | — | — |
| other | 9 203 | 6 238 | 1 765 | 1 200 | — | — |
| news | 2 548 | 637 | 1 911 | — | — | — |
| sentiment | 1 207 | 1 065 | 142 | — | — | — |
| socialmedia | 232 | 111 | 121 | — | — | — |
| risk | 941 | 920 | 21 | — | — | — |
| option | 619 | 619 | — | — | — | — |
| earnings | 588 | 357 | 231 | — | — | — |
| insiders | 185 | 118 | 67 | — | — | — |
| macro | 153 | 105 | 48 | — | — | — |
| shortinterest | 110 | 79 | 31 | — | — | — |
| institutions | 86 | 54 | 32 | — | — | — |
| imbalance | 2 | 2 | — | — | — | — |

**`coverage`:** min 0.0 · p10 0.50 · median 0.894 · p90 1.0 · max 1.0
→ `coverage == 0`: **82 field** (chết) · `< 0.5`: 5 565 · `≥ 0.95`: 30 291

**`dateCreated`:** 2022-05 → 2026-04. Đáng chú ý: **22 736 field tạo trong 2026-03**, 4 042 trong 2026-04 → catalog có dòng chảy mạnh, không phải tập tĩnh.

**`id`:** 100 % khớp `[a-z0-9_]`, độ dài 3–95 (median 29), 75 926 id unique. Không cần sanitize.

**`userCount` / `alphaCount`:** **25 549 field (33.6 %) có cả hai bằng 0** — chưa ai từng dùng. Số này **bằng nhau tuyệt đối** giữa hai cột (không field nào user>0 mà alpha=0) → có vẻ server dùng chung một cờ "đã dùng".

---

## 5. Stage 3 — Eligibility (đề xuất, chưa chốt)

| Tiêu chí | Dữ liệu | Đề xuất v1 | Lý do |
|---|---|---|---|
| `type` | xem §4 | **chỉ MATRIX** (57 356) | VECTOR cần chính sách aggregate riêng (analyst 6 031 + news 1 911 ≈ 48 % mọi VECTOR) → để stage sau, khi có chính sách |
| `coverage` | 82 field = 0 | loại `coverage == 0` | field chết, không có dữ liệu |
| `coverage` | p10 = 0.50 | **ngưỡng ≥ 0.5** (bỏ 5 565, còn ~70 361) | field phủ < 50 % instrument thì hầu như không dùng được; ngưỡng này có thể nới nếu giảm tỉ lệ fail |
| `dateCoverage` | thiếu 4.3 % | loại record thiếu | không biết độ sâu lịch sử → không đánh giá được tính khả dụng |
| `userCount`/`alphaCount` | 25 549 field = 0 | **giữ**, không lọc | xem §6 — đây là bias hai chiều, phải nêu chứ không giấu |
| `dateCreated` | 2026-03/04 có 26 778 field mới | không lọc, nhưng **ghi lại** | field mới = data-snooping risk nếu backtest trùng kỳ tạo field |
| `id` | 100 % sạch | không cần lọc | — |

---

## 6. Bias hai chiều của "field chưa ai dùng" (cần quyết định nghiên cứu)

25 549 field có `userCount = alphaCount = 0`.

- **Giữ** → không gian khám phá tối đa; tránh chọn field *đã biết là tốt* → selection bias theo hướng ngược (có thể thiên về field *tệ*).
- **Bỏ** → field đã từng được compile & backtest thành công → tỉ lệ lỗi thấp hơn, **nhưng** field được dùng nhiều thường là field tốt → bias *tăng* khả năng thành công (giống survivorship bias).

Không có lựa chọn nào "đúng" — phải nêu rõ trong paper và báo cáo cả hai chế độ nếu chạy.

---

## 7. Reproducibility: seed không đủ, phải đóng băng frame

Catalog là mục tiêu động (4 042 field mới trong 2026-04). Cùng `seed = 42` ở tuần sau sẽ ra bộ khác.

⇒ Đề xuất: **frame phải được pin bằng content-hash**, không chỉ bằng seed.

```
frame_id = sha256( sorted(field_ids) )[:8]
```

Và vì `universe` không đổi tập id nhưng đổi ngữ nghĩa backtest, `frame_id` **phải ghi kèm `(region, delay)`** — cùng một tập id ở scope khác vẫn là frame khác.

Mỗi dòng output phải mang đủ: `frame_id`, `region`, `delay`, `seed`, `draw_id`, `field_id`. Đủ để tái lập *bit-exact* sau này.

---

## 8. Phân phối mẫu: 4 phương án (chưa chốt)

**Hiện tượng lệch — đã đo:**

| Mức tập trung | Kết quả |
|---|---|
| Dataset lớn nhất (`pv87` — "Aggregated dataset") | 6 666 field = **8.8 %** |
| Top 5 dataset | 22.6 % |
| Top 10 dataset | 35.0 % |
| Top 20 dataset | 52.3 % |
| Top 50 dataset | 77.0 % |
| Top 100 dataset | 92.3 % |
| HHI theo dataset | 0.0216 → **hiệu dụng 46.3 / 286** dataset |
| HHI theo category | 0.1799 → **hiệu dụng 5.56 / 16** category |

**Bẫy family.** 1 278 id prefix, nhưng top 5 prefix đã chiếm 12 972 field: `pv87` 6 666 · `anl15` 2 538 · `fnd28` 2 209 · `anl10` 2 148 · `mdl264` 2 038. Field cùng prefix là **biến thể của cùng một khái niệm** (`anl10`/`anl15` = analyst forecast các kỳ khác nhau; `pv87` = 6 666 field cùng họ Price Volume).

Nếu uniform trên field, 3 field có thể ra 3 thành viên cùng họ → thực chất chỉ **1 feature độc lập**, không phải 3. Đây là lỗi thiết kế reviewer rất dễ chỉ ra, nên phải xử lý tường minh chứ không hy vọng nó hiếm xảy ra.

| | Cách làm | Đặc tính | Khi nào dùng |
|---|---|---|---|
| **A. Uniform field** | `sample` trên N id eligible | Đơn giản; nhưng **Model + Analyst ≈ 47 %** → thực chất là *Model-heavy baseline*; P(cả 3 cùng dataset) ≤ 0.19 % (bound: max p × HHI) | null baseline trung thực — **luôn nên chạy** |
| **B. Stratified theo category** | 16 nhóm, mỗi nhóm 1 field | Ép đa dạng ngữ nghĩa | baseline có kiểm soát |
| **C. Hai tầng: dataset → field** | chọn dataset uniform (286) rồi field uniform trong đó | Mỗi dataset đóng góp 1 dataset; frame phẳng hơn A nhiều | trả lời "dataset nào đáng khai thác" |
| **D. Cluster-aware (1 per family)** | gom theo id prefix, mỗi family 1 field | Đảm bảo 3 feature **thực sự khác nhau** | khi claim "3 independent features" |

**Đề xuất (chưa chốt):** chạy **A (null) + D (có kiểm soát)** song song, và **luôn báo cáo phân phối category/dataset của các draw**. Không thể gọi A là "random feature baseline" mà không nói rõ nó thiên về Model/Analyst.

---

## 9. Chi phí vận hành (ước tính)

| Việc | Quy mô |
|---|---|
| Tải 1 scope lớn | 41 MB / 5.5 s |
| Tải 1 scope nhỏ (`USA/0/TOP3000`) | 8.9 MB |
| Tải 16 cặp `(region, delay)` | ~150–250 MB, ~2–3 phút, 16 request |
| Rate limit | 1 req/s → **không phải nút thắt** |
| RAM lúc parse | ~322 MB peak (đo thật) |
| Cache format | parquet cần thêm `pyarrow`; không có thì CSV ~15–20 MB |

Sau khi cache một lần, mọi lần sample chỉ đọc local → gần như tức thì.

---

## 10. Các quyết định còn mở — CHƯA CHỐT

| # | Câu hỏi | Các lựa chọn | Hiện trạng |
|---|---|---|---|
| 1 | Frame là gì? | (a) chỉ `USA / delay 1` — 75 926 field, đơn giản, đúng scope mặc định hiện tại; (b) union 16 cặp `(region, delay)` + dedup theo id, gắn `(region, delay)` vào từng field | **chưa chốt** |
| 2 | Phương án lấy mẫu? | A / B / C / D ở §8 | **chưa chốt** |
| 3 | `type` nào được phép? | MATRIX-only (57 356) hay MATRIX+VECTOR (73 870, cần định nghĩa cách aggregate vector) | **chưa chốt** |
| 4 | Ngưỡng `coverage`? | ≥ 0.5 (bỏ 5 565, còn ~70 361) hay chỉ loại `coverage == 0` (bỏ 82) | **chưa chốt** |
| 5 | Field `userCount = alphaCount = 0` (25 549)? | giữ hay bỏ, và báo cáo bias hai chiều thế nào (§6) | **chưa chốt** |
| 6 | Có chạy cả A + D, hay chỉ một? | §8 | **chưa chốt** |
| 7 | Cache ở đâu, format gì? | `cache/` local, parquet vs CSV | **chưa chốt** |
| 8 | Bao nhiêu draw? | số draw N đủ để ước lượng phân phối với confidence interval hợp lý | **chưa chốt** |

---

## 11. Việc cần kiểm tra thêm trước khi chốt

- [ ] `delay 0` vs `delay 1`: nội dung field có thực sự khác nhau, hay chỉ là tập con? Có field nào chỉ có ở delay 0 không? (đo: `USA/0 − USA/1` = 3 089 field → **có**)
- [ ] Mối quan hệ giữa `coverage` và `dateCoverage` (hiện `dateCoverage` thiếu 4.3 % — các record thiếu có tập trung ở category nào không?)
- [ ] 41 subcategory: có subcategory nào "rác" (chứa field không liên quan) không? Ví dụ `other-aiml-data` có 7 800 field — cần xem mẫu để biết đây là dữ liệu gì.
- [ ] Có nên dùng `dataset` (286) làm *frame thứ cấp* thay vì field làm frame thứ cấp không?
- [ ] Kiểm tra `themes` — có bao nhiêu theme, phân bố ra sao, dùng được làm nhóm ngữ nghĩa thay `category` không?

---

## 12. Ghi chú lịch sử

- Tài liệu này là **ý tưởng + số đo kiểm chứng giả định**, chưa phải thiết kế chính thức.
- Mọi con số §1–§4, §8, §9 lấy từ API thật ngày **2026-10-21**, scope `EQUITY / USA / delay 1 / TOP3000` trừ khi ghi rõ khác.
- Phần mở rộng (expression, simulation) **chưa đề cập** — cố ý, để tách bạch vấn đề data với vấn đề alpha.
- Khi §10 được chốt, cập nhật lại §3 và §5 cho khớp, rồi chuyển trạng thái tài liệu từ "đề xuất" sang "thiết kế".
