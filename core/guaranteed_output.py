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
DEAD_WATER_RESULTS_CSV = OUTPUT_DIR / "dead_water_level_results.csv"
SUPPLY_PERIODS_CSV = OUTPUT_DIR / "dead_water_level_supply_periods.csv"

# Adjustable hydropower parameters.
K_OUTPUT = 8.5
DELTA_H = 1.0

DESIGN_GUARANTEE_RATE = 87.5
MONTHS = ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"]


@dataclass
class SchemeStorage:
    normal_level: float
    dead_level: float
    normal_storage: float
    dead_storage: float


@dataclass
class GuaranteedOutputResult:
    normal_level: float
    dead_level: float
    dead_storage_m3s_month: float
    active_storage_m3s_month: float
    guaranteed_output_kw: float
    guaranteed_output_10k_kw: float
    mean_annual_output_kw: float
    std_annual_output_kw: float
    skew_annual_output: float


@dataclass
class SupplyPeriod:
    normal_level: float
    year: int
    start_month: str
    end_month: str
    label: str


def read_curve(path: Path, x_col: str, y_col: str) -> tuple[list[float], list[float]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [float(row[x_col]) for row in rows], [float(row[y_col]) for row in rows]


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


def read_runoff(path: Path) -> list[tuple[int, list[float]]]:
    runoff: list[tuple[int, list[float]]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        year_col = reader.fieldnames[0] if reader.fieldnames else ""
        for row in reader:
            if not row.get(year_col):
                continue
            year = int(float(row[year_col]))
            flows = [float(row[month]) for month in MONTHS]
            runoff.append((year, flows))
    return runoff


def read_scheme_storages(
    path: Path,
    level_points: list[float],
    storage_m3s_month_points: list[float],
) -> list[SchemeStorage]:
    schemes: list[SchemeStorage] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            normal_level = float(row["正常蓄水位_m"])
            dead_level = float(row["死水位_m"])
            schemes.append(
                SchemeStorage(
                    normal_level=normal_level,
                    dead_level=dead_level,
                    normal_storage=interpolate(normal_level, level_points, storage_m3s_month_points),
                    dead_storage=interpolate(dead_level, level_points, storage_m3s_month_points),
                )
            )
    return schemes


def read_supply_periods(path: Path) -> dict[tuple[float, int], SupplyPeriod]:
    periods: dict[tuple[float, int], SupplyPeriod] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            normal_level = float(row["正常蓄水位_m"])
            year = int(row["年份"])
            periods[(normal_level, year)] = SupplyPeriod(
                normal_level=normal_level,
                year=year,
                start_month=row["供水期初"],
                end_month=row["供水期末"],
                label=row["供水期"],
            )
    return periods


def slice_supply_period_flows(flows: list[float], start_month: str, end_month: str) -> list[float]:
    start_index = MONTHS.index(start_month)
    end_index = MONTHS.index(end_month)
    if start_index <= end_index:
        return flows[start_index : end_index + 1]
    return flows[start_index:] + flows[: end_index + 1]


def solve_month_generation_flow(
    target_output_kw: float,
    start_storage: float,
    inflow: float,
    normal_storage: float,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float | None:
    def output_for_flow(flow: float) -> float:
        end_storage = min(normal_storage, start_storage + inflow - flow)
        average_storage = (start_storage + end_storage) / 2
        upstream_level = interpolate(average_storage, storage_points, level_points)
        downstream_level = interpolate(flow, downstream_flow_points, downstream_level_points)
        net_head = upstream_level - downstream_level - DELTA_H
        return K_OUTPUT * flow * max(net_head, 0.0)

    if target_output_kw <= 0:
        return 0.0

    high = max(inflow + max(start_storage, 0.0), 1.0)
    while output_for_flow(high) < target_output_kw and high < 100000:
        high *= 2
    if output_for_flow(high) < target_output_kw:
        return None

    low = 0.0
    for _ in range(80):
        mid = (low + high) / 2
        if output_for_flow(mid) >= target_output_kw:
            high = mid
        else:
            low = mid
    return high


def simulate_equal_output_year(
    target_output_kw: float,
    flows: list[float],
    scheme: SchemeStorage,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> tuple[bool, float]:
    storage = scheme.normal_storage
    min_storage = storage

    for inflow in flows:
        generation_flow = solve_month_generation_flow(
            target_output_kw,
            storage,
            inflow,
            scheme.normal_storage,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        if generation_flow is None:
            return False, min_storage

        end_storage = min(scheme.normal_storage, storage + inflow - generation_flow)
        min_storage = min(min_storage, end_storage)
        if end_storage < scheme.dead_storage:
            return False, min_storage
        storage = end_storage

    return True, min_storage


def annual_guaranteed_output(
    flows: list[float],
    scheme: SchemeStorage,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    low = 0.0
    high = 100000.0

    while True:
        feasible, _ = simulate_equal_output_year(
            high,
            flows,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        if not feasible:
            break
        high *= 2
        if high > 5000000:
            break

    for _ in range(80):
        mid = (low + high) / 2
        feasible, _ = simulate_equal_output_year(
            mid,
            flows,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        if feasible:
            low = mid
        else:
            high = mid
    return low


def p3_design_value(values: list[float], guarantee_rate: float) -> tuple[float, float, float, float]:
    mean_value = stats.tmean(values)
    std_value = stats.tstd(values)
    skew_value = stats.skew(values, bias=False)
    non_exceedance_probability = 1 - guarantee_rate / 100
    design_value = stats.pearson3.ppf(
        non_exceedance_probability,
        skew_value,
        loc=mean_value,
        scale=std_value,
    )
    return design_value, mean_value, std_value, skew_value


def write_annual_outputs(rows: list[tuple[float, int, str, float, int, float]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "guaranteed_output_annual_frequency.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["正常蓄水位_m", "年份", "供水期", "年保证出力_kW", "排位", "经验频率_%"])
        for row in rows:
            writer.writerow([row[0], row[1], row[2], round(row[3], 3), row[4], round(row[5], 3)])
    return output_path


def write_results(results: list[GuaranteedOutputResult]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "guaranteed_output_results.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "正常蓄水位_m",
                "死水位_m",
                "死库容_m3s月",
                "兴利库容_m3s月",
                "保证出力_kW",
                "保证出力_万kW",
                "年保证出力均值_kW",
                "年保证出力标准差_kW",
                "年保证出力偏态系数Cs",
                "K",
                "delta_H_m",
            ]
        )
        for row in results:
            writer.writerow(
                [
                    row.normal_level,
                    round(row.dead_level, 2),
                    round(row.dead_storage_m3s_month, 3),
                    round(row.active_storage_m3s_month, 3),
                    round(row.guaranteed_output_kw, 3),
                    round(row.guaranteed_output_10k_kw, 4),
                    round(row.mean_annual_output_kw, 3),
                    round(row.std_annual_output_kw, 3),
                    round(row.skew_annual_output, 4),
                    K_OUTPUT,
                    DELTA_H,
                ]
            )
    return output_path


def main() -> None:
    level_points, storage_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = read_curve(
        DOWNSTREAM_CURVE_CSV, "下游水位_m", "流量_m3每秒"
    )
    runoff = read_runoff(RUNOFF_CSV)
    schemes = read_scheme_storages(DEAD_WATER_RESULTS_CSV, level_points, storage_points)
    supply_periods = read_supply_periods(SUPPLY_PERIODS_CSV)

    results: list[GuaranteedOutputResult] = []
    annual_frequency_rows: list[tuple[float, int, str, float, int, float]] = []

    for scheme in schemes:
        annual_outputs: list[tuple[int, str, float]] = []
        for year, flows in runoff:
            period = supply_periods[(scheme.normal_level, year)]
            supply_flows = slice_supply_period_flows(flows, period.start_month, period.end_month)
            annual_outputs.append(
                (
                    year,
                    period.label,
                    annual_guaranteed_output(
                        supply_flows,
                        scheme,
                        level_points,
                        storage_points,
                        downstream_level_points,
                        downstream_flow_points,
                    ),
                )
            )

        sorted_outputs = sorted(annual_outputs, key=lambda item: item[2], reverse=True)
        n = len(sorted_outputs)
        for rank, (year, period_label, output_kw) in enumerate(sorted_outputs, start=1):
            annual_frequency_rows.append(
                (scheme.normal_level, year, period_label, output_kw, rank, rank / (n + 1) * 100)
            )

        design_output, mean_output, std_output, skew_output = p3_design_value(
            [output_kw for _, _, output_kw in annual_outputs],
            DESIGN_GUARANTEE_RATE,
        )
        results.append(
            GuaranteedOutputResult(
                normal_level=scheme.normal_level,
                dead_level=scheme.dead_level,
                dead_storage_m3s_month=scheme.dead_storage,
                active_storage_m3s_month=scheme.normal_storage - scheme.dead_storage,
                guaranteed_output_kw=design_output,
                guaranteed_output_10k_kw=design_output / 10000,
                mean_annual_output_kw=mean_output,
                std_annual_output_kw=std_output,
                skew_annual_output=skew_output,
            )
        )

    results_path = write_results(results)
    annual_path = write_annual_outputs(annual_frequency_rows)
    print(f"保证出力结果已写入: {results_path}")
    print(f"年保证出力排频表已写入: {annual_path}")
    for row in results:
        print(
            f"Z_normal={row.normal_level:.0f} m, "
            f"Np={row.guaranteed_output_kw:.3f} kW "
            f"({row.guaranteed_output_10k_kw:.4f} 万kW)"
        )


if __name__ == "__main__":
    main()
