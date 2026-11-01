# 美股财报日历 · 每日推送到微信

每天北京时间 10:00，GitHub Actions 会自动做三件事：

1. 读取 `watchlist.txt` 里的关注列表
2. 用 [Finnhub](https://finnhub.io) 查询每家公司未来 90 天内的财报日
3. 把结果整理好，通过 [Server酱](https://sct.ftqq.com) 推送到你的个人微信

推送内容按距离远近分组：过去 24 小时已发布、7 天内、8–30 天、30 天以上、暂无日期。每家公司都会显示：

- **北京时间**：已经从美东时间换算好，夏令时和冬令时自动处理。盘前发布大约是北京当天晚上，盘后发布大约是北京第二天凌晨。
- 美东日期、盘前还是盘后、EPS 预期、营收预期
- 一个 Earnings Whispers 链接，点开可以查看日期是否已确认，以及耳语数字

全部使用免费服务，不需要服务器。

## 配置步骤

### 1. 获取 Finnhub API key

在 <https://finnhub.io> 免费注册，登录后在 Dashboard 里复制 API key。免费版每分钟可以调用 60 次。

### 2. 获取 Server酱 SendKey

打开 <https://sct.ftqq.com>，用微信扫码登录，并关注"方糖"服务号。然后在 SendKey 页面复制你的 SendKey。

### 3. 把两个 key 填到 GitHub Secrets

进入仓库的 **Settings → Secrets and variables → Actions → New repository secret**，添加两个 secret：

| Name | Value |
|---|---|
| `FINNHUB_API_KEY` | 第 1 步拿到的 Finnhub API key |
| `SERVERCHAN_SENDKEY` | 第 2 步拿到的 Server酱 SendKey |

### 4. 合并到 main 分支

GitHub 只会运行**默认分支**上的定时任务，所以代码要先合并到 `main`。

### 5. 手动运行一次，验证配置

进入 **Actions → Daily earnings report → Run workflow**：

- **勾选 sample**：使用示例数据，只验证微信推送是否配置正确，不需要 Finnhub key
- **不勾选**：使用真实数据完整跑一遍

之后每天北京时间 10:00 会自动运行。如果运行失败，微信会收到一条"运行失败"的提醒，GitHub 也会发邮件通知你。

## 修改关注列表

编辑 `watchlist.txt`，每行写一个代码，后面可以跟一个中文名：

```
AAPL   苹果
NVDA   英伟达
TSLA
```

改完提交到 `main`，下次运行时生效。

## 修改推送时间

修改 `.github/workflows/daily-earnings.yml` 里的 `cron` 字段。注意它使用的是 **UTC 时间**，等于北京时间减 8 小时。比如：

- 北京时间 10:00 → `0 2 * * *`
- 北京时间 08:30 → `30 0 * * *`

## 本地运行

```bash
pip install -r requirements.txt
```

用示例数据预览，不需要任何 key：

```bash
python -m earnings_watch --sample --dry-run
```

用真实数据跑一遍，但不推送：

```bash
FINNHUB_API_KEY=xxx python -m earnings_watch --dry-run
```

运行测试：

```bash
pip install pytest && python -m pytest
```

报告会保存在 `output/report.md`。GitHub Actions 每次运行后，也会把这个文件存成 artifact，保留 14 天。

## 已知限制

- **日期可能是预估的**：较远的财报日大多是数据商估算的，公司正式公布后才会确定。Finnhub 不区分"已确认"和"预估"，可以点 EW 链接查看。
- **Server酱 免费版的限制**：
  - 每天 5 条，这个项目每天只用 1 条
  - 微信卡片上只显示标题，要点开才能看完整内容，所以标题里会直接写出 7 天内要发财报的公司
  - 消息内容只保留 1 天。如果转发到群里，群友需要在 1 天内点开
- **GitHub 定时任务可能延迟**：整点附近是高峰期，可能晚几分钟到几十分钟才运行。如果是公开仓库，连续 60 天没有提交，定时任务会被自动停用。

## 代码结构

```
earnings_watch/
  __main__.py    命令行入口
  watchlist.py   读取关注列表
  finnhub.py     Finnhub 数据源（以后可以换成 Earnings Whispers 等）
  report.py      分组、时间换算、生成 Markdown
  serverchan.py  推送到微信
  sample.py      示例数据
tests/           单元测试
```
