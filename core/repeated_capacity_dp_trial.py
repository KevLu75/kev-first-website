from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from repeated_capacity import (
    DISPATCH_LINES_CSV,
    DOWNSTREAM_CURVE_CSV,
    DispatchRule,
    OUTPUT_DIR,
    RUNOFF_CSV,
    STORAGE_CURVE_CSV,
    Scheme,
    interpolate,
    power_for_flow,
    read_curve,
    read_schemes,
    solve_flow_for_power,
)


NORMAL_LEVELS = [120.0, 115.0, 108.0, 100.0]
REPEATED_CAPACITIES_10K_KW = [float(value) for value in range(15, 105, 15)]
BASE_REPEATED_CAPACITY_10K_KW = 0.0
STORAGE_STATE_COUNT = 100
MONTH_HOURS = 730.0
CALC_MONTHS = ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"]


@dataclass
class Transition:
    end_index: int
    energy_kwh: float
    release_flow: float
    power_kw: float
    spill_storage: float
    mode: str


def make_storage_grid(scheme: Scheme) -> list[float]:
    step = (scheme.normal_storage - scheme.dead_storage) / (STORAGE_STATE_COUNT - 1)
    return [scheme.dead_storage + step * i for i in range(STORAGE_STATE_COUNT)]


def nearest_storage_index(storage: float, grid: list[float]) -> int:
    return min(range(len(grid)), key=lambda i: abs(grid[i] - storage))


def read_runoff_by_calc_months() -> list[tuple[int, list[float]]]:
    runoff: list[tuple[int, list[float]]] = []
    with RUNOFF_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        year_col = reader.fieldnames[0] if reader.fieldnames else ""
        for row in reader:
            if not row.get(year_col):
                continue
            runoff.append((int(float(row[year_col])), [float(row[month]) for month in CALC_MONTHS]))
    return runoff


def read_dispatch_rules_by_boundary_order(
    level_points: list[float],
    storage_points: list[float],
) -> dict[float, list[DispatchRule]]:
    rules: dict[float, dict[str, DispatchRule]] = {}
    with DISPATCH_LINES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            normal_level = float(row["正常蓄水位_m"])

            def optional_level_to_storage(column: str) -> float | None:
                value = row.get(column, "")
                if value == "":
                    return None
                return interpolate(float(value), level_points, storage_points)

            rules.setdefault(normal_level, {})[row["月份"]] = (
                DispatchRule(
                    month=row["月份"],
                    prevention_storage=float(row["防破坏线库蓄水量_m3s月"]),
                    flood_limit_storage=optional_level_to_storage("防洪限制水位_m"),
                    auxiliary_storages=(
                        optional_level_to_storage("加大出力辅助线1_m"),
                        optional_level_to_storage("加大出力辅助线2_m"),
                        optional_level_to_storage("加大出力辅助线3_m"),
                    ),
                )
            )

    ordered_rules: dict[float, list[DispatchRule]] = {}
    for normal_level, month_rules in rules.items():
        missing_months = [month for month in CALC_MONTHS if month not in month_rules]
        if missing_months:
            missing = "、".join(missing_months)
            raise RuntimeError(f"{normal_level:.0f}m 调度线缺少月份: {missing}")
        ordered_rules[normal_level] = [month_rules[month] for month in CALC_MONTHS]
    return ordered_rules


def upper_storage_for_month(rule, scheme: Scheme) -> float:
    return rule.flood_limit_storage if rule.flood_limit_storage is not None else scheme.normal_storage


def output_zone_target_power(start_storage: float, installed_kw: float, scheme: Scheme, rule) -> tuple[float | None, str]:
    if start_storage <= rule.prevention_storage + 1e-9:
        return min(scheme.guaranteed_output_kw, installed_kw), "低于防破坏线-保证出力"

    aux1, aux2, aux3 = rule.auxiliary_storages
    if rule.flood_limit_storage is not None and aux1 is not None and aux2 is not None and aux3 is not None:
        if start_storage <= aux1 + 1e-9:
            fraction = 0.25
            return min(scheme.guaranteed_output_kw + (installed_kw - scheme.guaranteed_output_kw) * fraction, installed_kw), "辅助线1区"
        if start_storage <= aux2 + 1e-9:
            fraction = 0.50
            return min(scheme.guaranteed_output_kw + (installed_kw - scheme.guaranteed_output_kw) * fraction, installed_kw), "辅助线2区"
        if start_storage <= aux3 + 1e-9:
            fraction = 0.75
            return min(scheme.guaranteed_output_kw + (installed_kw - scheme.guaranteed_output_kw) * fraction, installed_kw), "辅助线3区"
        if start_storage <= rule.flood_limit_storage + 1e-9:
            return installed_kw, "汛限线附近-满发"

    return None, "优化区"


def deterministic_transition(
    start_storage: float,
    inflow: float,
    target_power_kw: float,
    mode: str,
    upper_storage: float,
    installed_kw: float,
    scheme: Scheme,
    grid: list[float],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> Transition:
    release_flow = solve_flow_for_power(
        target_power_kw,
        start_storage,
        inflow,
        scheme,
        level_points,
        storage_points,
        downstream_level_points,
        downstream_flow_points,
    )
    raw_end_storage = max(scheme.dead_storage, start_storage + inflow - release_flow)
    spill_storage = max(raw_end_storage - upper_storage, 0.0)
    end_storage = min(raw_end_storage, upper_storage)
    end_storage = min(max(end_storage, scheme.dead_storage), scheme.normal_storage)

    power_kw = min(
        power_for_flow(
            release_flow,
            start_storage,
            end_storage,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        ),
        installed_kw,
    )
    return Transition(
        end_index=nearest_storage_index(end_storage, grid),
        energy_kwh=power_kw * MONTH_HOURS,
        release_flow=release_flow,
        power_kw=power_kw,
        spill_storage=spill_storage,
        mode=mode,
    )


def candidate_transitions(
    start_storage: float,
    inflow: float,
    rule,
    installed_kw: float,
    scheme: Scheme,
    grid: list[float],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> list[Transition]:
    upper_storage = upper_storage_for_month(rule, scheme)
    grid_step = grid[1] - grid[0]
    target_power, mode = output_zone_target_power(start_storage, installed_kw, scheme, rule)
    if target_power is not None:
        return [
            deterministic_transition(
                start_storage,
                inflow,
                target_power,
                mode,
                upper_storage,
                installed_kw,
                scheme,
                grid,
                level_points,
                storage_points,
                downstream_level_points,
                downstream_flow_points,
            )
        ]

    transitions: list[Transition] = []
    natural_max_end = min(start_storage + inflow, upper_storage)
    for end_index, end_storage in enumerate(grid):
        if end_storage < scheme.dead_storage - 1e-9:
            continue
        if end_storage > natural_max_end + 1e-9:
            continue

        release_flow = max(start_storage + inflow - end_storage, 0.0)
        raw_power_kw = power_for_flow(
            release_flow,
            start_storage,
            end_storage,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        power_kw = min(raw_power_kw, installed_kw)

        needs_spill = raw_power_kw > installed_kw + 1e-6
        if needs_spill and abs(end_storage - upper_storage) > grid_step:
            continue

        transitions.append(
            Transition(
                end_index=end_index,
                energy_kwh=power_kw * MONTH_HOURS,
                release_flow=release_flow,
                power_kw=power_kw,
                spill_storage=max(start_storage + inflow - release_flow - upper_storage, 0.0),
                mode="优化区-枚举月末库容",
            )
        )
    return transitions


def run_continuous_dp(
    repeated_capacity_10k_kw: float,
    scheme: Scheme,
    normal_level: float,
    grid: list[float],
    runoff: list[tuple[int, list[float]]],
    dispatch_rules,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> tuple[float, list[dict[str, float | int | str]]]:
    installed_capacity_10k_kw = scheme.required_capacity_10k_kw + repeated_capacity_10k_kw
    installed_kw = installed_capacity_10k_kw * 10000
    month_records = [(year, month_index, inflow) for year, flows in runoff for month_index, inflow in enumerate(flows)]

    start_index = nearest_storage_index(scheme.normal_storage, grid)
    dp = [-float("inf")] * len(grid)
    dp[start_index] = 0.0
    parents: list[list[tuple[int, Transition] | None]] = []

    for year, month_index, inflow in month_records:
        rule = dispatch_rules[month_index]
        next_dp = [-float("inf")] * len(grid)
        parent: list[tuple[int, Transition] | None] = [None] * len(grid)

        for start_i, previous_energy in enumerate(dp):
            if previous_energy == -float("inf"):
                continue
            for transition in candidate_transitions(
                grid[start_i],
                inflow,
                rule,
                installed_kw,
                scheme,
                grid,
                level_points,
                storage_points,
                downstream_level_points,
                downstream_flow_points,
            ):
                candidate = previous_energy + transition.energy_kwh
                if candidate > next_dp[transition.end_index]:
                    next_dp[transition.end_index] = candidate
                    parent[transition.end_index] = (start_i, transition)

        if max(next_dp) == -float("inf"):
            raise RuntimeError(
                f"{scheme.normal_level:.0f}m N={repeated_capacity_10k_kw:.0f}万kW "
                f"{year}年{CALC_MONTHS[month_index]}连续DP出现无可行转移"
            )
        dp = next_dp
        parents.append(parent)

    end_index = max(range(len(dp)), key=lambda i: dp[i])
    total_energy_kwh = dp[end_index]

    path: list[tuple[int, Transition]] = []
    current_index = end_index
    for parent in reversed(parents):
        previous = parent[current_index]
        if previous is None:
            raise RuntimeError("连续DP回溯失败")
        previous_index, transition = previous
        path.append((previous_index, transition))
        current_index = previous_index
    path.reverse()

    process_rows: list[dict[str, float | int | str]] = []
    current_storage_index = start_index
    for (year, month_index, inflow), (_, transition) in zip(month_records, path):
        start_storage = grid[current_storage_index]
        end_storage = grid[transition.end_index]
        process_rows.append(
            {
                "正常蓄水位_m": normal_level,
                "年份": year,
                "重复容量_万kW": repeated_capacity_10k_kw,
                "装机容量_万kW": installed_capacity_10k_kw,
                "月份": CALC_MONTHS[month_index],
                "运行方式": transition.mode,
                "月初库容_m3s月": start_storage,
                "月初水位_m": interpolate(start_storage, storage_points, level_points),
                "月末库容_m3s月": end_storage,
                "月末水位_m": interpolate(end_storage, storage_points, level_points),
                "来水量_m3s": inflow,
                "发电流量_m3s": transition.release_flow,
                "平均出力_kW": transition.power_kw,
                "弃水折算库容_m3s月": transition.spill_storage,
                "月发电量_kWh": transition.energy_kwh,
            }
        )
        current_storage_index = transition.end_index

    return total_energy_kwh, process_rows


def write_csv(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()})


def plot_relationship(normal_level: float, rows: list[dict[str, float | int | str]], output_path: Path) -> None:
    points = [
        (float(row["利用小时数_h"]), float(row["重复容量_万kW"]))
        for row in rows
        if row["利用小时数_h"] != ""
    ]
    if not points:
        return

    x_values = [x for x, _ in points] + [2500.0]
    y_values = [y for _, y in points]
    x_min, x_max = min(x_values) - 300, max(x_values) + 300
    y_min, y_max = 0.0, max(y_values) + 5

    width, height = 900, 540
    left, right, top, bottom = 90, 40, 50, 75
    plot_w, plot_h = width - left - right, height - top - bottom

    def px(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def py(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="450" y="28" text-anchor="middle" font-size="20">{normal_level:.0f}m 重复容量 N - 利用小时数 h 关系（连续DP）</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#444"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#444"/>',
    ]
    for tick in range(6):
        value = x_min + (x_max - x_min) * tick / 5
        x = px(value)
        elements.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height-bottom}" stroke="#e6e6e6"/>')
        elements.append(f'<text x="{x:.1f}" y="{height-bottom+24}" text-anchor="middle" font-size="12">{value:.0f}</text>')
    for tick in range(6):
        value = y_min + (y_max - y_min) * tick / 5
        y = py(value)
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e6e6e6"/>')
        elements.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12">{value:.0f}</text>')

    x2500 = px(2500.0)
    elements.append(f'<line x1="{x2500:.1f}" y1="{top}" x2="{x2500:.1f}" y2="{height-bottom}" stroke="#d62728" stroke-width="2" stroke-dasharray="6 4"/>')
    elements.append(f'<text x="{x2500+6:.1f}" y="{top+16}" font-size="12" fill="#d62728">2500h</text>')
    point_text = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in points)
    elements.append(f'<polyline points="{point_text}" fill="none" stroke="#1f77b4" stroke-width="2.5"/>')
    for x, y in points:
        elements.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3" fill="#1f77b4"/>')
    elements.append(f'<text x="{left + plot_w / 2:.0f}" y="{height-25}" text-anchor="middle" font-size="14">利用小时数 h</text>')
    elements.append(f'<text x="24" y="{height/2:.0f}" transform="rotate(-90 24,{height/2:.0f})" text-anchor="middle" font-size="14">重复容量 N (万kW)</text>')
    elements.append("</svg>")
    output_path.write_text("\n".join(elements), encoding="utf-8")


def quadratic_coefficients(points: list[tuple[float, float]]) -> tuple[float, float, float]:
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
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(3):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [matrix[row][index] - factor * matrix[column][index] for index in range(4)]
    return tuple(row[3] for row in matrix)


def plot_capacity_energy_relationship(
    normal_level: float,
    rows: list[dict[str, float | int | str]],
    output_path: Path,
) -> None:
    points = [
        (float(row["装机容量_万kW"]), float(row["多年平均年发电量_亿kWh"]))
        for row in rows
    ]
    if len(points) < 3:
        return
    a, b, c = quadratic_coefficients(points)
    x_min, x_max = min(x for x, _ in points), max(x for x, _ in points)
    y_values = [y for _, y in points]
    y_padding = max((max(y_values) - min(y_values)) * 0.15, 0.5)
    y_min, y_max = min(y_values) - y_padding, max(y_values) + y_padding
    dense = [x_min + (x_max - x_min) * index / 240 for index in range(241)]

    width, height = 900, 540
    left, right, top, bottom = 90, 40, 50, 75
    plot_w, plot_h = width - left - right, height - top - bottom

    def px(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def py(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="450" y="28" text-anchor="middle" font-size="20">{normal_level:.0f}m 装机容量-多年平均电能关系</text>',
    ]
    for tick in range(6):
        x_value = x_min + (x_max - x_min) * tick / 5
        y_value = y_min + (y_max - y_min) * tick / 5
        elements.append(f'<line x1="{px(x_value):.1f}" y1="{top}" x2="{px(x_value):.1f}" y2="{height-bottom}" stroke="#e5e7eb"/>')
        elements.append(f'<text x="{px(x_value):.1f}" y="{height-bottom+24}" text-anchor="middle" font-size="12">{x_value:.1f}</text>')
        elements.append(f'<line x1="{left}" y1="{py(y_value):.1f}" x2="{width-right}" y2="{py(y_value):.1f}" stroke="#e5e7eb"/>')
        elements.append(f'<text x="{left-8}" y="{py(y_value)+4:.1f}" text-anchor="end" font-size="12">{y_value:.2f}</text>')
    elements.extend([
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#64748b"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#64748b"/>',
    ])
    fit_points = " ".join(f"{px(x):.1f},{py(a*x*x+b*x+c):.1f}" for x in dense)
    elements.append(f'<polyline points="{fit_points}" fill="none" stroke="#0f6b8f" stroke-width="2.6"/>')
    for x, y in points:
        elements.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="4" fill="#f97316"/>')
    elements.append(f'<text x="{left + plot_w / 2:.0f}" y="{height-25}" text-anchor="middle" font-size="14">装机容量 (万kW)</text>')
    elements.append(f'<text x="24" y="{height/2:.0f}" transform="rotate(-90 24,{height/2:.0f})" text-anchor="middle" font-size="14">多年平均年发电量 (亿kWh)</text>')
    elements.append('</svg>')
    output_path.write_text("\n".join(elements), encoding="utf-8")


def main() -> None:
    level_points, storage_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = read_curve(DOWNSTREAM_CURVE_CSV, "下游水位_m", "流量_m3每秒")
    runoff = read_runoff_by_calc_months()
    schemes = read_schemes(level_points, storage_points)
    dispatch_rules_by_level = read_dispatch_rules_by_boundary_order(level_points, storage_points)

    output_dir = OUTPUT_DIR / "repeated_capacity_dp_trial"
    output_dir.mkdir(parents=True, exist_ok=True)

    all_summary_rows: list[dict[str, float | int | str]] = []
    for normal_level in NORMAL_LEVELS:
        scheme = next(s for s in schemes if abs(s.normal_level - normal_level) < 1e-9)
        dispatch_rules = dispatch_rules_by_level[normal_level]
        grid = make_storage_grid(scheme)
        summary_rows: list[dict[str, float | int | str]] = []
        process_rows: list[dict[str, float | int | str]] = []
        previous_energy_100m_kwh: float | None = None
        previous_repeated_capacity: float | None = None

        for repeated_capacity in [BASE_REPEATED_CAPACITY_10K_KW, *REPEATED_CAPACITIES_10K_KW]:
            total_energy_kwh, process = run_continuous_dp(
                repeated_capacity,
                scheme,
                normal_level,
                grid,
                runoff,
                dispatch_rules,
                level_points,
                storage_points,
                downstream_level_points,
                downstream_flow_points,
            )
            average_energy_100m_kwh = total_energy_kwh / len(runoff) / 100_000_000
            if previous_energy_100m_kwh is None or previous_repeated_capacity is None:
                delta_energy = ""
                utilization_hours = ""
            else:
                delta_capacity = repeated_capacity - previous_repeated_capacity
                delta_energy = average_energy_100m_kwh - previous_energy_100m_kwh
                utilization_hours = delta_energy * 10000 / delta_capacity

            if repeated_capacity != BASE_REPEATED_CAPACITY_10K_KW:
                row = {
                    "正常蓄水位_m": normal_level,
                    "重复容量_万kW": repeated_capacity,
                    "装机容量_万kW": scheme.required_capacity_10k_kw + repeated_capacity,
                    "多年平均年发电量_亿kWh": average_energy_100m_kwh,
                    "年发电量差值_亿kWh": delta_energy,
                    "利用小时数_h": utilization_hours,
                }
                summary_rows.append(row)
                all_summary_rows.append(row)
                process_rows.extend(process)
            previous_energy_100m_kwh = average_energy_100m_kwh
            previous_repeated_capacity = repeated_capacity

        summary_path = output_dir / f"dp_trial_{normal_level:.0f}m_continuous_summary.csv"
        process_path = output_dir / f"dp_trial_{normal_level:.0f}m_continuous_process.csv"
        chart_path = output_dir / f"dp_trial_{normal_level:.0f}m_N_h.svg"
        energy_chart_path = output_dir / f"dp_trial_{normal_level:.0f}m_capacity_energy_fit.svg"
        write_csv(summary_path, summary_rows)
        write_csv(process_path, process_rows)
        plot_relationship(normal_level, summary_rows, chart_path)
        plot_capacity_energy_relationship(normal_level, summary_rows, energy_chart_path)

        print(f"{normal_level:.0f}m 连续DP试算汇总已写入: {summary_path}")
        print(f"{normal_level:.0f}m 连续DP试算过程已写入: {process_path}")
        print(f"{normal_level:.0f}m N-h关系图已写入: {chart_path}")

    combined_summary_path = output_dir / "dp_trial_all_continuous_summary.csv"
    write_csv(combined_summary_path, all_summary_rows)
    print(f"全部方案连续DP汇总已写入: {combined_summary_path}")


if __name__ == "__main__":
    main()
