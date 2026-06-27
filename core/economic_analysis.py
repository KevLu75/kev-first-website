from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from flood_routing import interpolate, read_curve


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
STORAGE_CURVE_CSV = PROJECT_ROOT / "data" / "water_level_storage.csv"
INSTALLED_CAPACITY_CSV = OUTPUT_DIR / "installed_capacity_summary.csv"
FLOOD_ROUTING_SUMMARY_CSV = OUTPUT_DIR / "flood_routing" / "flood_routing_summary.csv"

ECONOMIC_DIR = OUTPUT_DIR / "economic_analysis"
COMPARISON_CSV = ECONOMIC_DIR / "economic_comparison.csv"
CASHFLOW_CSV = ECONOMIC_DIR / "economic_cashflow.csv"
ASSUMPTIONS_CSV = ECONOMIC_DIR / "economic_assumptions.csv"
COMPONENTS_CSV = ECONOMIC_DIR / "economic_components.csv"
TABLE_DIR = ECONOMIC_DIR / "scheme_tables"

DISCOUNT_RATE = 0.10
HYDRO_LIFE_YEARS = 50
THERMAL_LIFE_YEARS = 25
CONSTRUCTION_END_YEAR = 11


@dataclass(frozen=True)
class SchemeEconomicData:
    normal_level: float
    dam_height: float
    permanent_investment: float
    other_investment: float
    compensation: float
    hydro_operation_unit_yuan_per_kw: float
    hydro_repair_civil: float
    hydro_repair_house: float
    compensation_annual_charge: float
    fengtang_capacity_loss: float
    fengtang_energy_loss: float
    total_investment_distribution: list[float]
    compensation_distribution: list[float]


SCHEMES: dict[float, SchemeEconomicData] = {
    120.0: SchemeEconomicData(
        120.0,
        104.0,
        61850.0,
        71333.0,
        80000.0,
        2.0,
        352.6,
        17.7,
        1328.0,
        0.284,
        0.228,
        [0.127, 0.120, 0.081, 0.108, 0.070, 0.113, 0.145, 0.115, 0.097, 0.021, 0.003 - 0.204],
        [0.0, 0.125, 0.125, 0.167, 0.163, 0.163, 0.129, 0.128, 0.0, 0.0, 0.0],
    ),
    115.0: SchemeEconomicData(
        115.0,
        94.5,
        56356.0,
        65816.0,
        57093.0,
        2.0,
        319.0,
        17.5,
        974.7,
        0.02,
        0.0,
        [0.0, 0.125, 0.118, 0.085, 0.144, 0.054, 0.121, 0.133, 0.144, 0.053, 0.023 - 0.206],
        [0.0, 0.05, 0.10, 0.20, 0.25, 0.20, 0.20, 0.0, 0.0, 0.0, 0.0],
    ),
    108.0: SchemeEconomicData(
        108.0,
        87.5,
        53817.0,
        62854.0,
        38547.0,
        2.2,
        306.7,
        17.4,
        647.6,
        0.0,
        0.0,
        [0.0, 0.128, 0.118, 0.091, 0.130, 0.072, 0.124, 0.121, 0.107, 0.055, 0.054 - 0.209],
        [0.0, 0.05, 0.10, 0.20, 0.25, 0.20, 0.20, 0.0, 0.0, 0.0, 0.0],
    ),
    100.0: SchemeEconomicData(
        100.0,
        78.5,
        21019.0,
        56028.0,
        24989.0,
        2.3,
        283.3,
        17.1,
        442.3,
        0.0,
        0.0,
        [0.0, 0.131, 0.125, 0.096, 0.136, 0.073, 0.133, 0.148, 0.102, 0.045, 0.011 - 0.220],
        [0.0, 0.05, 0.10, 0.20, 0.25, 0.20, 0.20, 0.0, 0.0, 0.0, 0.0],
    ),
}

MECH_INVESTMENT_POINTS = [(92.0, 18190.0), (110.0, 25808.0), (150.0, 27981.0), (175.0, 28805.0)]
MECH_REPAIR_POINTS = [(92.0, 355.9), (110.0, 441.0), (150.0, 477.0), (175.0, 489.7)]
PERMANENT_INVESTMENT_POINTS = [(78.5, 21019.0), (87.5, 53817.0), (94.5, 56356.0), (104.0, 61850.0)]
CIVIL_REPAIR_POINTS = [(78.5, 283.3), (87.5, 306.7), (94.5, 319.0), (104.0, 352.6)]
DAM_BOTTOM_LEVEL = 30.0

THERMAL_PLANT_DISTRIBUTION = {8: 0.55, 9: 0.40, 10: 0.03, 11: 0.02}
COAL_MINE_DISTRIBUTION = {6: 0.16, 7: 0.34, 8: 0.35, 9: 0.10, 10: 0.05}
INITIAL_OPERATION_FRACTIONS = {9: 0.20, 10: 0.70, 11: 0.90}
HISTORICAL_REQUIRED_FLOOD_STORAGE = [15.2, 13.6, 10.1, 6.5, 6.2, 2.31, 1.38, 0.31]


def capital_recovery_factor(rate: float, years: int) -> float:
    factor = (1.0 + rate) ** years
    return rate * factor / (factor - 1.0)


def interpolate_points(x: float, points: list[tuple[float, float]]) -> float:
    points = sorted(points)
    if x <= points[0][0]:
        x0, y0 = points[0]
        x1, y1 = points[1]
        return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    if x >= points[-1][0]:
        x0, y0 = points[-2]
        x1, y1 = points[-1]
        return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    for index in range(1, len(points)):
        if x <= points[index][0]:
            x0, y0 = points[index - 1]
            x1, y1 = points[index]
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    raise RuntimeError("Interpolation failed")


def read_installed_capacity() -> dict[float, dict[str, float]]:
    rows: dict[float, dict[str, float]] = {}
    with INSTALLED_CAPACITY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            level = float(row["正常蓄水位_m"])
            rows[level] = {
                "必须容量_万kW": float(row["必须容量_万kW"]),
                "装机容量_万kW": float(row["装机容量_万kW"]),
                "多年平均电能_亿kWh": float(row["多年平均电能_亿kWh"]),
            }
    return rows


def read_flood_summary() -> dict[float, dict[str, float]]:
    rows: dict[float, dict[str, float]] = {}
    with FLOOD_ROUTING_SUMMARY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            level = float(row["正常蓄水位_m"])
            rows[level] = {
                "防洪限制水位_m": float(row["防洪限制水位_m"]),
                "防洪高水位_m": float(row["防洪高水位_m"]),
                "坝顶高程_m": float(row["坝顶高程_m"]),
            }
    return rows


def flood_benefit_10k_yuan(
    normal_level: float,
    flood_limit_level: float,
    flood_high_level: float,
    level_points: list[float],
    storage_100m_points: list[float],
) -> tuple[float, float, float, list[dict[str, float]]]:
    flood_limit_storage = interpolate(flood_limit_level, level_points, storage_100m_points)
    flood_high_storage = interpolate(flood_high_level, level_points, storage_100m_points)
    flood_control_storage = max(flood_high_storage - flood_limit_storage, 0.0)
    sorted_storages = sorted(HISTORICAL_REQUIRED_FLOOD_STORAGE, reverse=True)
    sample_count = len(sorted_storages)
    empirical = [
        (rank / (sample_count + 1) * 100.0, storage)
        for rank, storage in enumerate(sorted_storages, start=1)
    ]
    mean_p = sum(probability for probability, _ in empirical) / sample_count
    mean_w = sum(storage for _, storage in empirical) / sample_count
    fit_slope = sum(
        (probability - mean_p) * (storage - mean_w)
        for probability, storage in empirical
    ) / sum((probability - mean_p) ** 2 for probability, _ in empirical)
    fit_intercept = mean_w - fit_slope * mean_p
    original_zero_probability = -fit_intercept / fit_slope
    probabilities = sorted(
        {
            0.0,
            5.0,
            original_zero_probability,
            *[probability for probability, _ in empirical if probability < original_zero_probability],
        }
    )
    frequency_rows: list[dict[str, float]] = []
    for probability in probabilities:
        storage = max(fit_slope * probability + fit_intercept, 0.0)
        shifted_storage = max(storage - flood_control_storage, 0.0) if probability <= 5.0 else 0.0
        frequency_rows.append(
            {
                "正常蓄水位_m": normal_level,
                "频率_%": probability,
                "原拦洪量_亿m3": storage,
                "平移后拦洪量_亿m3": shifted_storage,
                "减少拦洪量_亿m3": storage - shifted_storage,
            }
        )
        if abs(probability - 5.0) < 1e-9:
            frequency_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "频率_%": 5.0,
                    "原拦洪量_亿m3": storage,
                    "平移后拦洪量_亿m3": 0.0,
                    "减少拦洪量_亿m3": storage,
                }
            )
    area = 0.0
    for previous, current in zip(frequency_rows, frequency_rows[1:]):
        width = current["频率_%"] - previous["频率_%"]
        area += width * (previous["减少拦洪量_亿m3"] + current["减少拦洪量_亿m3"]) / 2.0
    average_reduced_storage = area / 100.0
    reduced_farmland_10k_mu = 5.0 + 1.132 * average_reduced_storage
    benefit = 1000.0 * reduced_farmland_10k_mu
    plot_flood_benefit_frequency(
        normal_level,
        flood_control_storage,
        empirical,
        frequency_rows,
        fit_slope,
        fit_intercept,
    )
    return flood_control_storage, average_reduced_storage, benefit, frequency_rows


def plot_flood_benefit_frequency(
    normal_level: float,
    flood_control_storage: float,
    empirical: list[tuple[float, float]],
    rows: list[dict[str, float]],
    fit_slope: float,
    fit_intercept: float,
) -> None:
    chart_dir = ECONOMIC_DIR / "flood_benefit_charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    width, height = 920, 560
    left, right, top, bottom = 82, 34, 52, 76
    plot_w, plot_h = width - left - right, height - top - bottom
    original_zero_probability = -fit_intercept / fit_slope
    y_max = fit_intercept * 1.08

    def px(value: float) -> float:
        return left + value / 100.0 * plot_w

    def py(value: float) -> float:
        return top + (y_max - value) / y_max * plot_h

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2:.0f}" y="29" text-anchor="middle" font-size="20">{normal_level:.0f}m方案 拦洪量频率曲线及防洪库容平移</text>',
    ]
    for tick in range(6):
        probability = 100.0 * tick / 5
        storage = y_max * tick / 5
        elements.append(f'<line x1="{px(probability):.1f}" y1="{top}" x2="{px(probability):.1f}" y2="{height-bottom}" stroke="#e5e7eb"/>')
        elements.append(f'<text x="{px(probability):.1f}" y="{height-bottom+23}" text-anchor="middle" font-size="12">{probability:.0f}</text>')
        elements.append(f'<line x1="{left}" y1="{py(storage):.1f}" x2="{width-right}" y2="{py(storage):.1f}" stroke="#e5e7eb"/>')
        elements.append(f'<text x="{left-9}" y="{py(storage)+4:.1f}" text-anchor="end" font-size="12">{storage:.1f}</text>')
    original = [(px(0.0), py(fit_intercept)), (px(original_zero_probability), py(0.0))]
    shifted_at_0 = max(fit_intercept - flood_control_storage, 0.0)
    shifted_at_5 = max(fit_slope * 5.0 + fit_intercept - flood_control_storage, 0.0)
    shifted = [(px(0.0), py(shifted_at_0)), (px(5.0), py(shifted_at_5)), (px(5.0), py(0.0))]
    area_boundary = [
        original[0],
        original[1],
        (px(5.0), py(0.0)),
        (px(5.0), py(shifted_at_5)),
        (px(0.0), py(shifted_at_0)),
    ]
    area_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in area_boundary)
    original_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in original)
    shifted_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in shifted)
    elements.append(f'<polygon points="{area_points}" fill="#0f6b8f" opacity="0.14"/>')
    elements.append(f'<polyline points="{original_text}" fill="none" stroke="#0f6b8f" stroke-width="2.5"/>')
    elements.append(f'<polyline points="{shifted_text}" fill="none" stroke="#f97316" stroke-width="2.5"/>')
    for probability, storage in empirical:
        elements.append(f'<circle cx="{px(probability):.1f}" cy="{py(storage):.1f}" r="3.5" fill="#111827"/>')
    elements.extend([
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#64748b"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#64748b"/>',
        f'<text x="{width/2:.0f}" y="{height-25}" text-anchor="middle" font-size="14">频率 P (%)</text>',
        f'<text x="24" y="{height/2:.0f}" transform="rotate(-90 24,{height/2:.0f})" text-anchor="middle" font-size="14">拦洪量 (亿m3)</text>',
        f'<text x="{left+12}" y="{top+20}" font-size="12" fill="#475569">建库前一次最小二乘拟合：W={fit_slope:.4f}P+{fit_intercept:.4f}</text>',
        f'<text x="{left+12}" y="{top+38}" font-size="12" fill="#475569">防洪库容 ΔV={flood_control_storage:.3f} 亿m3；平移曲线在P=5%处竖直截断</text>',
        '</svg>',
    ])
    (chart_dir / f"flood_benefit_frequency_{normal_level:.0f}m.svg").write_text("\n".join(elements), encoding="utf-8")


def future_value_at_construction_end(amount: float, year: int) -> float:
    return amount * (1.0 + DISCOUNT_RATE) ** (CONSTRUCTION_END_YEAR - year)


def blank_years() -> dict[int, float]:
    return {year: 0.0 for year in range(1, CONSTRUCTION_END_YEAR + 1)}


def future_value_sum(year_values: dict[int, float]) -> float:
    return sum(future_value_at_construction_end(value, year) for year, value in year_values.items())


def percent_row(name: str, distribution: list[float] | dict[int, float], normal_value: float | str = "") -> dict[str, float | str]:
    row: dict[str, float | str] = {"项目": name}
    if isinstance(distribution, list):
        values = {year: distribution[year - 1] for year in range(1, len(distribution) + 1)}
    else:
        values = distribution
    for year in range(1, CONSTRUCTION_END_YEAR + 1):
        row[f"第{year}年"] = values.get(year, 0.0)
    row["正常运行期年值"] = normal_value
    row["折算到施工期末_万元"] = ""
    row["化算到正常运行期年费_万元"] = ""
    return row


def amount_row(
    name: str,
    year_values: dict[int, float],
    normal_value: float | str = "",
    annualized: bool = True,
    annualization_years: int = HYDRO_LIFE_YEARS,
) -> dict[str, float | str]:
    construction_end_value = future_value_sum(year_values)
    row: dict[str, float | str] = {"项目": name}
    for year in range(1, CONSTRUCTION_END_YEAR + 1):
        row[f"第{year}年"] = year_values.get(year, 0.0)
    row["正常运行期年值"] = normal_value
    row["折算到施工期末_万元"] = construction_end_value
    row["化算到正常运行期年费_万元"] = construction_end_value * capital_recovery_factor(DISCOUNT_RATE, annualization_years) if annualized else ""
    return row


def write_scheme_table(path: Path, rows: list[dict[str, float | str]]) -> None:
    fieldnames = ["项目", *[f"第{year}年" for year in range(1, CONSTRUCTION_END_YEAR + 1)], "正常运行期年值", "折算到施工期末_万元", "化算到正常运行期年费_万元"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()})


def main() -> None:
    ECONOMIC_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    level_points, _, storage_100m_points = read_curve(STORAGE_CURVE_CSV)
    installed = read_installed_capacity()
    flood_summary = read_flood_summary()
    hydro_annualization = capital_recovery_factor(DISCOUNT_RATE, HYDRO_LIFE_YEARS)
    thermal_annualization = capital_recovery_factor(DISCOUNT_RATE, THERMAL_LIFE_YEARS)

    baseline = installed[120.0]
    baseline_net_capacity = baseline["必须容量_万kW"] - SCHEMES[120.0].fengtang_capacity_loss
    baseline_net_energy = baseline["多年平均电能_亿kWh"] - SCHEMES[120.0].fengtang_energy_loss

    comparison_rows: list[dict[str, float | str]] = []
    cashflow_rows: list[dict[str, float | int | str]] = []
    assumptions_rows: list[dict[str, float | str]] = []
    components_rows: list[dict[str, float | str]] = []
    flood_frequency_rows: list[dict[str, float]] = []

    for normal_level in sorted(SCHEMES, reverse=True):
        data = SCHEMES[normal_level]
        installed_row = installed[normal_level]
        installed_capacity = installed_row["装机容量_万kW"]
        required_capacity = installed_row["必须容量_万kW"]
        energy = installed_row["多年平均电能_亿kWh"]
        net_capacity = required_capacity - data.fengtang_capacity_loss
        net_energy = energy - data.fengtang_energy_loss

        mech_investment = interpolate_points(installed_capacity, MECH_INVESTMENT_POINTS)
        mech_repair = interpolate_points(installed_capacity, MECH_REPAIR_POINTS)
        max_dam_height = flood_summary[normal_level]["坝顶高程_m"] - DAM_BOTTOM_LEVEL
        permanent_investment = interpolate_points(max_dam_height, PERMANENT_INVESTMENT_POINTS)
        civil_repair = interpolate_points(max_dam_height, CIVIL_REPAIR_POINTS)
        hydro_project_investment = permanent_investment + data.other_investment + mech_investment

        hydro_operation = installed_capacity * data.hydro_operation_unit_yuan_per_kw
        hydro_repair = civil_repair + data.hydro_repair_house + mech_repair
        hydro_normal_operation = hydro_operation + hydro_repair + data.compensation_annual_charge

        replacement_capacity = max(baseline_net_capacity - net_capacity, 0.0)
        replacement_energy = max(baseline_net_energy - net_energy, 0.0)
        thermal_plant_investment = 825.0 * replacement_capacity
        coal_mine_investment = 735.0 * replacement_energy
        thermal_operation = 0.08 * thermal_plant_investment
        thermal_fuel = 210.0 * replacement_energy

        flood_control_storage, average_reduced_storage, flood_benefit, frequency_rows = flood_benefit_10k_yuan(
            normal_level,
            flood_summary[normal_level]["防洪限制水位_m"],
            flood_summary[normal_level]["防洪高水位_m"],
            level_points,
            storage_100m_points,
        )
        flood_frequency_rows.extend(frequency_rows)

        construction_end_value = 0.0
        thermal_plant_construction_end_value = 0.0
        hydro_investment_years = blank_years()
        for index, share in enumerate(data.total_investment_distribution, start=1):
            amount = hydro_project_investment * share
            hydro_investment_years[index] = amount
            construction_end_value += future_value_at_construction_end(amount, index)
            cashflow_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "年份": index,
                    "项目": "永久机电临时投资",
                    "金额_万元": amount,
                    "折算至施工期末_万元": future_value_at_construction_end(amount, index),
                }
            )

        compensation_years = blank_years()
        for index, share in enumerate(data.compensation_distribution, start=1):
            if share == 0:
                continue
            amount = data.compensation * share
            compensation_years[index] = amount
            construction_end_value += future_value_at_construction_end(amount, index)
            cashflow_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "年份": index,
                    "项目": "水库补偿投资",
                    "金额_万元": amount,
                    "折算至施工期末_万元": future_value_at_construction_end(amount, index),
                }
            )

        thermal_plant_years = blank_years()
        for year, share in THERMAL_PLANT_DISTRIBUTION.items():
            amount = thermal_plant_investment * share
            thermal_plant_years[year] = amount
            folded_amount = future_value_at_construction_end(amount, year)
            construction_end_value += folded_amount
            thermal_plant_construction_end_value += folded_amount
            cashflow_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "年份": year,
                    "项目": "替代火电站投资",
                    "金额_万元": amount,
                    "折算至施工期末_万元": future_value_at_construction_end(amount, year),
                }
            )

        coal_mine_years = blank_years()
        for year, share in COAL_MINE_DISTRIBUTION.items():
            amount = coal_mine_investment * share
            coal_mine_years[year] = amount
            construction_end_value += future_value_at_construction_end(amount, year)
            cashflow_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "年份": year,
                    "项目": "煤矿额外投资",
                    "金额_万元": amount,
                    "折算至施工期末_万元": future_value_at_construction_end(amount, year),
                }
            )

        hydro_initial_operation_years = blank_years()
        thermal_initial_operation_years = blank_years()
        for year, fraction in INITIAL_OPERATION_FRACTIONS.items():
            amount = hydro_normal_operation * fraction
            hydro_initial_operation_years[year] = amount
            construction_end_value += future_value_at_construction_end(amount, year)
            cashflow_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "年份": year,
                    "项目": "水电站初期运行费",
                    "金额_万元": amount,
                    "折算至施工期末_万元": future_value_at_construction_end(amount, year),
                }
            )
            thermal_amount = thermal_fuel * fraction
            thermal_initial_operation_years[year] = thermal_amount
            construction_end_value += future_value_at_construction_end(thermal_amount, year)
            cashflow_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "年份": year,
                    "项目": "火电站初期燃料费",
                    "金额_万元": thermal_amount,
                    "折算至施工期末_万元": future_value_at_construction_end(thermal_amount, year),
                }
            )

        hydro_like_construction_end_value = construction_end_value - thermal_plant_construction_end_value
        thermal_plant_annual_cost = thermal_plant_construction_end_value * thermal_annualization
        hydro_like_annual_cost = hydro_like_construction_end_value * hydro_annualization
        capital_annual_cost = hydro_like_annual_cost + thermal_plant_annual_cost
        normal_annual_cost = hydro_normal_operation + thermal_operation + thermal_fuel - flood_benefit
        total_annual_cost = capital_annual_cost + normal_annual_cost

        yearly_total = {
            year: (
                hydro_investment_years[year]
                + compensation_years[year]
                + thermal_plant_years[year]
                + coal_mine_years[year]
                + hydro_initial_operation_years[year]
                + thermal_initial_operation_years[year]
            )
            for year in range(1, CONSTRUCTION_END_YEAR + 1)
        }
        thermal_investment_total_years = {
            year: thermal_plant_years[year] + coal_mine_years[year]
            for year in range(1, CONSTRUCTION_END_YEAR + 1)
        }
        thermal_investment_total_annual_cost = (
            thermal_plant_annual_cost
            + future_value_sum(coal_mine_years) * hydro_annualization
        )
        normal_total_row_value = normal_annual_cost

        scheme_table_rows = [
            percent_row("永久、机电、临时投资（%）", data.total_investment_distribution),
            amount_row("永久、机电、临时投资（万元）", hydro_investment_years),
            percent_row("水库补偿（%）", data.compensation_distribution),
            amount_row("水库补偿（万元）", compensation_years),
            percent_row("替代火电站投资（%）", THERMAL_PLANT_DISTRIBUTION),
            amount_row("替代火电站投资（万元）", thermal_plant_years, annualization_years=THERMAL_LIFE_YEARS),
            percent_row("煤矿额外投资（%）", COAL_MINE_DISTRIBUTION),
            amount_row("煤矿额外投资（万元）", coal_mine_years),
            percent_row("水电站初期运行（%）", INITIAL_OPERATION_FRACTIONS, "100%"),
            amount_row("水电站初期运行（万元）", hydro_initial_operation_years, hydro_normal_operation),
            percent_row("火电站初期燃料费（%）", INITIAL_OPERATION_FRACTIONS, "100%"),
            amount_row("火电站初期燃料费（万元）", thermal_initial_operation_years, thermal_fuel),
            amount_row("火电站正常运行费（万元）", blank_years(), thermal_operation, annualized=False),
            amount_row("火电站投资合计（万元，小计不重复计入总计）", thermal_investment_total_years, annualized=False),
            amount_row("下游防洪效益（万元）", blank_years(), -flood_benefit, annualized=False),
            amount_row("总计（万元）", yearly_total, normal_total_row_value, annualized=False),
        ]
        scheme_table_rows[-3]["化算到正常运行期年费_万元"] = thermal_investment_total_annual_cost
        scheme_table_rows[-1]["折算到施工期末_万元"] = construction_end_value
        scheme_table_rows[-1]["化算到正常运行期年费_万元"] = capital_annual_cost
        discounted_years = {
            year: future_value_at_construction_end(yearly_total[year], year)
            for year in range(1, CONSTRUCTION_END_YEAR + 1)
        }
        scheme_table_rows.append(amount_row("折算到施工期末（万元）", discounted_years, "", annualized=False))
        scheme_table_rows.append(amount_row("化算到正常运行期年费（万元）", blank_years(), capital_annual_cost, annualized=False))
        scheme_table_rows.append(amount_row("总计算支出（万元）", blank_years(), total_annual_cost, annualized=False))
        write_scheme_table(TABLE_DIR / f"economic_table_{normal_level:.0f}m.csv", scheme_table_rows)

        components_rows.extend(
            [
                {"正常蓄水位_m": normal_level, "计算部分": "装机与电能", "项目": "装机容量", "数值": installed_capacity, "单位": "万kW", "计算说明": "必须容量+重复容量"},
                {"正常蓄水位_m": normal_level, "计算部分": "装机与电能", "项目": "系统有效电能", "数值": net_energy, "单位": "亿kWh", "计算说明": "五强溪多年平均电能-凤滩电能损失"},
                {"正常蓄水位_m": normal_level, "计算部分": "水电投资", "项目": "坝顶高程", "数值": flood_summary[normal_level]["坝顶高程_m"], "单位": "m", "计算说明": "调洪计算成果"},
                {"正常蓄水位_m": normal_level, "计算部分": "水电投资", "项目": "最大坝高", "数值": max_dam_height, "单位": "m", "计算说明": "坝顶高程-坝底高程30m"},
                {"正常蓄水位_m": normal_level, "计算部分": "水电投资", "项目": "永久性建筑物投资", "数值": permanent_investment, "单位": "万元", "计算说明": "按最大坝高由表8线性插值/外推"},
                {"正常蓄水位_m": normal_level, "计算部分": "水电投资", "项目": "机电设备投资", "数值": mech_investment, "单位": "万元", "计算说明": "按装机容量由表9线性插值/外推"},
                {"正常蓄水位_m": normal_level, "计算部分": "水电投资", "项目": "其他投资", "数值": data.other_investment, "单位": "万元", "计算说明": "任务书表10"},
                {"正常蓄水位_m": normal_level, "计算部分": "水电投资", "项目": "水电工程投资合计", "数值": hydro_project_investment, "单位": "万元", "计算说明": "永久性建筑物+机电设备+其他投资"},
                {"正常蓄水位_m": normal_level, "计算部分": "水库补偿", "项目": "水库补偿投资", "数值": data.compensation, "单位": "万元", "计算说明": "任务书表11"},
                {"正常蓄水位_m": normal_level, "计算部分": "替代火电", "项目": "替代容量", "数值": replacement_capacity, "单位": "万kW", "计算说明": "相对120m方案的系统有效容量差"},
                {"正常蓄水位_m": normal_level, "计算部分": "替代火电", "项目": "替代电能", "数值": replacement_energy, "单位": "亿kWh", "计算说明": "相对120m方案的系统有效电能差"},
                {"正常蓄水位_m": normal_level, "计算部分": "替代火电", "项目": "火电站投资", "数值": thermal_plant_investment, "单位": "万元", "计算说明": "750元/kW并按1.1厂用电修正，折合825万元/万kW"},
                {"正常蓄水位_m": normal_level, "计算部分": "替代火电", "项目": "煤矿额外投资", "数值": coal_mine_investment, "单位": "万元", "计算说明": "0.07元/kWh并按1.05电能修正，折合735万元/亿kWh"},
                {"正常蓄水位_m": normal_level, "计算部分": "运行费", "项目": "水电正常年运行费", "数值": hydro_normal_operation, "单位": "万元/年", "计算说明": "电站运行费+大修费+补偿提成"},
                {"正常蓄水位_m": normal_level, "计算部分": "运行费", "项目": "火电正常年运行费", "数值": thermal_operation, "单位": "万元/年", "计算说明": "按火电站投资8%"},
                {"正常蓄水位_m": normal_level, "计算部分": "运行费", "项目": "火电正常燃料费", "数值": thermal_fuel, "单位": "万元/年", "计算说明": "按0.02元/kWh"},
                {"正常蓄水位_m": normal_level, "计算部分": "防洪效益", "项目": "防洪库容", "数值": flood_control_storage, "单位": "亿m3", "计算说明": "防洪高水位库容-汛限水位库容"},
                {"正常蓄水位_m": normal_level, "计算部分": "防洪效益", "项目": "多年平均减少拦洪量", "数值": average_reduced_storage, "单位": "亿m3", "计算说明": "历史拟合线自P=0%延伸至横轴；平移线自P=0%画至5%并竖直截断，取两者间面积"},
                {"正常蓄水位_m": normal_level, "计算部分": "防洪效益", "项目": "防洪年效益", "数值": flood_benefit, "单位": "万元/年", "计算说明": "1000万元/万亩 × 减少淹没面积"},
                {"正常蓄水位_m": normal_level, "计算部分": "折算年费用", "项目": "施工期末折算总值", "数值": construction_end_value, "单位": "万元", "计算说明": "施工期和初期运行现金流折算到第11年末"},
                {"正常蓄水位_m": normal_level, "计算部分": "折算年费用", "项目": "资本年费用", "数值": capital_annual_cost, "单位": "万元/年", "计算说明": "替代火电站投资按25年等额重置，其余施工期末折算值按50年化算"},
                {"正常蓄水位_m": normal_level, "计算部分": "折算年费用", "项目": "正常运行期年费用", "数值": normal_annual_cost, "单位": "万元/年", "计算说明": "水电运行费+火电运行费+燃料费-防洪效益"},
                {"正常蓄水位_m": normal_level, "计算部分": "折算年费用", "项目": "总年费用", "数值": total_annual_cost, "单位": "万元/年", "计算说明": "资本年费用+正常运行期年费用"},
            ]
        )

        comparison_rows.append(
            {
                "正常蓄水位_m": normal_level,
                "装机容量_万kW": installed_capacity,
                "必须容量_万kW": required_capacity,
                "五强溪多年平均电能_亿kWh": energy,
                "凤滩容量损失_万kW": data.fengtang_capacity_loss,
                "凤滩电能损失_亿kWh": data.fengtang_energy_loss,
                "系统有效容量_万kW": net_capacity,
                "系统有效电能_亿kWh": net_energy,
                "替代火电容量_万kW": replacement_capacity,
                "替代火电电能_亿kWh": replacement_energy,
                "水电工程投资_万元": hydro_project_investment,
                "水库补偿投资_万元": data.compensation,
                "替代火电站投资_万元": thermal_plant_investment,
                "煤矿额外投资_万元": coal_mine_investment,
                "施工期末折算总值_万元": construction_end_value,
                "资本年费用_万元": capital_annual_cost,
                "水电正常年运行费_万元": hydro_normal_operation,
                "火电正常年运行费_万元": thermal_operation,
                "火电正常燃料费_万元": thermal_fuel,
                "防洪库容_亿m3": flood_control_storage,
                "多年平均减少拦洪量_亿m3": average_reduced_storage,
                "防洪年效益_万元": flood_benefit,
                "正常运行期年费用_万元": normal_annual_cost,
                "总年费用_万元": total_annual_cost,
            }
        )

        assumptions_rows.extend(
            [
                {"正常蓄水位_m": normal_level, "项目": "最大坝高_m", "取值": max_dam_height, "说明": "由调洪坝顶高程减坝底高程30m"},
                {"正常蓄水位_m": normal_level, "项目": "永久性建筑物投资_万元", "取值": permanent_investment, "说明": "按最大坝高由表8线性插值/外推"},
                {"正常蓄水位_m": normal_level, "项目": "水工建筑物大修费_万元", "取值": civil_repair, "说明": "按最大坝高由大修费表线性插值/外推"},
                {"正常蓄水位_m": normal_level, "项目": "机电投资_万元", "取值": mech_investment, "说明": "按装机容量由表9线性插值/外推"},
                {"正常蓄水位_m": normal_level, "项目": "机电大修费_万元", "取值": mech_repair, "说明": "按装机容量由大修费表线性插值/外推"},
                {"正常蓄水位_m": normal_level, "项目": "防洪年效益_万元", "取值": flood_benefit, "说明": "8场有效历史拦洪量作一次最小二乘拟合；平移线从P=0%画至5%并竖直落到横轴后积分"},
            ]
        )

    best = min(comparison_rows, key=lambda row: float(row["总年费用_万元"]))
    for row in comparison_rows:
        row["是否推荐方案"] = "是" if row["正常蓄水位_m"] == best["正常蓄水位_m"] else ""

    write_rows(COMPARISON_CSV, comparison_rows)
    write_rows(CASHFLOW_CSV, cashflow_rows)
    write_rows(ASSUMPTIONS_CSV, assumptions_rows)
    write_rows(COMPONENTS_CSV, components_rows)
    write_rows(ECONOMIC_DIR / "flood_benefit_frequency_points.csv", flood_frequency_rows)
    print(f"经济比较结果已写入: {COMPARISON_CSV}")
    print(f"经济计算资金流程已写入: {CASHFLOW_CSV}")
    print(f"经济计算假定已写入: {ASSUMPTIONS_CSV}")
    print(f"经济计算分项明细已写入: {COMPONENTS_CSV}")
    print(f"各方案经济计算宽表已写入: {TABLE_DIR}")


def write_rows(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()})


if __name__ == "__main__":
    main()
