import nipype.pipeline.engine as pe
import nipype.interfaces.utility as util
import nipype.interfaces.io as nio

import re
import os
import sys
import glob

from CPAC.utils.datasource import create_gpa_dataflow


def prep_group_analysis_workflow(c, resource, subject_infos):
    print 'Preparing Group Analysis workflow for resource', resource
    print 'subjects', subject_infos
    
    p_id, s_ids, scan_ids, s_paths = (list(tup) for tup in zip(*subject_infos))
    
    if c.mixedScanAnalysis == True:
        wf = pe.Workflow(name = 'group_analysis/%s'%resource)
    else:
        wf = pe.Workflow(name = 'group_analysis/%s/%s'%(resource,scan_ids[0])) 
    
    wf.base_dir = c.workingDirectory
    
    #extract model files
    model_list = [line.rstrip('\r\n') for line in open(c.modelFile, 'r')]
    
    if not model_list:
        raise Exception("mode_list is empty. Please provide" \
                         "a model file with full paths of the" \
                         "folder containing models for group analysis")
    
    from collections import defaultdict
    model_map = defaultdict(list)
    
    #create a map of model as key and its sub files as values
    import os 
    import glob
    for model in model_list:
        if os.path.exists(model):
            files = glob.glob(os.path.join(model, '*'))
            model_map[os.path.basename(model)] = files
        else:
            raise Exception ("Path to the model %s doesn't exist"%model)
    
    #print model_map
    
    input_subject_list = [line.rstrip('\r\n') for line in open(c.groupAnalysisSubjectList, 'r')]
    
    strgy_path = os.path.dirname(s_paths[0]).split(scan_ids[0])[1]
    for ch in ['/','.']:
        if ch in strgy_path:
            strgy_path = strgy_path.replace(ch, '_')
    
    gp_flow = create_gpa_dataflow(model_map, c.fTest, "gp_dataflow%s"%strgy_path)
    gp_flow.inputs.inputspec.input_sublist = input_subject_list 
    gp_flow.inputs.inputspec.output_sublist = s_ids
    
    from CPAC.group_analysis import create_group_analysis
    
    gpa_wf = create_group_analysis(c.fTest, "gp_analysis%s"%strgy_path)
    gpa_wf.inputs.inputspec.zmap_files = s_paths
    
    wf.connect(gp_flow, 'outputspec.mat',
               gpa_wf, 'inputspec.mat_file')
    wf.connect(gp_flow, 'outputspec.con',
               gpa_wf, 'inputspec.con_file')
    wf.connect(gp_flow, 'outputspec.grp',
                gpa_wf, 'inputspec.grp_file')
        
    if c.fTest:
        wf.connect(gp_flow, 'outputspec.fts',
                   gpa_wf, 'inputspec.fts_file') 
    
    ds = pe.Node(nio.DataSink(), name='gpa_sink')
    out_dir = os.path.dirname(s_paths[0]).replace(s_ids[0], 'group_analysis_results')
    ds.inputs.base_directory = out_dir
    ds.inputs.container = resource
    
    ########datasink connections#########
    
    wf.connect(gp_flow, 'outputspec.mat',
               ds, 'model')
    wf.connect(gp_flow, 'outputspec.con',
               ds, 'model.@01')
    wf.connect(gp_flow, 'outputspec.grp',
               ds, 'model.@02')
    wf.connect(gp_flow, 'outputspec.sublist',
               ds, 'model.@03')
    wf.connect(gpa_wf, 'outputspec.merged',
               ds, 'merged')
    wf.connect(gpa_wf, 'outputspec.zstats',
               ds, 'stats.unthreshold')
    wf.connect(gpa_wf, 'outputspec.zfstats',
               ds,'stats.unthreshold.@01')
    wf.connect(gpa_wf, 'outputspec.fstats',
               ds,'stats.unthreshold.@02')
    wf.connect(gpa_wf, 'outputspec.cluster_threshold_zf',
               ds, 'stats.threshold')
    wf.connect(gpa_wf, 'outputspec.cluster_index_zf',
               ds,'stats.clusterMap')
    wf.connect(gpa_wf, 'outputspec.cluster_localmax_txt_zf',
               ds, 'stats.clusterMap.@01')
    wf.connect(gpa_wf, 'outputspec.overlay_threshold_zf',
               ds, 'rendered')
    wf.connect(gpa_wf, 'outputspec.rendered_image_zf',
               ds, 'rendered.@01')   
    wf.connect(gpa_wf, 'outputspec.cluster_threshold',
               ds,  'stats.threshold.@01')
    wf.connect(gpa_wf, 'outputspec.cluster_index',
               ds, 'stats.clusgpa_wfterMap.@02')
    wf.connect(gpa_wf, 'outputspec.cluster_localmax_txt',
               ds, 'stats.clusterMap.@03')
    wf.connect(gpa_wf, 'outputspec.overlay_threshold',
               ds, 'rendered.@02')
    wf.connect(gpa_wf, 'outputspec.rendered_image',
               ds, 'rendered.@03')
    
    ######################################
    
    wf.run(plugin='MultiProc',
                         plugin_args={'n_procs': c.numCoresPerSubject})

    



def run(config, subject_infos, resource):
    import re
    import commands
    commands.getoutput('source ~/.bashrc')
    import os
    import sys
    import pickle

    path, fname = os.path.split(os.path.realpath(config))
    sys.path.append(path)
    c = __import__(fname.split('.')[0])


    prep_group_analysis_workflow(c, pickle.load(open(resource, 'r') ), pickle.load(open(subject_infos, 'r')))
