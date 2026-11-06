from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ApiErrorPayload:
    status_code: int | None
    code: str
    message: str
    details: Any = None


class ApiClientError(RuntimeError):
    def __init__(self, payload: ApiErrorPayload):
        super().__init__(payload.message)
        self.payload = payload

    @property
    def status_code(self) -> int | None:
        return self.payload.status_code

    @property
    def code(self) -> str:
        return self.payload.code

    @property
    def message(self) -> str:
        return self.payload.message

    @property
    def details(self) -> Any:
        return self.payload.details


class HospitalApiClient:
    """Synchronous HTTP client used only by the Streamlit presentation layer.

    The UI never imports database repositories, training services, prediction engines,
    or promotion logic. All lifecycle operations go through the verified FastAPI API.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                )
        except httpx.RequestError as exc:
            raise ApiClientError(
                ApiErrorPayload(
                    status_code=None,
                    code="API_UNREACHABLE",
                    message=(
                        "Không kết nối được FastAPI. Hãy kiểm tra API đang chạy và "
                        "V2_API_BASE_URL đúng."
                    ),
                    details={"exception_type": type(exc).__name__},
                )
            ) from exc

        if response.is_success:
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        code = "API_ERROR"
        message = f"FastAPI trả HTTP {response.status_code}."
        details: Any = None

        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                code = str(error.get("code") or code)
                message = str(error.get("message") or message)
                details = error.get("details")
            else:
                details = body
        except ValueError:
            details = response.text[:1000]

        raise ApiClientError(
            ApiErrorPayload(
                status_code=response.status_code,
                code=code,
                message=message,
                details=details,
            )
        )

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def data_status(self) -> dict[str, Any]:
        return self._request("GET", "/data/status")

    def departments(self) -> list[dict[str, Any]]:
        return self._request("GET", "/departments")

    def pipeline_runs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return self._request("GET", "/pipeline/runs", params=params)

    def run_pipeline(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "/pipeline/run",
            json_body={"source_mode": "EXCEL_BOOTSTRAP"},
        )

    def data_quality(
        self,
        *,
        pipeline_run_id: str | None = None,
        department_id: int | None = None,
        severity: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if pipeline_run_id:
            params["pipeline_run_id"] = pipeline_run_id
        if department_id is not None:
            params["department_id"] = department_id
        if severity:
            params["severity"] = severity
        return self._request("GET", "/data-quality", params=params)

    def history(
        self,
        *,
        department_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "department_id": department_id,
            "limit": limit,
            "offset": offset,
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._request("GET", "/history", params=params)

    def start_training(
        self,
        *,
        requested_by: str = "streamlit",
        random_seed: int = 42,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/training/start",
            json_body={
                "requested_by": requested_by,
                "random_seed": random_seed,
            },
        )

    def training_status(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/training/status/{job_id}")

    def training_runs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return self._request("GET", "/training/runs", params=params)

    def training_results(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/training/results/{run_id}")


    def training_evaluation(
        self,
        *,
        run_id: str,
        horizon: int,
        model_family: str,
        department_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "horizon": horizon,
            "model_family": model_family,
        }
        if department_id is not None:
            params["department_id"] = department_id
        return self._request(
            "GET",
            f"/training/evaluation/{run_id}",
            params=params,
        )

    def models(
        self,
        *,
        run_id: str | None = None,
        horizon: int | None = None,
        model_family: str | None = None,
        registry_status: str | None = None,
        is_recommended: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if run_id:
            params["run_id"] = run_id
        if horizon is not None:
            params["horizon"] = horizon
        if model_family:
            params["model_family"] = model_family
        if registry_status:
            params["registry_status"] = registry_status
        if is_recommended is not None:
            params["is_recommended"] = is_recommended
        return self._request("GET", "/models", params=params)

    def production_models(self) -> dict[str, Any]:
        return self._request("GET", "/models/production")

    def promote_models(
        self,
        *,
        horizons: list[int],
        requested_by: str,
        reason: str,
        confirmation: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "horizons": horizons,
            "requested_by": requested_by,
            "reason": reason,
        }
        if confirmation is not None:
            body["confirmation"] = confirmation
        return self._request("POST", "/models/promote", json_body=body)

    def rollback_model(
        self,
        *,
        horizon: int,
        requested_by: str,
        reason: str,
        confirmation: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "horizon": horizon,
            "requested_by": requested_by,
            "reason": reason,
        }
        if confirmation is not None:
            body["confirmation"] = confirmation
        return self._request("POST", "/models/rollback", json_body=body)

    def forecast_preview(
        self,
        *,
        mode: str,
        origin_date: str | None,
        department_ids: list[int],
        horizons: list[int],
        custom_candidates: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "mode": mode,
            "department_ids": department_ids,
            "horizons": horizons,
            "custom_candidates": custom_candidates or {},
        }
        if origin_date:
            body["origin_date"] = origin_date
        return self._request("POST", "/forecasts/preview", json_body=body)

    def production_predict(
        self,
        *,
        origin_date: str | None,
        department_ids: list[int],
        horizons: list[int],
        created_by: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "department_ids": department_ids,
            "horizons": horizons,
            "created_by": created_by,
        }
        if origin_date:
            body["origin_date"] = origin_date
        return self._request("POST", "/forecasts/production", json_body=body)

    def forecast_drafts(
        self,
        *,
        origin_date: str | None = None,
        department_id: int | None = None,
        horizon: int | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if origin_date:
            params["origin_date"] = origin_date
        if department_id is not None:
            params["department_id"] = department_id
        if horizon is not None:
            params["horizon"] = horizon
        if status:
            params["status"] = status
        return self._request("GET", "/forecasts/drafts", params=params)

    def confirm_official(
        self,
        *,
        origin_date: str | None,
        confirmed_by: str,
        confirmation: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"confirmed_by": confirmed_by}
        if origin_date:
            body["origin_date"] = origin_date
        if confirmation is not None:
            body["confirmation"] = confirmation
        return self._request("POST", "/forecasts/official/confirm", json_body=body)

    def official_forecasts(
        self,
        *,
        origin_date: str | None = None,
        department_id: int | None = None,
        horizon: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if origin_date:
            params["origin_date"] = origin_date
        if department_id is not None:
            params["department_id"] = department_id
        if horizon is not None:
            params["horizon"] = horizon
        return self._request("GET", "/forecasts/official", params=params)

    def monitoring(self) -> dict[str, Any]:
        return self._request("GET", "/monitoring")

    def run_monitoring(self, pipeline_run_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if pipeline_run_id:
            body["pipeline_run_id"] = pipeline_run_id
        return self._request("POST", "/monitoring/run", json_body=body)