# 图片敏感词链接检测平台

在线上传 Excel，批量读取图片链接，使用服务器端 OCR 识别图片中的可见文字；命中指定关键词后清除对应图片链接，并提供处理后的 Excel 与完整识别日志。

## 主要功能

- 支持 `.xlsx`、`.xlsm`。
- 多关键词输入：逗号、分号或换行分隔。
- 支持完整单词、包含关键词、大小写控制与强化 OCR。
- 一个单元格含多条链接时，只删除命中的链接。
- 下载、DNS 或 OCR 失败时保留原链接，避免误删。
- 阻止内网、回环和保留地址，并逐跳验证重定向地址。
- 网站访问密码由部署平台生成，不写入代码仓库。
- 默认同一时间处理 1 个 OCR 任务，其他任务排队，减少服务器内存不足。

## Render 部署

仓库根目录包含 `render.yaml` 和 `Dockerfile`。在 Render 中选择 **New → Blueprint**，连接本仓库并部署即可。

默认配置为新加坡区域、Standard 2GB 实例，以保证 OCR 运行空间。部署完成后，在 Render 服务的 Environment 页面查看自动生成的 `APP_PASSWORD`，它就是网页访问密码。

## 本机运行

```bash
docker compose up --build
```

然后打开 `http://localhost:8000`。本机 compose 默认密码为 `change-this-password`，正式使用前必须修改。

## 注意

OCR 识别会受清晰度、字号、字体、角度、遮挡和复杂背景影响，无法保证识别出每一个字符。重要数据请开启强化 OCR，并复核 CSV 日志。部分 CDN 会限制云服务器 IP、地区、DNS、Referer 或访问频率；程序提供 `OUTBOUND_PROXY` 环境变量用于配置合规代理出口。

更详细说明见：[README_部署说明.md](README_部署说明.md)。
