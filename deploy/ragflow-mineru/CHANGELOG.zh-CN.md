# 2026-11-12：内网部署修复正式化

此前通过补丁包、容器文件挂载和内网手工修改解决的问题，现在纳入仓库源码与正常打包流程。

| 问题 | 正式处理 |
| --- | --- |
| 在解压目录执行 `up --project-dir ./`，复制源与目标相同 | 识别同一目录并跳过复制，统一解析相对路径、符号链接 |
| Compose v1 报 `pids_limit` 字符串类型错误 | 从 `.env` 读取并校验 `OFFICE_PIDS_LIMIT`，生成整数 YAML，默认 256 |
| `docker_redis_1` 与其他项目冲突、误用旧数据卷 | 默认使用 `doc2markdown` 项目名，移除固定容器名，容器、网络、命名卷统一按项目隔离 |
| Gradio 自定义组件 JavaScript 返回 HTML、MIME 错误 | 将遗漏前缀的 `/gradio_api/` 请求以 307 转到 `/mineru-ui/gradio_api/`，保留路径和查询参数 |
| 离线字体路径出现重复 `/mineru-ui/` | 使用适配 Gradio 根路径拼接规则的本地字体占位地址 |
| Office 网关健康但 UI 判断失败 | 保留 MinerU 原始健康协议与并发字段，追加网关和 LibreOffice 状态 |
| 提交任务报公开 API 禁止 `server_url` | 对本地引擎移除隐藏的 `server_url`；保留实际 HTTP 客户端后端所需的地址 |
| Office 转换后找不到 `hybrid_auto/文件名.md` | 镜像构建时修复结果目录解析，兼容网关实际生成的 `ocr` 目录；多个候选时明确报错 |
| 普通浏览器异常、无痕正常、转换按钮不可点击 | UI 禁用缓存，Markdown 转换页资源使用内容版本号，会话失败可重试，浏览器存储异常时保留提交能力 |
| 补丁包覆盖了新镜像或实际运行旧补丁 | 修复直接进入正式镜像；正常部署不再加载旧补丁覆盖文件，验证脚本按项目标签定位实际容器 |

## 重新打包

已有包含模型的 `mineru:latest` 时，在联网 Windows 机器运行：

```powershell
.\deploy\ragflow-mineru\scripts\package-windows.ps1 -EnvOverridePath .\airgap.prod.env
```

本次更新需要重新构建 Office 网关、Gradio 离线 UI 和 Markdown 转换服务，
不要添加它们的 `-Skip*Build` 参数。仅需复用已有模型时无需添加 `-BuildMineru`。
新生成的完整离线包会包含三项镜像、网关配置和配套脚本。

## 新部署

```bash
sudo bash scripts/deploy-linux.sh up --project-dir /opt/ragflow-mineru
bash scripts/verify-linux.sh --project-dir /opt/ragflow-mineru
```

自定义别名：首次部署添加 `--project-name internal-docs`。
脚本保存项目名，之后启动、停止、移除、验证均沿用它；另一套部署需同时使用不同目录、项目名和公网端口。

## 已有部署升级

项目名决定命名卷，直接从旧项目名切到新名字会连接新的数据卷，不会自动迁移已有数据。
先检查现有容器的 `com.docker.compose.project` 标签和 Redis/MySQL 等实际挂载，
备份 `.env`、Compose 配置与业务数据。完整的分阶段升级命令见同目录 README 的
“Existing deployments with manual hotfixes”部分；先 `--skip-up` 准备文件并核对自定义卷映射，再启动。

升级时保留服务器已有 `.env` 和业务数据目录。新镜像标签如与原配置不同，需在保留的 `.env` 中调整。
生成的 `*.v1.yml` 每次启动会重建，不要只修改生成文件。
旧补丁 ZIP 和 `apply-linux.sh` 不再使用；确保新容器没有旧 Python 文件挂载。
不要通过删除旧 Redis 卷、`down -v` 或 `rm --purge-data` 解决重名问题。

首次从旧页面升级后，对服务地址执行一次强制刷新或清理站点数据。
清理站点数据会清除匿名会话和本地任务历史；新增缓存控制用于避免后续更新重复出现旧页面问题。

## 验证范围

`verify-linux.sh` 验证实际项目容器、内置模型、网关路由，以及 DOCX → PDF → OCR → Markdown。
启用 `mineru-ui` 时还会检查健康协议、自定义组件及其 JavaScript 导入，
并调用与网页一致的异步转换函数，覆盖 Hybrid 选择、隐藏地址、下载解压和结果目录查找。
真实 OCR 验证需要目标服务器上的模型与 GPU，首次预热可能耗时数分钟。

仓库回归检查：

```bash
python -m unittest discover -s deploy/ragflow-mineru/tests -v
# 可选：本机已有 nginx:alpine 与 Docker 时验证真实反向代理
RUN_DOCKER_TESTS=1 python -m unittest discover -s deploy/ragflow-mineru/tests -p test_gateway_runtime.py -v
node --test services/md-convert/tests/ui_behavior.cjs
```

三个服务的 Python 测试分别在各服务目录执行 `python -m unittest discover -s tests -v`；
先安装对应服务依赖，Office 与 Markdown API 测试另外需要 `httpx`。
