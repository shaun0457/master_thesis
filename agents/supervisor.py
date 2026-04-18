# agents/supervisor.py
"""Supervisor Agent: Orchestrates team collaboration."""

from .base import BaseAgent


class SupervisorAgent(BaseAgent):
    """
    Supervisor: Plans, delegates, reviews, and coordinates the team.

    Responsibilities:
    - Create overall strategy
    - Delegate subtasks to workers (DE, DS, ME)
    - Review deliverables
    - Synthesize final results
    """

    def __init__(self, bb_store, router, **kwargs):
        super().__init__("supervisor", bb_store, router, **kwargs)

    def _build_prompt(self, context: dict) -> str:
        """Override to add supervisor-specific context."""
        base_prompt = super()._build_prompt(context)

        # Add supervisor-specific guidance
        supervisor_guidance = """

# Supervisor-Specific Guidance
- You are the team coordinator
- Break complex tasks into subtasks
- Delegate to DE (data), DS (modeling), ME (domain)
- Review their outputs and synthesize
- Always specify next_owner when delegating
"""
        return base_prompt + supervisor_guidance
