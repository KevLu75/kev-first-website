from __future__ import annotations

import csv
import importlib.util
import math
import statistics
import sys
import threading
import types
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))


if importlib.util.find_spec("scipy") is None:
    class _Pearson3:
        @staticmethod
        def ppf(probability: float, skew: float, loc: float, scale: float) -> float:
            z = statistics.NormalDist().inv_cdf(min(max(probability, 1e-9), 1.0 - 1e-9))
            adjusted = z + (skew / 6.0) * (z * z - 1.0)
            return loc + adjusted * scale

    class _Stats:
        pearson3 = _Pearson3()

        @staticmethod
        def tmean(values):
            return statistics.mean(values)

        @staticmethod
        def tstd(values):
            return statistics.stdev(values)

        @staticmethod
        def skew(values, bias=False):
            n = len(values)
            if n < 3:
                return 0.0
            mean = statistics.mean(values)
            m2 = sum((value - mean) ** 2 for value in values) / n
            if m2 <= 0:
                return 0.0
            g1 = (sum((value - mean) ** 3 for value in values) / n) / (m2 ** 1.5)
            return math.sqrt(n * (n - 1)) / (n - 2) * g1 if not bias else g1

    scipy_module = types.ModuleType("scipy")
    scipy_module.stats = _Stats()
    sys.modules["scipy"] = scipy_module

import dead_water_level as dead  # noqa: E402
import dispatch_chart as dispatch  # noqa: E402
import guaranteed_output as guaranteed  # noqa: E402


MONTHS = ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"]
CORE_LOCK = threading.Lock()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def project_paths(project_root: Path, project: dict) -> dict[str, Path]:
    base = project["baseData"]
    return {
        "storage": project_root / base["storageCurve"],
        "tailwater": project_root / base["tailwaterCurve"],
        "runoff": project_root / base["runoffSeries"],
    }


def guarantee_percent(project: dict) -> float:
    value = float(project.get("parameters", {}).get("designGuaranteeRate", 0.875))
    return value * 100.0 if value <= 1.0 else value


def adjusted_runoff(project_root: Path, project: dict) -> list[tuple[int, list[float]]]:
    path = project_paths(project_root, project)["runoff"]
    monthly = project.get("parameters", {}).get("navigationIrrigationConsumption", {}).get("monthly", {})
    rows = read_csv(path)
    output: list[tuple[int, list[float]]] = []
    for row in rows:
        year_key = "年份" if "年份" in row else next(iter(row))
        year_text = str(row.get(year_key, "")).strip().strip("\x1a")
        if not year_text:
            continue
        try:
            year = int(float(year_text))
        except ValueError:
            continue
        flows = [max(0.0, float(row[month]) - float(monthly.get(month, 0.0))) for month in MONTHS]
        output.append((year, flows))
    if not output:
        raise ValueError("径流系列为空，不能进行兴利计算")
    return output


def calculation_dir(project_root: Path, scheme_id: str) -> Path:
    return project_root / "calculations" / "hydropower" / scheme_id


def curve_inputs(project_root: Path, project: dict):
    paths = project_paths(project_root, project)
    levels, storages_100m = dead.read_curve(paths["storage"], "水位_m", "库容_亿m3")
    _, storages_month = dead.read_curve(paths["storage"], "水位_m", "库容_m3每秒月")
    tail_levels, tail_flows = dead.read_curve(paths["tailwater"], "下游水位_m", "流量_m3每秒")
    return levels, storages_100m, storages_month, tail_levels, tail_flows


def dead_result_row(result) -> dict:
    return {
        "正常蓄水位_m": result.normal_level,
        "迭代次数": result.iterations,
        "收敛前q0_m3s": round(result.q0, 3),
        "设计调节流量qp_m3s": round(result.qp, 3),
        "Z1_m": round(result.z1, 2),
        "Z2_m": round(result.z2, 2),
        "Z3_m": round(result.z3, 2),
        "死水位_m": round(result.dead_level, 2),
        "死库容_亿m3": round(result.dead_storage_100m_m3, 4),
        "正常库容_亿m3": round(result.normal_storage_100m_m3, 4),
        "兴利库容_亿m3": round(result.active_storage_100m_m3, 4),
        "兴利库容_m3s月": round(result.active_storage_m3s_month, 3),
    }


def supply_period_row(row) -> dict:
    return {
        "正常蓄水位_m": row.normal_level,
        "年份": row.year,
        "年调节流量_m3s": round(row.regulated_flow, 3),
        "下边界切点月份": row.lower_touch_month,
        "上边界切点月份": row.upper_touch_month,
        "供水期初": row.supply_start_month,
        "供水期末": row.supply_end_month,
        "供水期": row.supply_period,
    }


def run_dead_water(project_root: Path, project: dict, scheme: dict) -> tuple[dict, list[dict]]:
    level = float(scheme["normalWaterLevel"])
    levels, storages_100m, storages_month, tail_levels, tail_flows = curve_inputs(project_root, project)
    runoff = adjusted_runoff(project_root, project)
    parameters = project.get("parameters", {})
    annual_silt_100m = float(parameters.get("annualSedimentation", {}).get("value", 0.0))
    service_years = int(float(parameters.get("damServiceLifeYears", 50)))
    rate = guarantee_percent(project)
    with CORE_LOCK:
        originals = (dead.SILTATION_10K_M3_PER_YEAR, dead.SERVICE_YEARS, dead.DESIGN_GUARANTEE_RATE)
        dead.SILTATION_10K_M3_PER_YEAR = annual_silt_100m * 10000.0
        dead.SERVICE_YEARS = service_years
        dead.DESIGN_GUARANTEE_RATE = rate
        try:
            result, _ = dead.compute_scheme(
                level, levels, storages_100m, storages_month, tail_levels, tail_flows, runoff
            )
            periods = dead.build_supply_period_results([result], runoff)
        finally:
            dead.SILTATION_10K_M3_PER_YEAR, dead.SERVICE_YEARS, dead.DESIGN_GUARANTEE_RATE = originals
    result_row = dead_result_row(result)
    period_rows = [supply_period_row(row) for row in periods]
    output = calculation_dir(project_root, scheme["id"])
    write_csv(output / "dead_water_result.csv", [result_row])
    write_csv(output / "dead_water_supply_periods.csv", period_rows)
    return result_row, period_rows


def run_guaranteed_output(project_root: Path, project: dict, scheme: dict) -> tuple[dict, list[dict]]:
    output = calculation_dir(project_root, scheme["id"])
    dead_rows = read_csv(output / "dead_water_result.csv")
    period_rows = read_csv(output / "dead_water_supply_periods.csv")
    if not dead_rows or not period_rows:
        raise ValueError("找不到该方案的动态死水位成果")
    dead_row = dead_rows[0]
    levels, _, storages_month, tail_levels, tail_flows = curve_inputs(project_root, project)
    runoff = adjusted_runoff(project_root, project)
    level = float(scheme["normalWaterLevel"])
    dead_level = float(dead_row["死水位_m"])
    scheme_storage = guaranteed.SchemeStorage(
        normal_level=level,
        dead_level=dead_level,
        normal_storage=guaranteed.interpolate(level, levels, storages_month),
        dead_storage=guaranteed.interpolate(dead_level, levels, storages_month),
    )
    periods = {
        int(row["年份"]): guaranteed.SupplyPeriod(
            normal_level=level,
            year=int(row["年份"]),
            start_month=row["供水期初"],
            end_month=row["供水期末"],
            label=row["供水期"],
        )
        for row in period_rows
    }
    annual: list[tuple[int, str, float]] = []
    for year, flows in runoff:
        period = periods[year]
        supply_flows = guaranteed.slice_supply_period_flows(flows, period.start_month, period.end_month)
        power = guaranteed.annual_guaranteed_output(
            supply_flows, scheme_storage, levels, storages_month, tail_levels, tail_flows
        )
        annual.append((year, period.label, power))
    rate = guarantee_percent(project)
    design, mean, std, skew = guaranteed.p3_design_value([item[2] for item in annual], rate)
    result = {
        "正常蓄水位_m": level,
        "死水位_m": dead_level,
        "死库容_m3s月": round(scheme_storage.dead_storage, 3),
        "兴利库容_m3s月": round(scheme_storage.normal_storage - scheme_storage.dead_storage, 3),
        "保证出力_kW": round(design, 3),
        "保证出力_万kW": round(design / 10000.0, 4),
        "年保证出力均值_kW": round(mean, 3),
        "年保证出力标准差_kW": round(std, 3),
        "年保证出力偏态系数Cs": round(skew, 4),
        "K": guaranteed.K_OUTPUT,
        "delta_H_m": guaranteed.DELTA_H,
    }
    sorted_annual = sorted(annual, key=lambda item: item[2], reverse=True)
    total = len(sorted_annual)
    frequency = [
        {
            "正常蓄水位_m": level,
            "年份": year,
            "供水期": label,
            "年保证出力_kW": round(power, 3),
            "排位": rank,
            "经验频率_%": round(rank / (total + 1) * 100.0, 3),
        }
        for rank, (year, label, power) in enumerate(sorted_annual, start=1)
    ]
    write_csv(output / "guaranteed_output_result.csv", [result])
    write_csv(output / "guaranteed_output_frequency.csv", frequency)
    return result, frequency


def run_required_capacity(project_root: Path, scheme: dict) -> dict:
    output = calculation_dir(project_root, scheme["id"])
    guaranteed_rows = read_csv(output / "guaranteed_output_result.csv")
    if not guaranteed_rows:
        raise ValueError("找不到该方案的动态保证出力成果")
    source = guaranteed_rows[0]
    guaranteed_power = float(source["保证出力_万kW"])
    base = 10.0
    peak_guaranteed = guaranteed_power - base
    peak_work = 3.08 * peak_guaranteed + 7.0
    work = peak_work + base
    reserve = float(scheme.get("reserveCapacity", 0.0))
    result = {
        "正常蓄水位_m": float(scheme["normalWaterLevel"]),
        "死水位_m": float(source["死水位_m"]),
        "保证出力_万kW": round(guaranteed_power, 4),
        "航运基荷工作容量_万kW": base,
        "峰荷保证出力_万kW": round(peak_guaranteed, 4),
        "峰荷工作容量_万kW": round(peak_work, 4),
        "工作容量_万kW": round(work, 4),
        "备用容量_万kW": reserve,
        "必须容量_万kW": round(work + reserve, 4),
    }
    write_csv(output / "required_capacity_result.csv", [result])
    return result


def run_dispatch_chart(project_root: Path, project: dict, scheme: dict) -> tuple[list[dict], str]:
    output = calculation_dir(project_root, scheme["id"])
    dead_rows = read_csv(output / "dead_water_result.csv")
    guaranteed_rows = read_csv(output / "guaranteed_output_result.csv")
    period_rows = read_csv(output / "dead_water_supply_periods.csv")
    frequency_rows = read_csv(output / "guaranteed_output_frequency.csv")
    if not dead_rows or not guaranteed_rows or not period_rows or not frequency_rows:
        raise ValueError("动态调度图缺少上游兴利成果")
    levels, _, storages_month, tail_levels, tail_flows = curve_inputs(project_root, project)
    level = float(scheme["normalWaterLevel"])
    dead_level = float(dead_rows[0]["死水位_m"])
    source = guaranteed_rows[0]
    dispatch_scheme = dispatch.Scheme(
        normal_level=level,
        dead_level=dead_level,
        normal_storage=dispatch.interpolate(level, levels, storages_month),
        dead_storage=dispatch.interpolate(dead_level, levels, storages_month),
        guaranteed_output_kw=float(source["保证出力_kW"]),
        k_output=float(source["K"]),
        delta_h=float(source["delta_H_m"]),
    )
    runoff = {year: flows for year, flows in adjusted_runoff(project_root, project)}
    periods = {
        (level, int(row["年份"])): dispatch.SupplyPeriod(
            start_month=row["供水期初"], end_month=row["供水期末"], label=row["供水期"]
        )
        for row in period_rows
    }
    rate = guarantee_percent(project)
    selected_years = {int(row["年份"]) for row in frequency_rows if float(row["经验频率_%"]) <= rate}
    rows = dispatch.build_dispatch_lines(
        dispatch_scheme, runoff, periods, selected_years, levels, storages_month, tail_levels, tail_flows
    )
    write_csv(output / "dispatch_chart_lines.csv", rows)
    with CORE_LOCK:
        original_output = dispatch.OUTPUT_DIR
        dispatch.OUTPUT_DIR = output
        try:
            chart_path = dispatch.plot_dispatch_charts(rows)[0]
        finally:
            dispatch.OUTPUT_DIR = original_output
    return rows, chart_path.read_text(encoding="utf-8")
