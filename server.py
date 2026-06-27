from __future__ import annotations

import csv
import json
import math
import mimetypes
import os
import shutil
from statistics import NormalDist
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    from scipy import stats as scipy_stats
except ImportError:  # pragma: no cover - fallback for plain stdlib runtime.
    scipy_stats = None

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent / "core"))


WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
STATIC_ROOT = WEB_ROOT / "static"
APP_DATA_ROOT = WEB_ROOT / "app_data"
EXAMPLE_PROJECT_ROOT = APP_DATA_ROOT / "example"
PROJECT_FINAL_ROOT = WEB_ROOT / "project_final"
CURRENT_PROJECT_ROOT = PROJECT_FINAL_ROOT
DATA_ROOT = PROJECT_ROOT / "data"
OUTPUT_ROOT = PROJECT_ROOT / "output"

SCHEME_LEVELS = [120.0, 115.0, 108.0, 100.0]
SCHEME_NAMES = {120.0: "方案一", 115.0: "方案二", 108.0: "方案三", 100.0: "方案四"}
DISCOUNT_RATE = 0.10
HYDRO_LIFE_YEARS = 50
THERMAL_LIFE_YEARS = 25
DESIGN_GUARANTEE_RATE = 87.5

TABLE_SOURCES = {
    "installed_capacity": OUTPUT_ROOT / "installed_capacity_summary.csv",
    "runoff_utilization": OUTPUT_ROOT / "runoff_utilization_coefficient_results.csv",
    "dead_water_results": OUTPUT_ROOT / "dead_water_level_results.csv",
    "dead_water_supply_periods": OUTPUT_ROOT / "dead_water_level_supply_periods.csv",
    "guaranteed_output_results": OUTPUT_ROOT / "guaranteed_output_results.csv",
    "guaranteed_output_frequency": OUTPUT_ROOT / "guaranteed_output_annual_frequency.csv",
    "required_capacity": OUTPUT_ROOT / "required_capacity_results.csv",
    "manual_repeated_capacity": OUTPUT_ROOT / "repeated_capacity_dp_trial" / "manual_fit_2500h.csv",
    "repeated_capacity_fit": OUTPUT_ROOT / "repeated_capacity_dp_trial" / "dp_trial_fit_2500h.csv",
    "flood_summary": OUTPUT_ROOT / "flood_routing" / "flood_routing_summary.csv",
    "discharge_capacity": OUTPUT_ROOT / "flood_routing" / "flood_discharge_capacity.csv",
    "economic_comparison": OUTPUT_ROOT / "economic_analysis" / "economic_comparison.csv",
    "economic_components": OUTPUT_ROOT / "economic_analysis" / "economic_components.csv",
    "economic_cashflow": OUTPUT_ROOT / "economic_analysis" / "economic_cashflow.csv",
    "economic_frequency": OUTPUT_ROOT / "economic_analysis" / "flood_benefit_frequency_points.csv",
    "dispatch_lines": OUTPUT_ROOT / "dispatch_chart_lines.csv",
}

CHART_SOURCES = {
    "dispatch_120": OUTPUT_ROOT / "dispatch_charts" / "dispatch_chart_120m.svg",
    "dispatch_115": OUTPUT_ROOT / "dispatch_charts" / "dispatch_chart_115m.svg",
    "dispatch_108": OUTPUT_ROOT / "dispatch_charts" / "dispatch_chart_108m.svg",
    "dispatch_100": OUTPUT_ROOT / "dispatch_charts" / "dispatch_chart_100m.svg",
    "flood_discharge_all": OUTPUT_ROOT / "flood_routing" / "charts" / "discharge_capacity_all_schemes.svg",
    "repeated_fit_120": OUTPUT_ROOT / "repeated_capacity_dp_trial" / "dp_trial_120m_N_h_fit.svg",
    "repeated_fit_115": OUTPUT_ROOT / "repeated_capacity_dp_trial" / "dp_trial_115m_N_h_fit.svg",
    "repeated_fit_108": OUTPUT_ROOT / "repeated_capacity_dp_trial" / "dp_trial_108m_N_h_fit.svg",
    "repeated_fit_100": OUTPUT_ROOT / "repeated_capacity_dp_trial" / "dp_trial_100m_N_h_fit.svg",
}

BASE_DATASETS = {
    "storageCurve": {
        "name": "库容曲线",
        "description": "水位与库容关系，是兴利、防洪、调洪等计算的基础曲线。",
        "type": "csv",
        "path": "inputs/storage_curve.csv",
    },
    "areaCurve": {
        "name": "水位-面积曲线",
        "description": "水位与水面面积关系，主要用于风浪和淹没相关计算。",
        "type": "csv",
        "path": "inputs/area_curve.csv",
    },
    "tailwaterCurve": {
        "name": "尾水水位流量曲线",
        "description": "下泄流量与下游水位关系，用于水头和出力相关计算。",
        "type": "csv",
        "path": "inputs/tailwater_curve.csv",
    },
    "runoffSeries": {
        "name": "径流系列表",
        "description": "原始径流系列，保留未扣除航运、灌溉等综合利用消耗的版本。",
        "type": "csv",
        "path": "inputs/runoff_series.csv",
    },
    "designFlood": {
        "name": "设计洪水数据",
        "description": "不同频率设计洪水过程，用于调洪演算。",
        "type": "csv",
        "path": "inputs/design_flood.csv",
    },
    "parameters": {
        "name": "其他参数",
        "description": "综合利用消耗、吹程、设计风速、设计保证率、年淤积量、大坝使用寿命等。",
        "type": "json",
        "path": "project.json",
    },
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def project_root(kind: str) -> Path:
    if kind == "example":
        return EXAMPLE_PROJECT_ROOT
    return CURRENT_PROJECT_ROOT


def dataset_info(dataset_id: str) -> dict:
    if dataset_id not in BASE_DATASETS:
        raise KeyError(f"Unknown dataset: {dataset_id}")
    return BASE_DATASETS[dataset_id]


def dataset_path(dataset_id: str, kind: str = "current") -> Path:
    info = dataset_info(dataset_id)
    return project_root(kind) / info["path"]


def read_project_dataset(dataset_id: str, kind: str = "current") -> dict:
    info = dataset_info(dataset_id)
    path = dataset_path(dataset_id, kind)
    payload = {
        "id": dataset_id,
        "name": info["name"],
        "description": info["description"],
        "type": info["type"],
        "path": str(path.relative_to(WEB_ROOT)).replace("\\", "/") if path.exists() else info["path"],
        "exists": path.exists(),
    }
    if info["type"] == "csv":
        rows = read_csv(path)
        payload["columns"] = list(rows[0].keys()) if rows else []
        payload["rows"] = rows
    elif info["type"] == "json":
        project = read_json(project_root(kind) / "project.json")
        payload["parameters"] = project.get("parameters", {})
    else:
        payload["downloadOnly"] = True
        payload["note"] = "当前运行环境缺少 .xls 解析依赖，暂作为原始文件保存；后续可转换为 CSV 后预览。"
        payload["size"] = path.stat().st_size if path.exists() else 0
    return payload


def list_base_data() -> dict:
    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    datasets = []
    for dataset_id in BASE_DATASETS:
        item = read_project_dataset(dataset_id)
        item.pop("rows", None)
        item.pop("parameters", None)
        datasets.append(item)
    return {
        "project": {
            "name": project.get("projectName", "当前项目"),
            "description": project.get("description", ""),
        },
        "datasets": datasets,
    }


def copy_example_dataset(dataset_id: str) -> dict:
    info = dataset_info(dataset_id)
    if info["type"] == "json":
        current = read_json(CURRENT_PROJECT_ROOT / "project.json")
        example = read_json(EXAMPLE_PROJECT_ROOT / "project.json")
        current["parameters"] = example.get("parameters", {})
        current["calculationState"] = empty_calculation_state(current.get("calculationState", {}).get("revision", 0) + 1)
        write_json_file(CURRENT_PROJECT_ROOT / "project.json", current)
    else:
        source = dataset_path(dataset_id, "example")
        target = dataset_path(dataset_id, "current")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        current = read_json(CURRENT_PROJECT_ROOT / "project.json")
        current["calculationState"] = empty_calculation_state(current.get("calculationState", {}).get("revision", 0) + 1)
        write_json_file(CURRENT_PROJECT_ROOT / "project.json", current)
    return read_project_dataset(dataset_id)


def reset_project_to_initial() -> dict:
    """Restore the bundled inputs and the four starter schemes, then clear all results."""
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    revision = int(current.get("calculationState", {}).get("revision", 0)) + 1
    initial = read_json(EXAMPLE_PROJECT_ROOT / "project.json")
    if len(initial.get("schemes", [])) != 4:
        raise ValueError("初始项目配置不完整，无法执行清空")

    source_inputs = EXAMPLE_PROJECT_ROOT / "inputs"
    target_inputs = CURRENT_PROJECT_ROOT / "inputs"
    target_inputs.mkdir(parents=True, exist_ok=True)
    for source in source_inputs.iterdir():
        if source.is_file():
            shutil.copy2(source, target_inputs / source.name)

    initial["calculationState"] = empty_calculation_state(revision)
    write_json_file(CURRENT_PROJECT_ROOT / "project.json", initial)

    calculations = CURRENT_PROJECT_ROOT / "calculations"
    if calculations.exists():
        shutil.rmtree(calculations)
    calculations.mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "message": "已恢复初始四个方案并清空全部计算成果",
        "revision": revision,
        "schemeIds": [str(item["id"]) for item in initial["schemes"]],
    }


def save_project_dataset(dataset_id: str, payload: dict) -> dict:
    info = dataset_info(dataset_id)
    if info["type"] == "csv":
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError("CSV dataset expects rows: list[object]")
        write_csv(dataset_path(dataset_id), rows)
        current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    elif info["type"] == "json":
        current = read_json(CURRENT_PROJECT_ROOT / "project.json")
        parameters = payload.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("Parameter dataset expects parameters: object")
        current["parameters"] = parameters
    else:
        raise ValueError("This dataset type is download-only for now")
    current["calculationState"] = empty_calculation_state(current.get("calculationState", {}).get("revision", 0) + 1)
    write_json_file(CURRENT_PROJECT_ROOT / "project.json", current)
    return read_project_dataset(dataset_id)


def empty_calculation_state(revision: int = 0) -> dict:
    return {
        "engineVersion": 1,
        "revision": revision,
        "deadWaterLevels": [],
        "guaranteedOutputLevels": [],
        "dispatchChartLevels": [],
        "deadWaterSchemeIds": [],
        "guaranteedOutputSchemeIds": [],
        "dispatchChartSchemeIds": [],
        "repeatedCapacityMachineSchemeIds": [],
        "repeatedCapacityManualSchemeIds": [],
        "dischargeCapacitySchemeIds": [],
        "floodRoutingSchemeIds": [],
        "damCrestSchemeIds": [],
        "repeatedCapacitySelections": {},
    }


def parse_multipart_upload(content_type: str, body: bytes) -> tuple[str, bytes]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Missing multipart boundary")
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    delimiter = ("--" + boundary).encode("utf-8")
    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, _, content = part.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", errors="ignore")
        if 'name="file"' not in headers:
            continue
        filename = "upload.csv"
        if "filename=" in headers:
            filename = headers.split("filename=", 1)[1].split("\r\n", 1)[0].strip().strip('"')
        return filename, content.rstrip(b"\r\n")
    raise ValueError("No file field found")


def upload_project_dataset(dataset_id: str, content_type: str, body: bytes) -> dict:
    info = dataset_info(dataset_id)
    if info["type"] != "csv":
        raise ValueError("Only CSV base datasets can be uploaded here")
    filename, content = parse_multipart_upload(content_type, body)
    if not filename.lower().endswith(".csv"):
        raise ValueError("Only .csv files are accepted")
    target = dataset_path(dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise ValueError("CSV has no data rows")
    write_csv(target, rows)
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    current["calculationState"] = empty_calculation_state(current.get("calculationState", {}).get("revision", 0) + 1)
    write_json_file(CURRENT_PROJECT_ROOT / "project.json", current)
    return read_project_dataset(dataset_id)


def normalize_scheme(raw: dict) -> dict:
    return {
        "id": str(raw.get("id") or f"scheme-{len(str(raw))}"),
        "name": str(raw.get("name") or "新方案"),
        "normalWaterLevel": to_float(raw.get("normalWaterLevel")),
        "upstreamImpact": {
            "reducedInstalledCapacity": to_float(raw.get("upstreamImpact", {}).get("reducedInstalledCapacity")),
            "reducedAverageEnergy": to_float(raw.get("upstreamImpact", {}).get("reducedAverageEnergy")),
        },
        "spillway": {
            "holes": int(to_float(raw.get("spillway", {}).get("holes"))),
            "crestElevation": to_float(raw.get("spillway", {}).get("crestElevation")),
            "orificeWidth": to_float(raw.get("spillway", {}).get("orificeWidth")),
            "orificeHeight": to_float(raw.get("spillway", {}).get("orificeHeight")),
        },
        "middleOutlet": {
            "holes": int(to_float(raw.get("middleOutlet", {}).get("holes"))),
            "sillElevation": to_float(raw.get("middleOutlet", {}).get("sillElevation")),
            "orificeWidth": to_float(raw.get("middleOutlet", {}).get("orificeWidth")),
            "orificeHeight": to_float(raw.get("middleOutlet", {}).get("orificeHeight")),
        },
        "reserveCapacity": to_float(raw.get("reserveCapacity")),
    }


def list_schemes() -> dict:
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    example = read_json(EXAMPLE_PROJECT_ROOT / "project.json")
    return {
        "schemes": [normalize_scheme(item) for item in current.get("schemes", [])],
        "exampleSchemes": [normalize_scheme(item) for item in example.get("schemes", [])],
        "economicAutoNote": "坝高投资、装机容量投资、其他费用投资、水库补偿费、水电运行费、大修费、提成补偿不在此处录入；后续计算按正常蓄水位自动插值或读取任务书参数。",
    }


def save_schemes(schemes: list[dict]) -> dict:
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    old_schemes = {item["id"]: item for item in (normalize_scheme(raw) for raw in current.get("schemes", []))}
    normalized = [normalize_scheme(item) for item in schemes]

    def calculation_signature(scheme: dict) -> dict:
        return {key: value for key, value in scheme.items() if key not in {"id", "name"}}

    changed_ids = {
        scheme["id"] for scheme in normalized
        if scheme["id"] in old_schemes
        and calculation_signature(scheme) != calculation_signature(old_schemes[scheme["id"]])
    }
    state = current.setdefault("calculationState", {})
    state.setdefault("deadWaterSchemeIds", [f"scheme-{int(float(level))}" for level in state.get("deadWaterLevels", [])])
    state.setdefault("guaranteedOutputSchemeIds", [f"scheme-{int(float(level))}" for level in state.get("guaranteedOutputLevels", [])])
    state.setdefault("dispatchChartSchemeIds", [f"scheme-{int(float(level))}" for level in state.get("dispatchChartLevels", [])])
    for key in (
        "deadWaterSchemeIds",
        "guaranteedOutputSchemeIds",
        "dispatchChartSchemeIds",
        "repeatedCapacityMachineSchemeIds",
        "repeatedCapacityManualSchemeIds",
        "dischargeCapacitySchemeIds",
        "floodRoutingSchemeIds",
        "damCrestSchemeIds",
    ):
        state[key] = [scheme_id for scheme_id in state.get(key, []) if scheme_id not in changed_ids]
    selections = state.setdefault("repeatedCapacitySelections", {})
    for scheme_id in changed_ids:
        selections.pop(scheme_id, None)
    current["schemes"] = normalized
    write_json_file(CURRENT_PROJECT_ROOT / "project.json", current)
    return list_schemes()


def calculation_state() -> dict:
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    state = current.setdefault("calculationState", {})
    if int(state.get("engineVersion", 0)) != 1:
        state = empty_calculation_state(int(state.get("revision", 0)) + 1)
        current["calculationState"] = state
        write_json_file(CURRENT_PROJECT_ROOT / "project.json", current)
    state.setdefault("deadWaterLevels", [])
    state.setdefault("guaranteedOutputLevels", [])
    state.setdefault("dispatchChartLevels", [])
    state.setdefault("deadWaterSchemeIds", [f"scheme-{int(float(level))}" for level in state["deadWaterLevels"]])
    state.setdefault("guaranteedOutputSchemeIds", [f"scheme-{int(float(level))}" for level in state["guaranteedOutputLevels"]])
    state.setdefault("dispatchChartSchemeIds", [f"scheme-{int(float(level))}" for level in state["dispatchChartLevels"]])
    state.setdefault("repeatedCapacitySelections", {})
    return state


def save_calculation_state(state: dict) -> None:
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    current["calculationState"] = state
    write_json_file(CURRENT_PROJECT_ROOT / "project.json", current)


def mark_scheme_calculated(state_key: str, scheme_id: str) -> None:
    state = calculation_state()
    scheme_ids = {str(item) for item in state.get(state_key, [])}
    scheme_ids.add(scheme_id)
    state[state_key] = sorted(scheme_ids)
    save_calculation_state(state)


def completed_scheme_ids(state_key: str) -> set[str]:
    return {str(item) for item in calculation_state().get(state_key, [])}


def configured_scheme(scheme_id: str, level: float) -> dict:
    schemes = list_schemes()["schemes"]
    scheme = next((item for item in schemes if item["id"] == scheme_id), None)
    if not scheme:
        raise ValueError("找不到所选方案，请刷新页面后重试")
    if abs(to_float(scheme["normalWaterLevel"]) - level) > 1e-6:
        raise ValueError("方案参数已变化，请刷新页面后重新计算")
    return scheme


def add_scheme() -> dict:
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    schemes = [normalize_scheme(item) for item in current.get("schemes", [])]
    next_index = len(schemes) + 1
    schemes.append(
        normalize_scheme(
            {
                "id": f"scheme-custom-{next_index}",
                "name": f"新方案{next_index}",
                "normalWaterLevel": 0,
                "upstreamImpact": {"reducedInstalledCapacity": 0, "reducedAverageEnergy": 0},
                "spillway": {"holes": 0, "crestElevation": 0, "orificeWidth": 0, "orificeHeight": 0},
                "middleOutlet": {"holes": 0, "sillElevation": 0, "orificeWidth": 0, "orificeHeight": 0},
                "reserveCapacity": 0,
            }
        )
    )
    return save_schemes(schemes)


def apply_example_scheme(target_id: str, example_id: str) -> dict:
    current = read_json(CURRENT_PROJECT_ROOT / "project.json")
    examples = {item["id"]: normalize_scheme(item) for item in read_json(EXAMPLE_PROJECT_ROOT / "project.json").get("schemes", [])}
    if example_id not in examples:
        raise ValueError("Unknown example scheme")
    schemes = [normalize_scheme(item) for item in current.get("schemes", [])]
    replacement = examples[example_id]
    for index, scheme in enumerate(schemes):
        if scheme["id"] == target_id:
            replacement = {**replacement, "id": target_id, "name": scheme["name"] or replacement["name"]}
            schemes[index] = replacement
            return save_schemes(schemes)
    raise ValueError("Unknown target scheme")


def to_float(value: str | float | int | None, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def crf(rate: float, years: int) -> float:
    if years <= 0:
        raise ValueError("years must be positive")
    if abs(rate) < 1e-12:
        return 1.0 / years
    factor = (1.0 + rate) ** years
    return rate * factor / (factor - 1.0)


def rows_by_level(rows: list[dict[str, str]]) -> dict[float, dict[str, str]]:
    out: dict[float, dict[str, str]] = {}
    for row in rows:
        if "正常蓄水位_m" in row:
            out[to_float(row["正常蓄水位_m"])] = row
    return out


def pearson3_frequency_value(mean_value: float, std_value: float, skew_value: float, guarantee_rate: float) -> float:
    non_exceedance_probability = 1.0 - guarantee_rate / 100.0
    non_exceedance_probability = min(max(non_exceedance_probability, 1e-6), 1.0 - 1e-6)
    if scipy_stats is not None:
        return float(
            scipy_stats.pearson3.ppf(
                non_exceedance_probability,
                skew_value,
                loc=mean_value,
                scale=std_value,
            )
        )

    z = NormalDist().inv_cdf(non_exceedance_probability)
    adjusted_z = z + (skew_value / 6.0) * (z * z - 1.0)
    return mean_value + adjusted_z * std_value


def project_guarantee_rate(project: dict | None = None) -> float:
    project = project or read_json(CURRENT_PROJECT_ROOT / "project.json")
    value = to_float(project.get("parameters", {}).get("designGuaranteeRate"), 0.875)
    return value * 100.0 if value <= 1.0 else value


def build_theoretical_frequency_curve(result: dict[str, str], guarantee_rate: float | None = None) -> list[dict[str, float]]:
    mean_value = to_float(result.get("年保证出力均值_kW"))
    std_value = to_float(result.get("年保证出力标准差_kW"))
    skew_value = to_float(result.get("年保证出力偏态系数Cs"))
    design_rate = guarantee_rate if guarantee_rate is not None else project_guarantee_rate()
    frequencies = sorted({float(value) for value in range(1, 100)} | {design_rate})
    curve: list[dict[str, float]] = []
    for frequency in frequencies:
        output_kw = pearson3_frequency_value(mean_value, std_value, skew_value, frequency)
        if math.isfinite(output_kw):
            curve.append({"frequency": frequency, "outputKw": max(0.0, output_kw)})
    return curve


def table_row_value(path: Path, item: str, field: str) -> float:
    for row in read_csv(path):
        if row.get("项目") == item:
            return to_float(row.get(field))
    return 0.0


def build_summary() -> dict:
    economic = rows_by_level(read_csv(TABLE_SOURCES["economic_comparison"]))
    installed = rows_by_level(read_csv(TABLE_SOURCES["installed_capacity"]))
    flood = rows_by_level(read_csv(TABLE_SOURCES["flood_summary"]))
    runoff = rows_by_level(read_csv(TABLE_SOURCES["runoff_utilization"]))

    schemes = []
    for level in SCHEME_LEVELS:
        e = economic.get(level, {})
        i = installed.get(level, {})
        f = flood.get(level, {})
        r = runoff.get(level, {})
        schemes.append(
            {
                "level": level,
                "name": SCHEME_NAMES[level],
                "recommended": e.get("是否推荐方案") == "是",
                "installedCapacity": to_float(e.get("装机容量_万kW") or i.get("装机容量_万kW")),
                "requiredCapacity": to_float(e.get("必须容量_万kW") or i.get("必须容量_万kW")),
                "averageEnergy": to_float(e.get("五强溪多年平均电能_亿kWh") or i.get("多年平均电能_亿kWh")),
                "runoffUtilization": to_float(r.get("径流利用系数_%")),
                "floodLimitLevel": to_float(f.get("防洪限制水位_m")),
                "floodHighLevel": to_float(f.get("防洪高水位_m")),
                "designFloodLevel": to_float(f.get("设计洪水位_m")),
                "checkFloodLevel": to_float(f.get("校核洪水位_m")),
                "damCrestLevel": to_float(f.get("坝顶高程_m")),
                "totalAnnualCost": to_float(e.get("总年费用_万元")),
                "capitalAnnualCost": to_float(e.get("资本年费用_万元")),
                "normalAnnualCost": to_float(e.get("正常运行期年费用_万元")),
                "floodBenefit": to_float(e.get("防洪年效益_万元")),
                "replacementCapacity": to_float(e.get("替代火电容量_万kW")),
                "replacementEnergy": to_float(e.get("替代火电电能_亿kWh")),
            }
        )

    data_files = []
    for root in [DATA_ROOT, OUTPUT_ROOT]:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".csv", ".svg", ".docx"}:
                    data_files.append(
                        {
                            "name": path.name,
                            "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                            "size": path.stat().st_size,
                            "kind": path.suffix.lower().lstrip("."),
                        }
                    )

    return {
        "projectName": "五强溪水库水利计算示例项目",
        "mode": "example",
        "schemes": schemes,
        "modules": [
            {"id": "data", "name": "项目数据管理", "status": "配置四方案共用基础数据"},
            {"id": "config", "name": "方案配置", "status": "配置单方案计算参数"},
            {"id": "hydropower", "name": "兴利计算", "status": "死水位等兴利模块计算"},
            {"id": "flood", "name": "防洪演算", "status": "调洪与坝顶高程计算"},
            {"id": "economy", "name": "经济计算", "status": "年费用与方案比较"},
            {"id": "export", "name": "成果导出", "status": "下载过程表与成果文件"},
        ],
        "files": sorted(data_files, key=lambda item: item["path"]),
    }


def recalculate_economy(payload: dict) -> dict:
    rate = to_float(payload.get("discountRate"), DISCOUNT_RATE)
    hydro_years = int(to_float(payload.get("hydroLifeYears"), HYDRO_LIFE_YEARS))
    thermal_years = int(to_float(payload.get("thermalLifeYears"), THERMAL_LIFE_YEARS))
    normal_scale = to_float(payload.get("normalCostScale"), 1.0)
    flood_scale = to_float(payload.get("floodBenefitScale"), 1.0)

    economic = rows_by_level(read_csv(TABLE_SOURCES["economic_comparison"]))
    results = []
    for level in SCHEME_LEVELS:
        table_path = OUTPUT_ROOT / "economic_analysis" / "scheme_tables" / f"economic_table_{int(level)}m.csv"
        thermal_fv = table_row_value(table_path, "替代火电站投资（万元）", "折算到施工期末_万元")
        total_fv = table_row_value(table_path, "总计（万元）", "折算到施工期末_万元")
        hydro_like_fv = max(total_fv - thermal_fv, 0.0)

        base = economic.get(level, {})
        hydro_normal = to_float(base.get("水电正常年运行费_万元"))
        thermal_operation = to_float(base.get("火电正常年运行费_万元"))
        thermal_fuel = to_float(base.get("火电正常燃料费_万元"))
        flood_benefit = to_float(base.get("防洪年效益_万元"))
        normal_annual = (hydro_normal + thermal_operation + thermal_fuel) * normal_scale - flood_benefit * flood_scale
        capital_annual = hydro_like_fv * crf(rate, hydro_years) + thermal_fv * crf(rate, thermal_years)
        total_annual = capital_annual + normal_annual
        results.append(
            {
                "level": level,
                "name": SCHEME_NAMES[level],
                "constructionEndValue": total_fv,
                "thermalPlantConstructionEndValue": thermal_fv,
                "capitalAnnualCost": capital_annual,
                "normalAnnualCost": normal_annual,
                "totalAnnualCost": total_annual,
            }
        )
    best = min(results, key=lambda row: row["totalAnnualCost"])
    for row in results:
        row["recommended"] = row["level"] == best["level"]
    return {
        "assumptions": {
            "discountRate": rate,
            "hydroLifeYears": hydro_years,
            "thermalLifeYears": thermal_years,
            "normalCostScale": normal_scale,
            "floodBenefitScale": flood_scale,
        },
        "results": results,
    }


def calculate_dead_water(scheme_id: str, level: float) -> dict:
    scheme = configured_scheme(scheme_id, level)
    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    from hydropower_engine import run_dead_water

    result, process_rows = run_dead_water(CURRENT_PROJECT_ROOT, project, scheme)
    frequency_rows = build_regulated_flow_frequency(process_rows)
    mark_scheme_calculated("deadWaterSchemeIds", scheme_id)
    return {
        "schemeId": scheme_id,
        "level": level,
        "result": result,
        "processRows": process_rows,
        "frequencyRows": frequency_rows,
        "tables": {
            "result": [result],
            "process": process_rows,
            "frequency": frequency_rows,
        },
        "downloads": {
            "resultTable": "output/dead_water_level_results.csv",
            "processTable": "output/dead_water_level_supply_periods.csv",
        },
        "note": "本次结果由当前库容曲线、尾水曲线、原始径流、月综合利用消耗及方案参数实时计算。",
    }


def available_scheme_ids(state_key: str, table_key: str) -> set[str]:
    completed = completed_scheme_ids(state_key)
    historical_levels = set(rows_by_level(read_csv(TABLE_SOURCES[table_key])).keys())
    return {
        scheme["id"] for scheme in list_schemes()["schemes"]
        if scheme["id"] in completed and to_float(scheme["normalWaterLevel"]) in historical_levels
    }


def dead_water_available_scheme_ids() -> set[str]:
    return completed_scheme_ids("deadWaterSchemeIds")


def guaranteed_output_available_scheme_ids() -> set[str]:
    return completed_scheme_ids("guaranteedOutputSchemeIds")


def row_for_level(rows: list[dict[str, str]], level: float) -> dict[str, str] | None:
    for row in rows:
        if abs(to_float(row.get("正常蓄水位_m")) - level) < 1e-6:
            return row
    return None


def read_project_svg(path_text: str) -> str:
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        resolved = path.resolve()
        resolved.relative_to(PROJECT_ROOT.resolve())
    except (OSError, ValueError):
        return ""
    if not resolved.exists() or resolved.suffix.lower() != ".svg":
        return ""
    return resolved.read_text(encoding="utf-8")


def build_regulated_flow_frequency(process_rows: list[dict[str, str]]) -> list[dict[str, float | str | int]]:
    sorted_rows = sorted(
        process_rows,
        key=lambda row: to_float(row.get("年调节流量_m3s")),
        reverse=True,
    )
    total = len(sorted_rows)
    frequency_rows: list[dict[str, float | str | int]] = []
    for rank, row in enumerate(sorted_rows, start=1):
        frequency_rows.append(
            {
                "正常蓄水位_m": row.get("正常蓄水位_m", ""),
                "年份": row.get("年份", ""),
                "供水期": row.get("供水期", ""),
                "年调节流量_m3s": round(to_float(row.get("年调节流量_m3s")), 3),
                "排位": rank,
                "经验频率_%": round(rank / (total + 1) * 100, 3) if total else 0.0,
            }
        )
    return frequency_rows


def calculate_guaranteed_output(scheme_id: str, level: float) -> dict:
    scheme = configured_scheme(scheme_id, level)
    if scheme_id not in dead_water_available_scheme_ids():
        raise ValueError("该方案尚未完成死水位计算，不能进行保证出力计算")
    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    from hydropower_engine import run_guaranteed_output

    result, process_rows = run_guaranteed_output(CURRENT_PROJECT_ROOT, project, scheme)
    empirical_points = [
        {
            "frequency": to_float(row.get("经验频率_%")),
            "outputKw": to_float(row.get("年保证出力_kW")),
            "year": row.get("年份", ""),
        }
        for row in process_rows
    ]
    design_rate = project_guarantee_rate(project)
    theoretical_curve = build_theoretical_frequency_curve(result, design_rate)
    mark_scheme_calculated("guaranteedOutputSchemeIds", scheme_id)
    return {
        "schemeId": scheme_id,
        "level": level,
        "availableSchemeIds": sorted(dead_water_available_scheme_ids()),
        "result": result,
        "processRows": process_rows,
        "frequencyCurve": {
            "empirical": empirical_points,
            "theoretical": theoretical_curve,
            "designGuaranteeRate": design_rate,
        },
        "downloads": {
            "resultTable": "output/guaranteed_output_results.csv",
            "processTable": "output/guaranteed_output_annual_frequency.csv",
        },
        "note": "保证出力由当前动态死水位、供水期、径流系列、尾水曲线和设计保证率实时计算。",
    }


def calculate_installed_capacity(scheme_id: str, level: float) -> dict:
    scheme = configured_scheme(scheme_id, level)
    if scheme_id not in guaranteed_output_available_scheme_ids():
        raise ValueError("该方案尚未完成保证出力计算，不能进行必须容量计算")
    from hydropower_engine import run_required_capacity

    required_row = run_required_capacity(CURRENT_PROJECT_ROOT, scheme)

    return {
        "schemeId": scheme_id,
        "level": level,
        "availableSchemeIds": sorted(guaranteed_output_available_scheme_ids()),
        "result": required_row,
        "requiredCapacityRows": [required_row] if required_row else [],
        "downloads": {
            "requiredTable": "output/required_capacity_results.csv",
        },
        "note": "本节按任务书“四、水电站装机容量计算”计算必须容量：峰荷工作容量按保证出力扣除航运基荷后换算，工作容量再加备用容量得到必须容量。",
    }


def calculate_dispatch_chart(scheme_id: str, level: float) -> dict:
    scheme = configured_scheme(scheme_id, level)
    if scheme_id not in guaranteed_output_available_scheme_ids():
        raise ValueError("该方案尚未完成保证出力计算，不能绘制水电站调度图")

    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    from hydropower_engine import run_dispatch_chart

    rows, chart_svg = run_dispatch_chart(CURRENT_PROJECT_ROOT, project, scheme)

    mark_scheme_calculated("dispatchChartSchemeIds", scheme_id)
    flood_limit_levels = [
        to_float(row.get("防洪限制水位_m"))
        for row in rows if row.get("防洪限制水位_m") not in (None, "")
    ]
    return {
        "schemeId": scheme_id,
        "level": level,
        "availableSchemeIds": sorted(guaranteed_output_available_scheme_ids()),
        "summary": {
            "正常蓄水位_m": level,
            "防洪限制水位_m": flood_limit_levels[0] if flood_limit_levels else "",
            "防破坏线最低水位_m": min(to_float(row.get("防破坏线水位_m")) for row in rows),
            "防破坏线最高水位_m": max(to_float(row.get("防破坏线水位_m")) for row in rows),
        },
        "chartSvg": chart_svg,
        "tables": {"lines": rows},
        "note": "调度图由当前动态兴利成果按等出力法逆时序计算，横轴以3月末为起点。",
    }


def quadratic_capacity_at_hours(rows: list[dict], level: float, target_hours: float = 2500.0) -> float:
    excluded_by_level = {115.0: {30.0, 40.0}, 108.0: {20.0, 30.0}, 100.0: {30.0}}
    excluded = excluded_by_level.get(level, set())
    points = [
        (to_float(row.get("重复容量_万kW")), to_float(row.get("利用小时数_h")))
        for row in rows
        if to_float(row.get("重复容量_万kW")) not in excluded
    ]
    sums = {
        "n": len(points),
        "x": sum(x for x, _ in points),
        "x2": sum(x**2 for x, _ in points),
        "x3": sum(x**3 for x, _ in points),
        "x4": sum(x**4 for x, _ in points),
        "y": sum(y for _, y in points),
        "xy": sum(x * y for x, y in points),
        "x2y": sum(x**2 * y for x, y in points),
    }
    matrix = [
        [sums["x4"], sums["x3"], sums["x2"], sums["x2y"]],
        [sums["x3"], sums["x2"], sums["x"], sums["xy"]],
        [sums["x2"], sums["x"], sums["n"], sums["y"]],
    ]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(matrix[row][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        if abs(divisor) < 1e-12:
            return 0.0
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(3):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [matrix[row][index] - factor * matrix[column][index] for index in range(4)]
    a, b, c = [row[3] for row in matrix]
    c -= target_hours
    discriminant = b * b - 4 * a * c
    if discriminant < 0 or abs(a) < 1e-12:
        return 0.0
    roots = [(-b - math.sqrt(discriminant)) / (2 * a), (-b + math.sqrt(discriminant)) / (2 * a)]
    max_capacity = max(x for x, _ in points)
    valid = sorted(root for root in roots if 0 <= root <= max_capacity)
    return valid[0] if valid else 0.0


def calculate_repeated_capacity(scheme_id: str, level: float, mode: str, delta_n: float) -> dict:
    configured_scheme(scheme_id, level)
    if scheme_id not in completed_scheme_ids("dispatchChartSchemeIds"):
        raise ValueError("该方案尚未完成水电站调度图绘制，不能进行重复容量计算")
    if mode not in {"machine", "manual"}:
        raise ValueError("定线方式只能选择机器定线或人工定线")
    if delta_n <= 0:
        raise ValueError("ΔN必须大于0")

    from repeated_capacity_engine import run as run_repeated_capacity_dp

    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    delta_key = f"{delta_n:.6f}".rstrip("0").rstrip(".").replace(".", "_")
    level_key_text = f"{level:.3f}".rstrip("0").rstrip(".").replace(".", "_")
    cache_dir = PROJECT_FINAL_ROOT / "calculations" / "repeated_capacity" / scheme_id / f"level_{level_key_text}" / f"delta_{delta_key}"
    energy_summary, energy_process = run_repeated_capacity_dp(
        level, delta_n, cache_dir, CURRENT_PROJECT_ROOT, project, scheme_id
    )

    machine_target = quadratic_capacity_at_hours(energy_summary, level)
    repeated_capacity = machine_target
    mark_scheme_calculated(f"repeatedCapacity{mode.title()}SchemeIds", scheme_id)
    utilization: dict[float, dict[str, float]] = {}
    for row in energy_process:
        capacity = to_float(row.get("重复容量_万kW"))
        bucket = utilization.setdefault(capacity, {"inflow": 0.0, "generation": 0.0})
        bucket["inflow"] += to_float(row.get("来水量_m3s"))
        bucket["generation"] += to_float(row.get("发电流量_m3s"))
    runoff_rows = [
        {
            "正常蓄水位_m": level,
            "重复容量_万kW": capacity,
            "径流利用系数_%": round(values["generation"] / values["inflow"] * 100.0, 4) if values["inflow"] else 0.0,
        }
        for capacity, values in sorted(utilization.items())
    ]
    return {
        "schemeId": scheme_id,
        "level": level,
        "mode": mode,
        "result": {
            "正常蓄水位_m": level,
            "delta_N_万kW": delta_n,
            "定线方式": "机器二次函数拟合" if mode == "machine" else "人工定线",
            "2500h对应重复容量_万kW": repeated_capacity,
            "控制点数量": "系统拟合",
            "备注": "由当前项目数据动态计算",
        },
        "machineTarget": machine_target,
        "chartSvg": "",
        "tables": {
            "fit": [{
                "正常蓄水位_m": level,
                "delta_N_万kW": delta_n,
                "定线方式": "机器二次函数拟合" if mode == "machine" else "人工定线",
                "2500h对应重复容量_万kW": repeated_capacity,
            }],
            "energySummary": energy_summary,
            "energyProcess": energy_process,
            "runoffUtilization": runoff_rows,
        },
        "note": "采用DP逐月优化计算各重复容量下的多年平均电能和增量利用小时数，再由所选定线方式读取N-h曲线与2500 h交点。",
    }


def confirm_repeated_capacity(payload: dict) -> dict:
    scheme_id = str(payload.get("schemeId", ""))
    level = to_float(payload.get("level"))
    mode = str(payload.get("mode", ""))
    delta_n = to_float(payload.get("deltaN"))
    repeated_capacity = to_float(payload.get("repeatedCapacity"), -1.0)
    configured_scheme(scheme_id, level)
    if mode not in {"machine", "manual"}:
        raise ValueError("定线方式无效")
    if scheme_id not in completed_scheme_ids(f"repeatedCapacity{mode.title()}SchemeIds"):
        raise ValueError("该方案尚未完成所选方式的重复容量计算")
    if delta_n <= 0 or repeated_capacity < 0:
        raise ValueError("ΔN或重复容量无效")
    state = calculation_state()
    selections = state.setdefault("repeatedCapacitySelections", {})
    selections[scheme_id] = {
        "schemeId": scheme_id,
        "normalWaterLevel": level,
        "mode": mode,
        "deltaN": delta_n,
        "repeatedCapacity": repeated_capacity,
        "controlPoints": payload.get("controlPoints", []) if mode == "manual" else [],
    }
    save_calculation_state(state)
    return {"selection": selections[scheme_id]}


def dynamic_dispatch_rows(scheme_id: str) -> list[dict[str, str]]:
    path = PROJECT_FINAL_ROOT / "calculations" / "hydropower" / scheme_id / "dispatch_chart_lines.csv"
    return read_csv(path)


def calculate_discharge_capacity(scheme_id: str, level: float) -> dict:
    scheme = configured_scheme(scheme_id, level)
    if scheme_id not in completed_scheme_ids("dispatchChartSchemeIds"):
        raise ValueError("该方案尚未完成水电站调度图绘制，无法取得防洪限制水位")

    dispatch_rows = [row for row in dynamic_dispatch_rows(scheme_id) if row.get("防洪限制水位_m") not in (None, "")]
    if not dispatch_rows:
        raise ValueError("该方案暂无防洪限制水位成果")
    flood_limit_level = to_float(dispatch_rows[0].get("防洪限制水位_m"))
    spillway = scheme["spillway"]
    outlet = scheme["middleOutlet"]
    start_tenth = int(flood_limit_level * 10)
    end_tenth = int((level + 20.0) * 10)
    rows: list[dict[str, float]] = []
    for level_tenth in range(start_tenth, end_tenth + 1, 5):
        water_level = level_tenth / 10.0
        spillway_head = max(water_level - to_float(spillway["crestElevation"]), 0.0)
        spillway_release = (
            1.77 * int(spillway["holes"]) * to_float(spillway["orificeWidth"]) * spillway_head**1.5
        )
        outlet_release = 0.0
        if int(outlet["holes"]) > 0:
            opening = to_float(outlet["orificeHeight"])
            area = to_float(outlet["orificeWidth"]) * opening
            center_head = max(water_level - (to_float(outlet["sillElevation"]) + opening / 2.0), 1e-6)
            coefficient = max(0.0, 0.99 - 0.53 * opening / center_head)
            outlet_release = int(outlet["holes"]) * coefficient * area * math.sqrt(2 * 9.81 * center_head)
        rows.append(
            {
                "正常蓄水位_m": level,
                "水位_m": water_level,
                "溢洪坝泄量_m3s": round(spillway_release, 4),
                "中孔泄量_m3s": round(outlet_release, 4),
                "泄流能力_m3s": round(spillway_release + outlet_release, 4),
            }
        )

    mark_scheme_calculated("dischargeCapacitySchemeIds", scheme_id)
    return {
        "schemeId": scheme_id,
        "level": level,
        "summary": {
            "防洪限制水位_m": flood_limit_level,
            "曲线起点水位_m": rows[0]["水位_m"],
            "曲线终点水位_m": rows[-1]["水位_m"],
            "防洪限制水位泄流能力_m3s": rows[0]["泄流能力_m3s"],
            "最大计算泄流能力_m3s": rows[-1]["泄流能力_m3s"],
        },
        "facility": {
            "溢洪坝孔数": spillway["holes"],
            "溢洪坝堰顶高程_m": spillway["crestElevation"],
            "溢洪坝孔口宽度_m": spillway["orificeWidth"],
            "中孔孔数": outlet["holes"],
            "中孔坎底高程_m": outlet["sillElevation"],
            "中孔孔口宽度_m": outlet["orificeWidth"],
            "中孔孔口高度_m": outlet["orificeHeight"],
        },
        "tables": {"capacity": rows},
        "note": "泄流能力为溢洪坝与中孔泄量之和；当前计算水位均高于堰顶和中孔坎底，无需分段讨论启用条件。",
    }


def flood_calculation_dir(scheme_id: str) -> Path:
    return PROJECT_FINAL_ROOT / "calculations" / "flood_routing" / scheme_id


def calculate_flood_routing(scheme_id: str, level: float) -> dict:
    scheme = configured_scheme(scheme_id, level)
    if scheme_id not in completed_scheme_ids("dischargeCapacitySchemeIds"):
        raise ValueError("该方案尚未完成泄流能力曲线计算，不能进行调洪演算")
    dispatch_rows = [row for row in dynamic_dispatch_rows(scheme_id) if row.get("防洪限制水位_m") not in (None, "")]
    if not dispatch_rows:
        raise ValueError("该方案暂无防洪限制水位成果")
    flood_limit = to_float(dispatch_rows[0].get("防洪限制水位_m"))
    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    storage_path = CURRENT_PROJECT_ROOT / project["baseData"]["storageCurve"]
    flood_path = CURRENT_PROJECT_ROOT / project["baseData"]["designFlood"]
    from flood_engine import run_flood_routing

    safe_release = to_float(project.get("parameters", {}).get("downstreamSafeFlowM3s"), 20000.0)
    summary, process_rows = run_flood_routing(scheme, flood_limit, storage_path, flood_path, safe_release)
    output_dir = flood_calculation_dir(scheme_id)
    write_csv(output_dir / "flood_routing_summary.csv", [summary])
    write_csv(output_dir / "flood_routing_process.csv", process_rows)
    mark_scheme_calculated("floodRoutingSchemeIds", scheme_id)
    return {
        "schemeId": scheme_id,
        "level": level,
        "summary": summary,
        "tables": {
            "summary": [summary],
            "flood5": [row for row in process_rows if row["洪水标准"] == "5%"],
            "design": [row for row in process_rows if row["洪水标准"] == "0.1%"],
            "check": [row for row in process_rows if row["洪水标准"] == "0.01%"],
        },
        "note": "先按5%洪水确定防洪高水位，再分别对0.1%设计洪水和0.01%校核洪水进行调洪演算。",
    }


def calculate_dam_crest(scheme_id: str, level: float) -> dict:
    configured_scheme(scheme_id, level)
    if scheme_id not in completed_scheme_ids("floodRoutingSchemeIds"):
        raise ValueError("该方案尚未完成水库调洪演算，不能确定坝顶高程")
    summary_path = flood_calculation_dir(scheme_id) / "flood_routing_summary.csv"
    summary_rows = read_csv(summary_path)
    if not summary_rows:
        raise ValueError("找不到该方案的调洪汇总成果，请重新进行调洪演算")
    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    parameters = project.get("parameters", {})
    wind_speed = to_float(parameters.get("designWindSpeedMs"), 12.0)
    fetch_km = to_float(parameters.get("maxFetchKm"), 15.0)
    from flood_engine import dam_crest

    result = dam_crest(summary_rows[0], wind_speed, fetch_km)
    write_csv(flood_calculation_dir(scheme_id) / "dam_crest_result.csv", [result])
    mark_scheme_calculated("damCrestSchemeIds", scheme_id)
    return {
        "schemeId": scheme_id,
        "level": level,
        "result": result,
        "tables": {"result": [result]},
        "note": "设计工况与校核工况分别计算风浪高和安全超高，坝顶高程取两种工况计算值的较大者。",
    }


def economy_available_scheme_ids() -> set[str]:
    selected = set(calculation_state().get("repeatedCapacitySelections", {}))
    candidates = selected & completed_scheme_ids("damCrestSchemeIds")
    required_files = (
        ("hydropower", "required_capacity_result.csv"),
        ("flood_routing", "flood_routing_summary.csv"),
        ("flood_routing", "dam_crest_result.csv"),
    )
    return {
        scheme_id
        for scheme_id in candidates
        if all(
            (CURRENT_PROJECT_ROOT / "calculations" / group / scheme_id / filename).is_file()
            for group, filename in required_files
        )
    }


def calculate_economy_data(scheme_id: str, level: float) -> dict:
    scheme = configured_scheme(scheme_id, level)
    if scheme_id not in economy_available_scheme_ids():
        raise ValueError("该方案需要先确认定线成果并完成坝顶高程计算")
    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    from economic_engine import calculate_all

    results = calculate_all(CURRENT_PROJECT_ROOT, project, list_schemes()["schemes"], economy_available_scheme_ids())
    return results[scheme_id]


def calculate_economy_comparison() -> dict:
    project = read_json(CURRENT_PROJECT_ROOT / "project.json")
    from economic_engine import calculate_all

    results = calculate_all(CURRENT_PROJECT_ROOT, project, list_schemes()["schemes"], economy_available_scheme_ids())
    rows = [item["comparison"] for item in results.values()]
    return {"rows": rows, "completeSchemeIds": sorted(results)}


def calculation_status() -> dict:
    return {
        "deadWaterAvailableSchemeIds": sorted(dead_water_available_scheme_ids()),
        "guaranteedOutputAvailableSchemeIds": sorted(guaranteed_output_available_scheme_ids()),
        "dispatchChartSchemeIds": sorted(completed_scheme_ids("dispatchChartSchemeIds")),
        "repeatedCapacityMachineSchemeIds": sorted(completed_scheme_ids("repeatedCapacityMachineSchemeIds")),
        "repeatedCapacityManualSchemeIds": sorted(completed_scheme_ids("repeatedCapacityManualSchemeIds")),
        "dischargeCapacitySchemeIds": sorted(completed_scheme_ids("dischargeCapacitySchemeIds")),
        "floodRoutingSchemeIds": sorted(completed_scheme_ids("floodRoutingSchemeIds")),
        "damCrestSchemeIds": sorted(completed_scheme_ids("damCrestSchemeIds")),
        "repeatedCapacitySelections": calculation_state().get("repeatedCapacitySelections", {}),
        "economyAvailableSchemeIds": sorted(economy_available_scheme_ids()),
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "HydroCalcWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/summary":
            self.write_json(build_summary())
            return
        if path == "/api/base-data":
            dataset_id = parse_qs(parsed.query).get("id", [""])[0]
            if dataset_id:
                try:
                    self.write_json(read_project_dataset(dataset_id))
                except KeyError as exc:
                    self.write_json({"error": str(exc)}, status=404)
            else:
                self.write_json(list_base_data())
            return
        if path == "/api/schemes":
            self.write_json(list_schemes())
            return
        if path == "/api/calc/status":
            self.write_json(calculation_status())
            return
        if path == "/api/calc/dead-water":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_dead_water(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/guaranteed-output":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_guaranteed_output(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/installed-capacity":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_installed_capacity(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/dispatch-chart":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_dispatch_chart(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/repeated-capacity":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            mode = query.get("mode", ["machine"])[0]
            delta_n = to_float(query.get("deltaN", ["15"])[0], 15.0)
            try:
                self.write_json(calculate_repeated_capacity(scheme_id, level, mode, delta_n))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/discharge-capacity":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_discharge_capacity(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/flood-routing":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_flood_routing(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/dam-crest":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_dam_crest(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/economy-data":
            query = parse_qs(parsed.query)
            level = to_float(query.get("level", [""])[0])
            scheme_id = query.get("schemeId", [""])[0]
            try:
                self.write_json(calculate_economy_data(scheme_id, level))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/calc/economy-comparison":
            self.write_json(calculate_economy_comparison())
            return
        if path == "/api/table":
            key = parse_qs(parsed.query).get("key", [""])[0]
            source = TABLE_SOURCES.get(key)
            if not source:
                self.write_json({"error": "unknown table key"}, status=404)
                return
            self.write_json({"key": key, "rows": read_csv(source)})
            return
        if path == "/api/chart":
            key = parse_qs(parsed.query).get("key", [""])[0]
            source = CHART_SOURCES.get(key)
            if not source or not source.exists():
                self.write_json({"error": "unknown chart key"}, status=404)
                return
            self.write_bytes(source.read_bytes(), "image/svg+xml; charset=utf-8")
            return
        if path == "/api/download":
            rel = parse_qs(parsed.query).get("path", [""])[0]
            self.write_download(rel)
            return
        self.write_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/project/reset":
            try:
                self.write_json(reset_project_to_initial())
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/base-data/save":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
                dataset_id = payload.get("id", "")
                self.write_json(save_project_dataset(dataset_id, payload))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/schemes/save":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
                self.write_json(save_schemes(payload.get("schemes", [])))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/schemes/add":
            try:
                self.write_json(add_scheme())
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/schemes/use-example":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
                self.write_json(apply_example_scheme(payload.get("targetId", ""), payload.get("exampleId", "")))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/base-data/use-example":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
                dataset_id = payload.get("id", "")
                self.write_json(copy_example_dataset(dataset_id))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/base-data/upload":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            dataset_id = parse_qs(parsed.query).get("id", [""])[0]
            try:
                self.write_json(upload_project_dataset(dataset_id, self.headers.get("Content-Type", ""), body))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/recalculate/economy":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
                self.write_json(recalculate_economy(payload))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/calc/repeated-capacity/confirm":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                self.write_json(confirm_repeated_capacity(json.loads(raw)))
            except Exception as exc:  # noqa: BLE001
                self.write_json({"error": str(exc)}, status=400)
            return
        self.write_json({"error": "not found"}, status=404)

    def write_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            target = STATIC_ROOT / "index.html"
        else:
            target = (STATIC_ROOT / request_path.lstrip("/")).resolve()
        try:
            target.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self.write_json({"error": "forbidden"}, status=403)
            return
        if not target.exists() or not target.is_file():
            target = STATIC_ROOT / "index.html"
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif target.suffix in {".html", ".css"}:
            content_type = f"text/{target.suffix[1:]}; charset=utf-8"
        self.write_bytes(target.read_bytes(), content_type)

    def write_download(self, rel_path: str) -> None:
        target = (PROJECT_ROOT / rel_path).resolve()
        allowed_roots = [DATA_ROOT.resolve(), OUTPUT_ROOT.resolve(), APP_DATA_ROOT.resolve(), PROJECT_FINAL_ROOT.resolve()]
        if not any(target == root or root in target.parents for root in allowed_roots):
            self.write_json({"error": "forbidden"}, status=403)
            return
        if not target.exists() or not target.is_file():
            self.write_json({"error": "not found"}, status=404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{target.name.encode("utf-8").decode("latin-1", "ignore")}"')
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def write_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.write_bytes(data, "application/json; charset=utf-8", status=status)

    def write_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    port = int(os.environ.get("HYDROCALC_PORT", "8787"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print(f"HydroCalc Web running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
