
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def plot_cross_correlation(s1, s2, lag_range):
    '''
    Calculates and visualizes the cross-correlation between two time-series.

    Args:
        s1 (pd.Series): The first time series.
        s2 (pd.Series): The second time series.
        lag_range (int): The number of lags to test on each side of zero.

    Returns:
        int: The lag at which the maximum absolute correlation occurs.
    '''
    # Ensure series are aligned and have no NaNs from shifting
    s1_aligned = s1.dropna()
    s2_aligned = s2.dropna()
    common_index = s1_aligned.index.intersection(s2_aligned.index)
    s1_common = s1_aligned.loc[common_index]
    s2_common = s2_aligned.loc[common_index]


    correlations = {}
    for lag in range(-lag_range, lag_range + 1):
        # The shift operation introduces NaNs, which corr() handles by default (pairwise)
        correlations[lag] = s1_common.corr(s2_common.shift(lag))

    # Remove any NaN results from correlations dict before finding the max
    valid_correlations = {k: v for k, v in correlations.items() if pd.notna(v)}
    if not valid_correlations:
        print("Could not compute any valid correlations.")
        return None

    max_corr_lag = max(valid_correlations, key=lambda k: abs(valid_correlations[k]))

    plt.figure(figsize=(10, 6))
    # Use stem plot for better visualization of discrete lags
    (markerline, stemlines, baseline) = plt.stem(list(valid_correlations.keys()), list(valid_correlations.values()))
    plt.setp(markerline, 'markerfacecolor', 'b')
    plt.setp(baseline, 'color','r', 'linewidth', 2)

    plt.title(f'Cross-Correlation between {s1.name or "Series 1"} and {s2.name or "Series 2"}')
    plt.xlabel('Lag (s2 relative to s1)')
    plt.ylabel('Correlation')
    plt.grid(True)
    # Highlight the lag with the maximum absolute correlation
    plt.axvline(max_corr_lag, color='red', linestyle='--', label=f'Max Abs Corr Lag: {max_corr_lag}')
    plt.legend()
    
    # Save the figure
    figure_path = 'figures/cross_correlation_plot.png'
    plt.savefig(figure_path)
    plt.close() # Close the plot to free up memory

    print(f"Cross-correlation plot saved to {figure_path}")
    return max_corr_lag
