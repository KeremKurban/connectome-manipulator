"""
Module for building synaptic delay model, consisting of three basic functions:
  -extract(...): Extracts distance-dependent synaptic delays between samples of neurons
  -build(...): Fits a linear distance-dependent synaptic delay model of type "LinDelayModel" to the data
  -plot(...): Visualizes extracted data vs. actual model output
"""

import os.path

import matplotlib.pyplot as plt
import numpy as np
import progressbar
from sklearn.linear_model import LinearRegression

from connectome_manipulator.model_building import model_types


def extract(circuit, bin_size_um, max_range_um=None, sel_src=None, sel_dest=None, sample_size=None, **_):
    """Extract distance-dependent synaptic delays between samples of neurons."""
    # Select edge population [assuming exactly one edge population in given edges file]
    assert len(circuit.edges.population_names) == 1, 'ERROR: Only a single edge population per file supported for modelling!'
    edges = circuit.edges[circuit.edges.population_names[0]]

    # Select corresponding source/target nodes populations
    src_nodes = edges.source
    tgt_nodes = edges.target

    node_ids_src = src_nodes.ids(sel_src)
    node_ids_dest = tgt_nodes.ids(sel_dest)

    if sample_size is None or sample_size <= 0:
        sample_size = np.inf # Select all nodes
    sample_size_src = min(sample_size, len(node_ids_src))
    sample_size_dest = min(sample_size, len(node_ids_dest))
    node_ids_src_sel = node_ids_src[np.random.permutation([True] * sample_size_src + [False] * (len(node_ids_src) - sample_size_src))]
    node_ids_dest_sel = node_ids_dest[np.random.permutation([True] * sample_size_dest + [False] * (len(node_ids_dest) - sample_size_dest))]

    # Extract distance/delay values
    edges_table = edges.pathway_edges(source=node_ids_src_sel, target=node_ids_dest_sel, properties=['@source_node', 'delay', 'afferent_center_x', 'afferent_center_y', 'afferent_center_z'])

    print(f'INFO: Extracting delays from {edges_table.shape[0]} synapses (sel_src={sel_src}, sel_dest={sel_dest}, sample_size={sample_size} neurons)')

    src_pos = src_nodes.positions(edges_table['@source_node'].to_numpy()).to_numpy() # Soma position of pre-synaptic neuron
    tgt_pos = edges_table[['afferent_center_x', 'afferent_center_y', 'afferent_center_z']].to_numpy() # Synapse position on post-synaptic dendrite
    src_tgt_dist = np.sqrt(np.sum((tgt_pos - src_pos)**2, 1))
    src_tgt_delay = edges_table['delay'].to_numpy()

    # Extract distance-dependent delays
    if max_range_um is None:
        max_range_um = np.max(src_tgt_dist)
    num_bins = np.ceil(max_range_um / bin_size_um).astype(int)
    dist_bins = np.arange(0, num_bins + 1) * bin_size_um
    dist_delays_mean = np.full(num_bins, np.nan)
    dist_delays_std = np.full(num_bins, np.nan)
    dist_count = np.zeros(num_bins).astype(int)

    print('Extracting distance-dependent synaptic delays...', flush=True)
    pbar = progressbar.ProgressBar()
    for idx in pbar(range(num_bins)):
        d_sel = np.logical_and(src_tgt_dist >= dist_bins[idx], (src_tgt_dist < dist_bins[idx + 1]) if idx < num_bins - 1 else (src_tgt_dist <= dist_bins[idx + 1])) # Including last edge
        dist_count[idx] = np.sum(d_sel)
        if dist_count[idx] > 0:
            dist_delays_mean[idx] = np.mean(src_tgt_delay[d_sel])
            dist_delays_std[idx] = np.std(src_tgt_delay[d_sel])

    return {'dist_bins': dist_bins, 'dist_delays_mean': dist_delays_mean, 'dist_delays_std': dist_delays_std, 'dist_count': dist_count, 'dist_delay_min': np.min(src_tgt_delay)}


def build(dist_bins, dist_delays_mean, dist_delays_std, dist_delay_min, bin_size_um, **_):
    """Build distance-dependent synaptic delay model (linear model for delay mean, const model for delay std)."""
    assert np.all((np.diff(dist_bins) - bin_size_um) < 1e-12), 'ERROR: Bin size mismatch!'
    bin_offset = 0.5 * bin_size_um

    # Mean delay model (linear)
    X = np.array(dist_bins[:-1][np.isfinite(dist_delays_mean)] + bin_offset, ndmin=2).T
    y = dist_delays_mean[np.isfinite(dist_delays_mean)]
    dist_delays_mean_fit = LinearRegression().fit(X, y)
    delay_mean_coefs = [dist_delays_mean_model.coef_[0], dist_delays_mean_model.intercept_]

    # Std delay model (const)
    delay_std = np.mean(dist_delays_std)

    # Min delay model (const)
    delay_min = dist_delay_min

    # Create model
    model = model_types.LinDelayModel(delay_mean_coefs=delay_mean_coefs, delay_std=delay_std, delay_min=delay_min)
    print(model.get_model_str())

    return 


def plot(out_dir, dist_bins, dist_delays_mean, dist_delays_std, dist_count, model, **_):
    """Visualize data vs. model."""
    bin_width = np.diff(dist_bins[:2])[0]

    model_params = model.get_param_dict()
    mean_model_str = f'f(x) = {model_params["delay_mean_coefs"][1]:.3f} * x + {model_params["delay_mean_coefs"][0]:.3f}'
    std_model_str = f'f(x) = {model_params["delay_std"]:.3f}'
    min_model_str = f'f(x) = {model_params["delay_min"]:.3f}'

    # Draw figure
    plt.figure(figsize=(8, 4), dpi=300)
    plt.bar(dist_bins[:-1] + 0.5 * bin_width, dist_delays_mean, width=0.95 * bin_width, facecolor='tab:blue', label=f'Data mean: N = {np.sum(dist_count)} synapses')
    plt.bar(dist_bins[:-1] + 0.5 * bin_width, dist_delays_std, width=0.5 * bin_width, facecolor='tab:red', label=f'Data std: N = {np.sum(dist_count)} synapses')
    plt.plot(dist_bins, model.get_mean(dist_bins), '--', color='tab:brown', label='Model mean: ' + mean_model_str)
    plt.plot(dist_bins, model.get_std(dist_bins), '--', color='tab:olive', label='Model std: ' + std_model_str)
    plt.plot(dist_bins, model.get_min(dist_bins), '--', color='tab:gray', label='Model min: ' + min_model_str)
    plt.xlim((dist_bins[0], dist_bins[-1]))
    plt.xlabel('Distance [um]')
    plt.ylabel('Delay [ms]')
    plt.title('Distance-dependent synaptic delays', fontweight='bold')
    plt.legend(loc='upper left', bbox_to_anchor=(1.1, 1.0))

    # Add second axis with bin counts
    count_color = 'tab:orange'
    ax_count = plt.gca().twinx()
    ax_count.set_yscale('log')
    ax_count.step(dist_bins, np.concatenate((dist_count[:1], dist_count)), color=count_color)
    ax_count.set_ylabel('Count', color=count_color)
    ax_count.tick_params(axis='y', which='both', colors=count_color)
    ax_count.spines['right'].set_color(count_color)

    plt.tight_layout()

    out_fn = os.path.abspath(os.path.join(out_dir, 'data_vs_model.png'))
    print(f'INFO: Saving {out_fn}...')
    plt.savefig(out_fn)