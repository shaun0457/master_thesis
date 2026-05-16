from core.context_assembler import DynamicContextAssembler

_assembler = DynamicContextAssembler()


def get_system_prompt(agent_name: str, policy: str = "debate", phase: str = "default") -> str:
    return _assembler.assemble_system_prompt(agent_name, phase=phase, protocol=policy)
