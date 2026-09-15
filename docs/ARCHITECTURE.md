# 架构与验收说明

## 数据链路

本地 PDF → SHA-256 → PyMuPDF 文字块与 bbox → 阅读顺序启发式 → 稳定 block ID → 缓存查询 → 按页、按字符预算分批 → Chat Completions → JSON / ID / 占位符校验 → SQLite → Qt 段落行。

渲染与解析共享进程内锁，不并发操作 MuPDF。UI 与导入任务使用独立的 Document 对象；网络任务不访问 PDF 渲染对象。HTTP 使用异步请求，取消标志每 120 ms 检查，取消会终止待完成请求，不强制终止线程。导入在文件块和页面之间检查取消。

## 对齐定义

“逐段对齐”通过一个 QHBoxLayout 中的两个等宽单元格共享行高实现；原文为真实页面裁剪，中文采用纯文本 QLabel。长译文让整行增长，不做不可控的 PDF 字框压缩。

“原页定位”使用原始 bbox 经 rotation_matrix 映射到可见 PDF 页面，再映射到控件坐标。点击和高亮使用相同坐标变换。不是通过两个滚动条的百分比判断段落。

自动分栏只是一种启发式：识别页面中线两侧的文字块，再以跨栏标题、图注分割纵向区域。复杂表格和任意多栏不保证顺序。提供单栏/双栏覆盖。

## 模型边界

接口是非流式 Chat Completions，每批返回后增量更新界面。不是每个 token 流式输出。支持自定义兼容接口，不承诺任意供应商的所有模型都兼容。

响应必须为 `translations` 数组，每个输入 ID 恰好一次。空字符串、未知 ID、重复 ID、漏译、可识别的引用占位符丢失均被拒绝。格式失败时缩小批次；单项仍失败则有限重试并标记失败。HTTP 401/403 不盲目重试；429/5xx 采用有限退避。

提示词不能提供数学保真保证。公式的可靠参照是未改动的 PDF 图片；部分可提取的行内公式和数字引用有占位符保护。不能把错误文字编码修复为正确公式，也不翻译图片中的文字。

## 隐私边界

原 PDF 和图片不发送至翻译 API。文字、术语表和模型参数会发送到用户明确授权的地址。地址变化撤销已有许可；远端必须使用 HTTPS，仅 loopback 允许 HTTP；不跟随 HTTP 重定向。API Key 从不出现在缓存键、UI 错误响应正文或导出文件。

缓存中的译文不是加密数据库。Windows DPAPI 保护的是持久保存的 API Key，不是对同账户恶意软件或系统管理员的完整防御。

## 验收层级

1. 离线核心单测：解析、旋转、密码、阅读顺序、缓存隔离、URL 校验、JSON 校验、保护符、超长段落、取消、鉴权脱敏、重复调用恢复和 HTML 转义。
2. Windows 单测：补充 DPAPI 往返和 Qt 页面导航/定位测试。
3. 源码 GUI 冒烟：合成 PDF、明确标注的离线占位文本、布局截图和导出。
4. 打包 exe 冒烟：实际启动 PyInstaller 产物，验证成功标志和截图，异常退出判失败。
5. 真人验收：Win11 设备、实际 API Key、真实论文的翻译准确性、长文性能和高 DPI 使用体验。自动化测试不替代这一层。

## 官方技术资料

- Qt for Python：https://doc.qt.io/qtforpython-6/
- Qt Windows 支持：https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-windows.html
- PyMuPDF 文字提取：https://pymupdf.readthedocs.io/en/latest/app1.html
- PyMuPDF 阅读顺序限制：https://pymupdf.readthedocs.io/en/latest/faq/index.html
- PyInstaller 构建平台限制：https://www.pyinstaller.org/en/stable/
- 智谱 GLM-4.7-Flash：https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash
- 智谱思考模式：https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode
- Chat Completions：https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- Windows DPAPI：https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
