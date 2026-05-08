import os

# ▼▼▼ 核心修改 1：定义 prompts 文件夹的路径 ▼▼▼
# 使用 os.path.dirname(__file__) 可以确保无论您从哪里运行脚本，
# 路径总是相对于 prompt_builder.py 所在的位置，这更稳健。
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompt")
POLICY = 'minimal'

# ▲▲▲ 核心修改 1 ▲▲▲

def get_system_prompt(agent_name: str, policy: str = POLICY) -> str:
    """
    从 "prompts/" 子文件夹中加载并返回指定代理人的角色卡内容作为 System Prompt。
    它会根据 policy 优先尝试加载带后缀的特定版本角色卡。
    """

    # ▼▼▼ 核心修改 2：在构建文件名时，使用 PROMPTS_DIR 作为基础路径 ▼▼▼
    policy_card_filename = f"{agent_name.lower()}_card_{policy}.md"
    base_card_filename = f"{agent_name.lower()}_card.md"

    policy_card_path = os.path.join(PROMPTS_DIR, policy_card_filename)
    base_card_path = os.path.join(PROMPTS_DIR, base_card_filename)
    # ▲▲▲ 核心修改 2 ▲▲▲

    card_path_to_load = None
    if os.path.exists(policy_card_path):
        card_path_to_load = policy_card_path
    elif os.path.exists(base_card_path):
        card_path_to_load = base_card_path
    else:
        print(f"[ERROR][PromptBuilder] Role card not found for agent '{agent_name}' with policy '{policy}'.")
        print(f"  - Searched at: {policy_card_path}")
        print(f"  - Also searched at: {base_card_path}")
        return f"You are a helpful AI assistant acting as an expert: {agent_name}."

    try:
        with open(card_path_to_load, 'r', encoding='utf-8') as f:
            print(f"        [PromptBuilder] Loading role card from: '{card_path_to_load}'")
            content = f.read()
            # 最终的保险措施，防止因为 .md 文件中的 { char 而导致 KeyError
            safe_content = content.replace('{', '{{').replace('}', '}}')
            return safe_content

    except Exception as e:
        print(f"[ERROR][PromptBuilder] Failed to read role card at '{card_path_to_load}': {e}")

        return f"You are a helpful AI assistant acting as an expert: {agent_name}."
