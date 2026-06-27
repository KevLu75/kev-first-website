const state = {
  summary: null,
  activeModule: 'data',
  activeLevel: 115,
  baseData: null,
  activeDataset: 'storageCurve',
  schemeConfig: null,
  activeSchemeId: null,
  hydropowerSubmodule: 'deadWater',
  deadWaterResult: null,
  guaranteedOutputResult: null,
  installedCapacityResult: null,
  dispatchChartResult: null,
  repeatedCapacityResult: null,
  floodSubmodule: 'dischargeCapacity',
  dischargeCapacityResult: null,
  floodRoutingResult: null,
  damCrestResult: null,
  economySubmodule: 'basis',
  economyResult: null,
  parameterDraft: null,
};

const moduleDescriptions = {
  data: '项目数据管理',
  config: '方案配置',
  hydropower: '兴利计算',
  flood: '防洪演算',
  economy: '经济计算',
  export: '成果导出',
};

const motion = {
  reduced: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  current: null,
};

function animateModuleContent() {
  if (!window.gsap || motion.reduced) return;
  motion.current?.kill();
  const body = document.getElementById('moduleBody');
  const targets = Array.from(body.children).slice(0, 8);
  if (!targets.length) return;
  motion.current = window.gsap.timeline({ defaults: { duration: 0.28, ease: 'power2.out' } });
  motion.current.fromTo(targets, { autoAlpha: 0, y: 10 }, {
    autoAlpha: 1,
    y: 0,
    stagger: 0.035,
    clearProps: 'transform,opacity,visibility',
  });
}

const baseDataTabs = [
  ['storageCurve', '库容曲线'],
  ['areaCurve', '水位-面积曲线'],
  ['tailwaterCurve', '尾水水位流量曲线'],
  ['runoffSeries', '径流系列表'],
  ['designFlood', '设计洪水数据'],
  ['parameters', '其他参数'],
];

const fmt = (value, digits = 2, unit = '') => {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? '-';
  return `${number.toFixed(digits).replace(/\.?0+$/, '')}${unit}`;
};

const api = async (url, options) => {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(await res.text());
  const type = res.headers.get('content-type') || '';
  return type.includes('application/json') ? res.json() : res.text();
};

function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadRowsAsCsv(rows, filename) {
  if (!rows?.length) return;
  const headers = Object.keys(rows[0]);
  const csv = [
    headers.join(','),
    ...rows.map((row) => headers.map((key) => csvEscape(row[key])).join(',')),
  ].join('\r\n');
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function init() {
  document.documentElement.dataset.motionEngine = window.gsap ? 'gsap' : 'none';
  document.getElementById('refreshBtn').addEventListener('click', loadSummary);
  document.getElementById('schemeSelect').addEventListener('change', (event) => {
    state.activeLevel = Number(event.target.value);
    render();
  });
  await loadSummary();
}

async function loadSummary() {
  state.summary = await api('/api/summary');
  state.baseData = await api('/api/base-data');
  state.schemeConfig = await api('/api/schemes');
  state.activeSchemeId = state.schemeConfig.schemes[0]?.id ?? null;
  const recommended = state.summary.schemes.find((scheme) => scheme.recommended);
  state.activeLevel = recommended?.level ?? state.summary.schemes[0]?.level ?? 115;
  render();
}

function render() {
  renderNav();
  renderSchemeSelect();
  renderModule();
}

function activeScheme() {
  return state.summary.schemes.find((scheme) => scheme.level === state.activeLevel) || state.summary.schemes[0];
}

function renderNav() {
  const nav = document.getElementById('moduleNav');
  nav.innerHTML = state.summary.modules.map((module) => `
    <button class="nav-button ${state.activeModule === module.id ? 'active' : ''}" data-module="${module.id}">
      <strong>${module.name}</strong>
      <span>${module.status}</span>
    </button>
  `).join('');
  nav.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      state.activeModule = button.dataset.module;
      renderModule();
      renderNav();
    });
  });
}

function renderSchemeSelect() {
  const select = document.getElementById('schemeSelect');
  select.innerHTML = state.summary.schemes.map((scheme) => `
    <option value="${scheme.level}" ${scheme.level === state.activeLevel ? 'selected' : ''}>
      ${scheme.name} · ${fmt(scheme.level, 0, 'm')}
    </option>
  `).join('');
}

function renderModule() {
  const module = state.summary.modules.find((item) => item.id === state.activeModule);
  document.getElementById('activeModuleKicker').textContent = '功能区';
  document.getElementById('activeModuleTitle').textContent = moduleDescriptions[state.activeModule];
  document.getElementById('moduleStatus').textContent = module?.status ?? '示例成果';
  document.getElementById('schemePicker').style.display = 'none';

  const renderers = {
    data: renderDataModule,
    config: renderConfigModule,
    hydropower: renderHydropowerModule,
    flood: renderFloodModule,
    economy: renderEconomyModule,
    export: renderExportModule,
  };
  renderers[state.activeModule]();
  requestAnimationFrame(animateModuleContent);
}

function renderDataModule() {
  const active = baseDataTabs.find(([id]) => id === state.activeDataset) || baseDataTabs[0];
  document.getElementById('moduleBody').innerHTML = `
    <div class="subtabs">
      ${baseDataTabs.map(([id, label]) => `
        <button class="subtab ${id === state.activeDataset ? 'active' : ''}" data-dataset="${id}">${label}</button>
      `).join('')}
    </div>
    <div class="data-toolbar">
      <div>
        <h3>${active[1]}</h3>
        <p id="datasetDescription">正在读取当前项目数据。</p>
      </div>
      <div class="toolbar-actions">
        <label id="uploadCsvLabel" class="upload-label">
          上传 CSV
          <input id="uploadCsvInput" type="file" accept=".csv,text/csv" />
        </label>
        <button id="useExampleBtn" class="secondary">使用示例数据</button>
        <button id="saveDatasetBtn">保存当前数据</button>
      </div>
    </div>
    <div id="datasetEditor">加载中...</div>
  `;
  document.querySelectorAll('.subtab').forEach((button) => {
    button.addEventListener('click', () => {
      state.activeDataset = button.dataset.dataset;
      renderDataModule();
    });
  });
  document.getElementById('useExampleBtn').addEventListener('click', useExampleDataset);
  document.getElementById('saveDatasetBtn').addEventListener('click', saveDataset);
  document.getElementById('uploadCsvInput').addEventListener('change', uploadCsvDataset);
  loadDataset();
}

async function loadDataset() {
  const data = await api(`/api/base-data?id=${encodeURIComponent(state.activeDataset)}`);
  document.getElementById('datasetDescription').textContent = data.description;
  document.getElementById('saveDatasetBtn').style.display = data.downloadOnly ? 'none' : 'inline-flex';
  document.getElementById('uploadCsvLabel').style.display = data.type === 'csv' ? 'inline-flex' : 'none';

  if (data.type === 'csv') {
    document.getElementById('datasetEditor').innerHTML = `
      <div class="note">当前数据来源：web/${data.path}。表格可直接编辑，保存和上传只写入 web/project_final。</div>
      ${editableTable(data.columns, data.rows)}
    `;
    document.getElementById('addRowBtn').addEventListener('click', addDatasetRow);
    document.getElementById('addColumnBtn').addEventListener('click', addDatasetColumn);
    return;
  }

  if (data.type === 'json') {
    state.parameterDraft = structuredClone(data.parameters || {});
    document.getElementById('datasetEditor').innerHTML = parameterForm(state.parameterDraft);
    return;
  }

  document.getElementById('datasetEditor').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="file-list">
      <div class="file-row">
        <strong>${data.name}</strong>
        <span>${data.type.toUpperCase()} · ${Math.ceil((data.size || 0) / 1024)} KB</span>
        <a href="/api/download?path=${encodeURIComponent(`web/${data.path}`)}">
          <button class="secondary">下载原始文件</button>
        </a>
      </div>
    </div>
  `;
}

function editableTable(columns, rows) {
  const safeColumns = columns.length ? columns : ['字段1'];
  const safeRows = rows.length ? rows : [Object.fromEntries(safeColumns.map((col) => [col, '']))];
  return `
    <div class="table-wrap editable-wrap">
      <table id="datasetTable">
        <thead>
          <tr>${safeColumns.map((col) => `<th><input value="${escapeHtml(col)}" data-role="header" /></th>`).join('')}</tr>
        </thead>
        <tbody>
          ${safeRows.map((row) => `
            <tr>${safeColumns.map((col) => `<td><input value="${escapeHtml(row[col] ?? '')}" /></td>`).join('')}</tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="table-actions">
      <button id="addRowBtn" class="secondary">增加一行</button>
      <button id="addColumnBtn" class="secondary">增加一列</button>
    </div>
  `;
}

async function useExampleDataset() {
  const data = await api('/api/base-data/use-example', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: state.activeDataset }),
  });
  await loadDataset();
  toast(`已载入示例数据：${data.name}`);
}

async function saveDataset() {
  const payload = { id: state.activeDataset };
  if (state.activeDataset === 'parameters') {
    const parameters = readParameterForm();
    if (!parameters) return;
    payload.parameters = parameters;
  } else {
    payload.rows = readEditableTable();
  }
  const data = await api('/api/base-data/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  await loadDataset();
  toast(`已保存：${data.name}`);
}

function numericParameter(id, fallback = 0) {
  const input = document.getElementById(id);
  const value = Number(input?.value);
  return Number.isFinite(value) ? value : fallback;
}

function parameterField(id, label, value, unit, options = {}) {
  const { min = 0, max = '', step = 'any', help = '' } = options;
  return `
    <label class="parameter-field" for="${id}">
      <span>${label}</span>
      <div class="input-with-unit">
        <input id="${id}" type="number" value="${escapeHtml(value)}" min="${min}" ${max === '' ? '' : `max="${max}"`} step="${step}" />
        <span>${unit}</span>
      </div>
      ${help ? `<small>${help}</small>` : ''}
    </label>
  `;
}

function parameterForm(parameters) {
  const consumption = parameters.navigationIrrigationConsumption || {};
  const months = ['4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月', '1月', '2月', '3月'];
  const monthly = consumption.monthly || {};
  const highConsumptionMonths = new Set(['5月', '6月', '7月', '8月', '9月']);
  const sedimentation = parameters.annualSedimentation || {};
  return `
    <div class="parameter-form">
      <div class="note">参数按用途分组保存到当前项目。修改后点击右上角“保存当前数据”生效。</div>
      <section class="parameter-section">
        <div class="parameter-section-heading"><div><h4>工程与下游安全</h4><p>大坝使用年限及下游河道控制条件。</p></div></div>
        <div class="parameter-grid">
          ${parameterField('paramDamLife', '大坝使用寿命', parameters.damServiceLifeYears ?? 50, '年', { min: 1, step: 1, help: '用于工程比较期及费用折算。' })}
          ${parameterField('paramDownstreamSafeFlow', '下游安全流量', parameters.downstreamSafeFlowM3s ?? 20000, 'm³/s', { min: 0, step: 1, help: '下游河道允许安全通过的控制流量。' })}
          ${parameterField('paramMaxFetch', '最大吹程', parameters.maxFetchKm ?? 15, 'km', { min: 0, step: 0.1, help: '用于风浪爬高和坝顶高程计算。' })}
          ${parameterField('paramWindSpeed', '设计风速', parameters.designWindSpeedMs ?? 12, 'm/s', { min: 0, step: 0.1, help: '用于设计工况风浪计算。' })}
        </div>
      </section>
      <section class="parameter-section">
        <div class="parameter-section-heading"><div><h4>设计与经济参数</h4><p>保证率、折算率及年淤积量。</p></div></div>
        <div class="parameter-grid">
          ${parameterField('paramGuaranteeRate', '设计保证率', (Number(parameters.designGuaranteeRate ?? 0.9) * 100).toFixed(1), '%', { min: 0, max: 100, step: 0.1 })}
          ${parameterField('paramDiscountRate', '经济折算率', (Number(parameters.discountRate ?? 0.1) * 100).toFixed(1), '%', { min: 0, max: 100, step: 0.1 })}
          ${parameterField('paramSedimentation', '年淤积量', sedimentation.value ?? 0, '亿m³/年', { min: 0, step: 0.01 })}
        </div>
      </section>
      <section class="parameter-section">
        <div class="parameter-section-heading"><div><h4>航运、灌溉等综合利用消耗</h4><p>按水利年顺序填写各月平均消耗流量。</p></div><span class="parameter-unit-badge">m³/s</span></div>
        <div class="monthly-parameter-grid">
          ${months.map((month, index) => parameterField(`paramMonth${index}`, month, monthly[month] ?? (highConsumptionMonths.has(month) ? 45 : 10), 'm³/s', { min: 0, step: 0.1 })).join('')}
        </div>
      </section>
    </div>
  `;
}

function readParameterForm() {
  const damLife = numericParameter('paramDamLife', NaN);
  const safeFlow = numericParameter('paramDownstreamSafeFlow', NaN);
  const guaranteePercent = numericParameter('paramGuaranteeRate', NaN);
  const discountPercent = numericParameter('paramDiscountRate', NaN);
  if (!(damLife > 0) || !(safeFlow >= 0) || guaranteePercent < 0 || guaranteePercent > 100 || discountPercent < 0 || discountPercent > 100) {
    toast('请检查参数：使用寿命须大于0，流量不得为负，百分比应在0–100之间');
    return null;
  }
  const parameters = structuredClone(state.parameterDraft || {});
  const months = ['4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月', '1月', '2月', '3月'];
  parameters.damServiceLifeYears = damLife;
  parameters.downstreamSafeFlowM3s = safeFlow;
  parameters.maxFetchKm = numericParameter('paramMaxFetch', 15);
  parameters.designWindSpeedMs = numericParameter('paramWindSpeed', 12);
  parameters.designGuaranteeRate = guaranteePercent / 100;
  parameters.discountRate = discountPercent / 100;
  parameters.annualSedimentation = {
    ...(parameters.annualSedimentation || {}),
    value: numericParameter('paramSedimentation', 0),
    unit: parameters.annualSedimentation?.unit || '亿m3/年',
  };
  parameters.navigationIrrigationConsumption = {
    ...(parameters.navigationIrrigationConsumption || {}),
    description: parameters.navigationIrrigationConsumption?.description || '航运、灌溉等综合利用消耗，按月份配置。',
    unit: 'm3/s',
    monthly: Object.fromEntries(months.map((month, index) => [month, numericParameter(`paramMonth${index}`, 0)])),
  };
  return parameters;
}

async function uploadCsvDataset(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`/api/base-data/upload?id=${encodeURIComponent(state.activeDataset)}`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    toast(`上传失败：${await res.text()}`);
    event.target.value = '';
    return;
  }
  await loadDataset();
  toast(`已上传：${file.name}`);
  event.target.value = '';
}

function readEditableTable() {
  const table = document.getElementById('datasetTable');
  const headers = [...table.querySelectorAll('thead input')].map((input) => input.value.trim()).filter(Boolean);
  return [...table.querySelectorAll('tbody tr')].map((tr) => {
    const cells = [...tr.querySelectorAll('input')];
    return Object.fromEntries(headers.map((header, index) => [header, cells[index]?.value ?? '']));
  });
}

function addDatasetRow() {
  const table = document.getElementById('datasetTable');
  const columns = table.querySelectorAll('thead input').length;
  const tr = document.createElement('tr');
  tr.innerHTML = Array.from({ length: columns }, () => '<td><input value="" /></td>').join('');
  table.querySelector('tbody').appendChild(tr);
}

function addDatasetColumn() {
  const table = document.getElementById('datasetTable');
  const next = table.querySelectorAll('thead input').length + 1;
  const th = document.createElement('th');
  th.innerHTML = `<input value="字段${next}" data-role="header" />`;
  table.querySelector('thead tr').appendChild(th);
  table.querySelectorAll('tbody tr').forEach((tr) => {
    const td = document.createElement('td');
    td.innerHTML = '<input value="" />';
    tr.appendChild(td);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function toast(message) {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = message;
  document.body.appendChild(el);
  window.setTimeout(() => el.remove(), 1800);
}

function renderConfigModule() {
  const schemes = state.schemeConfig.schemes;
  if (!state.activeSchemeId && schemes.length) state.activeSchemeId = schemes[0].id;
  const scheme = schemes.find((item) => item.id === state.activeSchemeId) || schemes[0];
  const examples = state.schemeConfig.exampleSchemes;
  document.getElementById('moduleBody').innerHTML = `
    <div class="scheme-toolbar">
      <div class="scheme-tabs">
        ${schemes.map((item) => `
          <button class="subtab ${item.id === scheme.id ? 'active' : ''}" data-scheme-id="${item.id}">
            ${item.name || '未命名方案'}
          </button>
        `).join('')}
      </div>
      <div class="scheme-toolbar-actions">
        <button id="resetProjectBtn" class="danger">一键清空</button>
        <button id="addSchemeBtn">添加方案</button>
      </div>
    </div>
    <div class="note">${state.schemeConfig.economicAutoNote}</div>
    <div class="data-toolbar">
      <div>
        <h3>${scheme.name || '未命名方案'}</h3>
        <p>当前页面只配置单个方案直接参与计算的参数。经济投资与运行费参数后续按正常蓄水位自动插值。</p>
      </div>
      <div class="toolbar-actions">
        <label>
          一键填充样例
          <select id="exampleSchemeSelect">
            ${examples.map((item) => `<option value="${item.id}">${fmt(item.normalWaterLevel, 2, ' m')}</option>`).join('')}
          </select>
        </label>
        <button id="useExampleSchemeBtn" class="secondary">填充</button>
        <button id="saveSchemeBtn">保存方案</button>
      </div>
    </div>
    ${schemeForm(scheme)}
  `;
  document.querySelectorAll('[data-scheme-id]').forEach((button) => {
    button.addEventListener('click', () => {
      state.activeSchemeId = button.dataset.schemeId;
      renderConfigModule();
    });
  });
  document.getElementById('addSchemeBtn').addEventListener('click', addScheme);
  document.getElementById('resetProjectBtn').addEventListener('click', resetProject);
  document.getElementById('saveSchemeBtn').addEventListener('click', saveActiveScheme);
  document.getElementById('useExampleSchemeBtn').addEventListener('click', useExampleScheme);
}

function schemeForm(scheme) {
  return `
    <div class="scheme-form">
      <section>
        <h4>基本参数</h4>
        <div class="form-grid">
          ${textInput('schemeName', '方案名称', scheme.name)}
          ${numberInput('normalWaterLevel', '正常蓄水位(m)', scheme.normalWaterLevel, 0.1)}
          ${numberInput('reserveCapacity', '备用容量(万kW)', scheme.reserveCapacity, 0.1)}
        </div>
      </section>
      <section>
        <h4>对上游影响</h4>
        <div class="form-grid">
          ${numberInput('reducedInstalledCapacity', '减少的装机容量(万kW)', scheme.upstreamImpact.reducedInstalledCapacity, 0.001)}
          ${numberInput('reducedAverageEnergy', '多年平均发电量损失(亿kWh)', scheme.upstreamImpact.reducedAverageEnergy, 0.001)}
        </div>
      </section>
      <section>
        <h4>溢洪坝参数</h4>
        <div class="form-grid">
          ${numberInput('spillwayHoles', '孔数', scheme.spillway.holes, 1)}
          ${numberInput('spillwayCrestElevation', '堰顶高程(m)', scheme.spillway.crestElevation, 0.1)}
          ${numberInput('spillwayOrificeWidth', '孔口宽度(m)', scheme.spillway.orificeWidth, 0.1)}
          ${numberInput('spillwayOrificeHeight', '孔口高度(m)', scheme.spillway.orificeHeight, 0.1)}
        </div>
      </section>
      <section>
        <h4>中孔参数</h4>
        <div class="form-grid">
          ${numberInput('middleOutletHoles', '孔数', scheme.middleOutlet.holes, 1)}
          ${numberInput('middleOutletSillElevation', '坎底高程(m)', scheme.middleOutlet.sillElevation, 0.1)}
          ${numberInput('middleOutletOrificeWidth', '孔口宽度(m)', scheme.middleOutlet.orificeWidth, 0.1)}
          ${numberInput('middleOutletOrificeHeight', '孔口高度(m)', scheme.middleOutlet.orificeHeight, 0.1)}
        </div>
      </section>
    </div>
  `;
}

function readActiveSchemeForm() {
  return {
    id: state.activeSchemeId,
    name: document.getElementById('schemeName').value.trim() || '未命名方案',
    normalWaterLevel: Number(document.getElementById('normalWaterLevel').value),
    upstreamImpact: {
      reducedInstalledCapacity: Number(document.getElementById('reducedInstalledCapacity').value),
      reducedAverageEnergy: Number(document.getElementById('reducedAverageEnergy').value),
    },
    spillway: {
      holes: Number(document.getElementById('spillwayHoles').value),
      crestElevation: Number(document.getElementById('spillwayCrestElevation').value),
      orificeWidth: Number(document.getElementById('spillwayOrificeWidth').value),
      orificeHeight: Number(document.getElementById('spillwayOrificeHeight').value),
    },
    middleOutlet: {
      holes: Number(document.getElementById('middleOutletHoles').value),
      sillElevation: Number(document.getElementById('middleOutletSillElevation').value),
      orificeWidth: Number(document.getElementById('middleOutletOrificeWidth').value),
      orificeHeight: Number(document.getElementById('middleOutletOrificeHeight').value),
    },
    reserveCapacity: Number(document.getElementById('reserveCapacity').value),
  };
}

async function saveActiveScheme() {
  const schemes = state.schemeConfig.schemes.map((item) => (
    item.id === state.activeSchemeId ? readActiveSchemeForm() : item
  ));
  state.schemeConfig = await api('/api/schemes/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schemes }),
  });
  toast('方案参数已保存');
  renderConfigModule();
}

async function addScheme() {
  state.schemeConfig = await api('/api/schemes/add', { method: 'POST' });
  state.activeSchemeId = state.schemeConfig.schemes.at(-1).id;
  toast('已添加新方案');
  renderConfigModule();
}

async function resetProject() {
  const confirmed = window.confirm(
    '确定要一键清空吗？\n\n这会恢复初始四个方案和示例输入，并删除全部兴利、防洪、经济计算成果。此操作无法撤销。',
  );
  if (!confirmed) return;
  const button = document.getElementById('resetProjectBtn');
  button.disabled = true;
  button.textContent = '正在清空…';
  try {
    const result = await api('/api/project/reset', { method: 'POST' });
    state.activeSchemeId = result.schemeIds[0] ?? null;
    state.deadWaterResult = null;
    state.guaranteedOutputResult = null;
    state.installedCapacityResult = null;
    state.dispatchChartResult = null;
    state.repeatedCapacityResult = null;
    state.dischargeCapacityResult = null;
    state.floodRoutingResult = null;
    state.damCrestResult = null;
    state.economyResult = null;
    await loadSummary();
    state.activeModule = 'config';
    render();
    toast(result.message);
  } catch (error) {
    button.disabled = false;
    button.textContent = '一键清空';
    window.alert(`清空失败：${error.message}`);
  }
}

async function useExampleScheme() {
  const exampleId = document.getElementById('exampleSchemeSelect').value;
  state.schemeConfig = await api('/api/schemes/use-example', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targetId: state.activeSchemeId, exampleId }),
  });
  toast('已填充样例方案参数');
  renderConfigModule();
}

function renderHydropowerModule() {
  const submodules = [
    ['deadWater', '死水位计算'],
    ['guaranteedOutput', '保证出力计算'],
    ['installedCapacity', '水电站装机容量'],
    ['dispatchChart', '水电站调度图'],
    ['repeatedCapacity', '重复容量计算'],
  ];
  document.getElementById('moduleBody').innerHTML = `
    <div class="subtabs">
      ${submodules.map(([id, label]) => `
        <button class="subtab ${state.hydropowerSubmodule === id ? 'active' : ''}" data-hydropower-submodule="${id}">${label}</button>
      `).join('')}
    </div>
    <div id="hydropowerSubmoduleBody"></div>
  `;
  document.querySelectorAll('[data-hydropower-submodule]').forEach((button) => {
    button.addEventListener('click', () => {
      state.hydropowerSubmodule = button.dataset.hydropowerSubmodule;
      renderHydropowerModule();
    });
  });
  if (state.hydropowerSubmodule === 'deadWater') {
    renderDeadWaterPanel();
  } else if (state.hydropowerSubmodule === 'guaranteedOutput') {
    renderGuaranteedOutputPanel();
  } else if (state.hydropowerSubmodule === 'installedCapacity') {
    renderInstalledCapacityPanel();
  } else if (state.hydropowerSubmodule === 'dispatchChart') {
    renderDispatchChartPanel();
  } else {
    renderRepeatedCapacityPanel();
  }
}

function renderDeadWaterPanel() {
  document.getElementById('hydropowerSubmoduleBody').innerHTML = `
    <div class="data-toolbar">
      <div>
        <h3>死水位计算</h3>
        <p>选择当前方案后开始计算。计算完成后可查看结果，并在下方展开供水期过程表。</p>
      </div>
      <div class="toolbar-actions">
        <label>
          当前方案
          <select id="deadWaterSchemeSelect">
            ${state.schemeConfig.schemes.map((scheme) => `
              <option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>
            `).join('')}
          </select>
        </label>
        <button id="runDeadWaterBtn">开始计算</button>
      </div>
    </div>
    <div id="deadWaterResult" class="result-placeholder">尚未计算。请选择方案并点击“开始计算”。</div>
  `;
  document.getElementById('runDeadWaterBtn').addEventListener('click', runDeadWaterCalculation);
}

async function runDeadWaterCalculation() {
  const select = document.getElementById('deadWaterSchemeSelect');
  const schemeId = select.value;
  const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/dead-water?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.deadWaterResult = data;
  const result = data.result;
  const cards = [
    ['死水位', fmt(result['死水位_m'], 2, ' m')],
    ['死库容', fmt(result['死库容_亿m3'], 4, ' 亿m3')],
    ['兴利库容', fmt(result['兴利库容_亿m3'], 4, ' 亿m3')],
    ['设计调节流量', fmt(result['设计调节流量qp_m3s'], 3, ' m3/s')],
  ];
  document.getElementById('deadWaterResult').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="summary-grid">
      ${cards.map(([label, value]) => `
        <div class="info-tile">
          <span>${label}</span>
          <strong>${value}</strong>
        </div>
      `).join('')}
    </div>
    <div class="section-heading">
      <h4>计算表格</h4>
    </div>
    <div class="table-switcher">
      <div class="toolbar-actions">
        <label>
          输出表格
          <select id="deadWaterTableSelect">
            <option value="result">计算结果表</option>
            <option value="process">供水期计算过程表</option>
            <option value="frequency">调节流量排频表</option>
          </select>
        </label>
        <button class="secondary" id="downloadDeadWaterTableBtn">导出当前表格</button>
      </div>
      <div id="deadWaterSelectedTable"></div>
    </div>
  `;
  renderDeadWaterSelectedTable();
  document.getElementById('deadWaterTableSelect').addEventListener('change', renderDeadWaterSelectedTable);
  document.getElementById('downloadDeadWaterTableBtn').addEventListener('click', downloadSelectedDeadWaterTable);
}

function deadWaterTableMeta(key) {
  const level = state.deadWaterResult?.level ?? 'scheme';
  const labels = {
    result: ['计算结果表', `dead_water_result_${level}m.csv`],
    process: ['供水期计算过程表', `dead_water_supply_periods_${level}m.csv`],
    frequency: ['调节流量排频表', `dead_water_regulated_flow_frequency_${level}m.csv`],
  };
  return labels[key] || labels.result;
}

function renderDeadWaterSelectedTable() {
  const key = document.getElementById('deadWaterTableSelect')?.value || 'result';
  const rows = state.deadWaterResult?.tables?.[key] || [];
  const [label] = deadWaterTableMeta(key);
  document.getElementById('deadWaterSelectedTable').innerHTML = `
    <div class="selected-table-title">${label}（${rows.length} 行）</div>
    ${objectTable(rows)}
  `;
}

function downloadSelectedDeadWaterTable() {
  const key = document.getElementById('deadWaterTableSelect')?.value || 'result';
  const rows = state.deadWaterResult?.tables?.[key] || [];
  const [, filename] = deadWaterTableMeta(key);
  downloadRowsAsCsv(rows, filename);
}

function inverseNormalCdf(p) {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const low = 0.02425;
  const high = 1 - low;
  const pp = Math.min(Math.max(p, 1e-6), 1 - 1e-6);
  if (pp < low) {
    const q = Math.sqrt(-2 * Math.log(pp));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
      / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (pp > high) {
    const q = Math.sqrt(-2 * Math.log(1 - pp));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
      / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  const q = pp - 0.5;
  const r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
    / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

function frequencyCurveChart(curveData) {
  const empiricalPoints = Array.isArray(curveData) ? curveData : (curveData?.empirical || []);
  const theoreticalPoints = Array.isArray(curveData) ? curveData : (curveData?.theoretical || []);
  const designGuaranteeRate = Number(curveData?.designGuaranteeRate || 87.5);
  if (!theoreticalPoints.length && !empiricalPoints.length) return '<p>暂无曲线数据。</p>';
  const width = 820;
  const height = 300;
  const pad = { left: 70, right: 24, top: 28, bottom: 52 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const allPoints = [...theoreticalPoints, ...empiricalPoints];
  const ys = allPoints.map((p) => Number(p.outputKw) / 10000).filter((value) => Number.isFinite(value));
  const minX = inverseNormalCdf(0.01);
  const maxX = inverseNormalCdf(0.99);
  const minY = Math.floor(Math.min(...ys) / 5) * 5;
  const maxY = Math.ceil(Math.max(...ys) / 5) * 5;
  const xScale = (x) => {
    const probabilityX = inverseNormalCdf(Number(x) / 100);
    return pad.left + ((probabilityX - minX) / (maxX - minX)) * plotWidth;
  };
  const yScale = (y) => pad.top + plotHeight - ((y - minY) / (maxY - minY || 1)) * plotHeight;
  const theoryLine = theoreticalPoints
    .map((p, index) => `${index === 0 ? 'M' : 'L'} ${xScale(Number(p.frequency)).toFixed(2)} ${yScale(Number(p.outputKw) / 10000).toFixed(2)}`)
    .join(' ');
  const empiricalDots = empiricalPoints.map((p) => {
    const x = xScale(Number(p.frequency));
    const y = yScale(Number(p.outputKw) / 10000);
    return `<circle cx="${x}" cy="${y}" r="3" fill="#f97316" opacity="0.78"><title>${p.year}: ${fmt(Number(p.outputKw) / 10000, 2)} 万kW, P=${fmt(p.frequency, 3)}%</title></circle>`;
  }).join('');
  const designPoint = theoreticalPoints.reduce((closest, point) => (
    Math.abs(Number(point.frequency) - designGuaranteeRate) < Math.abs(Number(closest.frequency) - designGuaranteeRate) ? point : closest
  ), theoreticalPoints[0] || empiricalPoints[0]);
  const designX = xScale(designGuaranteeRate);
  const designY = designPoint ? yScale(Number(designPoint.outputKw) / 10000) : pad.top;
  const xTicks = [1, 5, 10, 20, 50, 75, 90, 95, 99].map((tick) => `
    <line x1="${xScale(tick)}" y1="${pad.top}" x2="${xScale(tick)}" y2="${pad.top + plotHeight}" stroke="#edf2f6"></line>
    <text x="${xScale(tick)}" y="${height - 22}" text-anchor="middle" font-size="12" fill="#64748b">${tick}</text>
  `).join('');
  const yTicks = Array.from({ length: 5 }, (_, i) => minY + ((maxY - minY) / 4) * i).map((tick) => `
    <line x1="${pad.left}" y1="${yScale(tick)}" x2="${width - pad.right}" y2="${yScale(tick)}" stroke="#edf2f6"></line>
    <text x="${pad.left - 10}" y="${yScale(tick) + 4}" text-anchor="end" font-size="12" fill="#64748b">${fmt(tick, 1)}</text>
  `).join('');
  return `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" role="img">
      <rect x="0" y="0" width="${width}" height="${height}" fill="#fff"></rect>
      ${xTicks}
      ${yTicks}
      <line x1="${pad.left}" y1="${pad.top + plotHeight}" x2="${width - pad.right}" y2="${pad.top + plotHeight}" stroke="#9fb3c1"></line>
      <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + plotHeight}" stroke="#9fb3c1"></line>
      <line x1="${designX}" y1="${pad.top}" x2="${designX}" y2="${pad.top + plotHeight}" stroke="#ef4444" stroke-dasharray="5 5"></line>
      ${designPoint ? `<circle cx="${designX}" cy="${designY}" r="4" fill="#ef4444"><title>设计保证率 ${fmt(designGuaranteeRate, 1)}%: ${fmt(Number(designPoint.outputKw) / 10000, 4)} 万kW</title></circle>` : ''}
      <path d="${theoryLine}" fill="none" stroke="#0f6b8f" stroke-width="2.5"></path>
      ${empiricalDots}
      <text x="${designX + 6}" y="${pad.top + 14}" font-size="12" fill="#ef4444">P=${fmt(designGuaranteeRate, 1)}%</text>
      <circle cx="${width - 172}" cy="18" r="4" fill="#f97316" opacity="0.78"></circle>
      <text x="${width - 162}" y="22" font-size="12" fill="#64748b">经验点</text>
      <line x1="${width - 92}" y1="18" x2="${width - 62}" y2="18" stroke="#0f6b8f" stroke-width="2.5"></line>
      <text x="${width - 54}" y="22" font-size="12" fill="#64748b">P-III理论线</text>
      <text x="${width / 2}" y="${height - 6}" text-anchor="middle" font-size="12" fill="#31475c">保证率 P (%)，概率格纸坐标</text>
      <text x="18" y="${height / 2}" text-anchor="middle" font-size="12" fill="#31475c" transform="rotate(-90 18 ${height / 2})">年保证出力 (万kW)</text>
    </svg>
  `;
}

async function renderGuaranteedOutputPanel() {
  const status = await api('/api/calc/status');
  const availableSchemeIds = status.deadWaterAvailableSchemeIds || [];
  const available = state.schemeConfig.schemes
    .filter((scheme) => availableSchemeIds.includes(scheme.id));
  document.getElementById('hydropowerSubmoduleBody').innerHTML = `
    <div class="data-toolbar">
      <div>
        <h3>保证出力计算</h3>
        <p>保证出力依赖死水位成果。没有死水位计算结果的方案不会出现在下拉框中。</p>
      </div>
      <div class="toolbar-actions">
        <label>
          当前方案
          <select id="guaranteedSchemeSelect">
            ${available.map((scheme) => `
              <option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>
            `).join('')}
          </select>
        </label>
        <button id="runGuaranteedBtn">开始计算</button>
      </div>
    </div>
    <div id="guaranteedOutputResult" class="result-placeholder">
      ${available.length
        ? '尚未计算。请选择已有死水位成果的方案并点击“开始计算”。'
        : '当前没有可计算方案。请先进入“死水位计算”，对目标方案点击“开始计算”。'}
    </div>
  `;
  document.getElementById('runGuaranteedBtn').disabled = available.length === 0;
  document.getElementById('runGuaranteedBtn').addEventListener('click', runGuaranteedOutputCalculation);
}

async function runGuaranteedOutputCalculation() {
  const select = document.getElementById('guaranteedSchemeSelect');
  const schemeId = select.value;
  const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/guaranteed-output?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.guaranteedOutputResult = data;
  const result = data.result;
  const cards = [
    ['死水位', fmt(result['死水位_m'], 2, ' m')],
    ['保证出力', fmt(result['保证出力_万kW'], 4, ' 万kW')],
    ['年保证出力均值', fmt(Number(result['年保证出力均值_kW']) / 10000, 4, ' 万kW')],
    ['偏态系数 Cs', fmt(result['年保证出力偏态系数Cs'], 4)],
  ];
  document.getElementById('guaranteedOutputResult').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="section-heading">
      <h4>保证出力排频曲线</h4>
    </div>
    <div class="mini-chart frequency-chart">${frequencyCurveChart(data.frequencyCurve)}</div>
    <div class="summary-grid">
      ${cards.map(([label, value]) => `
        <div class="info-tile">
          <span>${label}</span>
          <strong>${value}</strong>
        </div>
      `).join('')}
    </div>
    <div class="section-heading">
      <h4>计算结果表</h4>
      <a href="/api/download?path=${encodeURIComponent(data.downloads.resultTable)}"><button class="secondary">导出结果表</button></a>
    </div>
    ${objectTable([result])}
    <details class="process-details" open>
      <summary>查看年保证出力频率表（${data.processRows.length} 行）</summary>
      <div class="section-heading">
        <span></span>
        <a href="/api/download?path=${encodeURIComponent(data.downloads.processTable)}"><button class="secondary">导出过程表</button></a>
      </div>
      ${objectTable(data.processRows)}
    </details>
  `;
}

async function renderInstalledCapacityPanel() {
  const status = await api('/api/calc/status');
  const availableSchemeIds = status.guaranteedOutputAvailableSchemeIds || [];
  const available = state.schemeConfig.schemes
    .filter((scheme) => availableSchemeIds.includes(scheme.id));
  document.getElementById('hydropowerSubmoduleBody').innerHTML = `
    <div class="data-toolbar">
      <div>
        <h3>水电站装机容量</h3>
        <p>本节计算必须容量，依赖保证出力成果。没有保证出力计算结果的方案不会出现在下拉框中。</p>
      </div>
      <div class="toolbar-actions">
        <label>
          当前方案
          <select id="installedSchemeSelect">
            ${available.map((scheme) => `
              <option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>
            `).join('')}
          </select>
        </label>
        <button id="runInstalledBtn">开始计算</button>
      </div>
    </div>
    <div id="installedCapacityResult" class="result-placeholder">
      ${available.length
        ? '尚未计算。请选择已有保证出力成果的方案并点击“开始计算”。'
        : '当前没有可计算方案。请先进入“保证出力计算”，对目标方案点击“开始计算”。'}
    </div>
  `;
  document.getElementById('runInstalledBtn').disabled = available.length === 0;
  document.getElementById('runInstalledBtn').addEventListener('click', runInstalledCapacityCalculation);
}

async function runInstalledCapacityCalculation() {
  const select = document.getElementById('installedSchemeSelect');
  const schemeId = select.value;
  const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/installed-capacity?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.installedCapacityResult = data;
  const result = data.result;
  const cards = [
    ['保证出力', fmt(result['保证出力_万kW'], 4, ' 万kW')],
    ['航运基荷工作容量', fmt(result['航运基荷工作容量_万kW'], 4, ' 万kW')],
    ['峰荷保证出力', fmt(result['峰荷保证出力_万kW'], 4, ' 万kW')],
    ['峰荷工作容量', fmt(result['峰荷工作容量_万kW'], 4, ' 万kW')],
    ['工作容量', fmt(result['工作容量_万kW'], 4, ' 万kW')],
    ['备用容量', fmt(result['备用容量_万kW'], 4, ' 万kW')],
    ['必须容量', fmt(result['必须容量_万kW'], 4, ' 万kW')],
  ];
  document.getElementById('installedCapacityResult').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="summary-grid">
      ${cards.map(([label, value]) => `
        <div class="info-tile">
          <span>${label}</span>
          <strong>${value}</strong>
        </div>
      `).join('')}
    </div>
    <div class="section-heading">
      <h4>必须容量计算表</h4>
      <a href="/api/download?path=${encodeURIComponent(data.downloads.requiredTable)}"><button class="secondary">导出必须容量表</button></a>
    </div>
    ${objectTable([result])}
    <details class="process-details" open>
      <summary>计算关系说明</summary>
      ${objectTable(data.requiredCapacityRows)}
      <div class="formula-list">
        <p>峰荷保证出力 = 保证出力 - 航运基荷工作容量</p>
        <p>峰荷工作容量 = 3.08 × 峰荷保证出力 + 7.0</p>
        <p>工作容量 = 航运基荷工作容量 + 峰荷工作容量</p>
        <p>必须容量 = 工作容量 + 备用容量</p>
      </div>
    </details>
  `;
}

async function renderDispatchChartPanel() {
  const status = await api('/api/calc/status');
  const availableSchemeIds = status.guaranteedOutputAvailableSchemeIds || [];
  const available = state.schemeConfig.schemes
    .filter((scheme) => availableSchemeIds.includes(scheme.id));
  document.getElementById('hydropowerSubmoduleBody').innerHTML = `
    <div class="data-toolbar">
      <div>
        <h3>水电站调度图绘制</h3>
        <p>调度图依赖保证出力成果。未完成保证出力计算的方案不会出现在下拉框中。</p>
      </div>
      <div class="toolbar-actions">
        <label>
          当前方案
          <select id="dispatchSchemeSelect">
            ${available.map((scheme) => `
              <option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>
            `).join('')}
          </select>
        </label>
        <button id="runDispatchBtn">开始绘制</button>
      </div>
    </div>
    <div id="dispatchChartResult" class="result-placeholder">
      ${available.length
        ? '尚未绘制。请选择已有保证出力成果的方案并点击“开始绘制”。'
        : '当前没有可绘制方案。请先完成目标方案的保证出力计算。'}
    </div>
  `;
  document.getElementById('runDispatchBtn').disabled = available.length === 0;
  document.getElementById('runDispatchBtn').addEventListener('click', runDispatchChartCalculation);
}

async function runDispatchChartCalculation() {
  const select = document.getElementById('dispatchSchemeSelect');
  const schemeId = select.value;
  const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/dispatch-chart?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.dispatchChartResult = data;
  const summary = data.summary;
  const rows = data.tables.lines || [];
  document.getElementById('dispatchChartResult').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="summary-grid">
      <div class="info-tile"><span>正常蓄水位</span><strong>${fmt(summary['正常蓄水位_m'], 2, ' m')}</strong></div>
      <div class="info-tile"><span>防洪限制水位</span><strong>${fmt(summary['防洪限制水位_m'], 3, ' m')}</strong></div>
      <div class="info-tile"><span>防破坏线最低水位</span><strong>${fmt(summary['防破坏线最低水位_m'], 3, ' m')}</strong></div>
      <div class="info-tile"><span>防破坏线最高水位</span><strong>${fmt(summary['防破坏线最高水位_m'], 3, ' m')}</strong></div>
    </div>
    <div class="section-heading"><h4>水电站调度图</h4></div>
    <div class="svg-chart dispatch-chart">${data.chartSvg}</div>
    <div class="section-heading"><h4>计算表格</h4></div>
    <div class="table-switcher">
      <div class="toolbar-actions">
        <label>输出表格
          <select id="dispatchTableSelect"><option value="lines">调度图线计算表</option></select>
        </label>
        <button class="secondary" id="downloadDispatchTableBtn">导出当前表格</button>
      </div>
      <div class="selected-table-title">调度图线计算表（${rows.length} 行）</div>
      ${objectTable(rows)}
    </div>
  `;
  document.getElementById('downloadDispatchTableBtn').addEventListener('click', () => {
    downloadRowsAsCsv(rows, `dispatch_chart_lines_${level}m.csv`);
  });
}

async function renderRepeatedCapacityPanel() {
  const status = await api('/api/calc/status');
  const availableSchemeIds = status.dispatchChartSchemeIds || [];
  const available = state.schemeConfig.schemes
    .filter((scheme) => availableSchemeIds.includes(scheme.id));
  document.getElementById('hydropowerSubmoduleBody').innerHTML = `
    <div class="data-toolbar">
      <div>
        <h3>重复容量计算</h3>
        <p>采用DP方法计算多年平均电能，并根据N-h曲线与2500 h交点确定重复容量。</p>
      </div>
      <div class="toolbar-actions">
        <label>当前方案
          <select id="repeatedSchemeSelect">
            ${available.map((scheme) => `
              <option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>
            `).join('')}
          </select>
        </label>
        <label>定线方式
          <select id="repeatedFitMode">
            <option value="machine">机器定线（二次函数）</option>
            <option value="manual">人工定线</option>
          </select>
        </label>
        <label>ΔN（万kW）
          <input id="repeatedDeltaN" type="number" value="15" min="0.1" step="0.1" />
        </label>
        <button id="runRepeatedBtn">开始计算</button>
      </div>
    </div>
    <div id="repeatedCapacityResult" class="result-placeholder">
      ${available.length
        ? '尚未计算。请选择方案和定线方式后点击“开始计算”。'
        : '当前没有可计算方案。请先完成目标方案的水电站调度图绘制。'}
    </div>
  `;
  document.getElementById('runRepeatedBtn').disabled = available.length === 0;
  document.getElementById('runRepeatedBtn').addEventListener('click', runRepeatedCapacityCalculation);
}

async function runRepeatedCapacityCalculation() {
  const select = document.getElementById('repeatedSchemeSelect');
  const schemeId = select.value;
  const level = Number(select.selectedOptions[0].dataset.level);
  const mode = document.getElementById('repeatedFitMode').value;
  const deltaN = Number(document.getElementById('repeatedDeltaN').value);
  if (!Number.isFinite(deltaN) || deltaN <= 0) {
    toast('ΔN必须大于0');
    return;
  }
  const runButton = document.getElementById('runRepeatedBtn');
  runButton.disabled = true;
  runButton.textContent = 'DP计算中...';
  let data;
  try {
    data = await api(`/api/calc/repeated-capacity?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}&mode=${encodeURIComponent(mode)}&deltaN=${encodeURIComponent(deltaN)}`);
  } finally {
    runButton.disabled = false;
    runButton.textContent = '开始计算';
  }
  state.repeatedCapacityResult = data;
  const result = data.result;
  document.getElementById('repeatedCapacityResult').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="summary-grid">
      <div class="info-tile"><span>定线方式</span><strong>${result['定线方式']}</strong></div>
      <div class="info-tile"><span>ΔN</span><strong>${fmt(result['delta_N_万kW'], 3, ' 万kW')}</strong></div>
      <div class="info-tile"><span>2500 h对应重复容量</span><strong>${fmt(result['2500h对应重复容量_万kW'], 4, ' 万kW')}</strong></div>
      <div class="info-tile"><span>人工控制点</span><strong>${result['控制点数量']}</strong></div>
    </div>
    <div class="section-heading">
      <h4>N-h曲线与定线结果</h4>
      ${data.mode === 'manual' ? `
        <div class="toolbar-actions">
          <button class="secondary" id="undoManualPointBtn">撤销控制点</button>
          <button class="secondary" id="clearManualPointsBtn">清空并采用机器拟合</button>
          <button id="acceptManualFitBtn">确认人工定线</button>
        </div>
      ` : ''}
      <button id="confirmRepeatedFitBtn">确认为定线成果</button>
    </div>
    ${data.mode === 'manual' ? '<div class="note manual-fit-note">在图内点击添加控制点；2点为直线，3点及以上为保形曲线。控制点需覆盖2500 h才能读取交点。</div>' : ''}
    <div id="repeatedFitChart" class="svg-chart repeated-capacity-chart">${data.chartSvg}</div>
    <div class="section-heading"><h4>装机容量与多年平均电能关系</h4></div>
    <div class="svg-chart repeated-capacity-chart">${capacityEnergyFitChart(data.tables.energySummary)}</div>
    <div class="section-heading"><h4>计算表格</h4></div>
    <div class="table-switcher">
      <div class="toolbar-actions">
        <label>输出表格
          <select id="repeatedTableSelect">
            <option value="fit">定线及2500 h交点成果表</option>
            <option value="energySummary">多年平均电能计算表</option>
            <option value="energyProcess">多年平均电能逐月DP过程表</option>
            <option value="runoffUtilization">径流利用系数成果表</option>
          </select>
        </label>
        <button class="secondary" id="downloadRepeatedTableBtn">导出当前表格</button>
      </div>
      <div id="repeatedSelectedTable"></div>
    </div>
  `;
  renderRepeatedSelectedTable();
  document.getElementById('repeatedTableSelect').addEventListener('change', renderRepeatedSelectedTable);
  document.getElementById('downloadRepeatedTableBtn').addEventListener('click', downloadSelectedRepeatedTable);
  initializeManualFitEditor(data);
}

function solveQuadraticFit(points, xKey = '重复容量_万kW', yKey = '利用小时数_h') {
  const sums = points.reduce((acc, point) => {
    const x = Number(point[xKey]);
    const y = Number(point[yKey]);
    acc.n += 1; acc.x += x; acc.x2 += x ** 2; acc.x3 += x ** 3; acc.x4 += x ** 4;
    acc.y += y; acc.xy += x * y; acc.x2y += x ** 2 * y;
    return acc;
  }, { n: 0, x: 0, x2: 0, x3: 0, x4: 0, y: 0, xy: 0, x2y: 0 });
  const matrix = [
    [sums.x4, sums.x3, sums.x2, sums.x2y],
    [sums.x3, sums.x2, sums.x, sums.xy],
    [sums.x2, sums.x, sums.n, sums.y],
  ];
  for (let col = 0; col < 3; col += 1) {
    let pivot = col;
    for (let row = col + 1; row < 3; row += 1) if (Math.abs(matrix[row][col]) > Math.abs(matrix[pivot][col])) pivot = row;
    [matrix[col], matrix[pivot]] = [matrix[pivot], matrix[col]];
    const divisor = matrix[col][col];
    for (let j = col; j < 4; j += 1) matrix[col][j] /= divisor;
    for (let row = 0; row < 3; row += 1) {
      if (row === col) continue;
      const factor = matrix[row][col];
      for (let j = col; j < 4; j += 1) matrix[row][j] -= factor * matrix[col][j];
    }
  }
  return matrix.map((row) => row[3]);
}

function capacityEnergyFitChart(rows) {
  if (!rows || rows.length < 3) return '<p>至少需要3个计算点才能拟合曲线。</p>';
  const width = 900; const height = 500;
  const pad = { left: 82, right: 30, top: 30, bottom: 58 };
  const points = rows.map((row) => [Number(row['装机容量_万kW']), Number(row['多年平均年发电量_亿kWh'])]);
  const coefficients = solveQuadraticFit(rows, '装机容量_万kW', '多年平均年发电量_亿kWh');
  const rawMinX = Math.min(...points.map(([x]) => x));
  const rawMaxX = Math.max(...points.map(([x]) => x));
  const rawMinY = Math.min(...points.map(([, y]) => y));
  const rawMaxY = Math.max(...points.map(([, y]) => y));
  const xPadding = Math.max((rawMaxX - rawMinX) * 0.05, 1);
  const yPadding = Math.max((rawMaxY - rawMinY) * 0.12, 0.2);
  const minX = rawMinX - xPadding; const maxX = rawMaxX + xPadding;
  const minY = rawMinY - yPadding; const maxY = rawMaxY + yPadding;
  const xScale = (x) => pad.left + ((x - minX) / (maxX - minX)) * (width - pad.left - pad.right);
  const yScale = (y) => height - pad.bottom - ((y - minY) / (maxY - minY)) * (height - pad.top - pad.bottom);
  const ticks = Array.from({ length: 6 }, (_, i) => i / 5);
  const grid = ticks.map((ratio) => {
    const x = minX + ratio * (maxX - minX);
    const y = minY + ratio * (maxY - minY);
    return `<line x1="${xScale(x)}" y1="${pad.top}" x2="${xScale(x)}" y2="${height - pad.bottom}" stroke="#e5e7eb"/>
      <text x="${xScale(x)}" y="${height - pad.bottom + 22}" text-anchor="middle" font-size="12" fill="#64748b">${fmt(x, 1)}</text>
      <line x1="${pad.left}" y1="${yScale(y)}" x2="${width - pad.right}" y2="${yScale(y)}" stroke="#e5e7eb"/>
      <text x="${pad.left - 9}" y="${yScale(y) + 4}" text-anchor="end" font-size="12" fill="#64748b">${fmt(y, 2)}</text>`;
  }).join('');
  const curve = Array.from({ length: 241 }, (_, i) => {
    const x = rawMinX + (i / 240) * (rawMaxX - rawMinX);
    const y = coefficients[0] * x ** 2 + coefficients[1] * x + coefficients[2];
    return `${i ? 'L' : 'M'} ${xScale(x).toFixed(2)} ${yScale(y).toFixed(2)}`;
  }).join(' ');
  const dots = points.map(([x, y]) => `<circle cx="${xScale(x)}" cy="${yScale(y)}" r="4" fill="#f97316"><title>装机容量=${fmt(x, 3)}万kW，年电能=${fmt(y, 4)}亿kWh</title></circle>`).join('');
  return `<svg viewBox="0 0 ${width} ${height}" role="img">
    <rect width="${width}" height="${height}" fill="#fff"/>${grid}
    <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" stroke="#64748b"/>
    <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#64748b"/>
    <path d="${curve}" fill="none" stroke="#0f6b8f" stroke-width="2.6"/>${dots}
    <circle cx="${width - 205}" cy="18" r="4" fill="#f97316"/><text x="${width - 195}" y="22" font-size="12" fill="#64748b">DP计算点</text>
    <line x1="${width - 112}" y1="18" x2="${width - 82}" y2="18" stroke="#0f6b8f" stroke-width="2.6"/><text x="${width - 74}" y="22" font-size="12" fill="#64748b">二次拟合</text>
    <text x="${width / 2}" y="${height - 10}" text-anchor="middle" font-size="14">装机容量（万kW）</text>
    <text x="18" y="${height / 2}" text-anchor="middle" font-size="14" transform="rotate(-90 18 ${height / 2})">多年平均年发电量（亿kWh）</text>
  </svg>`;
}

function pchipCurve(controlPoints, samples = 180) {
  const byX = new Map();
  controlPoints.forEach(([x, y]) => {
    const key = Number(x.toFixed(6));
    const values = byX.get(key) || [];
    values.push(y); byX.set(key, values);
  });
  const points = [...byX.entries()].map(([x, ys]) => [x, ys.reduce((a, b) => a + b, 0) / ys.length]).sort((a, b) => a[0] - b[0]);
  if (points.length < 2) return [];
  if (points.length === 2) return Array.from({ length: samples }, (_, i) => {
    const t = i / (samples - 1);
    return [points[0][0] + t * (points[1][0] - points[0][0]), points[0][1] + t * (points[1][1] - points[0][1])];
  });
  const h = points.slice(0, -1).map((p, i) => points[i + 1][0] - p[0]);
  const delta = h.map((step, i) => (points[i + 1][1] - points[i][1]) / step);
  const slopes = Array(points.length).fill(0);
  slopes[0] = delta[0]; slopes[slopes.length - 1] = delta[delta.length - 1];
  for (let i = 1; i < points.length - 1; i += 1) {
    if (delta[i - 1] * delta[i] <= 0) slopes[i] = 0;
    else slopes[i] = (h[i - 1] + h[i]) / ((h[i - 1] / delta[i - 1]) + (h[i] / delta[i]));
  }
  return Array.from({ length: samples }, (_, sample) => {
    const x = points[0][0] + (sample / (samples - 1)) * (points.at(-1)[0] - points[0][0]);
    let i = points.length - 2;
    while (i > 0 && x < points[i][0]) i -= 1;
    const t = (x - points[i][0]) / h[i];
    const y = (2 * t ** 3 - 3 * t ** 2 + 1) * points[i][1]
      + (t ** 3 - 2 * t ** 2 + t) * h[i] * slopes[i]
      + (-2 * t ** 3 + 3 * t ** 2) * points[i + 1][1]
      + (t ** 3 - t ** 2) * h[i] * slopes[i + 1];
    return [x, y];
  });
}

function initializeManualFitEditor(data) {
  const isManual = data.mode === 'manual';
  data.manualFitAccepted = false;
  const sourcePoints = data.tables.energySummary;
  const excludedByLevel = { 115: [30, 40], 108: [20, 30], 100: [30] };
  const excluded = excludedByLevel[Number(data.level)] || [];
  const fitPoints = sourcePoints.filter((row) => !excluded.includes(Number(row['重复容量_万kW'])));
  const controlPoints = [];
  const width = 900; const height = 520;
  const pad = { left: 72, right: 28, top: 30, bottom: 58 };
  const rawMaxHours = Math.max(2800, ...sourcePoints.map((row) => Number(row['利用小时数_h']))) * 1.04;
  const maxHours = Math.ceil(rawMaxHours / 500) * 500;
  const rawMaxCapacity = Math.max(...sourcePoints.map((row) => Number(row['重复容量_万kW']))) + 8;
  const yTickStep = rawMaxCapacity <= 50 ? 10 : 20;
  const maxCapacity = Math.ceil(rawMaxCapacity / yTickStep) * yTickStep;
  const xScale = (x) => pad.left + (x / maxHours) * (width - pad.left - pad.right);
  const yScale = (y) => height - pad.bottom - (y / maxCapacity) * (height - pad.top - pad.bottom);
  const xValue = (px) => ((px - pad.left) / (width - pad.left - pad.right)) * maxHours;
  const yValue = (py) => ((height - pad.bottom - py) / (height - pad.top - pad.bottom)) * maxCapacity;
  const coefficients = solveQuadraticFit(fitPoints);

  const draw = () => {
    let curve;
    let target = Number(data.machineTarget);
    if (controlPoints.length >= 2) {
      curve = pchipCurve(controlPoints);
      const ordered = [...controlPoints].sort((a, b) => a[0] - b[0]);
      target = ordered[0][0] <= 2500 && ordered.at(-1)[0] >= 2500
        ? pchipCurve(controlPoints, 1001).reduce((best, p) => Math.abs(p[0] - 2500) < Math.abs(best[0] - 2500) ? p : best)[1]
        : null;
    } else {
      curve = Array.from({ length: 220 }, (_, i) => {
        const capacity = (i / 219) * Math.max(...sourcePoints.map((row) => Number(row['重复容量_万kW'])));
        return [coefficients[0] * capacity ** 2 + coefficients[1] * capacity + coefficients[2], capacity];
      }).filter(([hours, capacity]) => hours >= 0 && hours <= maxHours && capacity >= 0);
    }
    const path = curve.map(([x, y], i) => `${i ? 'L' : 'M'} ${xScale(x).toFixed(2)} ${yScale(y).toFixed(2)}`).join(' ');
    const sourceDots = sourcePoints.map((row) => `<circle cx="${xScale(Number(row['利用小时数_h']))}" cy="${yScale(Number(row['重复容量_万kW']))}" r="4" fill="#111827"><title>N=${row['重复容量_万kW']}万kW, h=${row['利用小时数_h']}</title></circle>`).join('');
    const controls = controlPoints.map(([x, y], i) => `<circle cx="${xScale(x)}" cy="${yScale(y)}" r="5" fill="#16a34a"><title>控制点${i + 1}: h=${fmt(x, 1)}, N=${fmt(y, 2)}</title></circle>`).join('');
    const xTickStep = 500;
    const xTicks = Array.from({ length: Math.floor(maxHours / xTickStep) + 1 }, (_, i) => i * xTickStep)
      .map((tick) => `<line x1="${xScale(tick)}" y1="${pad.top}" x2="${xScale(tick)}" y2="${height - pad.bottom}" stroke="#e5e7eb"/><text x="${xScale(tick)}" y="${height - pad.bottom + 22}" text-anchor="middle" font-size="12" fill="#64748b">${tick}</text>`).join('');
    const yTicks = Array.from({ length: Math.floor(maxCapacity / yTickStep) + 1 }, (_, i) => i * yTickStep)
      .map((tick) => `<line x1="${pad.left}" y1="${yScale(tick)}" x2="${width - pad.right}" y2="${yScale(tick)}" stroke="#e5e7eb"/><text x="${pad.left - 10}" y="${yScale(tick) + 4}" text-anchor="end" font-size="12" fill="#64748b">${tick}</text>`).join('');
    document.getElementById('repeatedFitChart').innerHTML = `
      <svg id="manualFitSvg" viewBox="0 0 ${width} ${height}" role="img" tabindex="0">
        <rect width="${width}" height="${height}" fill="#fff"/>
        ${xTicks}${yTicks}
        <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#64748b"/>
        <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" stroke="#64748b"/>
        <line x1="${xScale(2500)}" y1="${pad.top}" x2="${xScale(2500)}" y2="${height - pad.bottom}" stroke="#dc2626" stroke-dasharray="6 5"/>
        <text x="${xScale(2500) + 6}" y="${pad.top + 14}" fill="#dc2626" font-size="13">2500 h</text>
        <path d="${path}" fill="none" stroke="#0f6b8f" stroke-width="2.5"/>
        ${sourceDots}${controls}
        ${target == null ? '' : `<line x1="${pad.left}" y1="${yScale(target)}" x2="${xScale(2500)}" y2="${yScale(target)}" stroke="#16a34a" stroke-dasharray="5 4"/><text x="${xScale(2500) + 7}" y="${yScale(target) - 5}" fill="#15803d" font-size="13">N=${fmt(target, 4)}万kW</text>`}
        <text x="${width / 2}" y="${height - 12}" text-anchor="middle" font-size="14">利用小时数 h</text>
        <text x="18" y="${height / 2}" text-anchor="middle" font-size="14" transform="rotate(-90 18 ${height / 2})">重复容量 N（万kW）</text>
      </svg>`;
    data.manualControlPoints = controlPoints.map(([hours, capacity]) => ({ 利用小时数_h: Number(hours.toFixed(4)), 重复容量_万kW: Number(capacity.toFixed(4)) }));
    data.manualTarget = target;
    document.querySelector('#repeatedCapacityResult .summary-grid .info-tile:nth-child(3) strong').textContent = target == null ? '无交点' : fmt(target, 4, ' 万kW');
    document.querySelector('#repeatedCapacityResult .summary-grid .info-tile:nth-child(4) strong').textContent = controlPoints.length || '系统拟合';
    if (!isManual) return;
    document.getElementById('manualFitSvg').addEventListener('click', (event) => {
      event.currentTarget.focus();
      const rect = event.currentTarget.getBoundingClientRect();
      const px = ((event.clientX - rect.left) / rect.width) * width;
      const py = ((event.clientY - rect.top) / rect.height) * height;
      if (px < pad.left || px > width - pad.right || py < pad.top || py > height - pad.bottom) return;
      controlPoints.push([xValue(px), Math.max(0, yValue(py))]); data.manualFitAccepted = false; draw();
    });
    document.getElementById('manualFitSvg').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') document.getElementById('acceptManualFitBtn').click();
      if ((event.key === 'Backspace' || event.key === 'Delete') && controlPoints.length) {
        event.preventDefault(); controlPoints.pop(); data.manualFitAccepted = false; draw();
      }
    });
  };
  if (isManual) {
    document.getElementById('undoManualPointBtn').addEventListener('click', () => { controlPoints.pop(); data.manualFitAccepted = false; draw(); });
    document.getElementById('clearManualPointsBtn').addEventListener('click', () => { controlPoints.length = 0; data.manualFitAccepted = false; draw(); });
    document.getElementById('acceptManualFitBtn').addEventListener('click', () => {
      const acceptedTarget = data.manualTarget == null ? 0 : data.manualTarget;
      data.result['2500h对应重复容量_万kW'] = acceptedTarget;
      data.result['控制点数量'] = controlPoints.length;
      data.tables.fit = [{ ...data.result }];
      data.manualFitAccepted = true;
      document.querySelector('#repeatedCapacityResult .summary-grid .info-tile:nth-child(3) strong').textContent = fmt(acceptedTarget, 4, ' 万kW');
      renderRepeatedSelectedTable();
      toast(data.manualTarget == null ? '人工曲线与2500 h无交点，重复容量按0计' : '人工定线已确认');
    });
  }
  document.getElementById('confirmRepeatedFitBtn').addEventListener('click', async () => {
    if (isManual && !data.manualFitAccepted) {
      toast('请先点击“确认人工定线”');
      return;
    }
    const repeatedCapacity = Number(data.result['2500h对应重复容量_万kW']);
    await api('/api/calc/repeated-capacity/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schemeId: data.schemeId,
        level: data.level,
        mode: data.mode,
        deltaN: Number(data.result['delta_N_万kW']),
        repeatedCapacity,
        controlPoints: data.manualControlPoints || [],
      }),
    });
    const button = document.getElementById('confirmRepeatedFitBtn');
    button.textContent = '已确认为定线成果';
    button.disabled = true;
    toast('已保存为该方案的定线成果');
  });
  draw();
}

function repeatedTableMeta(key) {
  const data = state.repeatedCapacityResult;
  const suffix = `${data?.level ?? 'scheme'}m_${data?.mode ?? 'fit'}`;
  const labels = {
    fit: ['定线及2500 h交点成果表', `repeated_capacity_fit_${suffix}.csv`],
    energySummary: ['多年平均电能计算表', `average_annual_energy_${suffix}.csv`],
    energyProcess: ['多年平均电能逐月DP过程表', `average_annual_energy_dp_process_${suffix}.csv`],
    runoffUtilization: ['径流利用系数成果表', `runoff_utilization_${suffix}.csv`],
  };
  return labels[key] || labels.fit;
}

function renderRepeatedSelectedTable() {
  const key = document.getElementById('repeatedTableSelect')?.value || 'fit';
  const rows = state.repeatedCapacityResult?.tables?.[key] || [];
  const [label] = repeatedTableMeta(key);
  document.getElementById('repeatedSelectedTable').innerHTML = `
    <div class="selected-table-title">${label}（${rows.length} 行）</div>
    ${objectTable(rows)}
  `;
}

function downloadSelectedRepeatedTable() {
  const key = document.getElementById('repeatedTableSelect')?.value || 'fit';
  const rows = state.repeatedCapacityResult?.tables?.[key] || [];
  const [, filename] = repeatedTableMeta(key);
  downloadRowsAsCsv(rows, filename);
}

function renderFloodModule() {
  const submodules = [
    ['dischargeCapacity', '泄流能力曲线'],
    ['floodRouting', '水库调洪演算'],
    ['damCrest', '坝顶高程确定'],
  ];
  document.getElementById('moduleBody').innerHTML = `
    <div class="subtabs">
      ${submodules.map(([id, label]) => `
        <button class="subtab ${state.floodSubmodule === id ? 'active' : ''}" data-flood-submodule="${id}">${label}</button>
      `).join('')}
    </div>
    <div id="floodSubmoduleBody"></div>
  `;
  document.querySelectorAll('[data-flood-submodule]').forEach((button) => {
    button.addEventListener('click', () => {
      state.floodSubmodule = button.dataset.floodSubmodule;
      renderFloodModule();
    });
  });
  if (state.floodSubmodule === 'dischargeCapacity') renderDischargeCapacityPanel();
  else if (state.floodSubmodule === 'floodRouting') renderFloodRoutingPanel();
  else renderDamCrestPanel();
}

async function renderDischargeCapacityPanel() {
  const status = await api('/api/calc/status');
  const availableSchemeIds = status.dispatchChartSchemeIds || [];
  const available = state.schemeConfig.schemes.filter((scheme) => availableSchemeIds.includes(scheme.id));
  document.getElementById('floodSubmoduleBody').innerHTML = `
    <div class="data-toolbar">
      <div>
        <h3>泄流能力曲线</h3>
        <p>根据当前方案的溢洪坝和中孔参数，计算不同库水位下的总泄流能力。</p>
      </div>
      <div class="toolbar-actions">
        <label>当前方案
          <select id="dischargeSchemeSelect">
            ${available.map((scheme) => `<option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>`).join('')}
          </select>
        </label>
        <button id="runDischargeBtn">开始计算</button>
      </div>
    </div>
    <div id="dischargeCapacityResult" class="result-placeholder">
      ${available.length ? '尚未计算。请选择方案并点击“开始计算”。' : '当前没有可计算方案。请先完成目标方案的水电站调度图。'}
    </div>
  `;
  document.getElementById('runDischargeBtn').disabled = available.length === 0;
  document.getElementById('runDischargeBtn').addEventListener('click', runDischargeCapacityCalculation);
}

async function runDischargeCapacityCalculation() {
  const select = document.getElementById('dischargeSchemeSelect');
  const schemeId = select.value;
  const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/discharge-capacity?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.dischargeCapacityResult = data;
  const summary = data.summary;
  const rows = data.tables.capacity || [];
  document.getElementById('dischargeCapacityResult').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="summary-grid">
      <div class="info-tile"><span>防洪限制水位</span><strong>${fmt(summary['防洪限制水位_m'], 3, ' m')}</strong></div>
      <div class="info-tile"><span>曲线计算范围</span><strong>${fmt(summary['曲线起点水位_m'], 1)}–${fmt(summary['曲线终点水位_m'], 1)} m</strong></div>
      <div class="info-tile"><span>起点泄流能力</span><strong>${fmt(summary['防洪限制水位泄流能力_m3s'], 2, ' m³/s')}</strong></div>
      <div class="info-tile"><span>最大计算泄流能力</span><strong>${fmt(summary['最大计算泄流能力_m3s'], 2, ' m³/s')}</strong></div>
    </div>
    <div class="section-heading"><h4>泄流能力曲线</h4></div>
    <div class="svg-chart discharge-capacity-chart">${dischargeCapacityChart(rows)}</div>
    <details class="process-details">
      <summary>查看泄洪建筑物参数</summary>
      ${objectTable([data.facility])}
    </details>
    <div class="section-heading"><h4>计算表格</h4></div>
    <div class="table-switcher">
      <div class="toolbar-actions">
        <label>输出表格<select><option>泄流能力计算表</option></select></label>
        <button class="secondary" id="downloadDischargeTableBtn">导出当前表格</button>
      </div>
      <div class="selected-table-title">泄流能力计算表（${rows.length} 行）</div>
      ${objectTable(rows)}
    </div>
  `;
  document.getElementById('downloadDischargeTableBtn').addEventListener('click', () => {
    downloadRowsAsCsv(rows, `discharge_capacity_${data.schemeId}_${level}m.csv`);
  });
}

function dischargeCapacityChart(rows) {
  if (!rows.length) return '<p>暂无泄流能力数据。</p>';
  const width = 900; const height = 500;
  const pad = { left: 82, right: 30, top: 32, bottom: 58 };
  const levels = rows.map((row) => Number(row['水位_m']));
  const maxQ = Math.max(...rows.map((row) => Number(row['泄流能力_m3s']))) * 1.08;
  const minLevel = Math.min(...levels); const maxLevel = Math.max(...levels);
  const xScale = (x) => pad.left + ((x - minLevel) / (maxLevel - minLevel)) * (width - pad.left - pad.right);
  const yScale = (y) => height - pad.bottom - (y / maxQ) * (height - pad.top - pad.bottom);
  const ticks = Array.from({ length: 6 }, (_, i) => i / 5);
  const grid = ticks.map((ratio) => {
    const x = minLevel + ratio * (maxLevel - minLevel); const y = ratio * maxQ;
    return `<line x1="${xScale(x)}" y1="${pad.top}" x2="${xScale(x)}" y2="${height - pad.bottom}" stroke="#e5e7eb"/><text x="${xScale(x)}" y="${height - pad.bottom + 22}" text-anchor="middle" font-size="12" fill="#64748b">${fmt(x, 1)}</text><line x1="${pad.left}" y1="${yScale(y)}" x2="${width - pad.right}" y2="${yScale(y)}" stroke="#e5e7eb"/><text x="${pad.left - 9}" y="${yScale(y) + 4}" text-anchor="end" font-size="12" fill="#64748b">${fmt(y, 0)}</text>`;
  }).join('');
  const series = [
    ['泄流能力_m3s', '#0f6b8f', '总泄流能力'],
    ['溢洪坝泄量_m3s', '#f97316', '溢洪坝'],
    ['中孔泄量_m3s', '#16a34a', '中孔'],
  ];
  const paths = series.map(([key, color]) => `<path d="${rows.map((row, i) => `${i ? 'L' : 'M'} ${xScale(Number(row['水位_m'])).toFixed(2)} ${yScale(Number(row[key])).toFixed(2)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2.4"/>`).join('');
  const legend = series.map(([, color, label], i) => `<line x1="${width - 250 + i * 82}" y1="18" x2="${width - 225 + i * 82}" y2="18" stroke="${color}" stroke-width="2.4"/><text x="${width - 220 + i * 82}" y="22" font-size="11" fill="#64748b">${label}</text>`).join('');
  return `<svg viewBox="0 0 ${width} ${height}" role="img"><rect width="${width}" height="${height}" fill="#fff"/>${grid}<line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" stroke="#64748b"/><line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#64748b"/>${paths}${legend}<text x="${width / 2}" y="${height - 10}" text-anchor="middle" font-size="14">库水位（m）</text><text x="18" y="${height / 2}" text-anchor="middle" font-size="14" transform="rotate(-90 18 ${height / 2})">泄流能力（m³/s）</text></svg>`;
}

async function renderFloodRoutingPanel() {
  const status = await api('/api/calc/status');
  const availableIds = status.dischargeCapacitySchemeIds || [];
  const available = state.schemeConfig.schemes.filter((scheme) => availableIds.includes(scheme.id));
  document.getElementById('floodSubmoduleBody').innerHTML = `
    <div class="data-toolbar"><div><h3>水库调洪演算</h3><p>依次计算5%、0.1%和0.01%三种洪水标准的入库、出库过程。</p></div>
      <div class="toolbar-actions"><label>当前方案<select id="floodRoutingSchemeSelect">${available.map((scheme) => `<option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>`).join('')}</select></label><button id="runFloodRoutingBtn">开始计算</button></div>
    </div>
    <div id="floodRoutingResult" class="result-placeholder">${available.length ? '尚未计算。请选择已有泄流能力曲线成果的方案。' : '当前没有可计算方案。请先完成泄流能力曲线。'}</div>`;
  document.getElementById('runFloodRoutingBtn').disabled = available.length === 0;
  document.getElementById('runFloodRoutingBtn').addEventListener('click', runFloodRoutingCalculation);
}

async function runFloodRoutingCalculation() {
  const select = document.getElementById('floodRoutingSchemeSelect');
  const schemeId = select.value; const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/flood-routing?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.floodRoutingResult = data;
  const row = data.summary;
  document.getElementById('floodRoutingResult').innerHTML = `
    <div class="note">${data.note}</div>
    <div class="summary-grid">
      <div class="info-tile"><span>防洪高水位（5%）</span><strong>${fmt(row['防洪高水位_m'], 4, ' m')}</strong></div>
      <div class="info-tile"><span>设计洪水位（0.1%）</span><strong>${fmt(row['设计洪水位_m'], 4, ' m')}</strong></div>
      <div class="info-tile"><span>校核洪水位（0.01%）</span><strong>${fmt(row['校核洪水位_m'], 4, ' m')}</strong></div>
      <div class="info-tile"><span>校核最大泄量</span><strong>${fmt(row['校核洪水最大泄流量_m3s'], 2, ' m³/s')}</strong></div>
    </div>
    <div class="section-heading"><h4>调洪过程图</h4><label>洪水标准 <select id="routingChartSelect"><option value="flood5">5%</option><option value="design">0.1% 设计洪水</option><option value="check">0.01% 校核洪水</option></select></label></div>
    <div id="routingChartBody" class="svg-chart flood-routing-chart"></div>
    <div class="section-heading"><h4>计算表格</h4></div>
    <div class="table-switcher"><div class="toolbar-actions"><label>输出表格<select id="routingTableSelect"><option value="summary">调洪成果汇总表</option><option value="flood5">5%调洪过程表</option><option value="design">0.1%设计洪水过程表</option><option value="check">0.01%校核洪水过程表</option></select></label><button class="secondary" id="downloadRoutingTableBtn">导出当前表格</button></div><div id="routingSelectedTable"></div></div>`;
  renderRoutingChart(); renderRoutingTable();
  document.getElementById('routingChartSelect').addEventListener('change', renderRoutingChart);
  document.getElementById('routingTableSelect').addEventListener('change', renderRoutingTable);
  document.getElementById('downloadRoutingTableBtn').addEventListener('click', downloadRoutingTable);
}

function routingMeta(key) {
  const labels = { summary: '调洪成果汇总表', flood5: '5%调洪过程表', design: '0.1%设计洪水过程表', check: '0.01%校核洪水过程表' };
  return labels[key] || labels.summary;
}

function renderRoutingTable() {
  const key = document.getElementById('routingTableSelect')?.value || 'summary';
  const rows = state.floodRoutingResult?.tables?.[key] || [];
  document.getElementById('routingSelectedTable').innerHTML = `<div class="selected-table-title">${routingMeta(key)}（${rows.length} 行）</div>${objectTable(rows)}`;
}

function downloadRoutingTable() {
  const key = document.getElementById('routingTableSelect')?.value || 'summary';
  const rows = state.floodRoutingResult?.tables?.[key] || [];
  downloadRowsAsCsv(rows, `flood_routing_${state.floodRoutingResult.schemeId}_${key}.csv`);
}

function renderRoutingChart() {
  const key = document.getElementById('routingChartSelect')?.value || 'flood5';
  document.getElementById('routingChartBody').innerHTML = floodRoutingChart(state.floodRoutingResult?.tables?.[key] || []);
}

function floodRoutingChart(rows) {
  if (!rows.length) return '<p>暂无调洪过程数据。</p>';
  const width = 900; const height = 500; const pad = { left: 82, right: 30, top: 32, bottom: 58 };
  const maxTime = Math.max(...rows.map((row) => Number(row['时间_h'])));
  const maxQ = Math.max(...rows.flatMap((row) => [Number(row['入库流量_m3s']), Number(row['出库流量_m3s'])])) * 1.08;
  const x = (value) => pad.left + value / maxTime * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - value / maxQ * (height - pad.top - pad.bottom);
  const grid = Array.from({ length: 6 }, (_, i) => i / 5).map((ratio) => `<line x1="${x(ratio * maxTime)}" y1="${pad.top}" x2="${x(ratio * maxTime)}" y2="${height-pad.bottom}" stroke="#e5e7eb"/><text x="${x(ratio * maxTime)}" y="${height-pad.bottom+22}" text-anchor="middle" font-size="12">${fmt(ratio * maxTime, 0)}</text><line x1="${pad.left}" y1="${y(ratio * maxQ)}" x2="${width-pad.right}" y2="${y(ratio * maxQ)}" stroke="#e5e7eb"/><text x="${pad.left-9}" y="${y(ratio * maxQ)+4}" text-anchor="end" font-size="12">${fmt(ratio * maxQ, 0)}</text>`).join('');
  const path = (field) => rows.map((row, i) => `${i ? 'L' : 'M'} ${x(Number(row['时间_h'])).toFixed(2)} ${y(Number(row[field])).toFixed(2)}`).join(' ');
  return `<svg viewBox="0 0 ${width} ${height}" role="img"><rect width="100%" height="100%" fill="#fff"/>${grid}<line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height-pad.bottom}" stroke="#64748b"/><line x1="${pad.left}" y1="${height-pad.bottom}" x2="${width-pad.right}" y2="${height-pad.bottom}" stroke="#64748b"/><path d="${path('入库流量_m3s')}" fill="none" stroke="#0f6b8f" stroke-width="2.5"/><path d="${path('出库流量_m3s')}" fill="none" stroke="#f97316" stroke-width="2.5" stroke-dasharray="7 4"/><line x1="${width-205}" y1="18" x2="${width-175}" y2="18" stroke="#0f6b8f" stroke-width="2.5"/><text x="${width-168}" y="22" font-size="12">入库流量</text><line x1="${width-96}" y1="18" x2="${width-66}" y2="18" stroke="#f97316" stroke-width="2.5" stroke-dasharray="7 4"/><text x="${width-59}" y="22" font-size="12">出库流量</text><text x="${width/2}" y="${height-10}" text-anchor="middle" font-size="14">时间（h）</text><text x="18" y="${height/2}" text-anchor="middle" font-size="14" transform="rotate(-90 18 ${height/2})">流量（m³/s）</text></svg>`;
}

async function renderDamCrestPanel() {
  const status = await api('/api/calc/status');
  const availableIds = status.floodRoutingSchemeIds || [];
  const available = state.schemeConfig.schemes.filter((scheme) => availableIds.includes(scheme.id));
  document.getElementById('floodSubmoduleBody').innerHTML = `<div class="data-toolbar"><div><h3>坝顶高程确定</h3><p>根据设计、校核洪水位及风浪安全超高确定坝顶高程。</p></div><div class="toolbar-actions"><label>当前方案<select id="damCrestSchemeSelect">${available.map((scheme) => `<option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>`).join('')}</select></label><button id="runDamCrestBtn">开始计算</button></div></div><div id="damCrestResult" class="result-placeholder">${available.length ? '尚未计算。请选择已有调洪成果的方案。' : '当前没有可计算方案。请先完成水库调洪演算。'}</div>`;
  document.getElementById('runDamCrestBtn').disabled = available.length === 0;
  document.getElementById('runDamCrestBtn').addEventListener('click', runDamCrestCalculation);
}

async function runDamCrestCalculation() {
  const select = document.getElementById('damCrestSchemeSelect'); const schemeId = select.value; const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/dam-crest?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.damCrestResult = data; const row = data.result;
  document.getElementById('damCrestResult').innerHTML = `<div class="note">${data.note}</div><div class="summary-grid"><div class="info-tile"><span>设计工况坝顶高程</span><strong>${fmt(row['设计工况坝顶高程_m'], 4, ' m')}</strong></div><div class="info-tile"><span>校核工况坝顶高程</span><strong>${fmt(row['校核工况坝顶高程_m'], 4, ' m')}</strong></div><div class="info-tile"><span>采用坝顶高程</span><strong>${fmt(row['坝顶高程_m'], 4, ' m')}</strong></div></div><div class="formula-list"><p>设计工况 = 设计洪水位 + 设计风浪高 + 0.7 m</p><p>校核工况 = 校核洪水位 + 校核风浪高 + 0.5 m</p><p>坝顶高程 = max（设计工况，校核工况）</p></div><div class="section-heading"><h4>坝顶高程计算表</h4><button class="secondary" id="downloadDamCrestBtn">导出当前表格</button></div>${objectTable(data.tables.result)}</div>`;
  document.getElementById('downloadDamCrestBtn').addEventListener('click', () => downloadRowsAsCsv(data.tables.result, `dam_crest_${schemeId}_${level}m.csv`));
}

function renderEconomyModule() {
  const submodules = [
    ['basis', '经济参数与基础成果'],
    ['replacement', '替代火电计算'],
    ['floodBenefit', '防洪效益'],
    ['cashflow', '资金流程与费用折算'],
    ['comparison', '方案经济比较'],
  ];
  document.getElementById('moduleBody').innerHTML = `
    <div class="subtabs">
      ${submodules.map(([id, label]) => `<button class="subtab ${state.economySubmodule === id ? 'active' : ''}" data-economy-submodule="${id}">${label}</button>`).join('')}
    </div>
    <div id="economySubmoduleBody"></div>
  `;
  document.querySelectorAll('[data-economy-submodule]').forEach((button) => button.addEventListener('click', () => {
    state.economySubmodule = button.dataset.economySubmodule; renderEconomyModule();
  }));
  if (state.economySubmodule === 'comparison') renderEconomyComparisonPanel();
  else renderEconomySchemePanel(state.economySubmodule);
}

const economySectionTitles = {
  basis: ['经济参数与基础成果', '汇总已确认定线成果、坝顶高程及自动插值的水电工程经济参数。'],
  replacement: ['替代火电计算', '以120 m方案为基准，计算系统容量、电能差额及替代火电和煤矿费用。'],
  floodBenefit: ['防洪效益', '根据历史拦洪量一次拟合线和平移截断线之间的面积计算防洪效益。'],
  cashflow: ['资金流程与费用折算', '将施工期投资折算到第11年末，再按50年或25年等额重置化算成年费用。'],
};

async function renderEconomySchemePanel(section) {
  const status = await api('/api/calc/status');
  const ids = status.economyAvailableSchemeIds || [];
  const available = state.schemeConfig.schemes.filter((scheme) => ids.includes(scheme.id));
  const [title, description] = economySectionTitles[section];
  document.getElementById('economySubmoduleBody').innerHTML = `
    <div class="data-toolbar"><div><h3>${title}</h3><p>${description}</p></div><div class="toolbar-actions"><label>当前方案<select id="economySchemeSelect">${available.map((scheme) => `<option value="${scheme.id}" data-level="${scheme.normalWaterLevel}">${scheme.name} · ${fmt(scheme.normalWaterLevel, 2, ' m')}</option>`).join('')}</select></label><button id="runEconomySectionBtn">开始计算</button></div></div>
    <div id="economySectionResult" class="result-placeholder">${available.length ? '尚未计算。请选择方案并点击“开始计算”。' : '当前没有可计算方案。请先确认定线成果并完成坝顶高程计算。'}</div>`;
  document.getElementById('runEconomySectionBtn').disabled = available.length === 0;
  document.getElementById('runEconomySectionBtn').addEventListener('click', () => runEconomySection(section));
}

function economicItem(rows, name) {
  return rows?.find((row) => row['项目'] === name)?.['数值'] ?? '-';
}

async function runEconomySection(section) {
  const select = document.getElementById('economySchemeSelect'); const schemeId = select.value; const level = Number(select.selectedOptions[0].dataset.level);
  const data = await api(`/api/calc/economy-data?schemeId=${encodeURIComponent(schemeId)}&level=${encodeURIComponent(level)}`);
  state.economyResult = data;
  const components = data.components;
  if (section === 'basis') {
    const rows = [...(components['装机与电能'] || []), ...(components['水电投资'] || []), ...(components['水库补偿'] || [])];
    renderEconomySectionResult([
      ['确认重复容量', fmt(data.selection.repeatedCapacity, 4, ' 万kW')],
      ['装机容量', fmt(economicItem(components['装机与电能'], '装机容量'), 4, ' 万kW')],
      ['坝顶高程', fmt(economicItem(components['水电投资'], '坝顶高程'), 4, ' m')],
      ['水电工程投资', fmt(economicItem(components['水电投资'], '水电工程投资合计'), 2, ' 万元')],
    ], { basis: rows }, { basis: '经济参数与基础成果表' });
  } else if (section === 'replacement') {
    const rows = [...(components['替代火电'] || []), ...(components['运行费'] || [])];
    renderEconomySectionResult([
      ['替代火电容量', fmt(economicItem(components['替代火电'], '替代容量'), 4, ' 万kW')],
      ['替代火电电能', fmt(economicItem(components['替代火电'], '替代电能'), 4, ' 亿kWh')],
      ['火电站投资', fmt(economicItem(components['替代火电'], '火电站投资'), 2, ' 万元')],
      ['煤矿额外投资', fmt(economicItem(components['替代火电'], '煤矿额外投资'), 2, ' 万元')],
    ], { replacement: rows }, { replacement: '替代火电与运行费计算表' }, '<div class="formula-list"><p>替代火电站投资按25年寿命进行等额重置化算。</p><p>煤矿投资及水电工程投资按50年比较期化算。</p></div>');
  } else if (section === 'floodBenefit') {
    const rows = components['防洪效益'] || [];
    renderEconomySectionResult([
      ['防洪库容', fmt(economicItem(rows, '防洪库容'), 4, ' 亿m³')],
      ['多年平均减少拦洪量', fmt(economicItem(rows, '多年平均减少拦洪量'), 4, ' 亿m³')],
      ['防洪年效益', fmt(economicItem(rows, '防洪年效益'), 2, ' 万元/年')],
    ], { benefit: rows, frequency: data.tables.frequency }, { benefit: '防洪效益成果表', frequency: '拦洪量频率曲线计算表' }, `<div class="section-heading"><h4>拦洪量频率曲线</h4></div><div class="svg-chart">${data.floodBenefitSvg}</div>`);
  } else {
    const rows = components['折算年费用'] || [];
    renderEconomySectionResult([
      ['施工期末折算总值', fmt(economicItem(rows, '施工期末折算总值'), 2, ' 万元')],
      ['资本年费用', fmt(economicItem(rows, '资本年费用'), 2, ' 万元/年')],
      ['正常运行期年费用', fmt(economicItem(rows, '正常运行期年费用'), 2, ' 万元/年')],
      ['总年费用', fmt(economicItem(rows, '总年费用'), 2, ' 万元/年')],
    ], { annual: rows, cashflow: data.tables.cashflow, wide: data.tables.wide }, { annual: '年费用成果表', cashflow: '逐年资金流程表', wide: '方案经济计算大表' });
  }
}

function renderEconomySectionResult(cards, tables, labels, extra = '') {
  state.economyTables = tables; state.economyTableLabels = labels;
  const firstKey = Object.keys(tables)[0];
  document.getElementById('economySectionResult').innerHTML = `<div class="note">${state.economyResult.note}</div><div class="summary-grid">${cards.map(([label, value]) => `<div class="info-tile"><span>${label}</span><strong>${value}</strong></div>`).join('')}</div>${extra}<div class="section-heading"><h4>计算表格</h4></div><div class="table-switcher"><div class="toolbar-actions"><label>输出表格<select id="economyTableSelect">${Object.entries(labels).map(([key, label]) => `<option value="${key}">${label}</option>`).join('')}</select></label><button class="secondary" id="downloadEconomyTableBtn">导出当前表格</button></div><div id="economySelectedTable"></div></div>`;
  document.getElementById('economyTableSelect').value = firstKey; renderEconomySelectedTable();
  document.getElementById('economyTableSelect').addEventListener('change', renderEconomySelectedTable);
  document.getElementById('downloadEconomyTableBtn').addEventListener('click', () => { const key = document.getElementById('economyTableSelect').value; downloadRowsAsCsv(state.economyTables[key], `economic_${state.economyResult.schemeId}_${key}.csv`); });
}

function renderEconomySelectedTable() {
  const key = document.getElementById('economyTableSelect').value; const rows = state.economyTables[key] || [];
  document.getElementById('economySelectedTable').innerHTML = `<div class="selected-table-title">${state.economyTableLabels[key]}（${rows.length} 行）</div>${objectTable(rows)}`;
}

async function renderEconomyComparisonPanel() {
  const data = await api('/api/calc/economy-comparison');
  const chartRows = data.rows.map((row) => ({ name: row['方案名称'], totalAnnualCost: Number(row['总年费用_万元']) }));
  document.getElementById('economySubmoduleBody').innerHTML = `<div class="data-toolbar"><div><h3>方案经济比较</h3><p>仅比较已经确认定线成果并完成坝顶高程的方案。</p></div><button class="secondary" id="downloadEconomyComparisonBtn" ${data.rows.length ? '' : 'disabled'}>导出比较总表</button></div>${data.rows.length ? `<div class="mini-chart">${barChart(chartRows, 'totalAnnualCost')}</div>${objectTable(data.rows)}` : '<div class="result-placeholder">当前没有满足经济比较条件的方案。</div>'}`;
  if (data.rows.length) document.getElementById('downloadEconomyComparisonBtn').addEventListener('click', () => downloadRowsAsCsv(data.rows, 'economic_comparison.csv'));
}

function renderProcessModule() {
  document.getElementById('moduleBody').innerHTML = `
    <div class="note">过程表直接读取 output 中的 CSV，可用于追溯“结果从哪里来”。</div>
    <div class="form-grid">
      <label>选择过程表
        <select id="tableSelect">
          <option value="installed_capacity">装机容量总结</option>
          <option value="flood_summary">调洪与坝顶成果</option>
          <option value="discharge_capacity">泄流能力曲线表</option>
          <option value="economic_comparison">经济比较总表</option>
          <option value="economic_components">经济分项明细</option>
          <option value="runoff_utilization">径流利用系数</option>
        </select>
      </label>
    </div>
    <div id="tableResult" style="margin-top: 14px;"></div>
  `;
  document.getElementById('tableSelect').addEventListener('change', loadSelectedTable);
  loadSelectedTable();
}

async function loadSelectedTable() {
  const key = document.getElementById('tableSelect').value;
  const data = await api(`/api/table?key=${encodeURIComponent(key)}`);
  document.getElementById('tableResult').innerHTML = objectTable(data.rows);
}

function renderChartsModule() {
  const level = state.activeLevel;
  const levelKey = Math.round(level);
  document.getElementById('moduleBody').innerHTML = `
    <div class="note">图表页读取当前 output 中的 SVG 成果图。切换右上角方案后，可查看对应方案调度图和重复容量拟合图。</div>
    <div class="chart-grid">
      <div class="chart-box"><h4>调度图 · ${levelKey}m</h4><div id="dispatchChart">加载中...</div></div>
      <div class="chart-box"><h4>重复容量拟合 · ${levelKey}m</h4><div id="repeatChart">加载中...</div></div>
      <div class="chart-box" style="grid-column: 1 / -1;"><h4>泄流能力曲线</h4><div id="dischargeChart">加载中...</div></div>
    </div>
  `;
  loadSvg(`dispatch_${levelKey}`, 'dispatchChart');
  loadSvg(`repeated_fit_${levelKey}`, 'repeatChart');
  loadSvg('flood_discharge_all', 'dischargeChart');
}

async function loadSvg(key, targetId) {
  try {
    const svg = await api(`/api/chart?key=${encodeURIComponent(key)}`);
    document.getElementById(targetId).innerHTML = svg;
  } catch {
    document.getElementById(targetId).textContent = '没有找到对应图件。';
  }
}

function renderExportModule() {
  const files = state.summary.files.filter((file) => file.path.startsWith('output/'));
  document.getElementById('moduleBody').innerHTML = `
    <div class="note">这里列出当前示例项目已经生成的成果文件。第一版先支持下载，后续可接入“一键重新计算并生成报告”。</div>
    <div class="file-list">
      ${files.map(fileRow).join('')}
    </div>
  `;
}

function fileRow(file) {
  return `
    <div class="file-row">
      <strong title="${file.path}">${file.path}</strong>
      <span>${file.kind.toUpperCase()} · ${Math.ceil(file.size / 1024)} KB</span>
      <a href="/api/download?path=${encodeURIComponent(file.path)}"><button class="secondary">下载</button></a>
    </div>
  `;
}

function numberInput(id, label, value, step) {
  return `
    <label>${label}
      <input id="${id}" type="number" value="${value}" step="${step}" />
    </label>
  `;
}

function textInput(id, label, value) {
  return `
    <label>${label}
      <input id="${id}" type="text" value="${escapeHtml(value ?? '')}" />
    </label>
  `;
}

function tableHtml(headers, rows) {
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headers.map((h) => `<th>${h}</th>`).join('')}</tr></thead>
        <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
    </div>
  `;
}

function objectTable(rows) {
  if (!rows.length) return '<p>暂无数据。</p>';
  const headers = Object.keys(rows[0]);
  return tableHtml(headers, rows.map((row) => headers.map((key) => row[key] ?? '')));
}

function barChart(rows, key) {
  const width = 760;
  const height = 250;
  const pad = { left: 58, right: 18, top: 22, bottom: 42 };
  const values = rows.map((row) => Number(row[key]));
  const max = Math.max(...values) * 1.08;
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const gap = 28;
  const barWidth = (plotWidth - gap * (rows.length - 1)) / rows.length;
  const bars = rows.map((row, index) => {
    const x = pad.left + index * (barWidth + gap);
    const barHeight = (Number(row[key]) / max) * plotHeight;
    const y = pad.top + plotHeight - barHeight;
    const fill = row.recommended ? '#1b8a5a' : '#0f6b8f';
    return `
      <rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="5" fill="${fill}"></rect>
      <text x="${x + barWidth / 2}" y="${height - 17}" text-anchor="middle" font-size="12" fill="#526173">${row.name}</text>
      <text x="${x + barWidth / 2}" y="${y - 7}" text-anchor="middle" font-size="12" fill="#162232">${fmt(row[key], 0)}</text>
    `;
  }).join('');
  return `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" role="img">
      <line x1="${pad.left}" y1="${pad.top + plotHeight}" x2="${width - pad.right}" y2="${pad.top + plotHeight}" stroke="#d9e2ec"></line>
      <text x="16" y="18" font-size="12" fill="#64748b">总年费用（万元/年）</text>
      ${bars}
    </svg>
  `;
}

init().catch((error) => {
  document.getElementById('activeModuleTitle').textContent = '加载失败';
  document.getElementById('moduleBody').innerHTML = `<div class="note">${error.message}</div>`;
});
