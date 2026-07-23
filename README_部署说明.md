# 图片敏感词链接检测平台（在线网页版）

## 已实现功能

- 上传 `.xlsx` / `.xlsm` 文件。
- 输入一个或多个敏感词，支持逗号、分号、换行分隔。
- 批量读取工作簿内的普通图片链接、单元格超链接和 `HYPERLINK()` 公式。
- 服务端下载图片并进行中文、英文、数字全文 OCR。
- 支持完整单词匹配或包含匹配、大小写控制、强化 OCR。
- 一个单元格有多条链接时，只移除命中的链接。
- 下载失败、DNS失败或 OCR 失败时保留原链接，并写入 CSV 日志。
- 输出处理后的 Excel 和 OCR 全文日志，不覆盖原文件。
- 可设置网站访问密码，并阻止访问内网/回环地址，降低 SSRF 风险。
- 页面左侧为工具菜单，后续可继续加入其他工具。

> OCR 无法保证识别出图片上的每一个字符。极小文字、低清晰度、艺术字体、强反光、遮挡或复杂背景都可能导致漏识别。建议对重要数据开启“强化 OCR”，并复核日志。

## 最省事的在线部署方式：Docker 平台

本项目已经包含 `Dockerfile`，可以部署到任何支持 Docker Web Service 的云平台。

### 方法一：GitHub + Render

1. 新建一个 GitHub 仓库，把本压缩包内的所有文件上传到仓库根目录。
2. 在 Render 选择 **New → Blueprint**，连接该 GitHub 仓库。
3. Render 会自动读取仓库根目录的 `render.yaml` 与 `Dockerfile`。
4. 添加环境变量：
   - `APP_PASSWORD`：网站访问密码，建议设置。
   - `APP_TITLE`：网站名称，可选。
   - `MAX_UPLOAD_MB`：Excel 最大上传大小，默认 50。
   - `MAX_URLS_PER_JOB`：单次唯一图片链接上限，默认 5000。
   - `MAX_CONCURRENT_JOBS`：同时执行的 OCR 任务数，默认 1。
   - `JOB_TTL_HOURS`：结果保留小时数，默认 24。
   - `OUTBOUND_PROXY`：可选；服务器访问某些 CDN 失败时配置代理。
5. 部署完成后，平台会提供一个 HTTPS 网站地址。

### 方法二：自己的 Linux 服务器

服务器安装 Docker 和 Docker Compose 后，在项目目录执行：

```bash
docker compose up -d --build
```

然后打开：

```text
http://服务器IP:8000
```

正式使用建议再通过 Nginx 或 Caddy 配置域名和 HTTPS。

## 本机测试

已安装 Docker Desktop 时，在项目目录运行：

```bash
docker compose up --build
```

打开：

```text
http://localhost:8000
```

`docker-compose.yml` 默认密码为 `change-this-password`，正式上线前必须修改。

## 数据和隐私

- 上传文件和结果默认存放在服务器的 `data/任务ID/` 目录。
- 程序会在访问首页或新建任务时清理超过 `JOB_TTL_HOURS` 的任务目录。
- 云平台若使用临时磁盘，服务器重启后结果可能丢失；用户应在完成后立即下载。
- 需要长期保留时，可以把 `DATA_DIR` 指向持久磁盘，或继续接入对象存储。

## 资源建议

OCR 模型会占用一定内存和 CPU。`render.yaml` 默认使用 Standard 2GB 实例；大量图片或开启强化 OCR 时，可升级至 4GB 或更高。当前 Docker 默认只启动 1 个 Uvicorn worker，避免每个 worker 重复加载 OCR 模型。

## 目录结构

```text
app/
  main.py                 Web API、任务状态和下载
  services/
    excel.py              Excel 链接提取、修改和日志
    downloader.py         图片下载
    ocr.py                全文 OCR
    matcher.py            关键词匹配
    security.py           URL 安全校验
  static/
    index.html            网页
    style.css             页面样式
    app.js                上传、进度和下载逻辑
Dockerfile
render.yaml
docker-compose.yml
requirements.txt
```

## 添加其他工具

1. 在 `app/services/` 中新增处理模块。
2. 在 `app/main.py` 中新增对应 API。
3. 在 `app/static/index.html` 左侧菜单增加入口，并新增页面区域。
4. 在 `app/static/app.js` 增加上传和结果展示逻辑。

## 当前限制

- 不支持旧版 `.xls`。
- 密码保护适合个人或小团队，不是完整的多用户账户系统。
- 任务状态保存在内存中，服务重启后正在执行的任务不会继续。
- 某些图片 CDN 会限制数据中心 IP、地区、DNS 或请求来源；可通过 `OUTBOUND_PROXY` 使用合规代理出口。
