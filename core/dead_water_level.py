from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from scipy import stats


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

STORAGE_CURVE_CSV = DATA_DIR / "water_level_storage.csv"
DOWNSTREAM_CURVE_CSV = DATA_DIR / "downstream_level_flow.csv"
RUNOFF_CSV = DATA_DIR / "径流系列表_调整后.csv"

NORMAL_LEVELS = [120.0, 115.0, 108.0, 100.0]
SILTATION_10K_M3_PER_YEAR = 669.0
SERVICE_YEARS = 50
Z2_COMPREHENSIVE_USE = 82.0
INITIAL_Q0 = 204.0
DESIGN_GUARANTEE_RATE = 87.5
TOLERANCE_Q = 1.0
MONTHS = ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"]


@dataclass
class DeadWaterResult:
    normal_level: float
    iterations: int
    q0: float
    qp: float
    z1: float
    z2: float
    z3: float
    dead_level: float
    dead_storage_100m_m3: float
    normal_storage_100m_m3: float
    active_storage_100m_m3: float
    active_storage_m3s_month: float


@dataclass
class TangentResult:
    regulated_flow: float
    slope: float
    lower_touch_index: int
    upper_touch_index: int


@dataclass
class SupplyPeriodResult:
    normal_level: float
    year: int
    regulated_flow: float
    lower_touch_month: str
    upper_touch_month: str
    supply_start_month: str
    supply_end_month: str
    supply_period: str


def read_curve(path: Path, x_col: str, y_col: str) -> tuple[list[float], list[float]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    x_values = [float(row[x_col]) for row in rows]
    y_values = [float(row[y_col]) for row in rows]
    return x_values, y_values


def interpolate(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]

    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    raise RuntimeError("Interpolation failed")


def inverse_interpolate(y: float, xs: list[float], ys: list[float]) -> float:
    if y <= ys[0]:
        return xs[0]
    if y >= ys[-1]:
        return xs[-1]

    for i in range(1, len(ys)):
        if y <= ys[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            return x0 + (y - y0) * (x1 - x0) / (y1 - y0)
    raise RuntimeError("Inverse interpolation failed")


def read_runoff(path: Path) -> list[tuple[int, list[float]]]:
    runoff: list[tuple[int, list[float]]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        year_col = reader.fieldnames[0] if reader.fieldnames else ""
        for row in reader:
            if not row.get(year_col):
                continue
            year = int(float(row[year_col]))
            flows = [float(row[col]) for col in MONTHS]
            runoff.append((year, flows))
    return runoff


def tangent_regulated_flow_for_year(flows: list[float], active_storage_m3s_month: float) -> TangentResult:
    """Use the two-curve common tangent method taught in class.

    W_upper is the difference curve based on Q0 = average annual flow.
    W_lower = W_upper - V. The valid control line must first touch the lower
    boundary, then touch the upper boundary, so i < j.
    """
    q0 = sum(flows) / len(flows)
    w_upper: list[float] = []
    cumulative = 0.0
    for flow in flows:
        cumulative += flow - q0
        w_upper.append(cumulative)
    w_lower = [value - active_storage_m3s_month for value in w_upper]

    valid_tangents: list[tuple[float, int, int]] = []
    eps = 1e-5
    n = len(flows)

    for i in range(n):
        for j in range(n):
            if i >= j:
                continue

            slope = (w_upper[j] - w_lower[i]) / (j - i)
            line_ok = True
            for t in range(i, j + 1):
                y = w_lower[i] + slope * (t - i)
                if y > w_upper[t] + eps or y < w_lower[t] - eps:
                    line_ok = False
                    break
            if not line_ok:
                continue

            if 0 < i < n - 1:
                left_slope_i = w_lower[i] - w_lower[i - 1]
                right_slope_i = w_lower[i + 1] - w_lower[i]
                if (left_slope_i - slope) * (right_slope_i - slope) > eps:
                    continue

            if j != n - 1 and 0 < j < n - 1:
                left_slope_j = w_upper[j] - w_upper[j - 1]
                right_slope_j = w_upper[j + 1] - w_upper[j]
                if (left_slope_j - slope) * (right_slope_j - slope) > eps:
                    continue

            valid_tangents.append((slope, i, j))

    if not valid_tangents:
        raise RuntimeError("No valid common tangent found for this runoff year")

    best_slope, lower_touch_index, upper_touch_index = min(valid_tangents, key=lambda item: item[0])
    return TangentResult(
        regulated_flow=q0 + best_slope,
        slope=best_slope,
        lower_touch_index=lower_touch_index,
        upper_touch_index=upper_touch_index,
    )


def regulated_flow_for_year(flows: list[float], active_storage_m3s_month: float) -> float:
    return tangent_regulated_flow_for_year(flows, active_storage_m3s_month).regulated_flow


def design_qp_from_p3_fit(
    yearly_q: list[tuple[int, float]],
    guarantee_rate: float,
) -> tuple[float, float, float, float]:
    q_values = [q for _, q in yearly_q]
    mean_q = stats.tmean(q_values)
    std_q = stats.tstd(q_values)
    skew_q = stats.skew(q_values, bias=False)

    non_exceedance_probability = 1 - guarantee_rate / 100
    qp = stats.pearson3.ppf(
        non_exceedance_probability,
        skew_q,
        loc=mean_q,
        scale=std_q,
    )
    return qp, mean_q, std_q, skew_q


def compute_scheme(
    normal_level: float,
    level_points: list[float],
    storage_100m_m3_points: list[float],
    storage_m3s_month_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
    runoff: list[tuple[int, list[float]]],
) -> tuple[DeadWaterResult, tuple[float, float, float]]:
    silting_storage_100m_m3 = SILTATION_10K_M3_PER_YEAR * SERVICE_YEARS / 10000
    z1 = inverse_interpolate(silting_storage_100m_m3, level_points, storage_100m_m3_points)
    z2 = Z2_COMPREHENSIVE_USE
    normal_storage_100m_m3 = interpolate(normal_level, level_points, storage_100m_m3_points)

    q0 = INITIAL_Q0
    last_p3_params: tuple[float, float, float] = (0.0, 0.0, 0.0)

    for iteration in range(1, 101):
        downstream_level = interpolate(q0, downstream_flow_points, downstream_level_points)
        drawdown = (normal_level - downstream_level) * 0.35
        z3 = normal_level - drawdown
        dead_level = max(z1, z2, z3)
        dead_storage_100m_m3 = interpolate(dead_level, level_points, storage_100m_m3_points)
        dead_storage_m3s_month = interpolate(dead_level, level_points, storage_m3s_month_points)
        normal_storage_m3s_month = interpolate(normal_level, level_points, storage_m3s_month_points)
        active_storage_100m_m3 = normal_storage_100m_m3 - dead_storage_100m_m3
        active_storage_m3s_month = normal_storage_m3s_month - dead_storage_m3s_month

        yearly_q = [
            (year, regulated_flow_for_year(flows, active_storage_m3s_month))
            for year, flows in runoff
        ]
        qp, mean_q, std_q, skew_q = design_qp_from_p3_fit(yearly_q, DESIGN_GUARANTEE_RATE)
        last_p3_params = (mean_q, std_q, skew_q)

        if abs(qp - q0) < TOLERANCE_Q:
            return (
                DeadWaterResult(
                    normal_level=normal_level,
                    iterations=iteration,
                    q0=q0,
                    qp=qp,
                    z1=z1,
                    z2=z2,
                    z3=z3,
                    dead_level=dead_level,
                    dead_storage_100m_m3=dead_storage_100m_m3,
                    normal_storage_100m_m3=normal_storage_100m_m3,
                    active_storage_100m_m3=active_storage_100m_m3,
                    active_storage_m3s_month=active_storage_m3s_month,
                ),
                last_p3_params,
            )

        q0 = qp

    raise RuntimeError(f"Scheme {normal_level:g} did not converge")


def write_results(results: list[DeadWaterResult]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "dead_water_level_results.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "正常蓄水位_m",
                "迭代次数",
                "收敛前q0_m3s",
                "设计调节流量qp_m3s",
                "Z1_m",
                "Z2_m",
                "Z3_m",
                "死水位_m",
                "死库容_亿m3",
                "正常库容_亿m3",
                "兴利库容_亿m3",
                "兴利库容_m3s月",
            ]
        )
        for row in results:
            writer.writerow(
                [
                    row.normal_level,
                    row.iterations,
                    round(row.q0, 3),
                    round(row.qp, 3),
                    round(row.z1, 2),
                    round(row.z2, 2),
                    round(row.z3, 2),
                    round(row.dead_level, 2),
                    round(row.dead_storage_100m_m3, 4),
                    round(row.normal_storage_100m_m3, 4),
                    round(row.active_storage_100m_m3, 4),
                    round(row.active_storage_m3s_month, 3),
                ]
            )
    return output_path


def write_p3_parameters(p3_params: dict[float, tuple[float, float, float]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "dead_water_level_p3_fit_parameters.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["正常蓄水位_m", "均值_m3s", "标准差_m3s", "偏态系数Cs"])
        for normal_level in NORMAL_LEVELS:
            mean_q, std_q, skew_q = p3_params[normal_level]
            writer.writerow([normal_level, round(mean_q, 3), round(std_q, 3), round(skew_q, 4)])
    return output_path


def next_month_index(index: int) -> int:
    return (index + 1) % len(MONTHS)


def format_supply_period(lower_touch_index: int, upper_touch_index: int) -> str:
    start_month = MONTHS[next_month_index(lower_touch_index)]
    end_month = MONTHS[upper_touch_index]
    return f"{start_month}至{end_month}"


def build_supply_period_results(
    results: list[DeadWaterResult],
    runoff: list[tuple[int, list[float]]],
) -> list[SupplyPeriodResult]:
    period_rows: list[SupplyPeriodResult] = []
    for result in results:
        for year, flows in runoff:
            tangent = tangent_regulated_flow_for_year(flows, result.active_storage_m3s_month)
            supply_start_index = next_month_index(tangent.lower_touch_index)
            period_rows.append(
                SupplyPeriodResult(
                    normal_level=result.normal_level,
                    year=year,
                    regulated_flow=tangent.regulated_flow,
                    lower_touch_month=MONTHS[tangent.lower_touch_index],
                    upper_touch_month=MONTHS[tangent.upper_touch_index],
                    supply_start_month=MONTHS[supply_start_index],
                    supply_end_month=MONTHS[tangent.upper_touch_index],
                    supply_period=format_supply_period(tangent.lower_touch_index, tangent.upper_touch_index),
                )
            )
    return period_rows


def write_supply_periods(period_rows: list[SupplyPeriodResult]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "dead_water_level_supply_periods.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "正常蓄水位_m",
                "年份",
                "年调节流量_m3s",
                "下边界切点月份",
                "上边界切点月份",
                "供水期初",
                "供水期末",
                "供水期",
            ]
        )
        for row in period_rows:
            writer.writerow(
                [
                    row.normal_level,
                    row.year,
                    round(row.regulated_flow, 3),
                    row.lower_touch_month,
                    row.upper_touch_month,
                    row.supply_start_month,
                    row.supply_end_month,
                    row.supply_period,
                ]
            )
    return output_path


def main() -> None:
    level_points, storage_100m_m3_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_亿m3")
    _, storage_m3s_month_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = read_curve(
        DOWNSTREAM_CURVE_CSV, "下游水位_m", "流量_m3每秒"
    )
    runoff = read_runoff(RUNOFF_CSV)

    results: list[DeadWaterResult] = []
    p3_params: dict[float, tuple[float, float, float]] = {}

    for normal_level in NORMAL_LEVELS:
        result, p3_param = compute_scheme(
            normal_level,
            level_points,
            storage_100m_m3_points,
            storage_m3s_month_points,
            downstream_level_points,
            downstream_flow_points,
            runoff,
        )
        results.append(result)
        p3_params[normal_level] = p3_param

    results_path = write_results(results)
    p3_params_path = write_p3_parameters(p3_params)
    supply_periods_path = write_supply_periods(build_supply_period_results(results, runoff))

    print(f"P-III适线结果已写入: {results_path}")
    print(f"P-III适线参数已写入: {p3_params_path}")
    print(f"切点间供水期已写入: {supply_periods_path}")
    for row in results:
        print(
            f"Z_normal={row.normal_level:.0f} m, "
            f"Z_dead={row.dead_level:.2f} m, "
            f"qp={row.qp:.3f} m3/s, "
            f"iterations={row.iterations}"
        )


if __name__ == "__main__":
    main()
