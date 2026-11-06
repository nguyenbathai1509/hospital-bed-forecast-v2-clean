# Dự báo giường bệnh V2

Ứng dụng xử lý dữ liệu giường bệnh, huấn luyện và đánh giá mô hình, quản lý mô hình sử dụng, lập dự báo và đối chiếu với thực tế. Kiến trúc: **Streamlit → FastAPI → services/repositories → SQL Server**.

Nguồn hiện tại là hai file Excel `data/HSNoi.xlsx` và `data/hsNgoai.xlsx`, chưa phải kết nối trực tiếp HIS. Mô hình gồm RF, XGBoost, SVR và LSTM cho H+1/H+3; chỉ số đánh giá chính là MAE.

## Bắt đầu

- [Cài đặt và chạy trên Windows](docs/WINDOWS_QUICKSTART.md): môi trường, cấu hình, database, API và giao diện.
- [Quy trình vận hành](docs/OPERATIONS.md): thêm dữ liệu, huấn luyện, chọn mô hình, xác nhận dự báo và xử lý sự cố.
- [Kết quả nghiệm thu backend thật](docs/E2E_ACCEPTANCE.md): bằng chứng, môi trường cách ly và phạm vi chưa kiểm chứng.

Nếu đã cài đủ thư viện và cấu hình database, chạy từ thư mục gốc project trong **hai terminal PowerShell riêng**:

```powershell
# Terminal 1: backend
.venv\Scripts\python.exe -m scripts.run_api
```

```powershell
# Terminal 2: giao diện
$env:V2_API_BASE_URL = 'http://127.0.0.1:8000'
.venv\Scripts\python.exe -m scripts.run_dashboard
```

Mở giao diện tại `http://127.0.0.1:8501`. Backend đọc `.env`; cấu hình giao diện đọc biến môi trường của terminal, không tự nạp `.env`.

## Luồng sử dụng

```text
Excel mới → Chạy pipeline → Kiểm tra chất lượng và DATA_READY
                               ↓
                 Huấn luyện → Đánh giá → Chọn mô hình sử dụng
                                             ↓
                    Xem thử → Bản nháp → Xác nhận chính thức
                                             ↓
                   Dữ liệu thực tế mới → Đối chiếu và giám sát
```

Giao diện có tám trang: Tổng quan, Dữ liệu, Huấn luyện mô hình, Kết quả huấn luyện, Quản lý mô hình, Dự báo, Giám sát và Đặt lại trình diễn. Trang đặt lại không thuộc quy trình vận hành thông thường.

Thêm file/dòng Excel **không tự chạy pipeline hoặc huấn luyện**. Pipeline không tự tạo dự báo chính thức; người dùng phải kiểm tra và xác nhận. Không nhất thiết huấn luyện lại mỗi lần thêm ngày nếu mô hình đang sử dụng vẫn phù hợp.

## Lưu ý an toàn

- Phân quyền đang được bỏ qua theo phạm vi dự án: chỉ dùng cục bộ hoặc trong môi trường nội bộ được kiểm soát, không mở trực tiếp ra Internet.
- Không đưa `.env`, mật khẩu, dữ liệu bệnh viện hoặc artifact/bằng chứng chứa dữ liệu nhạy cảm lên dịch vụ công khai.
- Database `HospitalBedForecastV2_E2E` chứa dữ liệu thử; không dùng làm database vận hành.
- Timeout giao diện không chứng minh thao tác backend đã thất bại. Kiểm tra trạng thái/lịch sử trước khi gửi lại thao tác ghi.
- Khoảng dự báo tham khảo không bảo đảm mức bao phủ trên dữ liệu tương lai; nghiệm thu kỹ thuật không chứng nhận chất lượng sử dụng lâm sàng.

## Kiểm thử và tài liệu kỹ thuật

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Kiểm thử SQL tùy chọn cần bật riêng; công cụ E2E có thao tác ghi vào môi trường thử và không chạy trong bộ pytest mặc định. Xem hướng dẫn tương ứng trước khi chạy.

| Chủ đề | Tài liệu |
| --- | --- |
| Chia tập theo dữ liệu mới | [Dynamic training split](docs/DYNAMIC_TRAINING_SPLIT.md) |
| So sánh trên cùng cửa sổ | [Common-window backtest](docs/COMMON_WINDOW_BACKTEST.md) |
| Baseline và khoảng dự báo | [Baselines and uncertainty](docs/BASELINES_AND_UNCERTAINTY.md) |
| Worker và khôi phục tác vụ | [Training job recovery](docs/TRAINING_JOB_RECOVERY.md) |
| Giao diện và CSS | [Visual system](docs/UI_VISUAL_SYSTEM.md) |
| Quy trình giao diện | [Workflow review](docs/UI_WORKFLOW_REVIEW.md) |
| Hiệu năng giao diện | [UI performance](docs/UI_PERFORMANCE.md) |

## Chức năng và nguyên tắc hiện tại

| Thành phần | Trách nhiệm |
| --- | --- |
| Pipeline | RAW/DQ/CLEAN → đặc trưng → mẫu học; đối chiếu actual và giám sát |
| Huấn luyện | RF, XGBoost, SVR, LSTM cho H+1/H+3; chọn cấu hình trên validation, đánh giá test, refit riêng |
| Quản lý mô hình | Phân biệt ứng viên, khuyến nghị và mô hình sử dụng; promotion/rollback có xác nhận |
| Dự báo | Preview không lưu; Production Predict tạo/tái sử dụng Draft; xác nhận mới tạo Official |
| Giám sát | Chỉ dùng Official và actual đã có; không tạo chỉ số giả khi thiếu dữ liệu |
| Giao diện | Streamlit gọi FastAPI; không trực tiếp truy cập SQL hoặc huấn luyện mô hình |

### Huấn luyện nền và biểu đồ

Luồng tác vụ: **Training → Recommendation → Evaluation Replay → Job COMPLETED**.
Trạng thái API job khác scientific Training Run: replay thất bại có thể khiến job FAILED dù Training Run đã COMPLETED.
Retry có thể tái sử dụng các giai đoạn đã hoàn tất, không mặc định huấn luyện lại toàn bộ.

Replay dựng lại mô hình đánh giá từ cấu hình và split đã lưu, không dùng artifact đã refit toàn bộ dữ liệu để chấm test.
Trang kết quả có so sánh chỉ số, timeline train/validation/test, actual–prediction, residual và kết quả từng khoa khi có bằng chứng tương ứng.
Chọn run khác sẽ đọc kết quả của run đó; không đồng nghĩa giao diện tự polling liên tục.
Ngày và số mẫu phải lấy từ run đang xem, không coi các con số lịch sử là quy tắc cố định.

### Xác nhận và quản lý lịch sử

- Recommended chỉ là khuyến nghị; thay đổi mô hình sử dụng cần xác nhận.
- Quota thay đổi thông thường hiện xét theo **business_date + horizon**, không phải quota chung theo ngày như V2-16 ban đầu.
- Daily model lock quyết định hiệu lực IMMEDIATE hoặc NEXT_CYCLE; pipeline kích hoạt lịch đến hạn nếu không bị khóa.
- Rollback có xác nhận và audit riêng, không sửa Official lịch sử.
- Sai số giám sát có dấu `actual − prediction_raw`; bias dương nghĩa là dự báo thiếu.
- Giường kế hoạch là tham chiếu công suất, không phải mức trần bắt buộc của dự báo.

### API và nguồn mã

Các nhóm API gồm trạng thái/dữ liệu, pipeline, training, model registry/promotion/rollback, forecast và monitoring.
Endpoint `GET /training/evaluation/{run_id}` cung cấp bằng chứng biểu đồ theo horizon, model_family và khoa.
Xem hợp đồng cụ thể tại [src/api/app.py](src/api/app.py); endpoint ghi có thể thay đổi dữ liệu, không dùng để thử kết nối tùy tiện.

## Lịch sử phát triển đã hợp nhất

Sáu README theo giai đoạn được giữ trong các mục thu gọn dưới đây để thư mục gốc chỉ còn một README.
Đây là hồ sơ checkpoint, **không phải trạng thái hiện tại hoặc hướng dẫn chạy lại**.

Số test, phiên bản thư viện, run ID, trạng thái Production, ngày dữ liệu và số dòng chỉ mô tả thời điểm ghi nhận.
Ghi chú cũ về quota chung theo ngày, thiếu biểu đồ, polling, CODE-READY hoặc PENDING không thay thế hướng dẫn hiện hành phía trên.
Tài liệu `V2-11_*` trong `docs/` cũng là hồ sơ lịch sử.
Giữ [README dữ liệu](data/README.md) cạnh hai Excel để tra cứu hợp đồng nguồn.

<details>
<summary>V2-16 - Production Promotion + Rollback</summary>

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](docs/WINDOWS_QUICKSTART.md) và [quy trình vận hành](docs/OPERATIONS.md).

This phase adds the governed boundary between Recommendation and Production.

Key contracts:
- Recommended is advisory; only confirmed Promotion changes Production.
- One normal Production Change Transaction per business_date.
- If no daily model lock exists for a horizon, effect is IMMEDIATE.
- If a daily model lock exists, effect is NEXT_CYCLE.
- Emergency rollback is an audited quota exception with a stronger confirmation phrase.
- Rollback never rewrites historical Official Forecasts.
- Daily Pipeline activates due NEXT_CYCLE slots only when that business_date+horizon is not locked.

Initial bootstrap on the verified thesis dataset should activate Recommended RF for H+1 and Recommended SVR for H+3 in one confirmed IMMEDIATE transaction.

</details>

<details>
<summary>V2-18 - Actual Matching + Production Monitoring</summary>

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](docs/WINDOWS_QUICKSTART.md) và [quy trình vận hành](docs/OPERATIONS.md).

#### Part A - Monitoring Core

Part A defines the pure contracts before SQL persistence.

Key rules:
- Only Official Forecast is eligible for Actual Matching and Production Monitoring.
- If target_date is later than the latest CLEAN Actual date for that department, status is `WAITING_FOR_ACTUAL`; future Actual is never fabricated.
- Error sign is `actual - prediction`; positive error/bias means underprediction.
- Primary Production metrics use `prediction_raw` so they remain comparable with V2-09/V2-14 evaluation metrics.
- `prediction_rounded` remains operational evidence and does not replace raw model-quality metrics.

User verification: 43/43 tests PASS.

#### Part B - SQL Persistence + Daily Pipeline Integration

Part B adds:
- `migrations/007_actual_matching_monitoring.sql`
- `dbo.official_actual_matches`
- `dbo.production_monitoring_runs`
- `dbo.production_monitoring_metrics`
- `src/monitoring/repository.py`
- `src/monitoring/service.py`
- `scripts/run_monitoring.py`
- `scripts/verify_v2_18.py`
- Daily Pipeline stages `ACTUAL_MATCHING` and `MONITORING`

The match table is keyed by `official_id`, therefore Preview, Draft, Recommended and Custom forecasts cannot become Production monitoring evidence.

If CLEAN Actual is corrected later, the current match evidence is refreshed only when the actual value/quality/source revision changes; `match_revision_no` increments. Monitoring snapshots are attached to the Daily Pipeline run and remain auditable.

Capacity alert monitoring is connected here without changing the forecasting rule: `planned_beds` is still only a capacity reference, never a prediction cap. Actual capacity event is `actual_occupied_beds > planned_beds`; the Official `capacity_alert` is evaluated via TP/FP/FN/TN, precision, recall and accuracy.

With the current verified bootstrap dataset:
- latest CLEAN Actual = 2026-06-30
- Official H+1 target = 2026-07-01
- Official H+3 target = 2026-07-03

Therefore the scientifically correct initial integration result is 4 Official rows waiting for Actual, 0 matched rows and 0 monitoring metric rows. No future Actual is invented.

Part B internal code-ready snapshot: **48/48 tests PASS**. SQL integration remains pending until migration 007 and the updated Daily Pipeline are run on the user's SQL Server.

</details>

<details>
<summary>V2-19 - FastAPI and API Contract</summary>

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](docs/WINDOWS_QUICKSTART.md) và [quy trình vận hành](docs/OPERATIONS.md).

#### Part A - API Foundation + Data Status — COMPLETE

Verified on the user's Windows environment:

- FastAPI 0.141.1
- Uvicorn 0.52.4
- Pydantic 2.13.5
- HTTPX 0.28.1
- 54/54 tests PASS
- `GET /health` -> 200
- `GET /data/status` -> 200 against real SQL Server
- `GET /departments` -> 200 against real SQL Server
- Vietnamese Unicode verified from Python HTTPX; the earlier mojibake was only PowerShell console rendering.

#### Part B - Pipeline/Data API

Part B implements the remaining Master V2 section 19.2 endpoints:

- `GET /pipeline/runs` - Daily Pipeline history with quality summary.
- `POST /pipeline/run` - manual trigger delegating to the existing Daily Pipeline service.
- `GET /data-quality` - DQ issues by run/date/department/severity.
- `GET /history` - CLEAN occupancy and patient-flow history by department.

Architectural rules:

- FastAPI does not reimplement RAW/DQ/CLEAN/FEATURE/ML/Monitoring logic.
- `POST /pipeline/run` delegates to `run_daily_excel_pipeline` through a dependency.
- The endpoint does not accept arbitrary filesystem paths. Under current `EXCEL_BOOTSTRAP` it resolves the verified project paths `data/HSNoi.xlsx` and `data/hsNgoai.xlsx` internally. A future Hospital SQL source adapter can replace the dependency without changing the route contract.
- `GET /data-quality` defaults to the latest pipeline run, while an explicit unknown run returns HTTP 404.
- `GET /history` reads `dbo.clean_bed_daily`, not RAW, and returns occupancy, flows, derived `net_flow`, utilization, quality flag and source revision.
- Invalid request schemas return 422; invalid date ranges return 400; missing department/run resources return 404.
- Authorization for the manual pipeline trigger is still a required deployment gate and will be enforced in the later Roles/Permissions phase. Until that phase, the API is local/internal only and must not be exposed publicly.

Part B code-ready snapshot: **65/65 tests PASS** in the prepared snapshot. User-side unit verification and SQL/API runtime integration remain pending.

#### User unit-test verification

On the user's Windows environment, the full suite passed: **65 passed, 2 warnings in 2.60s**. The warnings are the existing Starlette/FastAPI TestClient and anyio deprecations; they are non-blocking. Runtime SQL/API verification remains pending.

#### Part B runtime read checkpoint — VERIFIED

User-side Windows + SQL Server verification:

- Full test suite: 65 passed, 2 deprecation warnings.
- `GET /pipeline/runs?limit=5` -> HTTP 200. Latest run `DAY_20260907T170849Z_7E731C5C` is `DATA_READY`, business date 2026-06-30, rows=362, DQ ERROR=0/WARNING=0/CHECK=2. Historical runs remain visible, including an older run with WARNING=231.
- `GET /data-quality?severity=CHECK&limit=10` -> HTTP 200, exactly 2 current CHECK rows, both rule `DQ07`, for department 343 on 2026-03-20 (-1 balance difference) and 2026-03-21 (+1 balance difference).
- `GET /history?department_id=343&start_date=2026-06-28&end_date=2026-06-30` -> HTTP 200, exactly 3 CLEAN rows. Occupied beds: 42, 44, 40; net flow: -7, +2, -4; quality=PASS; source_revision_no=1.
- Vietnamese mojibake seen in PowerShell is console rendering only; Part A already verified the HTTP JSON Unicode is correct with Python HTTPX.

Conclusion: Part B read-only runtime integration is verified. `POST /pipeline/run` runtime verification is still pending before Part B can be marked complete.

#### Part B runtime write/orchestration checkpoint — VERIFIED

User-side Windows + SQL Server verification:

- `POST /pipeline/run` -> HTTP 200 through FastAPI/Uvicorn.
- New run: `DAY_20260908T005428Z_CC275B88`, status `DATA_READY`, business date 2026-06-30, rows=362, data/feature versions unchanged.
- DQ remains ERROR=0/WARNING=0/CHECK=2.
- RAW inserted=0, updated=0, unchanged=362; CLEAN=362; FEATURE=362; H1 samples=354; H3 samples=350.
- Production-cycle activation PASS with 0 activations.
- Actual Matching remains `WAITING_FOR_ACTUAL`: Official=4, matched=0, waiting=4, missing=0.
- Monitoring snapshot `MON_DAY_20260908T005428Z_CC275B88` is linked to the new pipeline run and remains `WAITING_FOR_ACTUAL`, with metric_row_count=0 and no fabricated metrics.

Conclusion: Part B write/orchestration runtime integration is verified. Final regression checks for V2-12, V2-17 and V2-18 remain before marking Part B complete.

#### Part B final regression — COMPLETE

Final user-side regression on Windows after the real FastAPI-triggered Daily Pipeline run:

- `GET /pipeline/runs?limit=1` returned the new run `DAY_20260908T005428Z_CC275B88` as the latest run, status `DATA_READY`, 362 extracted rows, DQ ERROR=0/WARNING=0/CHECK=2.
- Full test suite remained green: **65 passed, 2 warnings in 2.75s**. The two warnings are the same non-blocking Starlette/FastAPI TestClient and anyio deprecations already recorded in Part A/B.
- `scripts.verify_v2_12` -> **PASS**. Latest run is `DAY_20260908T005428Z_CC275B88`; feature rows=362, full-lag3 rows=356, ML samples=704, RAW revisions >1 = 0, DQ=0/0/2.
- `scripts.verify_v2_17` -> **PASS**. Drafts=4, open drafts=0, Officials=4, duplicate Official keys=0, daily model locks=2, lock/target/value contracts all true.
- `scripts.verify_v2_18` -> **PASS**. Latest pipeline and monitoring snapshot are linked to the new run; Official=4, Actual available=0, matched=0, waiting=4, missing=0, metric rows=0, with no fabricated Actual or monitoring metrics.

**V2-19 Part B status: COMPLETE.** Pipeline/Data API now has verified unit contracts, real SQL read integration, real FastAPI write/orchestration integration, and regression protection for V2-12/V2-17/V2-18.

Next Master V2 section is **19.3 Training/Model API**: asynchronous training start/status/results/history plus registry/production/promotion/rollback endpoints. The API layer must continue delegating to the verified V2-13..V2-16 services and must not duplicate their business rules.

#### Part C1 - Asynchronous Training API + Persistent Job Runner

Part C1 implements the four Training endpoints from the V2 FastAPI contract:

- `POST /training/start`
- `GET /training/status/{job_id}`
- `GET /training/runs`
- `GET /training/results/{run_id}`

The central architectural rule is that model training must not run inside the HTTP
request. `POST /training/start` creates or reuses a persistent row in
`dbo.api_training_jobs`, returns HTTP 202 with a `job_id`, and launches a fixed worker
command using the same Python virtual environment. The worker then delegates all
scientific work to the already verified V2-14 `run_training()` service and V2-15
`generate_recommendations()` service.

Migration `008_api_training_jobs.sql` adds only API orchestration state. It does not
replace `dbo.training_runs`: `dbo.training_runs` remains the scientific/audit Training
Run and still enforces at most one COMPLETED Training Run per `business_date`.

Job statuses are `PENDING`, `RUNNING`, `COMPLETED`, and `FAILED`. PENDING/RUNNING jobs
for the same business date are reused, as is a completed API job linked to a still
COMPLETED Training Run. FAILED jobs are not reused, which preserves the V2 Retry rule.
The job stores lineage to the source DATA_READY pipeline run and, after success, to the
scientific Training Run.

The worker is launched as:

`<same-python> -m scripts.run_training_job --job-id <job_id>`

No executable path, Python module, artifact location, or filesystem path is accepted
from the HTTP client. This keeps the worker launch contract closed and auditable.

`GET /training/results/{run_id}` exposes overall candidate metrics, mandatory
per-department metrics, immutable recommendation snapshots, and ranking snapshots.
Recommended remains different from Production; Part C1 does not write
`dbo.production_models`.

Prepared code snapshot: **77/77 tests PASS** (65 prior tests + 12 Part C1 tests).
SQL migration/runtime verification on the user's Windows + SQL Server environment is
still pending, so Part C1 is CODE-READY rather than COMPLETE.

#### Part C1 user unit + SQL migration checkpoint — VERIFIED

User-side Windows verification on 2026-09-08:

- Full suite: **77 passed, 2 warnings in 3.10s**. The warnings are the existing non-blocking Starlette/FastAPI TestClient and anyio deprecations.
- `scripts.setup_db` run 1: migrations 001-007 skipped as already applied; `008_api_training_jobs.sql` applied successfully; migrations completed.
- `scripts.setup_db` run 2: migrations 001-008 all skipped as already applied, proving migration 008 is idempotent.
- No database reset and no V2-11..V2-18 schema rewrite was needed.

**Part C1 status: UNIT-TEST VERIFIED + SQL MIGRATION VERIFIED, PENDING ASYNC RUNTIME.** The remaining checkpoint is the real Uvicorn flow `POST /training/start` -> poll `/training/status/{job_id}` -> read `/training/results/{run_id}`. Because business date 2026-06-30 already has a COMPLETED V2-14 Training Run and V2-15 recommendation snapshot, the worker is expected to reuse `ALREADY_COMPLETED` / `ALREADY_RECOMMENDED` rather than retrain eight models.

#### Part C1 asynchronous runtime checkpoint — VERIFIED, reuse check pending

User-side Uvicorn + SQL Server verification on 2026-09-08:

- `GET /training/runs?limit=3` -> HTTP 200 and returned the existing scientific Training Run `TRN_20260907T105913Z_686E6A0C`, business_date 2026-06-30, status COMPLETED, row_count=704, department_count=2, random_seed=42, completed_candidate_count=8.
- `POST /training/start` -> HTTP 202 Accepted and created persistent job `TJOB_20260908T041159Z_AD19E47E`, status PENDING, source pipeline `DAY_20260908T005428Z_CC275B88`, reused=false.
- Detached worker claimed and completed the job quickly. `GET /training/status/TJOB_20260908T041159Z_AD19E47E` -> COMPLETED, linked to the existing Training Run `TRN_20260907T105913Z_686E6A0C`, error_message=null.
- `GET /training/results/TRN_20260907T105913Z_686E6A0C` -> candidate_count=8, department_metric_count=16, recommendation_count=2, ranking_count=8.
- H1 recommendation remains RF/KEEP although SVR is best on MAE; guardrail_pass=false, reason KEEP_THRESHOLD_AND_GUARDRAIL. H3 remains SVR/KEEP with guardrail_pass=true, reason BEST_IS_CHAMPION.
- Recommended remains separate from Production; Part C1 does not write `dbo.production_models`.

This verifies the real HTTP 202 -> persistent SQL job -> detached worker -> V2-14 Training Service -> V2-15 Recommendation -> polling/results flow. Because the business date already had a COMPLETED scientific Training Run, the worker reused it rather than retraining eight models.

**Part C1 status: ASYNC RUNTIME VERIFIED, PENDING FINAL REUSE/IDEMPOTENCY CHECK.** A second `POST /training/start` for the same business date must reuse `TJOB_20260908T041159Z_AD19E47E` with `reused=true` and must not create/launch a second job.

#### Part C1 reuse/idempotency runtime checkpoint — VERIFIED

A second real `POST /training/start` was executed for the same `business_date=2026-06-30` after the first API Training Job had already completed.

- The API returned HTTP 202 with the same persistent job `TJOB_20260908T041159Z_AD19E47E` and `reused=true`.
- The response remained linked to source pipeline `DAY_20260908T005428Z_CC275B88` and scientific Training Run `TRN_20260907T105913Z_686E6A0C`.
- `same_job_id=true`; no second TJOB was created.
- After an additional two-second wait, `created_at`, `started_at`, and `completed_at` were all unchanged, proving the completed job was not claimed again and the worker was not relaunched.
- Final status remained `COMPLETED`, `error_message=null`, and the scientific Training Run id remained unchanged.

This verifies the runtime reuse/idempotency contract for the asynchronous Training API. **Part C1 is still pending only the final regression suite before being marked COMPLETE.**


#### Part C1 final regression compatibility fix — CODE-READY, rerun pending

The first final regression after Part C1 produced `V2-14 VERIFY: FAIL` and `V2-15 VERIFY: FAIL` even though their scientific/training/recommendation contracts remained intact. The reports showed `active_production_count=2`, which is the valid downstream state created by the already-verified V2-16 Production Promotion step (H1 RF and H3 SVR are ACTIVE).

The cause was a stale stage-local verifier assumption left from the original V2-14/V2-15 checkpoints: both scripts still required `active_production_count == 0`. That was correct only before V2-16 existed, but it is no longer a valid regression condition after Promotion. Active Production is downstream state and must not make the immutable V2-14 Training or V2-15 Recommendation snapshots fail.

Fix: remove only the obsolete `active_production_count == 0` gate from `scripts/verify_v2_14.py` and `scripts/verify_v2_15.py`. The count remains in both JSON reports as informational evidence. No Training, Recommendation, Production, Official, Monitoring, SQL schema, model artifact, or database row is modified.

Expected rerun: V2-14 PASS and V2-15 PASS with `active_production_count=2`; V2-12/V2-17/V2-18 remain PASS. Part C1 remains pending until that rerun is verified.

#### Part C1 final regression — VERIFIED, COMPLETE

Final user-side rerun after the verifier compatibility fix:

- Full suite: **77 passed, 2 warnings in 2.99s**. The warnings are the same non-blocking FastAPI/Starlette TestClient and anyio deprecations.
- `scripts.verify_v2_14` -> **PASS** with `active_production_count=2`. Scientific Training evidence remains intact: run `TRN_20260907T105913Z_686E6A0C`, row_count=704, department_count=2, completed_candidate_count=8, 8 candidates, 16 per-department metric rows, no artifact-integrity errors.
- `scripts.verify_v2_15` -> **PASS** with `active_production_count=2`. Recommendation snapshot remains H1 RF/KEEP (best MAE candidate SVR, guardrail/threshold keep) and H3 SVR/KEEP; 2 recommendations, 8 rankings, 2 recommended flags.
- `scripts.verify_v2_12` -> **PASS**. Latest pipeline remains `DAY_20260908T005428Z_CC275B88`, DATA_READY, rows_extracted=362, DQ=0/0/2.
- `scripts.verify_v2_17` -> **PASS**. Officials=4, duplicate keys=0, daily model locks=2, lock/target/value contracts true.
- `scripts.verify_v2_18` -> **PASS**. Monitoring run `MON_DAY_20260908T005428Z_CC275B88` remains WAITING_FOR_ACTUAL with Official=4, matched=0, waiting=4, missing=0, metric rows=0.

The verifier change is lifecycle compatibility, not a relaxation of scientific criteria: only the stale pre-V2-16 assumption `active_production_count == 0` was removed from V2-14/V2-15 PASS gates. The count remains reported for downstream observability.

**V2-19 Part C1 status: COMPLETE.** Async Training API, persistent SQL job orchestration, detached worker, training-run/recommendation reuse, result read models, second-POST idempotency, and final regression are all verified on Windows + SQL Server.

Next: **V2-19 Part C2 — Model Registry / Production / Promotion / Rollback API**. FastAPI must continue delegating to the verified V2-13/V2-16 services and must not duplicate promotion, confirmation, daily-lock, rollback, or audit business rules.

#### Part C2 - Model Registry / Production / Promotion / Rollback API — CODE-READY

Part C2 adds the remaining four Model endpoints from Master V2 section 19.3:

- `GET /models`
- `GET /models/production`
- `POST /models/promote`
- `POST /models/rollback`

The read endpoints expose Model Registry metrics/status and the current Production state,
including ACTIVE/SCHEDULED slots, the latest recommendation, the latest DATA_READY
business date, the normal Production Change quota state, and any daily model lock for
that business date. Internal model artifact filesystem paths and SHA-256 values are not
exposed through `GET /models`; artifact integrity remains a backend registry concern.

The write endpoints do not reimplement Promotion or Rollback rules. A thin
`ModelCommandService` delegates directly to the already-verified V2-16
`execute_promotion()` and `execute_emergency_rollback()` services. Their exact explicit
confirmation phrases, normal daily quota, IMMEDIATE/NEXT_CYCLE decision, daily-lock
checks, transactional audit trail, rollback target resolution, and Official-history
immutability therefore remain owned by V2-16.

HTTP mapping is intentionally thin: V2-16 `ValueError` becomes HTTP 400 and V2-16
`RuntimeError` becomes HTTP 409. Normal service results `NO_CHANGE`,
`CONFIRMATION_REQUIRED`, and `COMPLETED` remain HTTP 200 response states so clients can
review the service-generated plan before sending the exact confirmation phrase.

The current verified database is expected to make a real `/models/promote` call without
confirmation return `NO_CHANGE`, because H1 RF and H3 SVR are already both Recommended
and ACTIVE Production. A real `/models/rollback` preview is expected to return HTTP 409
at the current state because the initial Production promotion had no previous RETIRED
candidate to roll back to. These are safe no-mutation runtime checks.

Part C2 also updates `scripts/verify_v2_16.py` for downstream lifecycle compatibility:
`daily_model_lock_count` remains reported, but it is no longer required to equal zero.
Zero locks was only the original pre-V2-17 checkpoint state; after Official confirmation,
V2-17 correctly creates daily model locks. All original V2-16 Promotion evidence and
normal-change quota checks remain in the verifier.

Prepared snapshot: **92/92 tests PASS** (77 prior + 15 Part C2 tests). No new SQL
migration and no dependency change are required. User-side Uvicorn + SQL runtime checks
remain pending, so Part C2 is CODE-READY rather than COMPLETE.

#### Part C2 - FINAL VERIFIED

User-side verification on Windows + SQL Server completed successfully. Final evidence:

- `pytest -q`: **92 passed, 2 warnings**. The two warnings remain the known FastAPI/Starlette TestClient and anyio deprecations and are not runtime failures.
- `scripts.verify_v2_16`: **PASS**. One committed NORMAL_PROMOTION exists for business date 2026-06-30, with 2 change items; ACTIVE Production remains H1 RF + H3 SVR; scheduled slots=0; daily model locks=2; normal-change quota count=1 and unique quota index is present.
- `scripts.verify_v2_15`: **PASS**. Two recommendation snapshots and eight ranking rows remain intact; H1 Recommended RF/KEEP, H3 Recommended SVR/KEEP.
- `scripts.verify_v2_17`: **PASS**. Four confirmed Drafts/Official forecasts remain immutable, duplicate Official keys=0, daily model locks=2 and Official lock/target/value contracts remain valid.
- `scripts.verify_v2_12`: **PASS**. Latest pipeline `DAY_20260908T005428Z_CC275B88` remains DATA_READY with 362 rows and DQ ERROR=0/WARNING=0/CHECK=2.
- `scripts.verify_v2_18`: **PASS**. Monitoring run `MON_DAY_20260908T005428Z_CC275B88` remains WAITING_FOR_ACTUAL with Official=4, matched=0, waiting=4, missing=0, metric rows=0.

Real command runtime was also verified without mutating Production:

- `POST /models/promote` without confirmation returned HTTP 200 `NO_CHANGE`, because Recommended H1 RF and H3 SVR are already ACTIVE Production. No new change transaction was created.
- `POST /models/rollback` without confirmation returned HTTP 409 `MODEL_ROLLBACK_CONFLICT`, because no previous RETIRED Production candidate exists yet for H1.
- A subsequent `GET /models/production` proved Production remained unchanged: H1 RF, H3 SVR, no scheduled slots, the same two daily locks, and normal-change quota already used exactly once.

**V2-19 Part C2 status: COMPLETE / FINAL VERIFIED.** FastAPI exposes Model Registry and Production read models and delegates Promotion/Rollback commands to the verified V2-16 service layer without duplicating business rules. The next lifecycle slice is **V2-19 Part D - Forecast Lifecycle + Monitoring API**.


#### V2-19 Part D - Forecast Lifecycle + Monitoring API (CODE-READY)

Part D exposes the already verified V2-17/V2-18 lifecycle through FastAPI without
reimplementing business rules. Preview remains non-persisted/non-Official; Production
Predict creates/reuses Draft only; only the exact `I_CONFIRM_OFFICIAL` phrase can move
open Drafts to immutable Official Forecasts; Monitoring is Official-only evidence.

Endpoints:
- `POST /forecasts/preview`
- `POST /forecasts/production`
- `GET /forecasts/drafts`
- `POST /forecasts/official/confirm`
- `GET /forecasts/official`
- `GET /monitoring`
- `POST /monitoring/run`

`/monitoring/run` is a local/internal recovery/manual trigger until Roles/Permissions is
implemented. Daily Pipeline behavior is unchanged and still owns the normal daily
Actual Matching + Monitoring stage. No SQL migration or dependency change is required.

Code-ready checkpoint: 107 tests pass in the prepared snapshot. Runtime verification
against the user's SQL Server is still required before Part D can be marked COMPLETE.

</details>

<details>
<summary>V2-20 Streamlit Dashboard</summary>

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](docs/WINDOWS_QUICKSTART.md) và [quy trình vận hành](docs/OPERATIONS.md).

V2-20 implements the Chapter 20 presentation layer from V2 MASTER. Streamlit is strictly a UI client of the already-verified V2-19 FastAPI backend. It does not connect to SQL Server and does not import Training, Forecast, Monitoring, Promotion, or Registry business services.

#### Menu

- 🏠 Tổng quan
- 📂 Dữ liệu
- 🔮 Dự báo
- 🧠 Huấn luyện
- 📊 Kết quả Training
- 🏆 Model Registry
- 📈 Monitoring

#### Architecture boundary

`Streamlit -> HTTP -> FastAPI -> verified service/repository -> SQL Server`

The UI must never bypass FastAPI. Exact confirmation phrases remain owned by the backend contracts and are only forwarded by the UI after explicit user input.

#### Install

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

#### Run

Terminal A:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_api
```

Terminal B:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_dashboard
```

Open `http://127.0.0.1:8501`.

Optional environment variables:

```text
V2_API_BASE_URL=http://127.0.0.1:8000
V2_UI_REQUEST_TIMEOUT_SECONDS=30
```

#### Important lifecycle rules reflected by the UI

- Preview is visibly non-persisted, non-Official, and not Monitoring-eligible.
- Production Predict creates/reuses Draft only.
- Official requires exact `I_CONFIRM_OFFICIAL`.
- Recommended and Production are displayed as different states.
- Promotion requires exact `I_CONFIRM_PROMOTION` when V2-16 returns `CONFIRMATION_REQUIRED`.
- Emergency Rollback requires exact `I_CONFIRM_EMERGENCY_ROLLBACK` when a rollback target exists.
- Training uses asynchronous API jobs and polling; Streamlit never trains inside the UI process.
- Monitoring is Official-only and delegates manual/recovery runs to V2-18 through FastAPI.

#### Chart limitation deliberately not fabricated

V2 MASTER asks for five principal Training charts. The current FastAPI Training Results endpoint exposes candidate metrics, per-department metrics, rankings, and recommendation, but not prediction-by-date evaluation rows. Therefore V2-20 can correctly render MAE Model Comparison and MAE by Department now. Train/Test Timeline, Actual vs Predicted Test, and Residual over Time require a future read-only chart-dataset API; the UI explicitly states this rather than reconstructing or fabricating evaluation predictions.

#### Current deployment boundary

Roles/Permissions are not implemented yet. Keep FastAPI and Streamlit on local/internal addresses only until the Scheduler + Roles phase is completed.

</details>

<details>
<summary>V2-20A — Automatic Evaluation Replay for Training Visualizations</summary>

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](docs/WINDOWS_QUICKSTART.md) và [quy trình vận hành](docs/OPERATIONS.md).

#### Status
CODE-READY. User runtime verification is still required before marking V2-20A COMPLETE.

#### Goal
Create immutable row-level TEST evaluation evidence for every completed Training Run so Streamlit can render:

1. Train / Validation / Test Timeline
2. Actual vs Predicted on the Test Set
3. Residual over Time

Global and per-department metrics (MAE, RMSE, WAPE, R2, Bias, P90, Max Error, Within ±2, Underprediction metrics) already belong to each Training Run and therefore update automatically when the UI selects the latest run.

#### Automatic workflow
From V2-20A onward, the persistent asynchronous Training Job completes only after:

Training -> Recommendation -> Evaluation Replay -> Job COMPLETED

Evaluation Replay reconstructs the historical holdout evaluation model from the stored Training Run contract. It never uses the ALL_MATURE Production artifact to predict the historical Test Set.

#### Retry behavior
If Training and Recommendation have already completed but Evaluation Replay fails, the API Training Job is FAILED. A retry creates a new orchestration job. V2-14 returns ALREADY_COMPLETED, V2-15 returns ALREADY_RECOMMENDED, and only Evaluation Replay is retried.

A legacy COMPLETED API job is no longer reused when its Training Run lacks the complete 592-row evaluation evidence dataset. This allows the existing 2026-06-30 Training Run to be backfilled safely without retraining the scientific model.

#### SQL evidence
Migration 009 creates `dbo.model_evaluation_predictions`.

Expected contract for the verified bootstrap Training Run:

- 8 candidates
- 74 TEST rows per candidate
- 37 TEST rows per department per candidate
- 592 rows total
- target_date 2026-05-25 through 2026-06-30
- residual = actual - predicted
- replay MAE must reproduce registry MAE within the configured absolute tolerance before any rows are committed

#### Safety boundaries
V2-20A does not:

- create a new Training Run during replay
- change Production models
- promote or rollback models
- alter Official Forecasts
- change Daily Model Locks
- fabricate Actual data

#### Manual verifier
After migration and replay/runtime backfill are complete:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_v2_20a
```

Expected final line:

`V2-20A VERIFY: PASS`

#### Checkpoint command

Chỉ chạy test ở checkpoint đầu tiên; chưa apply migration và chưa chạy replay.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: `119 passed` nếu chưa copy V2-20 Streamlit; `143 passed` nếu đã có 24 Streamlit tests.

</details>

<details>
<summary>V2-20B — Training Visualization API + Streamlit Integration</summary>

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](docs/WINDOWS_QUICKSTART.md) và [quy trình vận hành](docs/OPERATIONS.md).

#### Status
CODE-READY. Reference regression: 152 passed.

#### Goal
Expose immutable V2-20A evaluation evidence through a read-only FastAPI endpoint and render a Streamlit Training Results page with five automatically updating visualizations:

1. Metric comparison across RF / XGBoost / SVR / LSTM (MAE, RMSE, WAPE, R2, Bias, P90, Max Error, Within ±2, Underprediction metrics)
2. Train / Validation / Test Timeline
3. Actual vs Predicted — Test Set
4. Residual over Time
5. Per-department metric comparison / detailed metric table

#### Read-only API
`GET /training/evaluation/{run_id}` with query parameters:
- `horizon=1|3`
- `model_family=RF|XGBOOST|SVR|LSTM`
- optional `department_id`

The endpoint reads only `dbo.training_runs` and `dbo.model_evaluation_predictions`. It never trains or mutates Production/Official state.

#### Automatic update contract
Training Job completion remains:

Training -> Recommendation -> Evaluation Replay -> COMPLETED

The Streamlit page selects the newest COMPLETED Training Run by default. Therefore a future successful Training Run automatically becomes the default chart dataset while historic runs remain selectable.

#### Safety
- Streamlit calls FastAPI only.
- No SQL access from Streamlit.
- No hard-coded model metrics or chart predictions.
- Test predictions come from V2-20A immutable evaluation evidence, not Production artifacts.

</details>
