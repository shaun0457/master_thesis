# create_tep_database.py
import pandas as pd
from sqlalchemy import create_engine
import os

# --- 设定路径 ---
TEP_DATA_FILENAME = "TEP_FaultFree_Training.csv"
TEP_DATA_DIR = "TEP_data"
DB_FILENAME = "tep_database_FaultFree.db"

# --- 检查 CSV 档案是否存在 ---
csv_path = os.path.join(TEP_DATA_DIR, TEP_DATA_FILENAME)
if not os.path.exists(csv_path):
    print(f"错误：找不到 TEP CSV 档案 '{csv_path}'。请先准备好资料。")
    exit()

# --- 载入 CSV 并写入 SQLite ---
print(f"正在从 '{csv_path}' 载入资料...")
df = pd.read_csv(csv_path)

# 为了方便 SQL 查询，我们将栏位名中的特殊字元替换掉
df.columns = [col.replace('[', '').replace(']', '').replace(' ', '_').lower() for col in df.columns]

db_path = f"sqlite:///{DB_FILENAME}"
engine = create_engine(db_path)

table_name = "process_data"
print(f"正在将资料写入资料库 '{DB_FILENAME}' 的资料表 '{table_name}' 中...")
df.to_sql(table_name, engine, if_exists="replace", index=False)

print("\nTEP 资料库建立成功！")
print(f"资料库档案: {DB_FILENAME}")
print(f"资料表: {table_name}")
print("前 5 笔资料预览:")
with engine.connect() as conn:
    result_df = pd.read_sql(f"SELECT * FROM {table_name} LIMIT 5", conn)
    print(result_df)

# create_tep_database.py (在末尾追加的部分)

print("\n正在创建 fault_descriptions 资料表...")

# 建立一个包含故障描述的 DataFrame
fault_data = {
    'faultnumber': range(21), # 0-20
    'description': [
        'Normal Operation',
        'A/C Feed Ratio Step Change',
        'B Composition Step Change',
        'D Feed Temperature Step Change',
        'Reactor Cooling Water Inlet Temperature Step Change',
        'Condenser Cooling Water Inlet Temperature Step Change',
        'A Feed Loss',
        'C Header Pressure Loss',
        'A, B, C Feed Composition Random Variation',
        'D Feed Temperature Random Variation',
        'C Feed Temperature Random Variation',
        'Reactor Cooling Water Inlet Temperature Random Variation',
        'Condenser Cooling Water Inlet Temperature Random Variation',
        'Reaction Kinetics Slow Drift',
        'Reactor Cooling Water Valve Sticking',
        'Condenser Cooling Water Valve Sticking',
        'Unknown (but structured)',
        'Unknown (but structured)',
        'Unknown (but structured)',
        'Unknown (but structured)',
        'Unknown (but structured)'
    ]
}
df_faults = pd.DataFrame(fault_data)

# 将其写入同一个资料库
df_faults.to_sql("fault_descriptions", engine, if_exists="replace", index=False)

print("fault_descriptions 资料表已成功创建并写入。")