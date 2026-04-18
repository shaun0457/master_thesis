# agents/ds.py
"""
Data Scientist (DS) Agent with ML toolbox integration.
Trains and evaluates machine learning models.
"""

import pandas as pd
from .base import BaseAgent
from mas.tools import MLToolbox


class DataScientistAgent(BaseAgent):
    """
    Data Scientist agent with ML toolbox for model training.

    Capabilities:
    - Machine learning model training (sklearn)
    - Load data from DE via blackboard
    - Request domain knowledge from ME
    - Peer judging for DE and ME from ML perspective
    """

    def __init__(self, bb_store, router, **kwargs):
        """
        Initialize Data Scientist with ML toolbox.

        Args:
            bb_store: BlackboardStore instance
            router: Router instance
            **kwargs: Additional args passed to BaseAgent
        """
        super().__init__("ds", bb_store, router, **kwargs)

        # Initialize ML toolbox
        try:
            self.ml = MLToolbox()
            self.ml_enabled = True
            print(f"[DS] [OK] ML toolbox initialized with {len(self.ml.ALLOWED_MODELS)} models")
        except Exception as e:
            self.ml = None
            self.ml_enabled = False
            print(f"[DS] [WARN]  ML toolbox not available: {e}")

    def _build_prompt(self, context: dict) -> str:
        """
        Build prompt with ML workflow guidance.

        Args:
            context: Run context dict

        Returns:
            str: Enhanced prompt with ML workflow instructions
        """
        # Get base prompt from parent
        base_prompt = super()._build_prompt(context)

        # Add ML workflow guidance
        ml_guidance = """

# ML Workflow Guidance

When working on ML tasks:
1. **Request data from DE**: Ask DE to query process_data table
2. **Load data from blackboard**: Use bb://data/sql_result_* paths
3. **Request domain insights from ME**: Ask ME about fault types, process variables
4. **Train model**: Use ML toolbox with appropriate algorithm
5. **Interpret results**: Consult ME for domain-specific interpretation
6. **Write analysis to blackboard**: Store results at bb://analysis/*

Available models: random_forest_classifier, logistic_regression, decision_tree, kmeans, pca

Example workflow:
- Request: Ask DE to fetch fault data with specific conditions
- Load: Read data from bb://data/sql_result_1
- Consult: Ask ME about fault characteristics
- Train: Use ML toolbox to train classifier
- Validate: Check metrics and feature importance
- Report: Write findings to blackboard
"""

        return base_prompt + ml_guidance
