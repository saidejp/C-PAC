# CPAC/pipeline/cpac_runner.py
#
# FCP-INDI

'''
This module contains functions used to run a C-PAC pipeline
'''

# Import packages
from multiprocessing import Process
import os
from CPAC.utils.utils import create_seeds_, create_group_log_template
from CPAC.utils import Configuration
import yaml
import time
from time import strftime


# Validate length of directory
def validate(config_obj):
    
    #check for path lengths
    working_dir = config_obj.workingDirectory
    
    try:
        if len(working_dir) > 70:
            print "\n\n" + "WARNING: Path to working directory should NOT be more than 70 characters."
            print "Please update your configuration. Working directory: ", working_dir, "\n\n"
            raise Exception
    except:
        print "\n\n" + "ERROR: Your directories in Output Settings are empty." + "\n" + \
        "Error name: cpac_runner_0002" + "\n\n"
        raise Exception


def get_vectors(strat):

    paths = []
    def dfs(val_list, path):

        if val_list == []:
            paths.append(path)

        else:
            vals = []
            vals.append(val_list.pop())

            for val in vals:

                # make this an if statement because it trips up when it gets a
                # 'None' entry for one of the iterables
                if val != None:
                                    ### check if val is float, correct it on some version of python or ipython
                    ### avoid auto change to double quote of the path
                    if isinstance(val[0], float):
                        #val = '%.2f' % val[0]
                        val = [str(val[0])]


                if path == '':
                    dfs(list(val_list), str(val))

                else:
                    dfs(list(val_list), str(val) + '#' + path)


    val_list = []

    for key in sorted(strat.keys()):
        val_list.append(strat[key])


    dfs(val_list, '')
    

    return paths



def make_entries(paths, path_iterables):

    entries = []
    idx = 1
    for path in sorted(paths):

        sub_entries = []
        values = path.split('#')

        indx = 0
        for value in values:

            if '[' or '(' in value:

                value = value.strip('[]')
                value = value.strip('()')

            if ',' in value:
                import re
                value = re.sub(r',', '.', value)
                value = re.sub(r' ', '', value)
            sub_entries.append(path_iterables[indx] + '_' + value)
            indx += 1

        ### remove single quote in the paths
        sub_entries = map(lambda x: x.replace("'", ""), sub_entries)
        print "sub entries: "
        print sub_entries
      
        entries.append(sub_entries)

    return entries




def build_strategies(configuration):

    import collections

    ### make paths shorter
    path_iterables = ['_gm_threshold', '_wm_threshold', '_csf_threshold', '_threshold', '_compcor', '_target_angle_deg']
    non_strategy_iterables = ['_fwhm', '_hp', '_lp', '_bandpass_freqs']

    proper_names = {'_threshold':'Scrubbing Threshold = ', '_csf_threshold':'Cerebral Spinal Fluid Threshold = ',
                    '_gm_threshold':'Gray Matter Threshold = ',
                    'nc':'Compcor: Number Of Components = ', '_compcor':'Nuisance Signal Regressors = ',
                    '_target_angle_deg':'Median Angle Correction: Target Angle in Degree = ', '_wm_threshold':'White Matter Threshold = '}


    config_iterables = {'_gm_threshold': eval('configuration.grayMatterThreshold'), '_wm_threshold': eval('configuration.whiteMatterThreshold'), '_csf_threshold': eval('configuration.cerebralSpinalFluidThreshold'), '_threshold': eval('configuration.scrubbingThreshold'), '_compcor': eval('configuration.Regressors'), '_target_angle_deg': eval('configuration.targetAngleDeg')}


    """
    path_iterables = ['_gm_threshold', '_wm_threshold', '_csf_threshold', '_threshold', '_compcor', '_target_angle_deg']
    non_strategy_iterables = ['_fwhm', '_hp', '_lp', '_bandpass_freqs']

    proper_names = {'_threshold':'Scrubbing Threshold = ', '_csf_threshold':'Cerebral Spinal Fluid Threshold = ',
                    '_gm_threshold':'Gray Matter Threshold = ',
                    'nc':'Compcor: Number Of Components = ', '_compcor':'Nuisance Signal Regressors = ',
                    '_target_angle_deg':'Median Angle Correction: Traget Angle in Degree = ', '_wm_threshold':'White Matter Threshold = '}


    config_iterables = {'_gm_threshold': eval('configuration.grayMatterThreshold'), '_wm_threshold': eval('configuration.whiteMatterThreshold'), '_csf_threshold': eval('configuration.cerebralSpinalFluidThreshold'), '_threshold': eval('configuration.scrubbingThreshold'), '_compcor': eval('configuration.Regressors'), '_target_angle_deg': eval('configuration.targetAngleDeg')}
    """

    ### This is really dirty code and ordering of corrections in 
    ### in output directory is dependant on the nuisance workflow
    ### when the workflow is changed , change this section as well
    corrections_order = ['pc1', 'linear', 'wm', 'global', 'motion', 'quadratic', 'gm', 'compcor', 'csf']


    corrections_dict_list = config_iterables['_compcor']


    print "corrections dictionary list: "
    print corrections_dict_list

    main_all_options = []

    if corrections_dict_list != None:

        for corrections_dict in corrections_dict_list:
            string = ""
            for correction in corrections_order:

                string += correction + str(corrections_dict[correction]) + '.'

            string = string[0:len(string) -1]

            cmpcor_components = eval('configuration.nComponents')

            all_options = []
            for comp in cmpcor_components:

                comp = int(comp)
                all_options.append('ncomponents_%d' %comp + '_selector_' + string)

            main_all_options.append(str(str(all_options).strip('[]')).strip('\'\''))


        config_iterables['_compcor'] = main_all_options


    ############

    try:
        paths = get_vectors(config_iterables)
    except:
        print "\n\n" + "ERROR: There are no strategies to build." + "\n" + \
        "Error name: cpac_runner_0003" + "\n\n"
        raise Exception

    strategy_entries = make_entries(paths, sorted(path_iterables))

    print 'strategy_entries: ', strategy_entries, '\n\n'


    return strategy_entries


# Create and run SGE script
def run_sge_jobs(c, config_file, subject_list_file, strategies_file, p_name):
    '''
    Function to build an Grid engine batch job submission script and
    submit it to the queue via 'qsub'
    '''

    # Import packages
    import commands
    from time import strftime

    # Load in the subject list
    try:
        sublist = yaml.load(open(os.path.realpath(subject_list_file), 'r'))
    except:
        raise Exception ("Subject list is not in proper YAML format. Please check your file")

    # Init batch qsub script
    cluster_files_dir = os.path.join(c.logDirectory, 'cluster_files')
    subject_bash_file = os.path.join(cluster_files_dir, 'cpac_submit_%s.sge' % str(strftime("%Y_%m_%d_%H_%M_%S")))
    f = open(subject_bash_file, 'w')
    # Write config lines to it
    shell = commands.getoutput('echo $SHELL')
    print >>f, '#! %s' % shell
    print >>f, '#$ -N C-PAC Pipeline %s' % c.pipelineName
    print >>f, '#$ -wd %s' % cluster_files_dir
    print >>f, '#$ -S %s' % shell
    print >>f, '#$ -V' # For env vars
    print >>f, '#$ -t 1-%d' % len(sublist)
    print >>f, '#$ -q %s' % c.queue
    print >>f, '#$ -pe %s %d' % (c.parallelEnvironment, c.numCoresPerSubject)
    print >>f, '#$ -e %s' % os.path.join(cluster_files_dir, 'c-pac_%s.err' % str(strftime("%Y_%m_%d_%H_%M_%S")))
    print >>f, '#$ -o %s' % os.path.join(cluster_files_dir, 'c-pac_%s.out' % str(strftime("%Y_%m_%d_%H_%M_%S")))
    print >>f, 'source ~/.bashrc'
    print >>f, 'source /etc/profile.d/cpac_env.sh'

    # Init plugin arguments
    plugin_args = {'num_threads': c.numCoresPerSubject,
                   'memory': c.memoryAllocatedForDegreeCentrality}
    # Print C-PAC execution
    print >>f, 'python -c \"import CPAC; '\
               'CPAC.pipeline.cpac_pipeline.run(\\\"%s\\\", \\\"%s\\\", '\
               '\\\"$SGE_TASK_ID\\\", \\\"%s\\\", \\\"%s\\\", plugin=\\\"%s\\\", '\
               'plugin_args=%s) \" ' % (str(config_file), subject_list_file, \
               strategies_file, p_name, 'ResourceMultiProc', plugin_args)
    # Close file and make executable
    f.close()
    commands.getoutput('chmod +x %s' % subject_bash_file )

    # Open pid file and qsub batch script
    p = open(os.path.join(cluster_files_dir, 'pid.txt'), 'w') 
    out = commands.getoutput('qsub  %s ' % (subject_bash_file))

    # Check for successful qsub submission
    import re
    if re.search("(?<=Your job-array )\d+", out) == None:
        err_msg = 'Error: Running of \'qsub\' command in terminal failed. '\
                  'Please troubleshoot your SGE configuration with your '\
                  'system adminitrator and then try again.'
        raise Exception(err_msg)
    else:
        print "The command run was: qsub %s" % subject_bash_file

    # Get pid and send to pid file
    pid = re.search("(?<=Your job-array )\d+", out).group(0)
    print >> p, pid
    p.close()


# Create and run SGE script
def run_slurm_jobs(c, config_file, strategies_file, subject_list_file, p_name):
    '''
    Function to build a SLURM batch job submission script and
    submit it to the scheduler via 'sbatch'
    '''

    # Import packages
    import commands
    import getpass
    import re
    from time import strftime

    # Load in the subject list
    try:
        sublist = yaml.load(open(os.path.realpath(subject_list_file), 'r'))
    except:
        raise Exception ('Subject list is not in proper YAML format. '\
                         'Please check your file')

    # Init variables
    submit_timestamp = str(strftime("%Y_%m_%d_%H_%M_%S"))
    cluster_files_dir = os.path.join(c.logDirectory, 'cluster_files')
    subject_bash_file = os.path.join(cluster_files_dir, 'cpac_submit_%s.slurm' % submit_timestamp)

    # Batch file variables
    shell = commands.getoutput('echo $SHELL')
    user_account = getpass.getuser()
    num_subs = len(sublist)
    err_log = os.path.join(cluster_files_dir, 'cpac_slurm_task%%a_%s.err' \
                           % submit_timestamp)
    out_log = os.path.join(cluster_files_dir, 'cpac_slurm_task%%a_%s.out' \
                           % submit_timestamp)

    # Write config lines to it
    f = open(subject_bash_file, 'w')
    print >>f, '#! %s' % shell
    print >>f, '#SBATCH --array=0-%d' % (num_subs-1)
    print >>f, '#SBATCH --workdir=%s' % cluster_files_dir
    print >>f, '#SBATCH --cpus-per-task=%d' % c.numCoresPerSubject
    print >>f, '#SBATCH --job-name=C-PAC Pipeline %s' % c.pipelineName
    print >>f, '#SBATCH --uid=%s' % user_account
    print >>f, '#SBATCH --get-user-env'
    print >>f, '#SBATCH --error=%s' % err_log
    print >>f, '#SBATCH --output=%s' % out_log

    # Init plugin arguments
    plugin_args = {'num_threads': c.numCoresPerSubject,
                   'memory': c.memoryAllocatedForDegreeCentrality}
    # Print C-PAC execution
    print >>f, 'python -c \"import CPAC; '\
               'CPAC.pipeline.cpac_pipeline.run(\\\"%s\\\", \\\"%s\\\", '\
               '\\\"$SLURM_ARRAY_TASK_ID\\\", \\\"%s\\\", \\\"%s\\\", plugin=\\\"%s\\\", '\
               'plugin_args=%s) \" ' % (str(config_file), subject_list_file, \
               strategies_file, p_name, 'ResourceMultiProc', plugin_args)
    # Close file and make executable
    f.close()
    commands.getoutput('chmod +x %s' % subject_bash_file )

    # Open pid file and qsub batch script
    p = open(os.path.join(cluster_files_dir, 'pid.txt'), 'w') 
    out = commands.getoutput('sbatch %s' % (subject_bash_file))

    # Check for successful qsub submission
    if re.search('(?<=Submitted batch job )\d+', out) == None:
        err_msg = 'Error: Running of \'sbatch\' command in terminal failed. '\
                  'Please troubleshoot your SLURM configuration with your '\
                  'system adminitrator and then try again.'
        raise Exception(err_msg)
    else:
        print "The command run was: sbatch %s" % subject_bash_file

    # Get pid and send to pid file
    pid = re.search("(?<=Submitted batch job )\d+", out).group(0)
    print >> p, pid
    p.close()


# Run condor jobs
def run_condor_jobs(c, config_file, strategies_file, subject_list_file, p_name):
    '''
    '''

    # Import packages
    import commands
    from time import strftime

    try:
        sublist = yaml.load(open(os.path.realpath(subject_list_file), 'r'))
    except:
        raise Exception ("Subject list is not in proper YAML format. Please check your file")

    cluster_files_dir = os.path.join(os.getcwd(), 'cluster_files')
    subject_bash_file = os.path.join(cluster_files_dir, 'submit_%s.condor' % str(strftime("%Y_%m_%d_%H_%M_%S")))
    f = open(subject_bash_file, 'w')

    print >>f, "Executable = /usr/bin/python"
    print >>f, "Universe = vanilla"
    print >>f, "transfer_executable = False"
    print >>f, "getenv = True"
    print >>f, "log = %s" % os.path.join(cluster_files_dir, 'c-pac_%s.log' % str(strftime("%Y_%m_%d_%H_%M_%S")))

    sublist = yaml.load(open(os.path.realpath(subject_list_file), 'r'))
    for sidx in range(1,len(sublist)+1):
        print >>f, "error = %s" % os.path.join(cluster_files_dir, 'c-pac_%s.%s.err' % (str(strftime("%Y_%m_%d_%H_%M_%S")), str(sidx)))
        print >>f, "output = %s" % os.path.join(cluster_files_dir, 'c-pac_%s.%s.out' % (str(strftime("%Y_%m_%d_%H_%M_%S")), str(sidx)))

        print >>f, "arguments = \"-c 'import CPAC; CPAC.pipeline.cpac_pipeline.run( ''%s'',''%s'',''%s'',''%s'', ''%s'',''%s'',''%s'',''%s'')\'\"" % (str(config_file), subject_list_file, str(sidx), strategies_file, c.maskSpecificationFile, c.roiSpecificationFile, c.templateSpecificationFile, p_name)
        print >>f, "queue"

    f.close()

    #commands.getoutput('chmod +x %s' % subject_bash_file )
    print commands.getoutput("condor_submit %s " % (subject_bash_file))


# Run PBS jobs
def run_pbs_jobs(c, config_file, strategies_file, subject_list_file, p_name):
    '''
    '''

    # Import packages
    import commands
    from time import strftime


    try:
        sublist = yaml.load(open(os.path.realpath(subject_list_file), 'r'))
    except:
        raise Exception ("Subject list is not in proper YAML format. Please check your file")
    
    cluster_files_dir = os.path.join(os.getcwd(), 'cluster_files')
    shell = commands.getoutput('echo $SHELL')
    subject_bash_file = os.path.join(cluster_files_dir, 'submit_%s.pbs' % str(strftime("%Y_%m_%d_%H_%M_%S")))
    f = open(subject_bash_file, 'w')
    print >>f, '#! %s' % shell
    print >>f, '#PBS -S %s' % shell
    print >>f, '#PBS -V'
    print >>f, '#PBS -t 1-%d' % len(sublist)
    print >>f, '#PBS -q %s' % c.queue
    print >>f, '#PBS -l nodes=1:ppn=%d' % c.numCoresPerSubject
    print >>f, '#PBS -e %s' % os.path.join(cluster_files_dir, 'c-pac_%s.err' % str(strftime("%Y_%m_%d_%H_%M_%S")))
    print >>f, '#PBS -o %s' % os.path.join(cluster_files_dir, 'c-pac_%s.out' % str(strftime("%Y_%m_%d_%H_%M_%S")))
    print >>f, 'source ~/.bashrc'

    print >>f, "python -c \"import CPAC; CPAC.pipeline.cpac_pipeline.run(\\\"%s\\\",\\\"%s\\\",\\\"${PBS_ARRAYID}\\\",\\\"%s\\\", \\\"%s\\\" , \\\"%s\\\", \\\"%s\\\", \\\"%s\\\") \" " % (str(config_file), \
        subject_list_file, strategies_file, c.maskSpecificationFile, c.roiSpecificationFile, c.templateSpecificationFile, p_name)
    f.close()

    commands.getoutput('chmod +x %s' % subject_bash_file )


# Create and run script for CPAC to run on cluster
def run_cpac_on_cluster(config_file, subject_list_file, strategies_file,
                        cluster_files_dir):
    '''
    Function to build a SLURM batch job submission script and
    submit it to the scheduler via 'sbatch'
    '''

    # Import packages
    import commands
    import getpass
    import re
    from time import strftime

    from CPAC.utils import Configuration
    from CPAC.pipeline import cluster_templates

    # Load in pipeline config
    try:
        pipeline_dict = yaml.load(open(os.path.realpath(config_file), 'r'))
        pipeline_config = Configuration(pipeline_dict)
    except:
        raise Exception('Pipeline config is not in proper YAML format. '\
                        'Please check your file')
    # Load in the subject list
    try:
        sublist = yaml.load(open(os.path.realpath(subject_list_file), 'r'))
    except:
        raise Exception('Subject list is not in proper YAML format. '\
                        'Please check your file')

    # Init variables
    timestamp = str(strftime("%Y_%m_%d_%H_%M_%S"))
    job_scheduler = pipeline_config.resourceManager.lower()
    subject_bash_file = os.path.join(cluster_files_dir, 'cpac_submit_%s.%s' \
                                     % (timestamp, job_scheduler))
    # Batch file variables
    shell = commands.getoutput('echo $SHELL')
    user_account = getpass.getuser()
    num_subs = len(sublist)

    # Init plugin arguments
    plugin_args = {'num_threads': pipeline_config.numCoresPerSubject,
                   'memory': pipeline_config.memoryAllocatedForDegreeCentrality}

    # Set up config dictionary
    config_dict = {'timestamp' : timestamp,
                   'shell' : shell,
                   'pipeline_name' : pipeline_config.pipelineName,
                   'num_subs' : num_subs,
                   'queue' : pipeline_config.queue,
                   'par_env' : pipeline_config.parallelEnvironment,
                   'cores_per_sub' : pipeline_config.numCoresPerSubject,
                   'user' : user_account,
                   'work_dir' : cluster_files_dir,
                   'plugin_args' : plugin_args}

    # Get string template for job scheduler
    if job_scheduler == 'pbs':
        env_arr_idx = 'PBS_ARRAYID'
        err_fname = ''
        out_fname = ''
        batch_file_contents = cluster_templates.pbs_template
        confirm_str = '(?<=Your job-array )\d+'
        exec_cmd = 'qsub'
    elif job_scheduler == 'sge':
        env_arr_idx = 'SGE_TASK_ID'
        err_fname = 'cpac_sge_$JOB_ID.$TASK_ID.err'
        out_fname = 'cpac_sge_$JOB_ID.$TASK_ID.out'
        batch_file_contents = cluster_templates.sge_template
        confirm_str = '(?<=Your job-array )\d+'
        exec_cmd = 'qsub'
    elif job_scheduler == 'slurm':
        env_arr_idx = 'SLURM_ARRAY_TASK_ID'
        err_fname = 'cpac_slurm_%%j.%%a.err'
        out_fname = 'cpac_slurm_%%j.%%a.out'
        batch_file_contents = cluster_templates.slurm_template
        confirm_str = '(?<=Submitted batch job )\d+'
        exec_cmd = 'sbatch'

    # Populate rest of dictionary
    config_dict['env_arr_idx'] = env_arr_idx
    config_dict['err_log'] = os.path.join(cluster_files_dir, err_fname)
    config_dict['out_log'] = os.path.join(cluster_files_dir, out_fname)

    # Populate string from config dict values
    batch_file_contents = batch_file_contents % config_dict

    # Get output response from job submission
    out = commands.getoutput('%s %s' % (exec_cmd, subject_bash_file))

    # Check for successful qsub submission
    if re.search(confirm_str, out) == None:
        err_msg = 'Error submitting C-PAC pipeline run to %s queue' \
                  % job_scheduler
        raise Exception(err_msg)

    # Get pid and send to pid file
    pid = re.search(confirm_str, out).group(0)
    pid_file = os.path.join(cluster_files_dir, 'pid.txt')
    with open(pid_file, 'w') as f:
        f.write(pid)


def append_seeds_to_file(working_dir, seed_list, seed_file):

    existing_seeds = []
    filtered_list = []

    try:
        if os.path.isfile(seed_file):
            existing_seeds += [line.rstrip('\r\n') for line in open(seed_file, 'r').readlines() if not (line.startswith('#') and line == '\n')]

            for seed in seed_list:
                if not seed in existing_seeds:
                    filtered_list.append(seed)

            if not len(filtered_list) == 0:
                f = open(seed_file, 'a')
                for seed in filtered_list:
                    f.write("%s\n" % seed)
                f.close()

            return seed_file

        else:
            raise

    except:
        #make tempfile and add seeds to it
        import tempfile

        try:
            if not os.path.exists(working_dir):
                os.makedirs(working_dir)

        except Exception, e:

            print 'error encountered : ', e
            raise

        some_number, f_name = tempfile.mkstemp(suffix='.txt', prefix='temp_roi_seeds', dir=working_dir, text=True)

        f_handle = open(f_name, 'w')

        for seed in seed_list:
            f_handle.write('%s\n' % seed)

        f_handle.close()
        return f_name


# Run C-PAC subjects via job queue
def run(config_file, subject_list_file, p_name=None, plugin=None, plugin_args=None):
    '''
    '''

    # Import packages
    import commands
    import os
    import pickle
    import time

    from CPAC.pipeline.cpac_pipeline import prep_workflow

    # Init variables
    config_file = os.path.realpath(config_file)
    subject_list_file = os.path.realpath(subject_list_file)

    # take date+time stamp for run identification purposes
    unique_pipeline_id = strftime("%Y%m%d%H%M%S")
    pipeline_start_stamp = strftime("%Y-%m-%d_%H:%M:%S")

    # Load in pipeline config file
    try:
        if not os.path.exists(config_file):
            raise IOError
        else:
            c = Configuration(yaml.load(open(config_file, 'r')))
    except IOError:
        print "config file %s doesn't exist" % config_file
        raise
    except Exception:
        print "Error reading config file - %s" % config_file
        raise Exception

    # Do some validation
    validate(c)

    # Get the pipeline name
    p_name = c.pipelineName

    # Load in subject list
    try:
        sublist = yaml.load(open(subject_list_file, 'r'))
    except:
        print "Subject list is not in proper YAML format. Please check your file"
        raise Exception

    # NOTE: strategies list is only needed in cpac_pipeline prep_workflow for
    # creating symlinks
    strategies = sorted(build_strategies(c))

    # Print strategies
    print "strategies ---> "
    print strategies
    # Print subject list
    print "subject list: "
    print sublist

    # Populate subject scan map
    sub_scan_map ={}
    try:
        for sub in sublist:
            if sub['unique_id']:
                s = sub['subject_id']+"_" + sub["unique_id"]
            else:
                s = sub['subject_id']
            scan_ids = ['scan_anat']
            for id in sub['rest']:
                scan_ids.append('scan_'+ str(id))
            sub_scan_map[s] = scan_ids
    except:
        print "\n\n" + "ERROR: Subject list file not in proper format - check if you loaded the correct file?" + "\n" + \
              "Error name: cpac_runner_0001" + "\n\n"
        raise Exception

    create_group_log_template(sub_scan_map, c.logDirectory)
 
    '''
    seeds_created = []
    if not (c.seedSpecificationFile is None):

        try:
            if os.path.exists(c.seedSpecificationFile):
                seeds_created = create_seeds_(c.seedOutputLocation, c.seedSpecificationFile, c.FSLDIR)
                print 'seeds created %s -> ' % seeds_created
        except:
            raise IOError('Problem in seedSpecificationFile')


    if 1 in c.runVoxelTimeseries:

        if 'roi_voxelwise' in c.useSeedInAnalysis:

            c.maskSpecificationFile = append_seeds_to_file(c.workingDirectory, seeds_created, c.maskSpecificationFile)

    if 1 in c.runROITimeseries:

        if 'roi_average' in c.useSeedInAnalysis:

            c.roiSpecificationFile = append_seeds_to_file(c.workingDirectory, seeds_created, c.roiSpecificationFile)

    if 1 in c.runSCA:

        if 'roi_average' in c.useSeedInAnalysis:

            c.roiSpecificationFileForSCA = append_seeds_to_file(c.workingDirectory, seeds_created, c.roiSpecificationFileForSCA)

    if 1 in c.runNetworkCentrality:

        if 'centrality_outputs_smoothed' in c.useSeedInAnalysis:

            c.templateSpecificationFile = append_seeds_to_file(c.workingDirectory, seeds_created, c.templateSpecificationFile)
    '''

    pipeline_timing_info = []
    pipeline_timing_info.append(unique_pipeline_id)
    pipeline_timing_info.append(pipeline_start_stamp)
    pipeline_timing_info.append(len(sublist))

    # If we're running on cluster, execute job scheduler
    if c.runOnGrid:
        # Create cluster log dir
        cluster_files_dir = os.path.join(c.logDirectory, 'cluster_files')
        os.makedirs(cluster_files_dir)

        # Create strategies file
        strategies_file = os.path.join(cluster_files_dir, 'strategies.obj')
        with open(strategies_file, 'w') as f:
            pickle.dump(strategies, f)

        # Run on cluster
        run_cpac_on_cluster(config_file, subject_list_file, strategies_file,
                            cluster_files_dir)

        # Run one of the job schedulers over cluster
#         if 'sge' in c.resourceManager.lower():
#             run_sge_jobs(c, config_file, strategies_file, subject_list_file, p_name)
#         elif 'pbs' in c.resourceManager.lower():
#             run_pbs_jobs(c, config_file, strategies_file, subject_list_file, p_name)
#         elif 'condor' in c.resourceManager.lower():
#             run_condor_jobs(c, config_file, strategies_file, subject_list_file, p_name)
#         elif 'slurm' in c.resourceManager.lower():
#             run_slurm_jobs(c, config_file, strategies_file, subject_list_file, p_name)

    # Run on one computer
    else:
        # Init variables
        procss = [Process(target=prep_workflow,
                          args=(sub, c, strategies, 1,
                                pipeline_timing_info, p_name, plugin, plugin_args)) \
                  for sub in sublist]
        pid = open(os.path.join(c.workingDirectory, 'pid.txt'), 'w')
        # Init job queue
        jobQueue = []

        # If we're allocating more processes than are subjects, run them all
        if len(sublist) <= c.numSubjectsAtOnce:
            for p in procss:
                p.start()
                print >>pid,p.pid
        # Otherwise manage resources to run processes incrementally
        else:
            idx = 0
            while(idx < len(sublist)):
                # If the job queue is empty and we haven't started indexing
                if len(jobQueue) == 0 and idx == 0:
                    # Init subject process index
                    idc = idx
                    # Launch processes (one for each subject)
                    for p in procss[idc : idc+c.numSubjectsAtOnce]:
                        p.start()
                        print >>pid, p.pid
                        jobQueue.append(p)
                        idx += 1
                # Otherwise, jobs are running - check them
                else:
                    # Check every job in the queue's status
                    for job in jobQueue:
                        # If the job is not alive
                        if not job.is_alive():
                            # Find job and delete it from queue
                            print 'found dead job ', job
                            loc = jobQueue.index(job)
                            del jobQueue[loc]
                            # ...and start the next available process (subject)
                            procss[idx].start()
                            # Append this to job queue and increment index
                            jobQueue.append(procss[idx])
                            idx += 1
                    # Add sleep so while loop isn't consuming 100% of CPU
                    time.sleep(2)
        # Close PID txt file to indicate finish
        pid.close()
