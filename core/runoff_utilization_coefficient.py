from __future__ import annotations

import csv
from pathlib import Path

from repeated_capacity import (
    DOWNSTREAM_CURVE_CSV,
    OUTPUT_DIR,
    STORAGE_CURVE_CSV,
    read_curve,
    read_schemes,
)
from repeated_capacity_dp_trial import (
    CALC_MONTHS,
    make_storage_grid,
    read_dispatch_rules_by_boundary_order,
    read_runoff_by_calc_months,
    run_continuous_dp,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANUAL_REPEATED_CAPACITY_CSV = OUTPUT_DIR / "repeated_capacity_dp_trial" / "manual_fit_2500h.csv"
RESULT_CSV = OUTPUT_DIR / "runoff_utilization_coefficient_results.csv"


def read_manual_repeated_capacity() -> dict[float, float]:
    values: dict[float, float] = {}
    with MANUAL_REPEATED_CAPACITY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            value = row["2500h对应重复容量_万kW"]
            values[float(row["正常蓄水位_m"])] = float(value) if value != "" else 0.0
    return values


def average_runoff_flow(runoff: list[tuple[int, list[float]]]) -> float:
    values = [flow for _, flows in runoff for flow in flows]
    return sum(values) / len(values)


def annual_spill_flow(process_rows: list[dict[str, float | int | str]]) -> dict[int, float]:
    spill_by_year: dict[int, float] = {}
    for row in process_rows:
        year = int(row["年份"])
        spill_by_year[year] = spill_by_year.get(year, 0.0) + float(row["弃水折算库容_m3s月"])
    return {year: spill_storage / len(CALC_MONTHS) for year, spill_storage in spill_by_year.items()}


def write_rows(rows: list[dict[str, float | int]]) -> Path:
    with RESULT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "正常蓄水位_m",
                "必须容量_万kW",
                "重复容量_万kW",
                "装机容量_万kW",
                "多年平均流量Q0_m3s",
                "多年平均弃水流量Q弃_m3s",
                "径流利用系数",
                "径流利用系数_%",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(value, 6) if isinstance(value, float) else value for key, value in row.items()})
    return RESULT_CSV


def main() -> None:
    level_points, storage_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = read_curve(DOWNSTREAM_CURVE_CSV, "下游水位_m", "流量_m3每秒")
    runoff = read_runoff_by_calc_months()
    schemes = read_schemes(level_points, storage_points)
    repeated_capacity_by_level = read_manual_repeated_capacity()
    dispatch_rules_by_level = read_dispatch_rules_by_boundary_order(level_points, storage_points)
    q0 = average_runoff_flow(runoff)

    rows: list[dict[str, float | int]] = []
    for scheme in sorted(schemes, key=lambda item: item.normal_level, reverse=True):
        repeated_capacity = repeated_capacity_by_level[scheme.normal_level]
        grid = make_storage_grid(scheme)
        _, process_rows = run_continuous_dp(
            repeated_capacity,
            scheme,
            scheme.normal_level,
            grid,
            runoff,
            dispatch_rules_by_level[scheme.normal_level],
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        yearly_spill_flow = annual_spill_flow(process_rows)
        average_spill_flow = sum(yearly_spill_flow.values()) / len(yearly_spill_flow)
        utilization = (q0 - average_spill_flow) / q0
        rows.append(
            {
                "正常蓄水位_m": scheme.normal_level,
                "必须容量_万kW": scheme.required_capacity_10k_kw,
                "重复容量_万kW": repeated_capacity,
                "装机容量_万kW": scheme.required_capacity_10k_kw + repeated_capacity,
                "多年平均流量Q0_m3s": q0,
                "多年平均弃水流量Q弃_m3s": average_spill_flow,
                "径流利用系数": utilization,
                "径流利用系数_%": utilization * 100,
            }
        )

    result_path = write_rows(rows)
    print(f"径流利用系数结果已写入: {result_path}")


if __name__ == "__main__":
    main()
