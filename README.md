# readerPQR

面向 **Windows 11 x64** 的 AI 文献阅读器。导入 PDF，在本地提取文字与段落坐标，再通过你配置的 AI 接口生成 **逐页、逐段对齐的简体中文译文**。

> 当前版本：0.1.0。需要自备模型 API，或启动兼容 Chat Completions 的本机模型服务。没有内置付费密钥。扫描 PDF 暂不内置 OCR；本版本不是保持原版式的整本中文 PDF 重排器。

## 使用方式

### 便携版：无需安装 Python

在本仓库 **Actions → Windows desktop build → 最新成功的运行 → Artifacts** 下载 `readerPQR-Windows-x64`。解压整个压缩包，打开 `readerPQR.exe`。**不要单独移动 exe，必须保留 `_internal` 目录。** 构建尚未成功时不会生成该便携包。

便携包未做商业代码签名。请核对仓库、提交与构建记录；不要为了运行未知文件而关闭系统安全防护。

### 源码版：安装 Python 3.12 x64 后启动

下载本仓库源码 ZIP 并解压，然后双击 `start_windows.bat`。第一次运行会创建项目独立虚拟环境并安装依赖。也可以在项目目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m readerpqr
```

完整操作步骤见 [Windows 中文指南](docs/WINDOWS_GUIDE.md)。

## 第一次翻译

打开左下角 **AI 设置与术语表**，填写接口、模型和 API Key，点击 **测试连接**。确认地址可信后勾选文字发送许可，保存设置，再导入 PDF。

默认提供智谱配置：

```text
API Base URL: https://open.bigmodel.cn/api/paas/v4
Model: glm-4.7-flash
高级参数: {"thinking":{"type":"disabled"}}
```

模型名称、可用性与计费以服务商为准。通用接口请选择“通用 Chat Completions”，填写自己的 Base URL 与模型，先把高级参数设为 `{}`。API 地址也可以包含完整的 `/chat/completions` 后缀。

“导入 PDF 后自动翻译全文”默认启用，但只有正确配置密钥并授权当前地址后才会发送文字。可以取消自动翻译，先按“翻译本页”控制调用量。

## 功能与边界

| 功能 | 实现方式 |
| --- | --- |
| 逐段对齐 | 原文截图和中文共享同一行，行高随译文增长，统一滚动，不靠两个滚动条百分比凑齐 |
| 原页定位 | 完整 PDF 页面保留图表与公式；点击文字区域或译文的定位按钮，相互定位 |
| 双栏论文 | 使用坐标启发式排序；可手动切换单栏或双栏。复杂表格、多栏和浮动框可能仍需核对 |
| 自动翻译 | 后台分批处理；支持翻译本页、全文、停止、继续；正文不会阻塞界面等待 API |
| 防止错位 | 严格校验段落 ID、重复项、空译文和缺失项；格式不合格的结果不写入缓存 |
| 公式与引用 | 原文截图完整保留；可识别的公式块不翻译；文字内的数字引用与部分公式用占位符保护 |
| 学术术语 | 设置中编辑术语表，默认含机器人学习常见词汇；修改后使用独立缓存 |
| 缓存恢复 | SQLite 按 PDF 哈希、模型、服务地址、术语表和提示词版本隔离；已完成部分无需再次付费请求 |
| 导出 | 离线双语 HTML 和带坐标的 JSON。HTML 可在浏览器打印为 PDF，但不重建原 PDF 的图片与公式排版 |
| 密钥保护 | Windows 可选 DPAPI 加密保存；其他平台仅内存使用密钥 |

**不保证所有 PDF 都能正确分段，也不保证模型翻译无误。** 文本编码损坏、扫描文档、复杂数学排版和表格是主要限制。图中嵌入文字不会自动翻译。参考文献与作者信息应核对原文。

## 隐私与安全

PDF 文件和渲染图片留在本地；调用 API 时发送段落文字、术语表、固定翻译提示和所选参数。应用没有遥测、文件上传服务或嵌入的网页脚本。文本内容被当作待翻译材料，不会作为工具调用指令执行。

设置与缓存位置：`%LOCALAPPDATA%\readerPQR`。密钥不进入日志或缓存索引，DPAPI 密文绑定当前 Windows 用户。**译文本身是本地未加密缓存**，请用操作系统账户和磁盘权限保护敏感文献。不保存 PDF 打开密码。

## 开发与打包

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m readerpqr --self-test --output smoke
.\.venv\Scripts\python.exe scripts\build_windows.py
```

也可以双击 `build_windows.bat`。Windows 包必须在 Windows 上构建，不能把 Linux 的 PyInstaller 产物当成 exe。GitHub Actions 使用 Python 3.12 x64，运行离线单元测试、源代码 GUI 冒烟测试、打包后的 exe 冒烟测试，并提供测试截图和精确源码快照。

`--self-test` 使用程序生成的合成 PDF 和明确标注的离线占位文本，不调用真实模型，不证明模型翻译质量。真实 API 验收需用户填写密钥后完成。

## 项目结构

```text
readerpqr/pdf_engine.py   本地解析、阅读顺序、页面/段落渲染
readerpqr/translate.py    API、响应校验、可取消请求、缓存恢复
readerpqr/storage.py      设置、DPAPI、SQLite
readerpqr/ui.py           双语桌面界面、搜索、原文定位
readerpqr/dialogs.py      模型设置与连接测试
readerpqr/export.py       HTML / JSON 导出
readerpqr/smoke.py        离线合成文献与界面检查
scripts/build_windows.py Windows 打包及第三方许可收集
```

## 许可与技术资料

项目按 AGPL-3.0-only 发布；依赖的许可信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。打包版附带对应源代码。技术资料见 [架构与验收说明](docs/ARCHITECTURE.md)。
