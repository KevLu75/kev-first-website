from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

STORAGE_CURVE_CSV = DATA_DIR / "water_level_storage.csv"
DOWNSTREAM_CURVE_CSV = DATA_DIR / "downstream_level_flow.csv"
RUNOFF_CSV = DATA_DIR / "径流系列表_调整后.csv"
DEAD_WATER_RESULTS_CSV = OUTPUT_DIR / "dead_water_level_results.csv"
GUARANTEED_OUTPUT_CSV = OUTPUT_DIR / "guaranteed_output_results.csv"
SUPPLY_PERIODS_CSV = OUTPUT_DIR / "dead_water_level_supply_periods.csv"
ANNUAL_OUTPUT_FREQUENCY_CSV = OUTPUT_DIR / "guaranteed_output_annual_frequency.csv"

MONTHS = ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"]
CHART_MONTH_LABELS = ["3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"]
DESIGN_GUARANTEE_RATE = 87.5
FLOOD_LIMIT_STORAGE_MONTH = "8月"
FLOOD_LIMIT_PLOT_LABEL = "7月"


@dataclass
class Scheme:
    normal_level: float
    dead_level: float
    normal_storage: float
    dead_storage: float
    guaranteed_output_kw: float
    k_output: float
    delta_h: float


@dataclass
class SupplyPeriod:
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


def read_runoff(path: Path) -> dict[int, list[float]]:
    runoff: dict[int, list[float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        year_col = reader.fieldnames[0] if reader.fieldnames else ""
        for row in reader:
            if not row.get(year_col):
                continue
            year = int(float(row[year_col]))
            runoff[year] = [float(row[month]) for month in MONTHS]
    return runoff


def read_schemes(
    level_points: list[float],
    storage_points: list[float],
) -> list[Scheme]:
    guaranteed_by_level: dict[float, dict[str, str]] = {}
    with GUARANTEED_OUTPUT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            guaranteed_by_level[float(row["正常蓄水位_m"])] = row

    schemes: list[Scheme] = []
    with DEAD_WATER_RESULTS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            normal_level = float(row["正常蓄水位_m"])
            dead_level = float(row["死水位_m"])
            guaranteed = guaranteed_by_level[normal_level]
            schemes.append(
                Scheme(
                    normal_level=normal_level,
                    dead_level=dead_level,
                    normal_storage=interpolate(normal_level, level_points, storage_points),
                    dead_storage=interpolate(dead_level, level_points, storage_points),
                    guaranteed_output_kw=float(guaranteed["保证出力_kW"]),
                    k_output=float(guaranteed["K"]),
                    delta_h=float(guaranteed["delta_H_m"]),
                )
            )
    return schemes


def read_supply_periods() -> dict[tuple[float, int], SupplyPeriod]:
    periods: dict[tuple[float, int], SupplyPeriod] = {}
    with SUPPLY_PERIODS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            periods[(float(row["正常蓄水位_m"]), int(row["年份"]))] = SupplyPeriod(
                start_month=row["供水期初"],
                end_month=row["供水期末"],
                label=row["供水期"],
            )
    return periods


def read_selected_years(runoff: dict[int, list[float]], normal_levels: list[float]) -> dict[float, set[int]]:
    selected: dict[float, set[int]] = {}
    with ANNUAL_OUTPUT_FREQUENCY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if float(row["经验频率_%"]) <= DESIGN_GUARANTEE_RATE:
                selected.setdefault(float(row["正常蓄水位_m"]), set()).add(int(row["年份"]))
    return selected


def supply_month_indices(start_month: str, end_month: str) -> list[int]:
    start = MONTHS.index(start_month)
    end = MONTHS.index(end_month)
    if start <= end:
        return list(range(start, end + 1))
    return list(range(start, len(MONTHS))) + list(range(0, end + 1))


def solve_reverse_generation_flow(
    target_output_kw: float,
    end_storage: float,
    inflow: float,
    scheme: Scheme,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> float:
    max_flow = max(inflow + scheme.normal_storage - end_storage, 0.0)

    def output_for_flow(flow: float) -> float:
        start_storage = min(max(end_storage - inflow + flow, scheme.dead_storage), scheme.normal_storage)
        average_storage = (start_storage + end_storage) / 2
        upstream_level = interpolate(average_storage, storage_points, level_points)
        downstream_level = interpolate(flow, downstream_flow_points, downstream_level_points)
        net_head = upstream_level - downstream_level - scheme.delta_h
        return scheme.k_output * flow * max(net_head, 0.0)

    max_output = output_for_flow(max_flow)
    if max_output < target_output_kw:
        return max_flow

    flow = min(max(target_output_kw / max(scheme.k_output * 50.0, 1.0), 0.0), max_flow)
    for _ in range(100):
        start_storage = min(max(end_storage - inflow + flow, scheme.dead_storage), scheme.normal_storage)
        average_storage = (start_storage + end_storage) / 2
        upstream_level = interpolate(average_storage, storage_points, level_points)
        downstream_level = interpolate(flow, downstream_flow_points, downstream_level_points)
        net_head = max(upstream_level - downstream_level - scheme.delta_h, 1e-6)
        calculated_output = scheme.k_output * flow * net_head
        if abs(calculated_output - target_output_kw) < 1e-3:
            return min(max(flow, 0.0), max_flow)

        flow += (target_output_kw - calculated_output) / (scheme.k_output * net_head)
        flow = min(max(flow, 0.0), max_flow)

    # If the correction loop stalls near a nonlinear tail, fall back to a narrow
    # bracket for robustness while preserving the class-note iteration as primary.
    low, high = 0.0, max_flow
    for _ in range(40):
        mid = (low + high) / 2
        if output_for_flow(mid) < target_output_kw:
            low = mid
        else:
            high = mid
    return high


def reverse_late_storage_line(
    flows: list[float],
    period: SupplyPeriod,
    scheme: Scheme,
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> dict[int, float]:
    storage_at_month_start: dict[int, float] = {}
    current_end_storage = scheme.dead_storage
    end_index = MONTHS.index(period.end_month)
    reverse_indices = [(end_index - i) % len(MONTHS) for i in range(len(MONTHS))]

    for index in reverse_indices:
        generation_flow = solve_reverse_generation_flow(
            scheme.guaranteed_output_kw,
            current_end_storage,
            flows[index],
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        start_storage = min(max(current_end_storage - flows[index] + generation_flow, scheme.dead_storage), scheme.normal_storage)
        storage_at_month_start[index] = start_storage
        current_end_storage = start_storage

    return storage_at_month_start


def build_dispatch_lines(
    scheme: Scheme,
    runoff: dict[int, list[float]],
    periods: dict[tuple[float, int], SupplyPeriod],
    selected_years: set[int],
    level_points: list[float],
    storage_points: list[float],
    downstream_level_points: list[float],
    downstream_flow_points: list[float],
) -> list[dict[str, float | str]]:
    envelope_storage: dict[int, float] = {}

    for year in selected_years:
        line = reverse_late_storage_line(
            runoff[year],
            periods[(scheme.normal_level, year)],
            scheme,
            level_points,
            storage_points,
            downstream_level_points,
            downstream_flow_points,
        )
        for index, storage in line.items():
            envelope_storage[index] = max(envelope_storage.get(index, scheme.dead_storage), storage)

    rows: list[dict[str, float | str]] = []
    for index in range(len(MONTHS)):
        envelope_storage.setdefault(index, scheme.dead_storage)

    flood_limit_storage_index = MONTHS.index(FLOOD_LIMIT_STORAGE_MONTH)
    flood_limit_plot_index = CHART_MONTH_LABELS.index(FLOOD_LIMIT_PLOT_LABEL)
    flood_limit_storage = envelope_storage[flood_limit_storage_index]
    flood_limit_level = interpolate(flood_limit_storage, storage_points, level_points)
    prevention_levels = [
        interpolate(envelope_storage[index], storage_points, level_points)
        for index in range(len(MONTHS))
    ]

    for i, month in enumerate(MONTHS):
        prevention_storage = envelope_storage[i]
        prevention_level = prevention_levels[i]
        flood_control_level = min(scheme.normal_level, max(prevention_level, flood_limit_level))
        show_flood_lines = i <= flood_limit_plot_index
        rows.append(
            {
                "正常蓄水位_m": scheme.normal_level,
                "月份": month,
                "防破坏线有效蓄水量_m3s月": prevention_storage - scheme.dead_storage,
                "防破坏线库蓄水量_m3s月": prevention_storage,
                "防破坏线水位_m": prevention_level,
                "防洪限制水位_m": flood_limit_level if show_flood_lines else "",
                "加大出力辅助线1_m": prevention_level + (flood_control_level - prevention_level) * 1 / 4 if show_flood_lines else "",
                "加大出力辅助线2_m": prevention_level + (flood_control_level - prevention_level) * 2 / 4 if show_flood_lines else "",
                "加大出力辅助线3_m": prevention_level + (flood_control_level - prevention_level) * 3 / 4 if show_flood_lines else "",
                "正常蓄水位_m_线": scheme.normal_level,
            }
        )
    return rows


def write_dispatch_lines(rows: list[dict[str, float | str]]) -> Path:
    output_path = OUTPUT_DIR / "dispatch_chart_lines.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "正常蓄水位_m",
            "月份",
            "防破坏线有效蓄水量_m3s月",
            "防破坏线库蓄水量_m3s月",
            "防破坏线水位_m",
            "防洪限制水位_m",
            "加大出力辅助线1_m",
            "加大出力辅助线2_m",
            "加大出力辅助线3_m",
            "正常蓄水位_m_线",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (round(value, 3) if isinstance(value, float) else value)
                    for key, value in row.items()
                }
            )
    return output_path


def svg_polyline(points: list[tuple[float, float]], color: str, width: float = 2.0, dash: bool = False) -> str:
    if len(points) < 2:
        return ""
    dash_attr = ' stroke-dasharray="6 4"' if dash else ""
    point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="{width}"{dash_attr}/>'


def plot_dispatch_charts(rows: list[dict[str, float | str]]) -> list[Path]:
    chart_dir = OUTPUT_DIR / "dispatch_charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    levels = sorted({float(row["正常蓄水位_m"]) for row in rows}, reverse=True)

    for normal_level in levels:
        scheme_rows = [row for row in rows if float(row["正常蓄水位_m"]) == normal_level]
        def optional_series(column: str) -> list[float | None]:
            values: list[float | None] = []
            for row in scheme_rows:
                value = row[column]
                values.append(float(value) if value != "" else None)
            return values

        prevention_values = [float(row["防破坏线水位_m"]) for row in scheme_rows]
        dead_level = min(prevention_values)
        series = {
            "防破坏线": ("#1f77b4", False, prevention_values + [dead_level]),
            "辅助线1": ("#ff7f0e", True, optional_series("加大出力辅助线1_m") + [None]),
            "辅助线2": ("#2ca02c", True, optional_series("加大出力辅助线2_m") + [None]),
            "辅助线3": ("#9467bd", True, optional_series("加大出力辅助线3_m") + [None]),
            "防洪限制水位": ("#d62728", False, optional_series("防洪限制水位_m") + [None]),
            "正常蓄水位": ("#111111", False, [float(row["正常蓄水位_m_线"]) for row in scheme_rows] + [float(scheme_rows[0]["正常蓄水位_m_线"])]),
        }
        all_values = [value for _, _, values in series.values() for value in values if value is not None]
        y_min = min(all_values) - 2
        y_max = max(all_values) + 2
        width = 980
        height = 560
        left = 70
        right = 30
        top = 50
        bottom = 70
        plot_w = width - left - right
        plot_h = height - top - bottom

        def px(index: int) -> float:
            return left + plot_w * index / (len(CHART_MONTH_LABELS) - 1)

        def py(value: float) -> float:
            return top + (y_max - value) / (y_max - y_min) * plot_h

        elements: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<text x="{width / 2:.0f}" y="28" text-anchor="middle" font-size="20">调度图线 - 正常蓄水位 {normal_level:.0f} m（3月至次年3月）</text>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#444"/>',
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#444"/>',
        ]
        for tick in range(6):
            value = y_min + (y_max - y_min) * tick / 5
            y = py(value)
            elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#ddd"/>')
            elements.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12">{value:.1f}</text>')
        for index, month in enumerate(CHART_MONTH_LABELS):
            x = px(index)
            elements.append(f'<text x="{x:.1f}" y="{height-bottom+24}" text-anchor="middle" font-size="13">{month}</text>')
        elements.append(f'<text x="22" y="{height/2:.0f}" transform="rotate(-90 22,{height/2:.0f})" text-anchor="middle" font-size="14">水位 (m)</text>')

        legend_x = width - 170
        legend_y = 62
        for idx, (name, (color, dash, values)) in enumerate(series.items()):
            segment: list[tuple[float, float]] = []
            for i, value in enumerate(values):
                if value is None:
                    elements.append(svg_polyline(segment, color, 2.5 if name in {"防破坏线", "防洪限制水位"} else 1.8, dash))
                    segment = []
                else:
                    segment.append((px(i), py(value)))
            elements.append(svg_polyline(segment, color, 2.5 if name in {"防破坏线", "防洪限制水位"} else 1.8, dash))
            y = legend_y + idx * 22
            elements.append(svg_polyline([(legend_x, y), (legend_x + 34, y)], color, 2.5, dash))
            elements.append(f'<text x="{legend_x+42}" y="{y+4}" font-size="13">{name}</text>')
        elements.append("</svg>")

        path = chart_dir / f"dispatch_chart_{normal_level:.0f}m.svg"
        path.write_text("\n".join(elements), encoding="utf-8")
        paths.append(path)
    return paths


def main() -> None:
    level_points, storage_points = read_curve(STORAGE_CURVE_CSV, "水位_m", "库容_m3每秒月")
    downstream_level_points, downstream_flow_points = read_curve(
        DOWNSTREAM_CURVE_CSV, "下游水位_m", "流量_m3每秒"
    )
    runoff = read_runoff(RUNOFF_CSV)
    schemes = read_schemes(level_points, storage_points)
    periods = read_supply_periods()
    selected_years = read_selected_years(runoff, [scheme.normal_level for scheme in schemes])

    rows: list[dict[str, float | str]] = []
    for scheme in schemes:
        rows.extend(
            build_dispatch_lines(
                scheme,
                runoff,
                periods,
                selected_years[scheme.normal_level],
                level_points,
                storage_points,
                downstream_level_points,
                downstream_flow_points,
            )
        )

    csv_path = write_dispatch_lines(rows)
    chart_paths = plot_dispatch_charts(rows)
    print(f"调度图线成果已写入: {csv_path}")
    for path in chart_paths:
        print(f"调度图已写入: {path}")


if __name__ == "__main__":
    main()
