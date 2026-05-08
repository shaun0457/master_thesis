# 附錄：田納西-伊斯曼流程 (TEP) 變數詳解

**來源:** Rieth, C. A., et al. (2017). "A detailed description and OPC UA interface to the Tennessee Eastman process". *ArXiv e-prints*.

本文件詳細列出了田納西-伊斯曼流程中所有可測量和可操縱的變數，包括其描述、正常操作下的穩態值及單位。這份清單是理解 TEP 數據集和進行根本原因分析的核心依據。

---

## 附錄 A：過程測量變數 (Process Measurements - XMEAS)

總共有 41 個測量變數，分為兩組：22 個連續的過程測量值和 19 個有採樣延遲的成分分析測量值。

### **連續過程測量值 (XMEAS 1-22)**

| 變數 ID | 描述 (Description) | 穩態值 (Steady State) | 單位 (Unit) |
| :--- | :--- | :--- | :--- |
| XMEAS(1) | A feed (stream 1) | 0.25052 | kscmh |
| XMEAS(2) | D feed (stream 2) | 3664.0 | kg/hr |
| XMEAS(3) | E feed (stream 3) | 4509.3 | kg/hr |
| XMEAS(4) | A and C feed (stream 4) | 26.985 | % |
| XMEAS(5) | Recycle flow (stream 8) | 22.211 | % |
| XMEAS(6) | Reactor feed rate (stream 6) | 9622.7 | kscmh |
| XMEAS(7) | Reactor pressure | 2704.9 | kPa |
| XMEAS(8) | Reactor level | 80.235 | % |
| XMEAS(9) | Reactor temperature | 120.35 | °C |
| XMEAS(10)| Purge rate (stream 9) | 40.082 | kscmh |
| XMEAS(11)| Separator temperature | 90.133 | °C |
| XMEAS(12)| Separator level | 40.099 | % |
| XMEAS(13)| Separator pressure | 2705.1 | kPa |
| XMEAS(14)| Separator underflow (stream 10) | 59.558 | m³/hr |
| XMEAS(15)| Stripper level | 49.929 | % |
| XMEAS(16)| Stripper pressure | 2705.9 | kPa |
| XMEAS(17)| Stripper underflow (stream 11) | 33.221 | m³/hr |
| XMEAS(18)| Stripper temperature | 110.36 | °C |
| XMEAS(19)| Stripper steam flow | 118.99 | kg/hr |
| XMEAS(20)| Compressor work | 3020.3 | kW |
| XMEAS(21)| Reactor cooling water outlet temp. | 90.231 | °C |
| XMEAS(22)| Separator cooling water outlet temp. | 90.045 | °C |

### **成分分析測量值 (XMEAS 23-41)**

*注意：這些測量值在模擬中存在採樣延遲。*

| 變數 ID | 描述 (Description) | 穩態值 (Steady State) | 單位 (Unit) |
| :--- | :--- | :--- | :--- |
| XMEAS(23)| Reactor feed concentration, A | 0.099958 | mol % |
| XMEAS(24)| Reactor feed concentration, B | 0.039983 | mol % |
| XMEAS(25)| Reactor feed concentration, C | 0.44979 | mol % |
| XMEAS(26)| Reactor feed concentration, D | 0.17991 | mol % |
| XMEAS(27)| Reactor feed concentration, E | 0.14993 | mol % |
| XMEAS(28)| Reactor feed concentration, F | 0.080028 | mol % |
| XMEAS(29)| Purge gas concentration, A | 0.24641 | mol % |
| XMEAS(30)| Purge gas concentration, B | 0.098564 | mol % |
| XMEAS(31)| Purge gas concentration, C | 0.22401 | mol % |
| XMEAS(32)| Purge gas concentration, D | 0.14934 | mol % |
| XMEAS(33)| Purge gas concentration, E | 0.24890 | mol % |
| XMEAS(34)| Purge gas concentration, F | 0.016335 | mol % |
| XMEAS(35)| Purge gas concentration, G | 0.016439 | mol % |
| XMEAS(36)| Purge gas concentration, H | 0.0 | mol % |
| XMEAS(37)| Liquid product concentration, D | 0.31551 | mol % |
| XMEAS(38)| Liquid product concentration, E | 0.23935 | mol % |
| XMEAS(39)| Liquid product concentration, F | 0.40833 | mol % |
| XMEAS(40)| Liquid product concentration, G | 0.036814 | mol % |
| XMEAS(41)| Liquid product concentration, H | 0.0 | mol % |

---

## 附錄 B：操縱變數 (Manipulated Variables - XMV)

總共有 12 個操縱變數，這些是控制系統可以直接調整的閥門或設定點。

| 變數 ID | 描述 (Description) | 穩態值 (Steady State) | 單位 (Unit) |
| :--- | :--- | :--- | :--- |
| **XMV(1)** | D Feed Flow valve (stream 2) | 53.953 | % |
| **XMV(2)** | E Feed Flow valve (stream 3) | 44.453 | % |
| **XMV(3)** | A Feed Flow valve (stream 1) | 21.213 | % |
| **XMV(4)** | A & C Feed Flow valve (stream 4) | 61.302 | % |
| **XMV(5)** | Recycle Valve (stream 8) | 23.354 | % |
| **XMV(6)** | Reactor Cooling Water Flow valve | 50.117 | % |
| **XMV(7)** | Condenser Cooling Water Flow valve | 81.189 | % |
| **XMV(8)** | Purge Valve (stream 9) | 16.381 | % |
| **XMV(9)** | Separator Pot Liquid Flow valve (stream 10) | 50.493 | % |
| **XMV(10)**| Stripper Liquid Product Flow valve (stream 11)| 33.221 | % |
| **XMV(11)**| Stripper Steam Valve | 40.064 | % |
| **XMV(12)**| Reactor Agitator Speed | 50.000 | % |