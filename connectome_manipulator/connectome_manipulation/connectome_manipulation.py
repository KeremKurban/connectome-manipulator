"""
Main module for connectome manipulations:
  - Loads a SONATA connectome using SNAP
  - Applies manipulation(s) to the connectome, as specified by the manipulation config dict
  - Writes back the manipulated connectome to a SONATA edges file, together with a new circuit config
"""

import importlib
import json
import os
import pandas as pd
import resource
import subprocess
import time
from datetime import datetime

import numpy as np
from bluepysnap.circuit import Circuit

from connectome_manipulator import log


def load_circuit(sonata_config, N_split=1, popul_name=None):
    """Load given edges population of a SONATA circuit using SNAP."""
    # Load circuit
    log.info(f'Loading circuit from {sonata_config} (N_split={N_split})')
    c = Circuit(sonata_config)

    # Select edge population [assuming exactly one edge population in given edges file (to be manipulated)]
    log.log_assert(len(c.edges.population_names) > 0, 'No edge population found!')
    if popul_name is None:
        if len(c.edges.population_names) == 1:
            popul_name = c.edges.population_names[0] # Select the only existing population
        else:
            popul_name = 'default' # Use default name
            log.warning(f'Multiple edges populations found - Trying to load "{popul_name}" population!')
    log.log_assert(popul_name in c.edges.population_names, f'Population "{popul_name}" not found in edges file!')
    edges = c.edges[popul_name]
    edges_file = c.config['networks']['edges'][0]['edges_file']

    # Select corresponding source/target nodes populations
    src_nodes = edges.source
    tgt_nodes = edges.target
    nodes = [src_nodes, tgt_nodes]

    src_file_idx = np.where(np.array(c.nodes.population_names) == src_nodes.name)[0]
    log.log_assert(len(src_file_idx) == 1, 'Source nodes population file index error!')
    tgt_file_idx = np.where(np.array(c.nodes.population_names) == tgt_nodes.name)[0]
    log.log_assert(len(tgt_file_idx) == 1, 'Target nodes population file index error!')

    src_nodes_file = c.config['networks']['nodes'][src_file_idx[0]]['nodes_file']
    tgt_nodes_file = c.config['networks']['nodes'][tgt_file_idx[0]]['nodes_file']
    nodes_files = [src_nodes_file, tgt_nodes_file]

    log.info(f'Using edges population "{edges.name}" between nodes "{src_nodes.name}" and "{tgt_nodes.name}"')

    # Define target node splits
    tgt_node_ids = tgt_nodes.ids()
    node_ids_split = np.split(tgt_node_ids, np.cumsum([np.ceil(len(tgt_node_ids) / N_split).astype(int)] * (N_split - 1)))

    return nodes, nodes_files, node_ids_split, edges, edges_file, popul_name


def apply_manipulation(edges_table, nodes, manip_config, aux_dict):
    """Apply manipulation to connectome (edges_table) as specified in the manip_config."""
    log.info(f'APPLYING MANIPULATION "{manip_config["manip"]["name"]}"')
    for m_step in range(len(manip_config['manip']['fcts'])):
        manip_source = manip_config['manip']['fcts'][m_step]['source']
        manip_kwargs = manip_config['manip']['fcts'][m_step]['kwargs']
        log.info(f'>>Step {m_step + 1} of {len(manip_config["manip"]["fcts"])}: source={manip_source}, kwargs={manip_kwargs}')

        manip_module = importlib.import_module('connectome_manipulator.connectome_manipulation.' + manip_source)
        log.log_assert(hasattr(manip_module, 'apply'), f'Manipulation module "{manip_source}" requires apply() function!')
        edges_table = manip_module.apply(edges_table, nodes, aux_dict, **manip_kwargs)

    return edges_table


def edges_to_parquet(edges_table, output_file):
    """Write edge properties table to parquet file."""
    edges_table = edges_table.rename(columns={'@target_node': 'connected_neurons_post', '@source_node': 'connected_neurons_pre'}) # Convert column names
    edges_table['synapse_type_id'] = 0 # Add type ID, required for SONATA
    edges_table.to_parquet(output_file, index=False)


def parquet_to_sonata(input_file_list, output_file, nodes, nodes_files, keep_parquet=False):
    """Convert parquet file(s) to SONATA format (using parquet-converters tool; recomputes indices!!)."""
    log.info(f'Converting {len(input_file_list)} .parquet file(s) to SONATA')
    input_files = ' '.join(input_file_list)

    if os.path.exists(output_file):
        os.remove(output_file)

    # Running parquet conversion [Requires parquet-converters/0.5.7 from archive/2021-07 (which should be used by used JupyterLab kernel)]
    proc = subprocess.Popen(f'module load parquet-converters/0.5.7;\
                              parquet2hdf5 --format SONATA --from {nodes_files[0]} {nodes[0].name} --to {nodes_files[1]} {nodes[1].name} -o {output_file} {input_files}',
                            shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.info(proc.communicate()[0].decode())
    log.log_assert(os.path.exists(output_file), 'Parquet conversion error - SONATA file not created successfully!')

    # Delete temporary parquet files (optional)
    if not keep_parquet:
        log.info(f'Deleting {len(input_file_list)} temporary .parquet file(s)')
        for fn in input_file_list:
            os.remove(fn)


def create_new_file_from_template(new_file, template_file, replacements_dict, skip_comments=True):
    """Create new text file from template with replacements."""
    log.info(f'Creating file {new_file}')
    with open(template_file, 'r') as file:
        content = file.read()

    content_lines = []
    for line in content.splitlines():
        if skip_comments and len(line.strip()) > 0 and line.strip()[0] == '#': # Skip replacement in commented lines
            content_lines.append(line)
        else: # Apply replacements
            for (src, dest) in replacements_dict.items():
                line = line.replace(src, dest)
            content_lines.append(line)
    content = '\n'.join(content_lines)

    with open(new_file, 'w') as file:
        file.write(content)


def create_sonata_config(new_config_file, new_edges_fn, orig_config_file, orig_edges_fn, orig_base_dir=None, popul_name=None):
    """Create new SONATA config (.JSON) from original, incl. modifications."""
    log.info(f'Creating SONATA config {new_config_file}')

    def fct_update(d):
        if orig_base_dir is not None:
            d = {k: v.replace('$BASE_DIR', '$ORIG_BASE_DIR') if isinstance(v, str) else v for k, v in d.items()}

        if 'edges_file' in d.keys():
            if popul_name is None or 'populations' not in d.keys() or ('populations' in d.keys() and popul_name in d['populations']):
                if orig_base_dir is not None:
                    if '$NETWORK_EDGES_DIR' in d['edges_file']:
                        d['edges_file'] = d['edges_file'].replace('$NETWORK_EDGES_DIR', '$MANIP_NETWORK_EDGES_DIR')
                    else:
                        d['edges_file'] = d['edges_file'].replace('$ORIG_BASE_DIR', '$BASE_DIR')
                d['edges_file'] = d['edges_file'].replace(orig_edges_fn, new_edges_fn)
        return d
    
    with open(orig_config_file, 'r') as file:
        config = json.load(file, object_hook=fct_update)

    if orig_base_dir is not None:
        config['manifest'] = {'$ORIG_BASE_DIR': orig_base_dir, **config['manifest'], '$BASE_DIR': '.'}
        if '$NETWORK_EDGES_DIR' in config['manifest']:
            config['manifest']['$MANIP_NETWORK_EDGES_DIR'] = config['manifest']['$NETWORK_EDGES_DIR'].replace('$ORIG_BASE_DIR', '$BASE_DIR')

    with open(new_config_file, 'w') as f:
        json.dump(config, f, indent=2)


def create_workflow_config(circuit_path, blue_config, manip_name, output_path, template_file):
    """Create bbp-workflow config for circuit registration (from template)."""
    if manip_name is None:
        manip_name = ''

    if len(manip_name) > 0:
        workflow_file = os.path.split(os.path.splitext(template_file)[0])[1] + f'_{manip_name}' + os.path.splitext(template_file)[1]
        circuit_name = '_'.join(circuit_path.split('/')[-4:] + [manip_name])
        circuit_descr = f'{manip_name} applied to {circuit_path}'
        circuit_type = 'Circuit manipulated by connectome_manipulator'
    else:
        workflow_file = os.path.split(template_file)[1]
        circuit_name = '_'.join(circuit_path.split('/')[-4:])
        circuit_descr = f'No manipulation applied to {circuit_path}'
        circuit_type = 'Circuit w/o manipulation'

    workflow_path = os.path.join(output_path, 'workflows')
    if not os.path.exists(workflow_path):
        os.makedirs(workflow_path)

    config_replacements = {'$CIRCUIT_NAME': circuit_name,
                           '$CIRCUIT_DESCRIPTION': circuit_descr,
                           '$CIRCUIT_TYPE': circuit_type,
                           '$CIRCUIT_CONFIG': blue_config,
                           '$DATE': datetime.today().strftime('%Y-%m-%d %H:%M:%S') + ' [generated from template]',
                           '$FILE_NAME': workflow_file}
    create_new_file_from_template(os.path.join(workflow_path, workflow_file), template_file, config_replacements, skip_comments=False)


def resource_profiling(enabled=False, description='', reset=False, csv_file=None):  # pragma: no cover
    """Resources profiling (memory consumption, execution time) and writing to log file.
       Optional: If csv_file is provided, data is also written to a .csv file for
                 better machine readability.
    """
    if not enabled:
        return

    mem_curr = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2
    if not hasattr(resource_profiling, 'mem_before') or reset:
        mem_diff = None
    else:
        mem_diff = mem_curr - resource_profiling.mem_before
    resource_profiling.mem_before = mem_curr

    if not hasattr(resource_profiling, 't_init') or reset:
        resource_profiling.t_init = time.time()
        resource_profiling.t_start = resource_profiling.t_init
        t_tot = None
        t_dur = None
    else:
        t_end = time.time()
        t_tot = t_end - resource_profiling.t_init
        t_dur = t_end - resource_profiling.t_start
        resource_profiling.t_start = t_end

    if len(description) > 0:
        description_log = ' [' + description + ']'

    field_width = 36 + max(len(description_log) - 14, 0)

    log_msg = '\n'
    log_msg = log_msg + '*' * field_width + '\n'
    log_msg = log_msg + '* ' + 'RESOURCE PROFILING{}'.format(description_log).ljust(field_width - 4) + ' *' + '\n'
    log_msg = log_msg + '*' * field_width + '\n'

    log_msg = log_msg + '* ' + 'Max. memory usage (GB):' + '{:.3f}'.format(mem_curr).rjust(field_width - 27) + ' *' + '\n'

    if mem_diff is not None:
        log_msg = log_msg + '* ' + 'Max. memory diff. (GB):' + '{:.3f}'.format(mem_diff).rjust(field_width - 27) + ' *' + '\n'

    if t_tot is not None and t_dur is not None:
        log_msg = log_msg + '*' * field_width + '\n'

        if t_tot > 3600:
            t_tot_log = t_tot / 3600
            t_tot_unit = 'h'
        else:
            t_tot_log = t_tot
            t_tot_unit = 's'
        log_msg = log_msg + '* ' + f'Total time ({t_tot_unit}):        ' + '{:.3f}'.format(t_tot_log).rjust(field_width - 27) + ' *' + '\n'

        if t_dur > 3600:
            t_dur_log = t_dur / 3600
            t_dur_unit = 'h'
        else:
            t_dur_log = t_dur
            t_dur_unit = 's'
        log_msg = log_msg + '* ' + f'Elapsed time ({t_dur_unit}):      ' + '{:.3f}'.format(t_dur_log).rjust(field_width - 27) + ' *' + '\n'

    log_msg = log_msg + '*' * field_width + '\n'

    log.profiling(log_msg)

    # Add entry to performance table and write to .csv file (optional)
    if csv_file is not None:
        if not hasattr(resource_profiling, 'perf_table') or reset:
            resource_profiling.perf_table = pd.DataFrame([], columns=['label', 'i_split', 'N_split', 'mem_curr', 'mem_diff', 't_tot', 't_dur'])
            resource_profiling.perf_table.index.name = 'id'
            if not os.path.exists(os.path.split(csv_file)[0]):
                os.makedirs(os.path.split(csv_file)[0])

        label, *spec = description.split('-')
        i_split = np.nan
        N_split = np.nan

        if len(spec) == 1:
            spec = spec[0].split('/')
            if len(spec) == 2:
                i_split = spec[0]
                N_split = spec[1]

        resource_profiling.perf_table.loc[resource_profiling.perf_table.shape[0]] = [label, i_split, N_split, mem_curr, mem_diff, t_tot, t_dur]
        resource_profiling.perf_table.to_csv(csv_file)


def main(manip_config, do_profiling=False, do_resume=False, keep_parquet=False):  # pragma: no cover
    """Main entry point for circuit manipulations.
      [OPTIMIZATION FOR HUGE CONNECTOMES: Split post-synaptically
       into N disjoint parts of target neurons (OPTIONAL)]."""
    # Set output path
    if manip_config.get('output_path') is None:
        output_path = manip_config['circuit_path'] # If no path provided, use circuit path for output
    else:
        output_path = manip_config['output_path']
        if not os.path.exists(output_path):
            os.makedirs(output_path)

    # Initialize logger
    log_file = log.logging_init(output_path, name=__name__.rsplit('.', maxsplit=1)[-1])

    # Initialize profiler
    csv_file = os.path.splitext(log_file)[0] + '.csv'
    resource_profiling(do_profiling, 'initial', reset=True, csv_file=csv_file)

    # Load circuit
    log.log_assert(os.path.splitext(manip_config['circuit_config'])[-1] == '.json', 'SONATA (.json) config required!')
    sonata_config = os.path.join(manip_config['circuit_path'], manip_config['circuit_config'])
    with open(sonata_config, 'r') as file:
        cfg_dict = json.load(file)
        log.log_assert(os.path.normpath(cfg_dict['manifest']['$BASE_DIR']) == '.' or os.path.normpath(cfg_dict['manifest']['$BASE_DIR']) == os.path.normpath(os.path.join(manip_config['circuit_path'], os.path.split(manip_config['circuit_config'])[0])),
                       'Base dir in SONATA config must point to root directory of config file!') # Otherwise, manipulated folder structure may not be consistent any more
    N_split = max(manip_config.get('N_split_nodes', 1), 1)

    popul_name_spec = manip_config.get('population_name')
    nodes, nodes_files, node_ids_split, edges, edges_file, popul_name = load_circuit(sonata_config, N_split, popul_name_spec)

    log.log_assert(os.path.abspath(edges_file).find(os.path.abspath(manip_config['circuit_path'])) == 0, 'Edges file not within circuit path!')
    edges_fn = os.path.split(edges_file)[1]
    rel_edges_path = os.path.relpath(os.path.split(edges_file)[0], manip_config['circuit_path'])

    # Prepare output parquet path
    parquet_path = os.path.join(output_path, rel_edges_path, 'parquet')
    if not os.path.exists(parquet_path):
        os.makedirs(parquet_path)

    # Start processing
    np.random.seed(manip_config.get('seed', 123456))

    parquet_file_list = []
    N_syn_in = []
    N_syn_out = []
    aux_dict = {} # Auxiliary dict to pass information from one split iteration to another
    for i_split, split_ids in enumerate(node_ids_split):

        # Resume option: Don't recompute, if .parquet file of current split already exists
        parquet_file_manip = os.path.splitext(os.path.join(parquet_path, os.path.split(edges_file)[1]))[0] + f'_{manip_config["manip"]["name"]}' + (f'.{i_split:04d}' if N_split > 1 else '') + '.parquet'
        if do_resume and os.path.exists(parquet_file_manip):
            log.info(f'Split {i_split + 1}/{N_split}: Parquet file already exists - SKIPPING (do_resume={do_resume})')
        else:
            # Load edge table containing all edge (=synapse) properties
            edges_table = edges.afferent_edges(split_ids, properties=sorted(edges.property_names))
            log.info(f'Split {i_split + 1}/{N_split}: Loaded {edges_table.shape[0]} synapses with {edges_table.shape[1]} properties targeting {len(split_ids)} neurons')
            N_syn_in.append(edges_table.shape[0])
            resource_profiling(do_profiling, f'loaded-{i_split + 1}/{N_split}', csv_file=csv_file)

            # Apply connectome manipulation
            aux_dict.update({'N_split': N_split, 'i_split': i_split, 'split_ids': split_ids})
            edges_table_manip = apply_manipulation(edges_table, nodes, manip_config, aux_dict)
            log.log_assert(edges_table_manip['@target_node'].is_monotonic_increasing, 'Target nodes not monotonically increasing!') # [TESTING/DEBUGGING]
            N_syn_out.append(edges_table_manip.shape[0])
            resource_profiling(do_profiling, f'manipulated-{i_split + 1}/{N_split}', csv_file=csv_file)

            # Write back connectome to .parquet file
            edges_to_parquet(edges_table_manip, parquet_file_manip)
            resource_profiling(do_profiling, f'saved-{i_split + 1}/{N_split}', csv_file=csv_file)
        parquet_file_list.append(parquet_file_manip)

    log.info(f'Total input/output synapse counts: {np.sum(N_syn_in, dtype=int)}/{np.sum(N_syn_out, dtype=int)} (Diff: {np.sum(N_syn_out, dtype=int) - np.sum(N_syn_in, dtype=int)})\n')

    # Convert .parquet file(s) to SONATA file
    edges_file_manip = os.path.join(output_path, rel_edges_path, os.path.splitext(edges_fn)[0] + f'_{manip_config["manip"]["name"]}' + os.path.splitext(edges_file)[1])
    parquet_to_sonata(parquet_file_list, edges_file_manip, nodes, nodes_files, keep_parquet)

    # Create new SONATA config (.JSON) from original config file
    edges_fn_manip = os.path.split(edges_file_manip)[1]
    sonata_config_manip = os.path.join(output_path, os.path.splitext(manip_config['circuit_config'])[0] + f'_{manip_config["manip"]["name"]}' + os.path.splitext(manip_config['circuit_config'])[1])
    create_sonata_config(sonata_config_manip, edges_fn_manip, sonata_config, edges_fn, orig_base_dir=os.path.join(manip_config['circuit_path'], os.path.split(manip_config['circuit_config'])[0]) if manip_config['circuit_path'] != output_path else None, popul_name=popul_name)

    # Write manipulation config to JSON file
    json_file = os.path.join(os.path.split(sonata_config_manip)[0], f'manip_config_{manip_config["manip"]["name"]}.json')
    with open(json_file, 'w') as f:
        json.dump(manip_config, f, indent=2)
    log.info(f'Creating file {json_file}')

    # Create new symlinks and circuit config
    if not manip_config.get('blue_config_to_update') is None:
        blue_config = os.path.join(manip_config['circuit_path'], manip_config['blue_config_to_update'])
        log.log_assert(os.path.exists(blue_config), f'Blue config "{manip_config["blue_config_to_update"]}" does not exist!')
        with open(blue_config, 'r') as file: # Read blue config
            config = file.read()
        nrn_path = list(filter(lambda x: x.find('nrnPath') >= 0 and not x.strip()[0] == '#', config.splitlines()))[0].replace('nrnPath', '').strip() # Extract path to edges file from BlueConfig
        circ_path_entry = list(filter(lambda x: x.find('CircuitPath') >= 0 and not x.strip()[0] == '#', config.splitlines()))[0].strip() # Extract circuit path entry from BlueConfig
        log.log_assert(os.path.abspath(nrn_path).find(os.path.abspath(manip_config['circuit_path'])) == 0, 'nrnPath not within circuit path!')
        nrn_path_manip = os.path.join(output_path, os.path.relpath(nrn_path, manip_config['circuit_path'])) # Re-based path
        if not os.path.exists(os.path.split(nrn_path_manip)[0]):
            os.makedirs(os.path.split(nrn_path_manip)[0])

        # Symbolic link for edges.sonata
        symlink_src = os.path.relpath(edges_file_manip, os.path.split(nrn_path_manip)[0])
        symlink_dst = os.path.join(os.path.split(nrn_path_manip)[0], os.path.splitext(edges_fn_manip)[0] + '.sonata')
        if os.path.isfile(symlink_dst) or os.path.islink(symlink_dst):
            os.remove(symlink_dst) # Remove if already exists
        os.symlink(symlink_src, symlink_dst)
        log.info(f'Creating symbolic link ...{symlink_dst} -> {symlink_src}')

        # Create BlueConfig for manipulated circuit
        blue_config_manip = os.path.join(output_path, os.path.splitext(manip_config['blue_config_to_update'])[0] + f'_{manip_config["manip"]["name"]}' + os.path.splitext(manip_config['blue_config_to_update'])[1])
        config_replacement = {nrn_path: symlink_dst,
                              circ_path_entry: f'CircuitPath {output_path}'}
        create_new_file_from_template(blue_config_manip, blue_config, config_replacement)

        # Symbolic link for start.target (if not existing)
        symlink_src = os.path.join(manip_config['circuit_path'], 'start.target')
        symlink_dst = os.path.join(output_path, 'start.target')
        if os.path.isfile(symlink_src) and not os.path.isfile(symlink_dst):
            os.symlink(symlink_src, symlink_dst)
            log.info(f'Creating symbolic link ...{symlink_dst} -> {symlink_src}')

        # Symbolic link for CellLibraryFile (if not existing)
        cell_lib_fn = list(filter(lambda x: x.find('CellLibraryFile') >= 0, config.splitlines()))[0].replace('CellLibraryFile', '').strip() # Extract cell library file from BlueConfig
        if len(os.path.split(cell_lib_fn)[0]) == 0: # Filename only, no path
            symlink_src = os.path.join(manip_config['circuit_path'], cell_lib_fn)
            symlink_dst = os.path.join(output_path, cell_lib_fn)
            if os.path.isfile(symlink_src) and not os.path.isfile(symlink_dst):
                os.symlink(symlink_src, symlink_dst)
                log.info(f'Creating symbolic link ...{symlink_dst} -> {symlink_src}')

        # Create bbp-workflow config from template to register manipulated circuit
        if not manip_config.get('workflow_template') is None:
            create_workflow_config(manip_config['circuit_path'], blue_config_manip, manip_config['manip']['name'], output_path, manip_config['workflow_template'])

    resource_profiling(do_profiling, 'final', csv_file=csv_file)