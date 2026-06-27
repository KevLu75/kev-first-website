from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

RUNOFF_CSV = DATA_DIR / "径流系列表_调整后.csv"
STORAGE_CURVE_CSV = DATA_DIR / "water_level_storage.csv"
DOWNSTREAM_CURVE_CSV = DATA_DIR / "downstream_level_flow.csv"
GUARANTEED_OUTPUT_CSV = OUTPUT_DIR / "guaranteed_output_results.csv"
REQUIRED_CAPACITY_CSV = OUTPUT_DIR / "required_capacity_results.csv"
DEAD_WATER_CSV = OUTPUT_DIR / "dead_water_level_results.csv"
DISPATCH_LINES_CSV = OUTPUT_DIR / "dispatch_chart_lines.csv"

MONTHS = ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"]

# Try multiple repeated-capacity step sizes, in 10k kW.
DELTA_N_OPTIONS_10K_KW = [1.0, 2.0, 5.0, 10.0]
MAX_REPEATED_CAPACITY_10K_KW = 80.0
ECONOMIC_UTILIZATION_HOURS = 2500.0


@dataclass
class Scheme:
    normal_level: float
    dead_level: float
    dead_storage: float
    normal_storage: float
    guaranteed_output_kw: float
    required_capacity_10k_kw: float
    k_output: float
    delta_h: float


@dataclass
class DispatchRule:
    month: str
    prevention_storage: float
    flood_limit_storage: float | None
    auxiliary_storages: tuple[float | None, float | None, float | None]


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


def read_runoff() -> list[tuple[int, list[float]]]:
    runoff: list[tuple[int, list[float]]] = []
    with RUNOFF_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        year_col = reader.fieldnames[0] if reader.fieldnames else ""
        for row in reader:
            if not row.get(year_col):
                continue
            runoff.append((int(float(row[year_col])), [float(row[month]) for month in MONTHS]))
    return runoff


def read_dispatch_rules(
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

            rules.setdefault(normal_level, {})[row["月份"]] = DispatchRule(
                month=row["月份"],
                prevention_storage=float(row["防破坏线库蓄水量_m3s月"]),
                flood_limit_storage=optional_level_to_storage("防洪限制水位_m"),
                auxiliary_storages=(
                    optional_level_to_storage("加大出力辅助线1_m"),
                    optional_level_to_storage("加大出力辅助线2_m"),
                    optional_level_to_storage("加大出力辅助线3_m"),
                ),
            )
    return {
        normal_level: [month_rules[month] for month in MONTHS]
        for normal_level, month_rules in rules.items()
    }


def read_schemes(
    level_points: list[float],
    storage_points: list[float],
) -> list[Scheme]:
    guaranteed: dict[float, dict[str, str]] = {}
    with GUARANTEED_OUTPUT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            guaranteed[float(row["正常蓄水位_m"])] = row

    required: dict[float, dict[str, str]] = {}
    with REQUIRED_CAPACITY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            required[float(row["正常蓄水位_m"])] = row

    schemes: list[Scheme] = []
    with DEAD_WATER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            normal_level = float(row["正常蓄水位_m"])
            dead_level = float(row["死水位_m"])
            g = guaranteed[normal_level]
            r = required[normal_level]
            schemes.append(
                Scheme(
                    normal_level=normal_level,
                    dead_level=dead_level,
                    dead_storage=interpolate(dead_level, level_points, storage_points),
                    normal_storage=interpolate(normal_level, level_points, storage_points),
                    guaranteed_output_kw=float(g["保证出力_kW"]),
                    required_capacity_10k_kw=float(r["必须容量_万kW"]),
                    k_output=float(g["K"]),
                    delta_h=float(g["delta_H_m"]),
                )
            )
    return schemes


def power_for_flow(
    flow: float,
    start_storage: float,
    end_storage: float,
    scheme: Scheme,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    average_storage = (start_storage + end_storage) / 2
    upstream_level = interpolate(average_storage, storage_points, level_points)
    downstream_level = interpolate(flow, downstream_flow_points, downstream_level_points)
    net_head = max(upstream_level - downstream_level - scheme.delta_h, 0.0)
    return scheme.k_output * flow * net_head


def solve_flow_for_power(
    target_power_kw: float,
    start_storage: float,
    inflow: float,
    scheme: Scheme,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    high = max(start_storage + inflow - scheme.dead_storage, 1.0)
    high = min(high, 100000.0)

    def calc(flow: float) -> float:
        end_storage = min(scheme.normal_storage, max(scheme.dead_storage, start_storage + inflow - flow))
        return power_for_flow(
            flow,
            start_storage,
            end_storage,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )

    if calc(high) < target_power_kw:
        return high

    low = 0.0
    for _ in range(70):
        mid = (low + high) / 2
        if calc(mid) < target_power_kw:
            low = mid
        else:
            high = mid
    return high


def calculate_end_storage(start_storage: float, inflow: float, release_flow: float, scheme: Scheme) -> float:
    return min(scheme.normal_storage, max(scheme.dead_storage, start_storage + inflow - release_flow))


def power_for_month(
    release_flow: float,
    start_storage: float,
    inflow: float,
    scheme: Scheme,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> tuple[float, float]:
    end_storage = calculate_end_storage(start_storage, inflow, release_flow, scheme)
    power = power_for_flow(
        release_flow,
        start_storage,
        end_storage,
        scheme,
        level_points,
        storage_points,
        downstream_level_points,
        downstream_flow_points,
    )
    return power, end_storage


def target_power_by_dispatch_zone(
    start_storage: float,
    inflow: float,
    month_index: int,
    installed_kw: float,
    scheme: Scheme,
    dispatch_rules: list[DispatchRule],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    rule = dispatch_rules[month_index]
    guaranteed_kw = scheme.guaranteed_output_kw

    if start_storage <= rule.prevention_storage + 1e-9:
        return min(guaranteed_kw, installed_kw)

    aux1, aux2, aux3 = rule.auxiliary_storages
    if (
        rule.flood_limit_storage is not None
        and aux1 is not None
        and aux2 is not None
        and aux3 is not None
        and start_storage <= rule.flood_limit_storage + 1e-9
    ):
        if start_storage <= aux1:
            fraction = 0.25
        elif start_storage <= aux2:
            fraction = 0.50
        elif start_storage <= aux3:
            fraction = 0.75
        else:
            fraction = 1.00
        return min(guaranteed_kw + (installed_kw - guaranteed_kw) * fraction, installed_kw)

    next_rule = dispatch_rules[(month_index + 1) % len(dispatch_rules)]
    target_end_storage = max(next_rule.prevention_storage, scheme.dead_storage)
    desired_release = max(start_storage + inflow - target_end_storage, 0.0)
    desired_power, _ = power_for_month(
        desired_release,
        start_storage,
        inflow,
        scheme,
        level_points,
        storage_points,
        downstream_level_points,
        downstream_flow_points,
    )
    return min(max(desired_power, guaranteed_kw), installed_kw)


def simulate_dispatch_year_energy(
    flows: list[float],
    installed_capacity_10k_kw: float,
    scheme: Scheme,
    dispatch_rules: list[DispatchRule],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    installed_kw = installed_capacity_10k_kw * 10000
    storage = scheme.normal_storage
    energy_kwh = 0.0

    for month_index, inflow in enumerate(flows):
        target_power_kw = target_power_by_dispatch_zone(
            storage,
            inflow,
            month_index,
            installed_kw,
            scheme,
            dispatch_rules,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        generation_flow = solve_flow_for_power(
            target_power_kw,
            storage,
            inflow,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        month_power, storage = power_for_month(
            generation_flow,
            storage,
            inflow,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        energy_kwh += min(month_power, installed_kw) * 730.0

    return energy_kwh


def average_annual_energy_100m_kwh(
    installed_capacity_10k_kw: float,
    scheme: Scheme,
    runoff: list[tuple[int, list[float]]],
    dispatch_rules: list[DispatchRule],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    year_energies = [
        simulate_dispatch_year_energy(
            flows,
            installed_capacity_10k_kw,
            scheme,
            dispatch_rules,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        for _, flows in runoff
    ]
    return sum(year_energies) / len(year_energies) / 100_000_000


def simulate_year_energy(
    flows: list[float],
    installed_capacity_10k_kw: float,
    scheme: Scheme,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    installed_kw = installed_capacity_10k_kw * 10000
    storage = scheme.normal_storage
    energy_kwh = 0.0

    for inflow in flows:
        available_flow = max(storage + inflow - scheme.dead_storage, 0.0)
        end_if_full_release = calculate_end_storage(storage, inflow, available_flow, scheme)
        max_power = power_for_flow(
            available_flow,
            storage,
            end_if_full_release,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )

        if max_power <= installed_kw:
            generation_flow = available_flow
            month_power = max_power
        else:
            generation_flow = solve_flow_for_power(
                installed_kw,
                storage,
                inflow,
                scheme,
                level_points,
                storage_points,
                downstream_level_points,
                downstream_flow_points,
            )
            month_power = installed_kw

        storage = min(scheme.normal_storage, max(scheme.dead_storage, storage + inflow - generation_flow))
        energy_kwh += month_power * 730.0

    return energy_kwh


def average_annual_energy_without_dispatch_100m_kwh(
    installed_capacity_10k_kw: float,
    scheme: Scheme,
    runoff: list[tuple[int, list[float]]],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    energies = [
        simulate_year_energy(
            flows,
            installed_capacity_10k_kw,
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        for _, flows in runoff
    ]
    return sum(energies) / len(energies) / 100_000_000


def repeated_capacity_rows_for_scheme(
    scheme: Scheme,
    delta_n: float,
    runoff: list[tuple[int, list[float]]],
    dispatch_rules: list[DispatchRule],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> list[list[float | str]]:
    rows: list[list[float | str]] = []
    previous_energy: float | None = None
    repeated = 0.0
    while repeated <= MAX_REPEATED_CAPACITY_10K_KW + 1e-9:
        installed = scheme.required_capacity_10k_kw + repeated
        energy = average_annual_energy_100m_kwh(
            installed,
            scheme,
            runoff,
            dispatch_rules,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        if previous_energy is None:
            delta_energy = ""
            utilization_hours = ""
        else:
            delta_energy = energy - previous_energy
            utilization_hours = delta_energy * 10000 / delta_n
        rows.append(
            [
                scheme.normal_level,
                delta_n,
                scheme.required_capacity_10k_kw,
                repeated,
                installed,
                energy,
                delta_energy,
                utilization_hours,
                "是" if isinstance(utilization_hours, float) and utilization_hours >= ECONOMIC_UTILIZATION_HOURS else "",
            ]
        )
        previous_energy = energy
        repeated += delta_n
    return rows


def write_rows(rows: list[list[float | str]]) -> Path:
    output_path = OUTPUT_DIR / "repeated_capacity_results.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "正常蓄水位_m",
                "重复容量步长_万kW",
                "必须容量_万kW",
                "重复容量_万kW",
                "装机容量_万kW",
                "多年平均年发电量_亿kWh",
                "年发电量差值_亿kWh",
                "利用小时数_h",
                "利用小时数是否不小于2500h",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    round(value, 4) if isinstance(value, float) else value
                    for value in row
                ]
            )
    return output_path


def write_summary(rows: list[list[float | str]]) -> Path:
    grouped: dict[tuple[float, float], list[list[float | str]]] = {}
    for row in rows:
        grouped.setdefault((float(row[0]), float(row[1])), []).append(row)

    output_path = OUTPUT_DIR / "repeated_capacity_summary.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "正常蓄水位_m",
                "重复容量步长_万kW",
                "按首次低于2500h确定的重复容量_万kW",
                "首次低于2500h时重复容量_万kW",
                "首次低于2500h利用小时数_h",
                "全表最大重复容量_万kW",
                "全表最大装机容量_万kW",
                "全表最大多年平均年发电量_亿kWh",
            ]
        )
        for (normal_level, delta_n), group in sorted(grouped.items(), reverse=True):
            previous_repeated = 0.0
            first_bad_repeated = ""
            first_bad_hours = ""
            accepted_repeated = 0.0
            for row in group[1:]:
                repeated = float(row[3])
                hours = row[7]
                if isinstance(hours, float) and hours < ECONOMIC_UTILIZATION_HOURS:
                    first_bad_repeated = repeated
                    first_bad_hours = hours
                    accepted_repeated = previous_repeated
                    break
                previous_repeated = repeated
                accepted_repeated = repeated

            max_row = max(group, key=lambda r: float(r[5]))
            writer.writerow(
                [
                    round(normal_level, 2),
                    round(delta_n, 2),
                    round(accepted_repeated, 4),
                    round(first_bad_repeated, 4) if first_bad_repeated != "" else "",
                    round(first_bad_hours, 4) if first_bad_hours != "" else "",
                    round(float(max_row[3]), 4),
                    round(float(max_row[4]), 4),
                    round(float(max_row[5]), 4),
                ]
            )
    return output_path


def svg_polyline(points: list[tuple[float, float]], color: str, width: float = 2.0) -> str:
    if len(points) < 2:
        return ""
    point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="{width}"/>'


def plot_repeated_capacity_relationship(rows: list[list[float | str]]) -> list[Path]:
    chart_dir = OUTPUT_DIR / "repeated_capacity_charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    colors = {
        1.0: "#1f77b4",
        2.0: "#ff7f0e",
        5.0: "#2ca02c",
        10.0: "#9467bd",
    }

    normal_levels = sorted({float(row[0]) for row in rows}, reverse=True)
    for normal_level in normal_levels:
        scheme_rows = [row for row in rows if float(row[0]) == normal_level and isinstance(row[7], float)]
        points_by_delta: dict[float, list[tuple[float, float]]] = {}
        for row in scheme_rows:
            delta_n = float(row[1])
            repeated_capacity = float(row[3])
            utilization_hours = float(row[7])
            points_by_delta.setdefault(delta_n, []).append((utilization_hours, repeated_capacity))

        all_hours = [hour for points in points_by_delta.values() for hour, _ in points]
        all_repeated = [capacity for points in points_by_delta.values() for _, capacity in points]
        if not all_hours or not all_repeated:
            continue

        x_min = min(min(all_hours), ECONOMIC_UTILIZATION_HOURS) - 300
        x_max = max(max(all_hours), ECONOMIC_UTILIZATION_HOURS) + 300
        y_min = 0.0
        y_max = max(all_repeated) + 5

        width = 980
        height = 560
        left = 90
        right = 170
        top = 50
        bottom = 80
        plot_w = width - left - right
        plot_h = height - top - bottom

        def px(value: float) -> float:
            return left + (value - x_min) / (x_max - x_min) * plot_w

        def py(value: float) -> float:
            return top + (y_max - value) / (y_max - y_min) * plot_h

        elements: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<text x="{width / 2:.0f}" y="28" text-anchor="middle" font-size="20">重复容量-利用小时数关系 - 正常蓄水位 {normal_level:.0f} m</text>',
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

        x_2500 = px(ECONOMIC_UTILIZATION_HOURS)
        elements.append(f'<line x1="{x_2500:.1f}" y1="{top}" x2="{x_2500:.1f}" y2="{height-bottom}" stroke="#d62728" stroke-width="2" stroke-dasharray="6 4"/>')
        elements.append(f'<text x="{x_2500+6:.1f}" y="{top+16}" font-size="12" fill="#d62728">2500h</text>')
        elements.append(f'<text x="{left + plot_w / 2:.0f}" y="{height-28}" text-anchor="middle" font-size="14">利用小时数 (h)</text>')
        elements.append(f'<text x="24" y="{height/2:.0f}" transform="rotate(-90 24,{height/2:.0f})" text-anchor="middle" font-size="14">重复容量 N (万kW)</text>')

        legend_x = width - right + 35
        legend_y = 82
        for index, delta_n in enumerate(sorted(points_by_delta)):
            color = colors.get(delta_n, "#333333")
            points = [(px(hour), py(capacity)) for hour, capacity in points_by_delta[delta_n]]
            elements.append(svg_polyline(points, color, 2.2))
            for x, y in points:
                elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="{color}"/>')
            y = legend_y + index * 24
            elements.append(svg_polyline([(legend_x, y), (legend_x + 34, y)], color, 2.2))
            elements.append(f'<text x="{legend_x+42}" y="{y+4}" font-size="13">delta_N={delta_n:g}</text>')

        elements.append("</svg>")
        path = chart_dir / f"repeated_capacity_hours_{normal_level:.0f}m.svg"
        path.write_text("\n".join(elements), encoding="utf-8")
        paths.append(path)

    return paths


def main() -> None:
    level_points, storage_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = read_curve(
        DOWNSTREAM_CURVE_CSV, "下游水位_m", "流量_m3每秒"
    )
    runoff = read_runoff()
    schemes = read_schemes(level_points, storage_points)
    dispatch_rules_by_level = read_dispatch_rules(level_points, storage_points)

    rows: list[list[float | str]] = []
    for scheme in schemes:
        for delta_n in DELTA_N_OPTIONS_10K_KW:
            rows.extend(
                repeated_capacity_rows_for_scheme(
                    scheme,
                    delta_n,
                    runoff,
                    dispatch_rules_by_level[scheme.normal_level],
                    level_points,
                    storage_points,
                    downstream_level_points,
                    downstream_flow_points,
                )
            )

    output_path = write_rows(rows)
    summary_path = write_summary(rows)
    chart_paths = plot_repeated_capacity_relationship(rows)
    print(f"重复容量计算结果已写入: {output_path}")
    print(f"重复容量汇总已写入: {summary_path}")
    for path in chart_paths:
        print(f"关系图已写入: {path}")


if __name__ == "__main__":
    main()
