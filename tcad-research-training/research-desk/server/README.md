# 服务器展示入口

`https://tcad.xjtu.shop/desk/` 使用受邀账号访问。页面、静态资源与 API 共用 HTTPS 鉴权。Caddy 在科研站点导入 `desk.caddy`，通过 `/srv/dram-see-desk/current` 读取展示文件；该目录只发布页面、Material 组件、脱敏波形及依赖许可证。与状态页、仿真目录及运行队列独立。

| 路径（相对 `/desk/`） | 方法 | 当前结果 |
|---|---|---|
| `api/v1/catalog` | GET | 200；列出实际归档别名，训练数据与模型列表保持空数组 |
| `api/v1/predict-r` | POST | 503；`status=model_pending`，预测值为 `null` |
| `api/v1/predict-f` | POST | 同上 |

占位响应只用于接口联调，服务不处理或保存推理输入。真实模型、访问配额和科学准入均就绪后再切换推理后端。服务器账号 `owner` 的初始凭据仅保存在服务器 root 私有目录；导师使用独立账号，另行发放。
