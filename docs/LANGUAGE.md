# 中文界面 / Chinese language support

Trading Simulator now provides **English** and **简体中文** options across:

- The original Trading Terminal and historical replay
- Single-asset Trading Arcade
- Multi-asset Portfolio Arcade
- The no-code strategy builder, order tickets, portfolio summaries, risk controls, trade journals, labels and accessibility descriptions

Click **EN / 中文** in the lower-right corner. Your choice is saved locally
in this browser under `trading-simulator-language`, and follows you between
all modes and refreshes.

## 中文使用指南

1. 打开 `http://127.0.0.1:5173`。
2. 点击右下角的 **中文**，立即切换简体中文。
3. 在交易竞技场中选择历史品种、日期与时间跨度，模拟买卖并查看成交记录。
4. 在组合交易竞技场中选择2至5种支持的美元资产，共享一个模拟资金账户。
5. 使用策略编辑器编写或生成交易规则，保存后再推进历史时间。

**策略语言保留英文，这是有意设计的。** 例如：

```text
WHEN spy SMA(20) CROSSES ABOVE SMA(100) BUY 50% qqq
WHEN spy SMA(20) CROSSES BELOW SMA(100) SELL 100% qqq
```

原因：`WHEN`、`SMA`、`BUY`、`SELL`、ticker代码和指标参数属于程序语法，
不是界面文字。切换中文不会修改历史存档、已保存策略、股票代码、交易或后台数据。

## Developers

- `src/i18n.tsx`: React context, persisted locale, translation catalog and
  known server-event translations.
- `src/i18n.css`: responsive switch styling.
- `scripts/check_i18n.py`: check missing direct translation keys, duplicate
  catalog entries, locale persistence and provider integration.
- `.github/workflows/ci.yml`: run localization check before TypeScript build.

Add new user-facing English UI strings to the catalog, then render with
`const {t} = useI18n();` and `{t("English label")}`.

Leave asset identifiers, program instructions, prices and provider quotes
unchanged. Localization only affects presentation, not simulated execution.

There are no new npm or Python dependencies in this update.
