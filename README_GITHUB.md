# Twitter热门信息推送机器人 🐦➡️💬

自动抓取美国、韩国、中国三国的**技术类**和**股市/金融类**Twitter热门信息，翻译整理后推送到飞书。

## 推送日程

| 时间 (CST) | 内容 | 说明 |
|-----------|------|------|
| **08:00** | 📅 昨日回顾 | 前一天的Twitter热门汇总 |
| **17:00** | 🔴 今日实时 | 当天的实时热门信息 |

## GitHub Secrets 配置

在仓库 Settings → Secrets and variables → Actions 中配置以下 Secrets：

### 飞书配置（必填）

| Secret | 说明 | 示例 |
|--------|------|------|
| `FEISHU_APP_ID` | 飞书应用App ID | `cli_a92c1c508339dcd2` |
| `FEISHU_APP_SECRET` | 飞书应用App Secret | `Md2r9gR9...` |
| `FEISHU_RECEIVE_ID` | 接收方ID | `ou_xxxxx` |
| `FEISHU_RECEIVE_ID_TYPE` | 接收方类型 | `open_id` 或 `chat_id` |

## 手动触发

也可以手动触发推送：

1. 进入仓库 **Actions** 页面
2. 选择 **Twitter热门推送** 工作流
3. 点击 **Run workflow**
4. 选择模式：`today`（今日实时）或 `yesterday`（昨日回顾）
5. 点击 **Run**