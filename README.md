# PetLens MVP

一个面向手机浏览器的宠物物品风险筛查 Demo：

- 文字输入、手机拍照、图片上传
- 本地知识库匹配
- 可选 Tavily 可信域名网络检索
- 可选 Claude 图像识别与综合分析
- 五维雷达图：食品 / 毒性 / 玩具 / 危险 / 兴趣
- 结构化结论、例外、建议、急症信号和来源
- SQLite 本地查询历史

## 1. 本地运行（Windows 10 推荐在 WSL2 中）

```bash
cd ~/code
unzip petlens-mvp.zip
cd petlens-mvp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run streamlit_app.py
```

浏览器打开终端显示的地址。手机与电脑在同一局域网时，也可用电脑局域网 IP 加 `:8501` 访问。

### 服务启停

以下命令均可在项目根目录执行。服务固定监听 `0.0.0.0:8501`，关闭终端后仍会继续运行。

```bash
# 后台启动（日志写入 logs/petlens.log）
./scripts/start.sh

# 查看运行状态、PID 和网页响应情况
./scripts/status.sh

# 停止服务
./scripts/stop.sh

# 重启服务
./scripts/restart.sh

# 持续查看日志；按 Ctrl+C 只退出日志查看
./scripts/logs.sh
```

本机访问地址：<http://localhost:8501>。服务 PID 保存在 `run/petlens.pid`。

## 2. API 配置

编辑 `.env`：

- `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL`：图片识别；也可负责最终综合分析。
- `OPENAI_COMPATIBLE_*`：可选，用 DeepSeek 等 OpenAI 兼容接口承担文本综合分析。
- `TAVILY_API_KEY`：网络检索。未配置时，应用仍能以本地知识库演示运行。

不要把 `.env` 提交到 GitHub。

## 3. 测试

```bash
pytest -q
```

## 4. 部署到手机可访问的网址

最省事的是推送到 GitHub，再部署到 Streamlit Community Cloud。把密钥放在部署平台的 Secrets，不要写进代码。

## 5. 三天 MVP 的边界

- 高可信本地条目先覆盖猫和狗。
- 不做登录、支付、原生安卓、3D 猫窝、推送提醒。
- 不把模型输出当医疗诊断；紧急情形始终引导联系兽医。
- 分类不是互斥标签，同一物品可以同时“像玩具”且“高危险”。

## 6. 推荐的 Codex 第一个任务

把整个文件夹作为项目打开，然后发：

> 先阅读 README、streamlit_app.py 和 app 目录。不要立即重构。运行 pytest 和 Streamlit，列出当前功能、失败点和三天 MVP 最重要的三个改进。得到我确认后再逐项修改，每次修改都运行测试并展示 diff。
