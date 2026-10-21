# Mô tả dữ liệu WorldQuant BRAIN

Ghi lại cấu trúc catalog dữ liệu của BRAIN platform: tập scope hợp lệ, và snapshot số lượng dataset / data field theo từng category.

Nguồn: `Functions/data.py` (`BrainData.settings`, `BrainData.datasets`, `BrainData.datafields`), snapshot runtime ngày 2026-10-21.

## 1. Scope space

Mọi endpoint catalog của BRAIN (`/data-sets`, `/data-fields`, `/simulations`) đều **scoped** theo bộ 4 giá trị:

```
instrumentType, region, delay, universe
```

Tập scope hợp lệ **không phải** do client suy ra — nó được publish sẵn trong payload `OPTIONS /simulations`, dưới dạng cây:

```
children.instrumentType.choices                          → list phẳng
children.region.choices.instrumentType[EQUITY]           → list region
children.delay.choices.instrumentType[EQUITY].region[R]   → list delay
children.universe.choices.instrumentType[EQUITY].region[R] → list universe
```

Lưu ý: `region` nest 1 cấp dưới `instrumentType`, còn `delay` và `universe` nest **2 cấp** (thêm `region` ở giữa). Đọc sai cấp sẽ ra scope sai.

| Region | Delay | Universe |
|---|---|---|
| ALL | 1 | LARGE, MEDIUM, SMALL |
| USA | 1, 0 | TOP3000, TOP2000, TOP1000, TOP500, TOP200, TOPSP500 |
| GLB | 1 | TOP3000, MINVOL1M, MINVOL10M, TOPDIV3000 |
| EUR | 1, 0 | TOP2500, TOP1200, TOP800, TOP400, TOPCS1600 |
| ASI | 1 | MINVOL1M, MINVOL10M, TOP500 |
| CHN | 0, 1 | TOP2000U |
| KOR | 1 | TOP600 |
| TWN | 1 | TOP500, TOP100 |
| HKG | 1 | TOP800, TOP500 |
| IND | 1 | TOP500 |
| DEU | 1, 0 | TOP500 |
| GBR | 1, 0 | TOP700 |

Tổng: **12 region**, **30 cặp (region, universe)**, **44 scope** hợp lệ (mỗi region nhân với số delay của nó).

### Cảnh báo: tên universe KHÔNG phải là khoá duy nhất

Trong 30 cặp trên chỉ có **21 tên universe distinct** — cùng một tên xuất hiện ở nhiều region với ý nghĩa khác nhau:

| Universe name | Xuất hiện ở region |
|---|---|
| `TOP3000` | ALL, USA, GLB |
| `MINVOL1M` | GLB, ASI |
| `MINVOL10M` | GLB, ASI |
| `TOP500` | USA, ASI, TWN, HKG, IND, DEU |
| `TOP3000` / `TOP500` | **không có** ở EUR (EUR dùng `TOP2500`, `TOP1200`, `TOP800`, `TOP400`, `TOPCS1600`) |

`TOP500` chẳng hạn là 6 scope khác nhau ở 6 region khác nhau. Unit of analysis phải là **tuple đầy đủ** `(region, delay, universe)`, không phải tên universe.

## 2. Snapshot catalog — scope `EQUITY / USA / delay 1 / TOP3000`

Đây là scope dùng mặc định trong `main.py`. Số liệu dưới đây **thuộc về scope này**, không phải số liệu toàn platform.

```
Datasets: 286      Data fields: 75926
```

### 2.1 Cột trả về

**`/data-sets`** (20 cột):

```
id, name, description, categoryid, categoryname, subcategoryid, subcategoryname,
region, delay, universe, dateCoverage, coverage, valueScore, userCount, alphaCount,
fieldCount, pyramidMultiplier, themes, dateUpdated, researchPapers
```

**`/data-fields`** (19 cột):

```
id, description, datasetid, datasetname, categoryid, categoryname, subcategoryid,
subcategoryname, region, delay, universe, type, dateCoverage, coverage, userCount,
alphaCount, pyramidMultiplier, themes, dateCreated
```

Ghi chú: response gốc của BRAIN là JSON **lồng nhau** (`category: {id, name}`, `dataset: {id, name}`, `themes: [...]`). `Functions/data.py` dùng `_flatten` đệ quy với tiền tố để tách mỗi leaf thành cột `parent_child` (`categoryid`, `categoryname`, `datasetid`, `datasetname`), tránh va chạm tên key giữa các record.

### 2.2 Data field theo `type`

| type | Số lượng |
|---|---|
| MATRIX | 57 356 |
| VECTOR | 16 514 |
| GROUP | 2 041 |
| SYMBOL | 8 |
| UNIVERSE | 7 |
| **Tổng** | **75 926** |

- `MATRIX` — giá trị một số cho mỗi instrument mỗi ngày (giá, volume, analyst estimate…).
- `VECTOR` — vector nhiều chiều cho mỗi instrument (vd. embedding, factor vector).
- `GROUP` — nhóm dùng để gom field (vd. `price` group của dataset Price Volume).
- `SYMBOL` / `UNIVERSE` — field định danh instrument và field định danh tập universe.

Chỉ `MATRIX` và `VECTOR` mới dùng được trực tiếp làm input của một expression backtest.

### 2.3 Dataset theo category

| categoryname | Số dataset |
|---|---|
| Model | 69 |
| Other | 56 |
| Price Volume | 30 |
| News | 26 |
| Analyst | 25 |
| Fundamental | 23 |
| Sentiment | 10 |
| Macro | 7 |
| Risk | 7 |
| Earnings | 6 |
| Option | 6 |
| Short Interest | 6 |
| Insiders | 5 |
| Social Media | 5 |
| Institutions | 4 |
| Imbalance | 1 |
| **Tổng** | **286** |

### 2.4 Data field theo category

| categoryname | Số field |
|---|---|
| Model | 18 971 |
| Analyst | 17 215 |
| Price Volume | 12 825 |
| Fundamental | 11 041 |
| Other | 9 203 |
| News | 2 548 |
| Sentiment | 1 207 |
| Risk | 941 |
| Option | 619 |
| Earnings | 588 |
| Social Media | 232 |
| Insiders | 185 |
| Macro | 153 |
| Short Interest | 110 |
| Institutions | 86 |
| **Tổng** | **75 926** |

## 3. Nhận xét về cấu trúc dữ liệu

**Model là category lớn nhất, và cả về dataset lẫn field.** 18 971 / 75 926 ≈ 25 % toàn bộ field thuộc category `Model`, và 69/286 dataset. Đây là các model do người dùng BRAIN tự train và publish (vd. model dự báo lợi nhuận, model sentiment). Với nghiên cứu alpha, đây là nguồn feature **đã được người khác huấn luyện sẵn** — dùng lại chúng rẻ hơn nhiều so với tự build feature từ raw field.

**Tỷ lệ VECTOR/MATRIX ≈ 22 %** (16 514 / 75 356). Không nhỏ. Bất kỳ pipeline nào chỉ xử lý field `MATRIX` sẽ bỏ sót hơn 1/5 catalog. Cần quyết định rõ: có dùng vector field hay không, và nếu có thì cách aggregate (mean/median/first-component) phải được định nghĩa cố định.

**`Other` đứng thứ 5 về số dataset (56) nhưng chỉ thứ 5 về số field (9 203)** → trung bình ~164 field/dataset, thấp hơn nhiều so với `Model` (~275) và `Analyst` (~689). Dataset `Other` chủ yếu là dataset nhỏ, đa dạng, khó phân loại.

**`Fundamental` là category "sạch" nhất về mặt ý nghĩa** — báo cáo tài chính, không phụ thuộc sentiment/model. Nếu cần baseline defensible cho paper, đây là nhóm nên chọn.

**Cột `fieldCount` của dataset nên dùng làm sanity check** khi đối chiếu với `/data-fields`: tổng `fieldCount` trong một scope phải bằng `len(datafields(scope))`. Nếu lệch → endpoint bị paginate cắt hoặc scope sai.

## 4. Ràng buộc kỹ thuật khi duyệt catalog

**Rate limit theo giây.** Response header `X-RateLimit-Remaining-Second` cho biết số request còn được phép trong giây hiện tại. Sweep toàn bộ 44 scope = 88 request → tối thiểu ~88 giây nếu giữ đúng 1 req/s.

**`BrainData._get` hiện chưa retry khi response không phải JSON.** Dưới rate limit, `GET /data-fields` có thể trả về body HTML lỗi → `requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. `summary()` trên toàn bộ 44 scope đã tái hiện được lỗi này. Cần retry theo kiểu: thử parse → fail thì sleep → gọi lại.

**Không cộng dồn số field giữa các scope.** Cùng một field (vd. một field trong dataset Price Volume) xuất hiện ở nhiều universe trong cùng region, và có thể ở cả nhiều region. Tổng `n_datafields` của 44 scope **không phải** kích thước catalog, chỉ là tổng số scope-field. Muốn kích thước catalog thật thì phải deduplicate theo `id`.

> **Cập nhật (2026-10-21, đo trực tiếp):** giả định "cùng field xuất hiện ở nhiều universe" ở trên cần đính chính — đo trên tập id cho thấy `universe` **không làm thay đổi tập field id** (`USA/1/TOP3000` và `USA/1/TOP500` trả về *đúng* 75 926 id giống nhau, Jaccard = 1.000). Chỉ `region` và `delay` mới thay đổi tập id. Chi tiết và hệ quả thiết kế: [random-field-pipeline-proposal.md](random-field-pipeline-proposal.md) §2.

## 5. Cách tái lập snapshot

```bash
uv run main.py
```

In ra: số dataset, số data field, danh sách cột, breakdown theo `type` và theo `categoryname`, cho scope mặc định `EQUITY / USA / 1 / TOP3000`.

Để đổi scope, sửa biến `scope` trong `main.py`:

```python
scope = {"instrumentType": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
```

Liệt kê toàn bộ scope hợp lệ:

```bash
uv run python -c "
from Functions.login import BrainLogin
from Functions.data import BrainData
l = BrainLogin(); s = l.get_session(); d = BrainData(s, l.base_url)
for sc in d.combinations():
    print(sc)
"
```
