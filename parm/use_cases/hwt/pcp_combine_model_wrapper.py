#!/usr/bin/env python

'''
Program Name: pcp_combine_model_wrapper.py
Contact(s): George McCabe
Abstract: Runs pcp_combine to merge multiple forecast files
History Log:  Initial version
Usage:
Parameters: None
Input Files: grib2 files
Output Files: pcp_combine files
Condition codes: 0 for success, 1 for failure
'''

from __future__ import (print_function, division)

import produtil.setup
from produtil.run import batchexe, run, checkrun
import logging
import os
import sys
import met_util as util
import re
import csv
import subprocess
import glob
import datetime
import string_template_substitution as sts

from command_builder import CommandBuilder
from pcp_combine_wrapper import PcpCombineWrapper
from task_info import TaskInfo
from gempak_to_cf_wrapper import GempakToCFWrapper


class PcpCombineModelWrapper(PcpCombineWrapper):
    def __init__(self, p, logger):
        super(PcpCombineModelWrapper, self).__init__(p, logger)


    def clear(self):
        super(PcpCombineModelWrapper, self).clear()


    def run_at_time(self, init_time, valid_time):
        task_info = TaskInfo()
        task_info.init_time = init_time
        task_info.valid_time = valid_time        
        var_list = util.parse_var_list(self.p)
        max_forecast = self.p.getint('config', 'FCST_MAX_FORECAST')

        if init_time == -1:
            #Create a list of files to loop over
            gen_seq = util.getlistint(self.p.getstr('config','GEN_SEQ'))
            init_interval = self.p.getint('config','FCST_INIT_INTERVAL')
            valid_hr  = int(valid_time[8:10])
            #Find lead times
            lead_seq = []
            for gs in gen_seq:
                if valid_hr >= gs:
                    current_lead = valid_hr - gs
                elif valid_hr < gs:
                    current_lead = valid_hr + gs
            while current_lead <= max_forecast:
                lead_seq.append(current_lead)
                current_lead = current_lead + 24

            lead_seq = sorted(lead_seq)


        if valid_time == -1:
            lead_seq = util.getlistint(self.p.getstr('config', 'LEAD_SEQ'))
            
        # want to combine fcst data files to get total accum matching obs?
        # obs_level = self.p.getstr('config', 'OBS_LEVEL')
        fcst_level = self.p.getstr('config', 'FCST_LEVEL')
        # TODO: should use getpath or something?
        in_dir = self.p.getstr('config', 'FCST_PCP_COMBINE_INPUT_DIR')
        in_template = self.p.getraw('filename_templates',
                                     'FCST_PCP_COMBINE_INPUT_TEMPLATE')
        out_dir = self.p.getstr('config', 'FCST_PCP_COMBINE_OUTPUT_DIR')
        out_template = self.p.getraw('filename_templates',
                                     'FCST_PCP_COMBINE_OUTPUT_TEMPLATE')
        for lead in lead_seq:
            task_info.lead = lead
            for var_info in var_list:
                out_level = var_info.obs_level
                if out_level[0].isalpha():
                    out_level = out_level[1:]
                if not self.p.has_option('config', 'PCP_COMBINE_METHOD') or \
                  self.p.getstr('config', 'PCP_COMBINE_METHOD') == "ADD":
                    self.run_add_method(task_info.getValidTime(),
                                        task_info.getInitTime(),
                                          out_level,
                                          var_info.obs_name,
                                          "FCST", True)
                elif self.p.getstr('config', 'PCP_COMBINE_METHOD') == "SUM":
                    self.run_sum_method(task_info.getValidTime(),
                                 task_info.getInitTime(),
                                 fcst_level, out_level,
                                 in_dir, out_dir, out_template)
                elif self.p.getstr('config', 'PCP_COMBINE_METHOD') == "SUBTRACT":
                    self.run_subtract_method(task_info, var_info, int(out_level),
                                             in_dir, out_dir, in_template,
                                             out_template)
                else:
                    self.logger.error("Invalid PCP_COMBINE_METHOD specified")
                    exit(1)
