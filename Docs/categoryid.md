# `categoryid` của catalog WorldQuant BRAIN

Có **16 `categoryid`** trong catalog. `categoryid` và `categoryname` ánh xạ 1:1.

Nguồn: snapshot cache `USA_1_TOP3000` (`cache/USA_1_TOP3000/*.npz`), fetch ngày **2026-10-22**, đã lọc `coverage` và `dateCoverage` > `MIN_COVERAGE`. `frame_id`: MATRIX `33440e2d`, VECTOR `1f7b5e84`, GROUP `f55798bc`.

---

## 1. Bảng đầy đủ

Số field theo từng field type. Cột **dataset** và **subcategory** đếm trên cả ba type.

| `categoryid` | `categoryname` | MATRIX | VECTOR | GROUP | dataset | subcategory |
| --- | --- | --- | --- | --- | --- | --- |
| `model` | Model | 14591 | 1794 | 1 | 58 | 12 |
| `analyst` | Analyst | 6269 | 3479 | 0 | 17 | 3 |
| `other` | Other | 5834 | 1186 | 1200 | 40 | 6 |
| `pv` | Price Volume | 3974 | 271 | 469 | 24 | 2 |
| `fundamental` | Fundamental | 2505 | 1054 | 0 | 18 | 3 |
| `sentiment` | Sentiment | 938 | 79 | 0 | 8 | 1 |
| `risk` | Risk | 887 | 21 | 0 | 7 | 2 |
| `option` | Option | 613 | 0 | 0 | 6 | 3 |
| `news` | News | 502 | 1020 | 0 | 25 | 2 |
| `earnings` | Earnings | 350 | 143 | 0 | 3 | 1 |
| `socialmedia` | Social Media | 111 | 19 | 0 | 4 | 1 |
| `insiders` | Insiders | 94 | 30 | 0 | 5 | 1 |
| `macro` | Macro | 82 | 10 | 0 | 5 | 1 |
| `shortinterest` | Short Interest | 70 | 31 | 0 | 5 | 1 |
| `institutions` | Institutions | 32 | 31 | 0 | 4 | 1 |
| `imbalance` | Imbalance | 2 | 0 | 0 | 1 | 1 |
| | **Tổng** | **36854** | **9168** | **1670** | | |

Số `categoryid` có mặt theo type: MATRIX 16, VECTOR 14 (thiếu `option`, `imbalance`), GROUP 3 (`model`, `other`, `pv`).

---

## 2. Độ lệch phân phối (MATRIX)

`model`, `analyst`, `other` chiếm **72,4%** field MATRIX (26694 / 36854). `imbalance` chỉ có 2 field. Rút ngẫu nhiên đều theo dòng nên bị ba category lớn chi phối.

---

## 3. Phạm vi theo scope

Trên 41 scope đã cache, hợp các `categoryid` vẫn là 16 và `USA_1_TOP3000` có đủ cả 16. Nhưng chỉ **4** `categoryid` có mặt ở **mọi** scope: `analyst`, `model`, `news`, `other`.

Các scope khác thiếu một số category, ví dụ `USA_0_*` thiếu `imbalance` và `macro`; `EUR_1_*` thiếu `earnings`, `imbalance`, `insiders`, `macro`, `option`, `shortinterest`. Một theme trỏ vào category vắng ở scope đang bốc sẽ không có field nào.

---

## 4. Cách sinh lại bảng

```python
from Functions.cache import CatalogCache, FIELD_TYPES

scope = {"region": "USA", "delay": 1, "universe": "TOP3000"}
cache = CatalogCache()
for field_type in FIELD_TYPES:
    snapshot = cache.open(scope, field_type)
    frame = snapshot.take(range(snapshot.n_rows), columns=["categoryid", "categoryname", "datasetid"])
    snapshot.close()
    print(field_type, frame.groupby("categoryid").size())
```

Số liệu đổi khi snapshot được fetch lại (tối đa 15 ngày, xem `CATALOG_MAX_AGE_SECONDS` trong `Functions/cache.py`).
