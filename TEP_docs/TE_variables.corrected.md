# Tennessee Eastman Process — Variables Dictionary (XMEAS & XMV)

本檔整理 TE 常用的量測變數（XMEAS 1–41）與可操縱變數（XMV 1–12），方便與資料欄位 `xmeas_#`、`xmv_#` 對齊。

> Note: 不同資料版本的單位記法略有差異；此處採用文獻中常見標示。若與你使用的版本不符，請以資料附件或論文中給定單位為準。

---

## 1) Process Measurements — XMEAS (41)

| Index | Tag | Description | Base (steady) | Unit (standardized) |
|---:|:---|:---|---:|:---|
| 1 | XMEAS1 | A feed (stream 1) | 0.25052 | kscmh |
| 2 | XMEAS2 | D feed (stream 2) | 3664.0 | kg/hr |
| 3 | XMEAS3 | E feed (stream 3) | 4509.3 | kg/hr |
| 4 | XMEAS4 | A and C feed (stream 4) | 26.985 | % |
| 5 | XMEAS5 | Recycle flow (stream 8) | 22.211 | % |
| 6 | XMEAS6 | Reactor feed rate (stream 6) | 9622.7 | kscmh |
| 7 | XMEAS7 | Reactor pressure | 2704.9 | kPa |
| 8 | XMEAS8 | Reactor level | 80.235 | % |
| 9 | XMEAS9 | Reactor temperature | 120.35 | °C |
| 10 | XMEAS10 | Purge rate (stream 9) | 40.082 | kscmh |
| 11 | XMEAS11 | Separator temperature | 90.133 | °C |
| 12 | XMEAS12 | Separator level | 40.099 | % |
| 13 | XMEAS13 | Separator pressure | 2705.1 | kPa |
| 14 | XMEAS14 | Separator underflow (stream 10) | 59.558 | m³/hr |
| 15 | XMEAS15 | Stripper level | 49.929 | % |
| 16 | XMEAS16 | Stripper pressure | 2705.9 | kPa |
| 17 | XMEAS17 | Stripper underflow (stream 11) | 33.221 | m³/hr |
| 18 | XMEAS18 | Stripper temperature | 110.36 | °C |
| 19 | XMEAS19 | Stripper steam flow | 118.99 | kg/hr |
| 20 | XMEAS20 | Compressor work | 3020.3 | kW |
| 21 | XMEAS21 | Reactor cooling water outlet temp. | 90.231 | °C |
| 22 | XMEAS22 | Separator cooling water outlet temp. | 90.045 | °C |
| 23 | XMEAS23 | Reactor feed concentration, A | 0.099958 | mol % |
| 24 | XMEAS24 | Reactor feed concentration, B | 0.039983 | mol % |
| 25 | XMEAS25 | Reactor feed concentration, C | 0.44979 | mol % |
| 26 | XMEAS26 | Reactor feed concentration, D | 0.17991 | mol % |
| 27 | XMEAS27 | Reactor feed concentration, E | 0.14993 | mol % |
| 28 | XMEAS28 | Reactor feed concentration, F | 0.080028 | mol % |
| 29 | XMEAS29 | Purge gas concentration, A | 0.24641 | mol % |
| 30 | XMEAS30 | Purge gas concentration, B | 0.098564 | mol % |
| 31 | XMEAS31 | Purge gas concentration, C | 0.22401 | mol % |
| 32 | XMEAS32 | Purge gas concentration, D | 0.14934 | mol % |
| 33 | XMEAS33 | Purge gas concentration, E | 0.24890 | mol % |
| 34 | XMEAS34 | Purge gas concentration, F | 0.016335 | mol % |
| 35 | XMEAS35 | Purge gas concentration, G | 0.016439 | mol % |
| 36 | XMEAS36 | Purge gas concentration, H | 0.0 | mol % |
| 37 | XMEAS37 | Liquid product concentration, D | 0.31551 | mol % |
| 38 | XMEAS38 | Liquid product concentration, E | 0.23935 | mol % |
| 39 | XMEAS39 | Component D in purge stream | — | mol% |
| 40 | XMEAS40 | Component E in purge stream | — | mol% |
| 41 | XMEAS41 | Component F in purge stream | — | mol% |

## 2) Manipulated Variables — XMV (12)

| Index | Tag  | Description | Unit (typical) |
|---:|:---|:---|:---|
| 1 | XMV1 | D feed flow | kg/hr |
| 2 | XMV2 | E feed flow | kg/hr |
| 3 | XMV3 | A feed flow | kscmh |
| 4 | XMV4 | A + C feed flow | kscmh |
| 5 | XMV5 | Compressor recycle valve | % |
| 6 | XMV6 | Purge valve | % |
| 7 | XMV7 | Separator pot liquid flow | m³/hr |
| 8 | XMV8 | Stripper liquid product flow | m³/hr |
| 9 | XMV9 | Stripper steam valve | % |
| 10 | XMV10 | Reactor cooling water flow | kg/hr |
| 11 | XMV11 | Condenser cooling water flow | kg/hr |
| 12 | XMV12 | Agitator speed | rpm |

---

### 對齊建議
- 若原始資料欄位名為 `xmeas_#`、`xmv_#`，可用本表對照成語義化名稱。
- 建議在 ME 的 RAG 檢索中同時索引「Index、Tag、描述關鍵詞」以提升召回率。