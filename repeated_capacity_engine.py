from __future__ import annotations

import csv
import sys
import threading
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

import repeated_capacity_dp_trial as dp  # noqa: E402
from repeated_capacity import Scheme  # noqa: E402
from hydropower_engine import adjusted_runoff, calculation_dir  # noqa: E402


ENGINE_LOCK = threading.Lock()


def capacity_points(delta_n: float) -> list[float]:
    if delta_n <= 0:
        raise ValueError("ΔN必须大于0")
    if delta_n < 10:
        count = max(1, round(60.0 / delta_n))
    else:
        count = 6
    return [round(delta_n * index, 6) for index in range(1, count + 1)]


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
        for row in rows:
            writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()})


def build_context(level: float, project_root: Path, project: dict, scheme_id: str):
    base = project["baseData"]
    storage_path = project_root / base["storageCurve"]
    tailwater_path = project_root / base["tailwaterCurve"]
    level_points, storage_points = dp.read_curve(storage_path, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = dp.read_curve(tailwater_path, "下游水位_m", "流量_m3每秒")
    runoff = adjusted_runoff(project_root, project)
    hydro_dir = calculation_dir(project_root, scheme_id)
    dead_rows = read_csv(hydro_dir / "dead_water_result.csv")
    guaranteed_rows = read_csv(hydro_dir / "guaranteed_output_result.csv")
    required_rows = read_csv(hydro_dir / "required_capacity_result.csv")
    dispatch_path = hydro_dir / "dispatch_chart_lines.csv"
    if not dead_rows or not guaranteed_rows or not required_rows or not dispatch_path.exists():
        raise ValueError("重复容量计算缺少动态兴利成果")
    dead_row, guaranteed_row, required_row = dead_rows[0], guaranteed_rows[0], required_rows[0]
    dead_level = float(dead_row["死水位_m"])
    scheme = Scheme(
        normal_level=level,
        dead_level=dead_level,
        dead_storage=dp.interpolate(dead_level, level_points, storage_points),
        normal_storage=dp.interpolate(level, level_points, storage_points),
        guaranteed_output_kw=float(guaranteed_row["保证出力_kW"]),
        required_capacity_10k_kw=float(required_row["必须容量_万kW"]),
        k_output=float(guaranteed_row["K"]),
        delta_h=float(guaranteed_row["delta_H_m"]),
    )
    with ENGINE_LOCK:
        original_dispatch = dp.DISPATCH_LINES_CSV
        dp.DISPATCH_LINES_CSV = dispatch_path
        try:
            dispatch_rules = dp.read_dispatch_rules_by_boundary_order(level_points, storage_points)[level]
        finally:
            dp.DISPATCH_LINES_CSV = original_dispatch
    return (
        scheme, dp.make_storage_grid(scheme), runoff, dispatch_rules, level_points, storage_points,
        downstream_level_points, downstream_flow_points,
    )


def run(
    level: float,
    delta_n: float,
    cache_dir: Path,
    project_root: Path,
    project: dict,
    scheme_id: str,
) -> tuple[list[dict], list[dict]]:
    summary_path = cache_dir / "average_energy_summary.csv"
    process_path = cache_dir / "average_energy_process.csv"
    (scheme, grid, runoff, dispatch_rules, level_points, storage_points,
     downstream_level_points, downstream_flow_points) = build_context(level, project_root, project, scheme_id)

    summary_rows: list[dict] = []
    process_rows: list[dict] = []
    previous_energy: float | None = None
    previous_capacity: float | None = None
    for repeated_capacity in [0.0, *capacity_points(delta_n)]:
        total_energy, process = dp.run_continuous_dp(
            repeated_capacity,
            scheme,
            level,
            grid,
            runoff,
            dispatch_rules,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        average_energy = total_energy / len(runoff) / 100_000_000
        if previous_energy is not None and previous_capacity is not None:
            delta_energy = average_energy - previous_energy
            utilization_hours = delta_energy * 10000 / (repeated_capacity - previous_capacity)
            summary_rows.append(
                {
                    "正常蓄水位_m": level,
                    "重复容量_万kW": repeated_capacity,
                    "装机容量_万kW": scheme.required_capacity_10k_kw + repeated_capacity,
                    "多年平均年发电量_亿kWh": average_energy,
                    "年发电量差值_亿kWh": delta_energy,
                    "利用小时数_h": utilization_hours,
                }
            )
            process_rows.extend(process)
        previous_energy = average_energy
        previous_capacity = repeated_capacity

    write_csv(summary_path, summary_rows)
    write_csv(process_path, process_rows)
    return summary_rows, process_rows


def run_single_capacity(
    level: float,
    repeated_capacity: float,
    output_dir: Path,
    project_root: Path,
    project: dict,
    scheme_id: str,
) -> tuple[dict, list[dict]]:
    (scheme, grid, runoff, dispatch_rules, level_points, storage_points,
     downstream_level_points, downstream_flow_points) = build_context(level, project_root, project, scheme_id)
    total_energy, process = dp.run_continuous_dp(
        repeated_capacity, scheme, level, grid, runoff, dispatch_rules, level_points, storage_points,
        downstream_level_points, downstream_flow_points,
    )
    result = {
        "正常蓄水位_m": level,
        "重复容量_万kW": repeated_capacity,
        "装机容量_万kW": scheme.required_capacity_10k_kw + repeated_capacity,
        "多年平均年发电量_亿kWh": total_energy / len(runoff) / 100_000_000,
    }
    write_csv(output_dir / "exact_energy_result.csv", [result])
    write_csv(output_dir / "exact_energy_process.csv", process)
    return result, process
