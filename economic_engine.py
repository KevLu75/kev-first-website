from __future__ import annotations

import csv
import json
from pathlib import Path

from hydropower_engine import calculation_dir, read_csv, write_csv
from repeated_capacity_engine import run_single_capacity


WEB_ROOT = Path(__file__).resolve().parent
PARAMETER_PATH = WEB_ROOT / "economic_parameters.json"


def load_parameters() -> dict:
    return json.loads(PARAMETER_PATH.read_text(encoding="utf-8"))


def interpolate(x: float, points: list[list[float]]) -> float:
    points = sorted((float(a), float(b)) for a, b in points)
    if x <= points[0][0]:
        left, right = points[0], points[1]
    elif x >= points[-1][0]:
        left, right = points[-2], points[-1]
    else:
        right_index = next(index for index, point in enumerate(points) if x <= point[0])
        left, right = points[right_index - 1], points[right_index]
    return left[1] + (x - left[0]) * (right[1] - left[1]) / (right[0] - left[0])


def interpolate_distribution(level: float, values: dict[str, list[float]]) -> list[float]:
    levels = sorted(float(key) for key in values)
    if level <= levels[0]:
        left, right = levels[0], levels[1]
    elif level >= levels[-1]:
        left, right = levels[-2], levels[-1]
    else:
        right_index = next(index for index, value in enumerate(levels) if level <= value)
        left, right = levels[right_index - 1], levels[right_index]
    ratio = (level - left) / (right - left)
    left_values, right_values = values[f"{left:g}"], values[f"{right:g}"]
    return [a + ratio * (b - a) for a, b in zip(left_values, right_values)]


def storage_curve(path: Path) -> tuple[list[float], list[float]]:
    rows = read_csv(path)
    return [float(row["水位_m"]) for row in rows], [float(row["库容_亿m3"]) for row in rows]


def curve_value(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    index = next(index for index, value in enumerate(xs) if x <= value)
    return ys[index - 1] + (x - xs[index - 1]) * (ys[index] - ys[index - 1]) / (xs[index] - xs[index - 1])


def crf(rate: float, years: int) -> float:
    if abs(rate) < 1e-12:
        return 1.0 / years
    factor = (1.0 + rate) ** years
    return rate * factor / (factor - 1.0)


def flood_benefit(level: float, flood_limit: float, flood_high: float, levels, storages, parameters):
    flood_storage = max(curve_value(flood_high, levels, storages) - curve_value(flood_limit, levels, storages), 0.0)
    samples = sorted((float(value) for value in parameters["historicalRequiredFloodStorage100m3"]), reverse=True)
    empirical = [(rank / (len(samples) + 1) * 100.0, storage) for rank, storage in enumerate(samples, 1)]
    mean_p = sum(point[0] for point in empirical) / len(empirical)
    mean_w = sum(point[1] for point in empirical) / len(empirical)
    slope = sum((p - mean_p) * (w - mean_w) for p, w in empirical) / sum((p - mean_p) ** 2 for p, _ in empirical)
    intercept = mean_w - slope * mean_p
    zero_probability = -intercept / slope
    probabilities = sorted({0.0, 5.0, zero_probability, *[p for p, _ in empirical if p < zero_probability]})
    rows = []
    for probability in probabilities:
        original = max(slope * probability + intercept, 0.0)
        shifted = max(original - flood_storage, 0.0) if probability <= 5.0 else 0.0
        rows.append({"正常蓄水位_m": level, "频率_%": probability, "原拦洪量_亿m3": original, "平移后拦洪量_亿m3": shifted, "减少拦洪量_亿m3": original - shifted})
        if abs(probability - 5.0) < 1e-9:
            rows.append({"正常蓄水位_m": level, "频率_%": 5.0, "原拦洪量_亿m3": original, "平移后拦洪量_亿m3": 0.0, "减少拦洪量_亿m3": original})
    area = sum((b["频率_%"] - a["频率_%"]) * (a["减少拦洪量_亿m3"] + b["减少拦洪量_亿m3"]) / 2.0 for a, b in zip(rows, rows[1:]))
    average_reduced = area / 100.0
    costs = parameters["unitCosts"]
    farmland = costs["baseReducedFarmland10kMu"] + costs["reducedFarmlandPer100m3"] * average_reduced
    benefit = costs["floodBenefitPer10kMu"] * farmland
    return flood_storage, average_reduced, benefit, rows, flood_svg(level, flood_storage, empirical, slope, intercept)


def flood_svg(level, flood_storage, empirical, slope, intercept) -> str:
    width, height = 920, 560
    left, right, top, bottom = 82, 34, 52, 76
    plot_w, plot_h = width - left - right, height - top - bottom
    zero = -intercept / slope
    y_max = intercept * 1.08
    px = lambda value: left + value / 100.0 * plot_w
    py = lambda value: top + (y_max - value) / y_max * plot_h
    shifted0, shifted5 = max(intercept - flood_storage, 0.0), max(slope * 5 + intercept - flood_storage, 0.0)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>', f'<text x="{width/2}" y="29" text-anchor="middle" font-size="20">{level:g}m方案 拦洪量频率曲线及防洪库容平移</text>']
    for tick in range(6):
        p, storage = 20.0 * tick, y_max * tick / 5
        parts.extend([f'<line x1="{px(p):.1f}" y1="{top}" x2="{px(p):.1f}" y2="{height-bottom}" stroke="#e5e7eb"/>', f'<text x="{px(p):.1f}" y="{height-bottom+23}" text-anchor="middle" font-size="12">{p:.0f}</text>', f'<line x1="{left}" y1="{py(storage):.1f}" x2="{width-right}" y2="{py(storage):.1f}" stroke="#e5e7eb"/>', f'<text x="{left-9}" y="{py(storage)+4:.1f}" text-anchor="end" font-size="12">{storage:.1f}</text>'])
    original = f'{px(0):.1f},{py(intercept):.1f} {px(zero):.1f},{py(0):.1f}'
    shifted = f'{px(0):.1f},{py(shifted0):.1f} {px(5):.1f},{py(shifted5):.1f} {px(5):.1f},{py(0):.1f}'
    parts.extend([f'<polyline points="{original}" fill="none" stroke="#0f6b8f" stroke-width="2.5"/>', f'<polyline points="{shifted}" fill="none" stroke="#f97316" stroke-width="2.5"/>'])
    parts.extend(f'<circle cx="{px(p):.1f}" cy="{py(w):.1f}" r="3.5" fill="#111827"/>' for p, w in empirical)
    parts.extend([f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#64748b"/>', f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#64748b"/>', f'<text x="{width/2}" y="{height-25}" text-anchor="middle" font-size="14">频率 P (%)</text>', f'<text x="24" y="{height/2}" transform="rotate(-90 24,{height/2})" text-anchor="middle" font-size="14">拦洪量 (亿m3)</text>', f'<text x="{left+12}" y="{top+20}" font-size="12" fill="#475569">建库前拟合：W={slope:.4f}P+{intercept:.4f}</text>', f'<text x="{left+12}" y="{top+38}" font-size="12" fill="#475569">防洪库容 ΔV={flood_storage:.3f} 亿m3</text>', '</svg>'])
    return "".join(parts)


def exact_energy(project_root: Path, project: dict, scheme: dict, selection: dict, output_dir: Path) -> dict:
    existing_path = output_dir / "exact_energy_result.csv"
    cache_path = output_dir / "exact_energy_cache.json"
    revision = int(project.get("calculationState", {}).get("revision", 0))
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    if existing_path.exists() and cache.get("revision") == revision:
        existing = read_csv(existing_path)
        if existing and abs(float(existing[0]["重复容量_万kW"]) - float(selection["repeatedCapacity"])) < 1e-8:
            return existing[0]
    result, _ = run_single_capacity(float(scheme["normalWaterLevel"]), float(selection["repeatedCapacity"]), output_dir, project_root, project, scheme["id"])
    cache_path.write_text(
        json.dumps({"revision": revision, "repeatedCapacity": float(selection["repeatedCapacity"])}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def yearly_values(distribution, amount, years):
    values = {year: 0.0 for year in range(1, years + 1)}
    iterator = enumerate(distribution, 1) if isinstance(distribution, list) else ((int(year), share) for year, share in distribution.items())
    for year, share in iterator:
        values[year] = amount * float(share)
    return values


def calculate_all(project_root: Path, project: dict, schemes: list[dict], available_ids: set[str]) -> dict[str, dict]:
    parameters = load_parameters()
    comparison = parameters["comparison"]
    project_parameters = project.get("parameters", {})
    rate = float(project_parameters.get("discountRate", comparison["discountRate"]))
    hydro_years = int(project_parameters.get("damServiceLifeYears", comparison["hydroLifeYears"]))
    thermal_years = int(comparison["thermalLifeYears"])
    end_year = int(comparison["constructionEndYear"])
    interpolation = parameters["interpolation"]
    distributions = parameters["distributions"]
    costs = parameters["unitCosts"]
    levels, storages = storage_curve(project_root / project["baseData"]["storageCurve"])
    state = project.get("calculationState", {})
    selections = state.get("repeatedCapacitySelections", {})
    eligible = [scheme for scheme in schemes if scheme["id"] in available_ids]
    if not eligible:
        return {}
    source_rows = {}
    for scheme in eligible:
        scheme_id, level = scheme["id"], float(scheme["normalWaterLevel"])
        output_dir = project_root / "calculations" / "economy" / scheme_id
        output_dir.mkdir(parents=True, exist_ok=True)
        required = read_csv(calculation_dir(project_root, scheme_id) / "required_capacity_result.csv")[0]
        flood = read_csv(project_root / "calculations" / "flood_routing" / scheme_id / "flood_routing_summary.csv")[0]
        crest = read_csv(project_root / "calculations" / "flood_routing" / scheme_id / "dam_crest_result.csv")[0]
        energy = exact_energy(project_root, project, scheme, selections[scheme_id], output_dir)
        required_capacity = float(required["必须容量_万kW"])
        repeated_capacity = float(selections[scheme_id]["repeatedCapacity"])
        installed_capacity = required_capacity + repeated_capacity
        average_energy = float(energy["多年平均年发电量_亿kWh"])
        capacity_loss = float(scheme.get("upstreamImpact", {}).get("reducedInstalledCapacity", 0.0))
        energy_loss = float(scheme.get("upstreamImpact", {}).get("reducedAverageEnergy", 0.0))
        source_rows[scheme_id] = {"scheme": scheme, "level": level, "output_dir": output_dir, "required": required_capacity, "installed": installed_capacity, "energy": average_energy, "netCapacity": required_capacity - capacity_loss, "netEnergy": average_energy - energy_loss, "flood": flood, "crest": crest, "selection": selections[scheme_id]}
    baseline = max(source_rows.values(), key=lambda row: row["level"])
    results = {}
    for scheme_id, source in source_rows.items():
        scheme, level, output_dir = source["scheme"], source["level"], source["output_dir"]
        installed_capacity, required_capacity, average_energy = source["installed"], source["required"], source["energy"]
        max_dam_height = float(source["crest"]["坝顶高程_m"]) - float(comparison["damBottomElevationM"])
        mech_investment = interpolate(installed_capacity, interpolation["mechanicalInvestment"])
        mech_repair = interpolate(installed_capacity, interpolation["mechanicalRepair"])
        permanent_investment = interpolate(max_dam_height, interpolation["permanentInvestmentByDamHeight"])
        civil_repair = interpolate(max_dam_height, interpolation["civilRepairByDamHeight"])
        other_investment = interpolate(level, interpolation["otherInvestmentByNormalLevel"])
        compensation = interpolate(level, interpolation["compensationByNormalLevel"])
        operation_unit = interpolate(level, interpolation["hydroOperationYuanPerKwByNormalLevel"])
        house_repair = interpolate(level, interpolation["houseRepairByNormalLevel"])
        compensation_charge = interpolate(level, interpolation["compensationAnnualChargeByNormalLevel"])
        hydro_investment = permanent_investment + mech_investment + other_investment
        hydro_operation = installed_capacity * operation_unit
        hydro_repair = civil_repair + house_repair + mech_repair
        hydro_normal = hydro_operation + hydro_repair + compensation_charge
        replacement_capacity = max(baseline["netCapacity"] - source["netCapacity"], 0.0)
        replacement_energy = max(baseline["netEnergy"] - source["netEnergy"], 0.0)
        thermal_investment = costs["thermalPlantInvestmentPer10kKw"] * replacement_capacity
        coal_investment = costs["coalMineInvestmentPer100mKwh"] * replacement_energy
        thermal_operation = costs["thermalOperationRate"] * thermal_investment
        thermal_fuel = costs["thermalFuelPer100mKwh"] * replacement_energy
        flood_storage, average_reduced, benefit, frequency, svg = flood_benefit(level, float(source["flood"]["防洪限制水位_m"]), float(source["flood"]["防洪高水位_m"]), levels, storages, parameters)
        hydro_distribution = interpolate_distribution(level, distributions["hydroInvestmentByNormalLevel"])
        compensation_distribution = interpolate_distribution(level, distributions["compensationByNormalLevel"])
        hydro_years_values = yearly_values(hydro_distribution, hydro_investment, end_year)
        compensation_years_values = yearly_values(compensation_distribution, compensation, end_year)
        thermal_years_values = yearly_values(distributions["thermalPlant"], thermal_investment, end_year)
        coal_years_values = yearly_values(distributions["coalMine"], coal_investment, end_year)
        hydro_initial = yearly_values(distributions["initialOperation"], hydro_normal, end_year)
        thermal_initial = yearly_values(distributions["initialOperation"], thermal_fuel, end_year)
        future = lambda value, year: value * (1 + rate) ** (end_year - year)
        yearly_total = {year: hydro_years_values[year] + compensation_years_values[year] + thermal_years_values[year] + coal_years_values[year] + hydro_initial[year] + thermal_initial[year] for year in range(1, end_year + 1)}
        construction_end = sum(future(value, year) for year, value in yearly_total.items())
        thermal_end = sum(future(value, year) for year, value in thermal_years_values.items())
        capital_annual = (construction_end - thermal_end) * crf(rate, hydro_years) + thermal_end * crf(rate, thermal_years)
        normal_annual = hydro_normal + thermal_operation + thermal_fuel - benefit
        total_annual = capital_annual + normal_annual
        components = [
            {"正常蓄水位_m": level, "计算部分": "装机与电能", "项目": "必须容量", "数值": required_capacity, "单位": "万kW", "计算说明": "动态必须容量"},
            {"正常蓄水位_m": level, "计算部分": "装机与电能", "项目": "重复容量", "数值": float(source["selection"]["repeatedCapacity"]), "单位": "万kW", "计算说明": "确认定线成果"},
            {"正常蓄水位_m": level, "计算部分": "装机与电能", "项目": "装机容量", "数值": installed_capacity, "单位": "万kW", "计算说明": "必须容量+重复容量"},
            {"正常蓄水位_m": level, "计算部分": "装机与电能", "项目": "多年平均电能", "数值": average_energy, "单位": "亿kWh", "计算说明": "确认重复容量下精确DP"},
            {"正常蓄水位_m": level, "计算部分": "装机与电能", "项目": "系统有效电能", "数值": source["netEnergy"], "单位": "亿kWh", "计算说明": "扣除上游影响"},
            {"正常蓄水位_m": level, "计算部分": "水电投资", "项目": "坝顶高程", "数值": float(source["crest"]["坝顶高程_m"]), "单位": "m", "计算说明": "动态坝顶成果"},
            {"正常蓄水位_m": level, "计算部分": "水电投资", "项目": "最大坝高", "数值": max_dam_height, "单位": "m", "计算说明": "坝顶高程-坝底高程"},
            {"正常蓄水位_m": level, "计算部分": "水电投资", "项目": "永久性建筑物投资", "数值": permanent_investment, "单位": "万元", "计算说明": "默认参数文件插值"},
            {"正常蓄水位_m": level, "计算部分": "水电投资", "项目": "机电设备投资", "数值": mech_investment, "单位": "万元", "计算说明": "默认参数文件插值"},
            {"正常蓄水位_m": level, "计算部分": "水电投资", "项目": "其他投资", "数值": other_investment, "单位": "万元", "计算说明": "按正常蓄水位插值"},
            {"正常蓄水位_m": level, "计算部分": "水电投资", "项目": "水电工程投资合计", "数值": hydro_investment, "单位": "万元", "计算说明": "永久建筑+机电+其他"},
            {"正常蓄水位_m": level, "计算部分": "水库补偿", "项目": "水库补偿投资", "数值": compensation, "单位": "万元", "计算说明": "按正常蓄水位插值"},
            {"正常蓄水位_m": level, "计算部分": "替代火电", "项目": "替代容量", "数值": replacement_capacity, "单位": "万kW", "计算说明": "相对最高正常蓄水位基准方案"},
            {"正常蓄水位_m": level, "计算部分": "替代火电", "项目": "替代电能", "数值": replacement_energy, "单位": "亿kWh", "计算说明": "相对最高正常蓄水位基准方案"},
            {"正常蓄水位_m": level, "计算部分": "替代火电", "项目": "火电站投资", "数值": thermal_investment, "单位": "万元", "计算说明": "默认单位造价"},
            {"正常蓄水位_m": level, "计算部分": "替代火电", "项目": "煤矿额外投资", "数值": coal_investment, "单位": "万元", "计算说明": "默认单位造价"},
            {"正常蓄水位_m": level, "计算部分": "运行费", "项目": "水电正常年运行费", "数值": hydro_normal, "单位": "万元/年", "计算说明": "运行费+大修费+补偿提成"},
            {"正常蓄水位_m": level, "计算部分": "运行费", "项目": "火电正常年运行费", "数值": thermal_operation, "单位": "万元/年", "计算说明": "火电投资比例"},
            {"正常蓄水位_m": level, "计算部分": "运行费", "项目": "火电正常燃料费", "数值": thermal_fuel, "单位": "万元/年", "计算说明": "替代电能单位燃料费"},
            {"正常蓄水位_m": level, "计算部分": "防洪效益", "项目": "防洪库容", "数值": flood_storage, "单位": "亿m³", "计算说明": "动态调洪成果"},
            {"正常蓄水位_m": level, "计算部分": "防洪效益", "项目": "多年平均减少拦洪量", "数值": average_reduced, "单位": "亿m³", "计算说明": "频率线面积"},
            {"正常蓄水位_m": level, "计算部分": "防洪效益", "项目": "防洪年效益", "数值": benefit, "单位": "万元/年", "计算说明": "默认效益参数"},
            {"正常蓄水位_m": level, "计算部分": "折算年费用", "项目": "施工期末折算总值", "数值": construction_end, "单位": "万元", "计算说明": "折算到第11年末"},
            {"正常蓄水位_m": level, "计算部分": "折算年费用", "项目": "资本年费用", "数值": capital_annual, "单位": "万元/年", "计算说明": "火电25年，其余按大坝寿命"},
            {"正常蓄水位_m": level, "计算部分": "折算年费用", "项目": "正常运行期年费用", "数值": normal_annual, "单位": "万元/年", "计算说明": "运行费+燃料费-防洪效益"},
            {"正常蓄水位_m": level, "计算部分": "折算年费用", "项目": "总年费用", "数值": total_annual, "单位": "万元/年", "计算说明": "资本年费用+正常运行期年费用"},
        ]
        cashflow = [{"正常蓄水位_m": level, "年份": year, "水电工程投资_万元": hydro_years_values[year], "水库补偿_万元": compensation_years_values[year], "替代火电站投资_万元": thermal_years_values[year], "煤矿投资_万元": coal_years_values[year], "初期运行及燃料费_万元": hydro_initial[year] + thermal_initial[year], "合计_万元": yearly_total[year], "折算至施工期末_万元": future(yearly_total[year], year)} for year in range(1, end_year + 1)]
        wide = [{"项目": "总计（万元）", **{f"第{year}年": yearly_total[year] for year in range(1, end_year + 1)}, "正常运行期年值": normal_annual, "折算到施工期末_万元": construction_end, "化算到正常运行期年费_万元": capital_annual}, {"项目": "总计算支出（万元）", **{f"第{year}年": 0.0 for year in range(1, end_year + 1)}, "正常运行期年值": total_annual, "折算到施工期末_万元": "", "化算到正常运行期年费_万元": ""}]
        comparison_row = {"方案ID": scheme_id, "方案名称": scheme["name"], "正常蓄水位_m": level, "装机容量_万kW": installed_capacity, "必须容量_万kW": required_capacity, "五强溪多年平均电能_亿kWh": average_energy, "系统有效容量_万kW": source["netCapacity"], "系统有效电能_亿kWh": source["netEnergy"], "替代火电容量_万kW": replacement_capacity, "替代火电电能_亿kWh": replacement_energy, "水电工程投资_万元": hydro_investment, "水库补偿投资_万元": compensation, "防洪年效益_万元": benefit, "总年费用_万元": total_annual}
        write_csv(output_dir / "economic_components.csv", components)
        write_csv(output_dir / "economic_cashflow.csv", cashflow)
        write_csv(output_dir / "economic_wide_table.csv", wide)
        write_csv(output_dir / "flood_benefit_frequency.csv", frequency)
        write_csv(output_dir / "economic_comparison.csv", [comparison_row])
        (output_dir / "flood_benefit.svg").write_text(svg, encoding="utf-8")
        results[scheme_id] = {"schemeId": scheme_id, "schemeName": scheme["name"], "level": level, "selection": source["selection"], "comparison": comparison_row, "components": {section: [row for row in components if row["计算部分"] == section] for section in {row["计算部分"] for row in components}}, "tables": {"cashflow": cashflow, "wide": wide, "frequency": frequency, "comparison": [comparison_row]}, "floodBenefitSvg": svg, "note": "经济成果由动态兴利、防洪成果和 web/economic_parameters.json 默认参数实时计算。"}
    best = min(results.values(), key=lambda item: float(item["comparison"]["总年费用_万元"]))
    for item in results.values():
        item["comparison"]["当前比较推荐"] = "是" if item["schemeId"] == best["schemeId"] else ""
        write_csv(source_rows[item["schemeId"]]["output_dir"] / "economic_comparison.csv", [item["comparison"]])
    return results
