# CPAC/pipeline/workflow_bundler.py
#

'''
Module containing the prototype workflow bundler for a C-PAC pipeline
'''

# Import packages
from multiprocessing import Process, Pool, cpu_count, pool
from traceback import format_exception
import os
import sys

import numpy as np
from copy import deepcopy
from nipype.pipeline.engine import MapNode
from nipype.utils.misc import str2bool
from nipype import logging
from nipype.pipeline.plugins import semaphore_singleton
from nipype.pipeline.plugins.base import (DistributedPluginBase, report_crash)
from nipype.pipeline.plugins.multiproc \
    import get_system_total_memory_gb, NonDaemonPool, run_node, release_lock


# Init logger
logger = logging.getLogger('workflow')


def create_cpac_arg_list(sublist_filepath, config_filepath,
                         plugin='MultiProc', plugin_args=None):
    '''
    Function to create a list of arguments to feed to the 
    '''

    # Import packages
    import yaml
    from multiprocessing import cpu_count
    from nipype.pipeline.plugins.multiproc import get_system_total_memory_gb
    from CPAC.pipeline.cpac_runner import build_strategies

    # Init variables
    arg_list = []
    sublist = yaml.load(open(sublist_filepath, 'r'))
    pipeline_config = yaml.load(open(config_filepath, 'r'))
    strategies = build_strategies(pipeline_config)

    # Plugin args
    if plugin_args is None:
        plugin_args = {'n_procs' : cpu_count(),
                       'memory_gb' : get_system_total_memory_gb()}

    # Create args list
    for sub_dict in sublist:
        


class BundlerMetaPlugin(DistributedPluginBase):
    """Execute workflow with multiprocessing, not sending more jobs at once
    than the system can support.

    The plugin_args input to run can be used to control the multiprocessing
    execution and defining the maximum amount of memory and threads that 
    should be used. When those parameters are not specified,
    the number of threads and memory of the system is used.

    System consuming nodes should be tagged:
    memory_consuming_node.interface.estimated_memory_gb = 8
    thread_consuming_node.interface.num_threads = 16

    The default number of threads and memory for a node is 1. 

    Currently supported options are:

    - non_daemon : boolean flag to execute as non-daemon processes
    - n_procs: maximum number of threads to be executed in parallel
    - memory_gb: maximum memory (in GB) that can be used at once.

    """

    def __init__(self, plugin_args=None):
        # Init variables and instance attributes
        super(BundlerMetaPlugin, self).__init__(plugin_args=plugin_args)
        self._taskresult = {}
        self._taskid = 0
        non_daemon = True
        self.plugin_args = plugin_args
        self.processors = cpu_count()
        self.memory_gb = get_system_total_memory_gb()*0.9 # 90% of system memory

        # Check plugin args
        if not self.plugin_args or not (plugin_args.has_key('function_handle') \
                                        and plugin_args.has_key('args_list')):
            err_msg = 'The "function_handle" and "args_list" keys in the '\
                      'plugin_args must be provided for bundler to execute!'
            raise Exception(err_msg)

        # Get plugin arguments
        function_handle = plugin_args['function_handle']
        args_list = plugin_args['args_list']
        if 'non_daemon' in self.plugin_args:
            non_daemon = plugin_args['non_daemon']
        if 'n_procs' in self.plugin_args:
            self.processors = self.plugin_args['n_procs']
        if 'memory_gb' in self.plugin_args:
            self.memory_gb = self.plugin_args['memory_gb']

        # Instantiate different thread pools for non-daemon processes
        if non_daemon:
            # run the execution using the non-daemon pool subclass
            self.pool = NonDaemonPool(processes=self.processors)
        else:
            self.pool = Pool(processes=self.processors)

        # Build list of workflows
        wflow_list = []
        for args, kwargs in args_list:
            wflow = function_handle(*args, **kwargs)
            wflow_list.append(wflow)



    def _wait(self):
        if len(self.pending_tasks) > 0:
            semaphore_singleton.semaphore.acquire()
        semaphore_singleton.semaphore.release()

    def _get_result(self, taskid):
        if taskid not in self._taskresult:
            raise RuntimeError('Multiproc task %d not found' % taskid)
        if not self._taskresult[taskid].ready():
            return None
        return self._taskresult[taskid].get()

    def _report_crash(self, node, result=None):
        if result and result['traceback']:
            node._result = result['result']
            node._traceback = result['traceback']
            return report_crash(node,
                                traceback=result['traceback'])
        else:
            return report_crash(node)

    def _clear_task(self, taskid):
        del self._taskresult[taskid]

    def _submit_job(self, node, updatehash=False):
        self._taskid += 1
        if hasattr(node.inputs, 'terminal_output'):
            if node.inputs.terminal_output == 'stream':
                node.inputs.terminal_output = 'allatonce'

        self._taskresult[self._taskid] = \
            self.pool.apply_async(run_node,
                                  (node, updatehash),
                                  callback=release_lock)
        return self._taskid

    def _send_procs_to_workers(self, updatehash=False, graph=None):
        """ Sends jobs to workers when system resources are available.
            Check memory (gb) and cores usage before running jobs.
        """
        executing_now = []

        # Check to see if a job is available
        jobids = np.flatnonzero((self.proc_pending == True) & \
                                (self.depidx.sum(axis=0) == 0).__array__())

        # Check available system resources by summing all threads and memory used
        busy_memory_gb = 0
        busy_processors = 0
        for jobid in jobids:
            busy_memory_gb += self.procs[jobid]._interface.estimated_memory_gb
            busy_processors += self.procs[jobid]._interface.num_threads

        free_memory_gb = self.memory_gb - busy_memory_gb
        free_processors = self.processors - busy_processors

        # Check all jobs without dependency not run
        jobids = np.flatnonzero((self.proc_done == False) & \
                                (self.depidx.sum(axis=0) == 0).__array__())

        # Sort jobs ready to run first by memory and then by number of threads
        # The most resource consuming jobs run first
        jobids = sorted(jobids,
                        key=lambda item: (self.procs[item]._interface.estimated_memory_gb,
                                          self.procs[item]._interface.num_threads))

        logger.debug('Free memory (GB): %d, Free processors: %d',
                     free_memory_gb, free_processors)

        # While have enough memory and processors for first job
        # Submit first job on the list
        for jobid in jobids:
            logger.debug('Next Job: %d, memory (GB): %d, threads: %d' \
                         % (jobid, self.procs[jobid]._interface.estimated_memory_gb,
                            self.procs[jobid]._interface.num_threads))

            if self.procs[jobid]._interface.estimated_memory_gb <= free_memory_gb and \
               self.procs[jobid]._interface.num_threads <= free_processors:
                logger.info('Executing: %s ID: %d' %(self.procs[jobid]._id, jobid))
                executing_now.append(self.procs[jobid])

                if isinstance(self.procs[jobid], MapNode):
                    try:
                        num_subnodes = self.procs[jobid].num_subnodes()
                    except Exception:
                        etype, eval, etr = sys.exc_info()
                        traceback = format_exception(etype, eval, etr)
                        report_crash(self.procs[jobid], traceback=traceback)
                        self._clean_queue(jobid, graph)
                        self.proc_pending[jobid] = False
                        continue
                    if num_subnodes > 1:
                        submit = self._submit_mapnode(jobid)
                        if not submit:
                            continue

                # change job status in appropriate queues
                self.proc_done[jobid] = True
                self.proc_pending[jobid] = True

                free_memory_gb -= self.procs[jobid]._interface.estimated_memory_gb
                free_processors -= self.procs[jobid]._interface.num_threads

                # Send job to task manager and add to pending tasks
                if self._status_callback:
                    self._status_callback(self.procs[jobid], 'start')
                if str2bool(self.procs[jobid].config['execution']['local_hash_check']):
                    logger.debug('checking hash locally')
                    try:
                        hash_exists, _, _, _ = self.procs[
                            jobid].hash_exists()
                        logger.debug('Hash exists %s' % str(hash_exists))
                        if (hash_exists and (self.procs[jobid].overwrite == False or \
                                             (self.procs[jobid].overwrite == None and \
                                              not self.procs[jobid]._interface.always_run))):
                            self._task_finished_cb(jobid)
                            self._remove_node_dirs()
                            continue
                    except Exception:
                        etype, eval, etr = sys.exc_info()
                        traceback = format_exception(etype, eval, etr)
                        report_crash(self.procs[jobid], traceback=traceback)
                        self._clean_queue(jobid, graph)
                        self.proc_pending[jobid] = False
                        continue
                logger.debug('Finished checking hash')

                if self.procs[jobid].run_without_submitting:
                    logger.debug('Running node %s on master thread' \
                                 % self.procs[jobid])
                    try:
                        self.procs[jobid].run()
                    except Exception:
                        etype, eval, etr = sys.exc_info()
                        traceback = format_exception(etype, eval, etr)
                        report_crash(self.procs[jobid], traceback=traceback)
                    self._task_finished_cb(jobid)
                    self._remove_node_dirs()

                else:
                    logger.debug('submitting %s' % str(jobid))
                    tid = self._submit_job(deepcopy(self.procs[jobid]),
                                           updatehash=updatehash)
                    if tid is None:
                        self.proc_done[jobid] = False
                        self.proc_pending[jobid] = False
                    else:
                        self.pending_tasks.insert(0, (tid, jobid))
            else:
                break

        logger.debug('No jobs waiting to execute')