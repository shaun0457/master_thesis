# Appendix: Tennessee Eastman Process (TEP) Variable Descriptions

**Source:** Rieth, C. A., et al. (2017). "A detailed description and OPC UA interface to the Tennessee Eastman process". *ArXiv e-prints*.

This document provides a detailed list of all measurable and manipulated variables within the Tennessee Eastman Process, including their descriptions, steady-state values under normal operation, and units. This list is a core reference for understanding the TEP dataset and performing root cause analysis.

---

## Appendix A: Process Measurements (XMEAS)

There are a total of 41 measurement variables, divided into two groups: 22 continuous process measurements and 19 component analysis measurements, which have a sampling delay.

### **Continuous Process Measurements (XMEAS 1-22)**

| Variable ID | Description | Steady State | Unit | Lower limit | Upper limit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| XMEAS(1) | A feed (stream 1) | 0.25052 | kscmh | — | — |
| XMEAS(2) | D feed (stream 2) | 3664.0 | kg/hr | — | — |
| XMEAS(3) | E feed (stream 3) | 4509.3 | kg/hr | — | — |
| XMEAS(4) | A and C feed (stream 4) | 26.985 | % | — | — |
| XMEAS(5) | Recycle flow (stream 8) | 22.211 | % | — | — |
| XMEAS(6) | Reactor feed rate (stream 6) | 9622.7 | kscmh | — | — |
| XMEAS(7) | Reactor pressure | 2704.9 | kPa | — | — |
| XMEAS(8) | Reactor level | 80.235 | % | — | — |
| XMEAS(9) | Reactor temperature | 120.35 | °C | — | — |
| XMEAS(10)| Purge rate (stream 9) | 40.082 | kscmh | — | — |
| XMEAS(11)| Separator temperature | 90.133 | °C | — | — |
| XMEAS(12)| Separator level | 40.099 | % | — | — |
| XMEAS(13)| Separator pressure | 2705.1 | kPa | — | — |
| XMEAS(14)| Separator underflow (stream 10) | 59.558 | m³/hr | — | — |
| XMEAS(15)| Stripper level | 49.929 | % | — | — |
| XMEAS(16)| Stripper pressure | 2705.9 | kPa | — | — |
| XMEAS(17)| Stripper underflow (stream 11) | 33.221 | m³/hr | — | — |
| XMEAS(18)| Stripper temperature | 110.36 | °C | — | — |
| XMEAS(19)| Stripper steam flow | 118.99 | kg/hr | — | — |
| XMEAS(20)| Compressor work | 3020.3 | kW | — | — |
| XMEAS(21)| Reactor cooling water outlet temp. | 90.231 | °C | — | — |
| XMEAS(22)| Separator cooling water outlet temp. | 90.045 | °C | — | — |

### **Component Analysis Measurements (XMEAS 23-41)**

*Note: These measurements have a sampling delay in the simulation.*

| Variable ID | Description | Steady State | Unit | Lower limit | Upper limit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| XMEAS(23)| Reactor feed concentration, A | 0.099958 | mol % | — | — |
| XMEAS(24)| Reactor feed concentration, B | 0.039983 | mol % | — | — |
| XMEAS(25)| Reactor feed concentration, C | 0.44979 | mol % | — | — |
| XMEAS(26)| Reactor feed concentration, D | 0.17991 | mol % | — | — |
| XMEAS(27)| Reactor feed concentration, E | 0.14993 | mol % | — | — |
| XMEAS(28)| Reactor feed concentration, F | 0.080028 | mol % | — | — |
| XMEAS(29)| Purge gas concentration, A | 0.24641 | mol % | — | — |
| XMEAS(30)| Purge gas concentration, B | 0.098564 | mol % | — | — |
| XMEAS(31)| Purge gas concentration, C | 0.22401 | mol % | — | — |
| XMEAS(32)| Purge gas concentration, D | 0.14934 | mol % | — | — |
| XMEAS(33)| Purge gas concentration, E | 0.24890 | mol % | — | — |
| XMEAS(34)| Purge gas concentration, F | 0.016335 | mol % | — | — |
| XMEAS(35)| Purge gas concentration, G | 0.016439 | mol % | — | — |
| XMEAS(36)| Purge gas concentration, H | 0.0 | mol % | — | — |
| XMEAS(37)| Liquid product concentration, D | 0.31551 | mol % | — | — |
| XMEAS(38)| Liquid product concentration, E | 0.23935 | mol % | — | — |
| XMEA