from __future__ import annotations

import csv
from pathlib import Path

from repeated_capacity import (
    DOWNSTREAM_CURVE_CSV,
    STORAGE_CURVE_CSV,
    read_curve,
    read_schemes,
)
from repeated_capacity_dp_trial import (
    make_storage_grid,
    read_dispatch_rules_by_boundary_order,
    read_runoff_by_calc_months,
    run_continuous_dp,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
REQUIRED_CAPACITY_CSV = OUTPUT_DIR / "required_capacity_results.csv"
MANUAL_REPEATED_CAPACITY_CSV = OUTPUT_DIR / "repeated_capacity_dp_trial" / "manual_fit_2500h.csv"
RESULT_CSV = OUTPUT_DIR / "installed_capacity_summary.csv"


def read_required_capacity() -> dict[float, dict[str, float]]:
    rows: dict[float, dict[str, float]] = {}
    with REQUIRED_CAPACITY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            level = float(row["正常蓄水位_m"])
            rows[level] = {
                "死水位_m": float(row["死水位_m"]),
                "保证出力_万kW": float(row["保证出力_万kW"]),
                "工作容量_万kW": float(row["工作容量_万kW"]),
                "备用容量_万kW": float(row["备用容量_万kW"]),
                "必须容量_万kW": float(row["必须容量_万kW"]),
            }
    return rows


def read_repeated_capacity() -> dict[float, float]:
    values: dict[float, float] = {}
    with MANUAL_REPEATED_CAPACITY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            value = row["2500h对应重复容量_万kW"]
            values[float(row["正常蓄水位_m"])] = float(value) if value != "" else 0.0
    return values


def write_summary(rows: list[dict[str, float]]) -> Path:
    fieldnames = [
        "正常蓄水位_m",
        "死水位_m",
        "保证出力_万kW",
        "工作容量_万kW",
        "备用容量_万kW",
        "必须容量_万kW",
        "重复容量_万kW",
        "装机容量_万kW",
        "多年平均电能_亿kWh",
    ]
    with RESULT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(value, 4) for key, value in row.items()})
    return RESULT_CSV


def main() -> None:
    level_points, storage_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = read_curve(DOWNSTREAM_CURVE_CSV, "下游水位_m", "流量_m3每秒")
    runoff = read_runoff_by_calc_months()
    schemes = read_schemes(level_points, storage_points)
    dispatch_rules_by_level = read_dispatch_rules_by_boundary_order(level_points, storage_points)
    required_by_level = read_required_capacity()
    repeated_by_level = read_repeated_capacity()

    rows: list[dict[str, float]] = []
    for scheme in sorted(schemes, key=lambda item: item.normal_level, reverse=True):
        repeated_capacity = repeated_by_level[scheme.normal_level]
        installed_capacity = scheme.required_capacity_10k_kw + repeated_capacity
        total_energy_kwh, _ = run_continuous_dp(
            repeated_capacity,
            scheme,
            scheme.normal_level,
            make_storage_grid(scheme),
            runoff,
            dispatch_rules_by_level[scheme.normal_level],
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        average_energy_100m_kwh = total_energy_kwh / len(runoff) / 100_000_000
        required = required_by_level[scheme.normal_level]
        rows.append(
            {
                "正常蓄水位_m": scheme.normal_level,
                "死水位_m": required["死水位_m"],
                "保证出力_万kW": required["保证出力_万kW"],
                "工作容量_万kW": required["工作容量_万kW"],
                "备用容量_万kW": required["备用容量_万kW"],
                "必须容量_万kW": required["必须容量_万kW"],
                "重复容量_万kW": repeated_capacity,
                "装机容量_万kW": installed_capacity,
                "多年平均电能_亿kWh": average_energy_100m_kwh,
            }
        )

    output_path = write_summary(rows)
    print(f"装机容量汇总已写入: {output_path}")


if __name__ == "__main__":
    main()
