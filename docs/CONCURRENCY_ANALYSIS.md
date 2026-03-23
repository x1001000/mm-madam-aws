# Lambda 並行控制分析：Reserved vs Provisioned Concurrency

**日期**：2026-03-23
**用途**：MM AI 後端 Madam（FastAPI + Lambda）
**參考文件**：[AWS Lambda 並行文件](https://docs.aws.amazon.com/zh_tw/lambda/latest/dg/lambda-concurrency.html)

---

## 兩種並行控制比較

| 項目 | Reserved Concurrency（預留並行） | Provisioned Concurrency（佈建並行） |
|------|-------------------------------|-----------------------------------|
| 定義 | 設定函數的最大並行執行環境數量 | 設定**預先初始化**的執行環境數量 |
| 佈建行為 | 按需建立實例（on-demand） | **預先暖機**，在收到請求前就已就緒 |
| 冷啟動 | **仍會發生**——Lambda 需要即時建立新實例 | **消除冷啟動**——實例已預先初始化 |
| 限流行為 | 達到上限即限流（throttle） | 超出預置數量後，使用未預留並行（除非同時設定了 reserved） |
| 費用 | 免費 | **額外收費**（即使閒置也計費） |

---

## 結論：應選擇 Provisioned Concurrency

### 原因

**Reserved Concurrency 無法解決冷啟動問題。** 它只保留容量上限，但實例仍然是按需建立的。

根據 `COLD_START_TEST.md` 的測試結果：

- **冷啟動延遲高達 25-30 秒**（Python 環境 + 大量套件載入）
- **基礎暖機實例僅 2 個**
- 對聊天氣泡的使用者體驗而言，30 秒的等待完全無法接受

唯有 **Provisioned Concurrency** 能預先初始化執行環境，讓請求直接命中暖機實例。

---

## 建議配置

### 估算所需並行數

```
並行數 = 平均每秒請求數 × 平均請求處理時間（秒）
```

以聊天氣泡為例：
- 假設尖峰 10 req/s，平均回應時間 2 秒
- 並行數 = 10 × 2 = **20**

### 配置方案

| 方案 | Provisioned | Reserved | 說明 |
|------|-------------|----------|------|
| 保守型 | 5 | 不設定 | 確保 5 個實例零冷啟動，超出部分使用帳戶未預留並行（可能冷啟動） |
| 建議型 | 5-10 | 20 | 基礎負載零冷啟動，尖峰最多 20 個實例（超出預置的部分仍可能冷啟動） |
| 搭配自動擴展 | 5（基礎）| 20 | 結合 Application Auto Scaling，依排程或使用率自動調整預置數量 |

### 重要注意事項

1. **Provisioned Concurrency 只能用於已發佈的版本（published version）或別名（alias）**，不能用於 `$LATEST`
2. **設定後不會立即生效**——Lambda 需要 1-2 分鐘開始分配，且必須全部分配完成後才能使用
3. **費用考量**——預置的實例即使閒置也會計費，務必搭配 Auto Scaling 避免浪費。可使用 [AWS Lambda 費用計算器](https://calculator.aws/#/createCalculator/Lambda) 估算成本
4. 若 provisioned concurrency 的總量等於 reserved concurrency，`$LATEST` 版本將無法執行

---

## 搭配其他冷啟動優化

Provisioned Concurrency 能消除冷啟動，但也應同步優化啟動時間以降低成本：

| 優化方法 | 預期效果 | 優先順序 |
|----------|---------|---------|
| 延遲載入套件（Lazy imports） | 將初始化時間從 ~30s 降至 ~5-10s | 高 |
| 縮小部署包（移除非必要依賴） | 加快程式碼下載速度 | 中 |
| Provisioned Concurrency | 完全消除使用者端冷啟動感知 | 高 |
| Application Auto Scaling | 依排程自動調整預置數量，節省成本 | 中 |

---

## 替代方案評估

若冷啟動問題嚴重且成本偏高，可考慮：

| 替代方案 | 優點 | 缺點 |
|---------|------|------|
| **ECS Fargate** | 容器常駐，無冷啟動 | 需自行管理容器、最低成本較高 |
| **App Runner** | 全託管、自動擴展、容器常駐 | 較少細粒度控制 |
| **Lambda + 佈建並行** | 無伺服器、按用量計費、與現有架構一致 | 預置部分有固定成本 |

以目前 MM AI 聊天氣泡的規模，**Lambda + Provisioned Concurrency** 是最務實的選擇——維持現有架構不變，僅需加上佈建並行設定即可大幅改善使用者體驗。
