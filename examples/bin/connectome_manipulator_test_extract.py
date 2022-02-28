# Python script to apply connectome manipulations to SONATA circuit
# Circuit: circuit-build-S1_v1 (toy circuit)

# Initialization

""" Imports """
from connectome_manipulator.connectome_manipulation import connectome_manipulation


# Connectome manipulation - Configuration
manip_config = {}

""" Circuit """
manip_config['circuit_path'] = '/gpfs/bbp.cscs.ch/data/scratch/proj83/home/pokorny/circuit-build-S1_v1'
manip_config['circuit_config'] = 'sonata/circuit_config.json' # SONATA (.json) format; path rel. to 'circuit_path'
manip_config['output_path'] = '/gpfs/bbp.cscs.ch/data/scratch/proj83/home/pokorny/circuit-build-S1_v1_manip' # Optional
manip_config['blue_config_to_update'] = 'CircuitConfig' # Optional; path rel. to 'circuit_path'
manip_config['workflow_template'] = '../templates/bbp-workflow_RegisterCircuit.cfg' # Optional; to create bbp-workflow config from

""" General settings """
manip_config['seed'] = 3210
manip_config['N_split_nodes'] = 10

""" Manipulation (name + sequence of manipulation functions with arguments) """
manip_config['manip'] = {'name': 'EmptyConnectome', 'fcts': [{'source': 'conn_extraction', 'kwargs': {}}]}


# Connectome manipulation - Apply manipulation
connectome_manipulation.main(manip_config, do_profiling=True)