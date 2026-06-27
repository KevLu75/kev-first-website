# 五强溪水利计算平台 Web 原型

这是一个零外部依赖的 BS 端原型，当前用于把课程设计已有成果作为示例项目加载到网页中。

## 启动

在项目根目录运行：

```powershell
python web/server.py
```

然后打开：

```text
http://127.0.0.1:8787
```

如果使用 Codex bundled Python，可运行：

```powershell
& 'C:\Users\kevin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' web/server.py
```

## 当前功能

- 将基础输入数据放在 `web/app_data/` 中管理。
- `web/app_data/example/` 保存内置示例项目。
- `web/project_final/` 保存当前正在编辑的项目，也是上传 CSV 的落点。
- 展示四个正常蓄水位方案的关键指标。
- 项目数据管理支持 6 个基础数据子模块：
  - 库容曲线
  - 水位-面积曲线
  - 尾水水位流量曲线
  - 径流系列表
  - 设计洪水数据
  - 其他参数
- 每个基础数据子模块都提供“使用示例数据”按钮。
- CSV 数据可在网页中预览和编辑，保存只写入 `web/project_final/`。
- `.xls` 径流原始表当前作为原始文件保存和下载，后续可转换为 CSV 后接入在线预览。
- 查看装机容量、调洪、经济、径流利用等过程表。
- 展示调度图、重复容量拟合图、泄流能力曲线等 SVG 成果图。
- 下载已有 CSV、SVG、DOCX 成果文件。
- 在不改动 `output/` 的前提下，在线重算经济比较：
  - 折算率
  - 水电比较期
  - 火电寿命
  - 运行费倍率
  - 防洪效益倍率

## 设计约束

- `web/` 是网站全部内容。
- 原来的 `data/`、`core/`、`output/` 不由网页写入。
- 当前网页项目数据写入 `web/project_final/`。
- 当前后端使用 Python 标准库实现，方便在没有 FastAPI/React/Vite 的环境中直接运行。

## 后续扩展

后续可以逐步接入：

- 项目上传和数据字段校验。
- 在线编辑方案参数。
- 调用 `core/` 中的计算模块，在独立工作目录中生成新项目成果。
- 生成完整 Word/PDF 报告。
- 若允许安装依赖，可升级为 FastAPI + React/Vite + ECharts。
