#!/usr/bin/env python

"""
Program Name: tc_pairs_wrapper.py
Contact(s): Julie Prestopnik, Minna Win
Abstract: Invokes the MET tool tc_pairs to parse ADeck and BDeck ATCF files,
          filter the data, and match them up
History Log:  Initial version
Usage:
Parameters: None
Input Files: adeck and bdeck files
Output Files: tc_pairs files
Condition codes: 0 for success, 1 for failure

"""

from __future__ import (print_function, division)

import os
import sys
import re
import csv
import errno
import produtil.setup
from command_builder import CommandBuilder
import met_util as util
import config_metplus

'''!@namespace TcPairs
@brief Wraps the MET tool tc_pairs to parse ADeck and BDeck ATCF files,
filter the data, and match them up.

Call as follows:
@code{.sh}
tc_pairs_wrapper.py [-c /path/to/user.template.conf]
@endcode
'''


class TcPairsWrapper(CommandBuilder):
    """!Wraps the MET tool, tc_pairs to parse and match ATCF adeck and
       bdeck files.  Pre-processes extra tropical cyclone data.
    """

    def __init__(self, config):
        self.logger = util.get_logger(config)
        self.config = config
        super(TcPairsWrapper, self).__init__(config, self.logger)

    def run_at_time(self, requested_time):
        """! Build up the command to invoke the MET tool, tc_pairs.
             Args:
                 @param requested_time:  The time of interest in YYYYMMDD_hh

        """

        # pylint:disable=protected-access
        # sys._getframe is a legitimate way to access the current
        # filename and method.
        # Used for logging information
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name
        self.logger.debug("DEBUGGER|" + cur_filename + "|" + cur_function)

        # Retrieve values set in the configuration file(s).
        input_track_data = self.config.getdir('TRACK_DATA_DIR')
        atcf_output_dir = self.config.getdir('TRACK_DATA_SUBDIR_MOD')
        adeck_file_prefix = self.config.getstr('config',
                                               'ADECK_FILE_PREFIX')
        bdeck_file_prefix = self.config.getstr('config',
                                               'BDECK_FILE_PREFIX')
        track_type = self.config.getstr('config', 'TRACK_TYPE')
        tc_pairs_dir = self.config.getdir('TC_PAIRS_DIR')

        year_month_list = [year_month for year_month in
                           os.listdir(input_track_data)]
        # Check for empty data directories and whether data exists for this
        # requested time.
        self.perform_checks(requested_time, year_month_list)

        # Create a one element list of the requested_time, this will be needed
        # to set the INIT_INC environment variable used by the MET
        # tc_pairs configuration file.
        requested_year_month_list = [requested_time]
        dir_list = self.get_year_month_full_path(year_month_list)
        for mydir in dir_list:
            myfiles = os.listdir(mydir)
            # Need to do extra processing if track_type is extra_tropical
            # cyclone
            if track_type == "extra_tropical_cyclone":
                # Create an atcf output directory for writing the modified
                # files

                adeck_mod = os.path.join(atcf_output_dir,
                                         os.path.basename(mydir))

                produtil.fileop.makedirs(adeck_mod, logger=self.logger)

            # Iterate over the files, modifying them and writing new output
            # files if necessary ("extra_tropical_cyclone" track type), and
            # build up the command to run the MET tool, tc_pairs.
            for myfile in myfiles:
                # Check to see if the files have the ADeck prefix
                if myfile.startswith(adeck_file_prefix):
                    # Create the output directory for the pairs, if
                    # it doesn't already exist
                    pairs_out_dir = \
                        os.path.join(tc_pairs_dir, os.path.basename(mydir))
                    produtil.fileop.makedirs(pairs_out_dir, logger=self.logger)

                    # Need to do extra processing if track_type is
                    # extra_tropical_cyclone
                    if track_type == "extra_tropical_cyclone":
                        adeck_file_path, bdeck_file_path = \
                            self.process_extra_tropical_tracks(
                                adeck_file_prefix, bdeck_file_prefix, mydir,
                                myfile)
                    else:
                        # Set up the adeck and bdeck file paths
                        adeck_file_path = os.path.join(mydir, myfile)
                        bdeck_file_path = re.sub(adeck_file_prefix,
                                                 bdeck_file_prefix,
                                                 adeck_file_path)

                    # Run tc_pairs to build up the command
                    self.build_tc_pairs(pairs_out_dir, myfile,
                                        adeck_file_path, bdeck_file_path,
                                        requested_year_month_list)
                    self.run()

                    # Clean up previous command
                    self.clear_command()

    def perform_checks(self, requested_time, year_month_list):
        """! Performs checks for the absence of input data
             Args:
                 @param requested_time:  The time of interest
                 @param year_month_list: A list of the year_month
                                         subdirectories in the input directory.
        """

        # pylint:disable=protected-access
        # sys._getframe is a legitimate way to access the current
        # filename and method.
        # Used for logging information
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name

        self.logger.debug("DEBUG|" + cur_function + "|" + cur_filename)

        # Check that input directory is not empty.
        if not os.listdir(self.config.getdir('TRACK_DATA_DIR')):
            self.logger.error("ERROR|" + cur_filename + "|" + cur_function +
                              " | " + os.strerror(errno.ENODATA) + "| " +
                              "input data directory is empty or " +
                              "non-existent, exiting.")
            sys.exit(errno.ENODATA)

            # Check that the requested time has a corresponding year_month
            # sub-directory in the input directory.
            match = re.match(r'^\d{6}', requested_time)
            if match:
                requested_year_month = match.group(0)
            else:
                self.logger.error(
                    "ERROR|" + cur_filename + "|" + cur_function +
                    "| " + os.strerror(errno.EINVAL) +
                    "| date-time format for requested time is " +
                    "unrecognized, exiting.")
                sys.exit(errno.EINVAL)

            # Do the actual checking for corresponding year_month dir.
            if requested_year_month not in year_month_list:
                self.logger.error(
                    "ERROR| " + cur_filename + "|" + cur_function +
                    os.strerror(errno.ENODATA) + "| exiting.")
                sys.exit(errno.ENODATA)

    def get_year_month_full_path(self, year_month_list):
        """! Retrieve a list of the full path for each year_month directory
             in the input directory.
             Args:
                   @param year_month_list: A list of the year_months
             Returns:
                   dir_list:  A list of full paths to each year_month
                              sub-directory in the input directory.
        """
        # pylint:disable=protected-access
        # sys._getframe is a legitimate way to access the current
        # filename and method.
        # Used for logging information
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name

        self.logger.debug("DEBUG|" + cur_filename + "|" + cur_function)
        # Get a list of files in the dated subdirectories
        dir_list = []
        for year_month in os.listdir(self.config.getdir('TRACK_DATA_DIR')):
            # if the full directory path isn't an empty directory,
            # check if the current year_month is the requested time.
            if os.path.isdir(os.path.join(self.config.getdir('TRACK_DATA_DIR'),
                                          year_month)) \
                    and year_month in year_month_list:
                dir_list.append(
                    os.path.join(self.config.getdir('TRACK_DATA_DIR'),
                                 year_month))

        if not dir_list:
            self.logger.warning("ERROR | [" + cur_filename + ":" +
                                cur_function + "] | There are no dated"
                                               "sub-directories (YYYYMM) " +
                                "with input data as expected in: " +
                                self.config.getdir('TRACK_DATA_DIR'))
            exit(0)

        return dir_list

    def process_extra_tropical_tracks(self, adeck_file_prefix,
                                      bdeck_file_prefix, mydir, myfile):
        """! Extra tropical cyclone data requires additional processing:
             removing the YYYYMMDD column and concatenating the month with
             the storm id.
             Args:
                 @param adeck_file_prefix: The file prefix for adeck files
                 @param bdeck_file_prefix: The file prefix for bdeck files
                 @param mydir:  The current year_month data directory
                 @param myfile:  The current track file
             Returns:
                 adeck_file_path, bdeck_file_path tuple
        """
        # pylint:disable=protected-access
        # sys._getframe is a legitimate way to access the current
        # filename and method.
        # Used for logging information
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name

        self.logger.debug("DEBUG|" + cur_filename + "|" + cur_function)

        # Retrieve necessary values from the config file.
        atcf_output_dir = self.config.getdir('TRACK_DATA_SUBDIR_MOD')
        adeck_mod = os.path.join(atcf_output_dir,
                                 os.path.basename(mydir))
        bdeck_mod = os.path.join(atcf_output_dir,
                                 os.path.basename(mydir))

        # Form the adeck and bdeck input filename paths
        adeck_in_file_path = os.path.join(mydir, myfile)
        bdeck_in_file_path = re.sub(adeck_file_prefix,
                                    bdeck_file_prefix,
                                    adeck_in_file_path)
        adeck_file_path = os.path.join(adeck_mod, myfile)
        bdeck_file_path = os.path.join(bdeck_mod, re.sub(
            adeck_file_prefix, bdeck_file_prefix, myfile))

        # Get the storm number e.g. 0004 in
        # amlq2012033118.gfso.0004
        # split_basename = myfile.split(".")

        # Get the YYYYMM e.g 201203 in amlq2012033118.gfso.0004
        year_month = myfile[4:10]

        # Get the MM from the YYYYMM
        storm_month = year_month[-2:]

        # Set up the adeck and bdeck track file paths for the
        # extra tropical cyclone data.
        self.setup_extra_tropical_track_dirs(
            adeck_in_file_path, adeck_file_path, storm_month)

        # Read in the bdeck file, modify it,
        # and write a new bdeck file
        # Check for existence of data and overwrite if desired
        self.setup_extra_tropical_track_dirs(
            bdeck_in_file_path,
            bdeck_file_path,
            storm_month)

        return adeck_file_path, bdeck_file_path

    def setup_extra_tropical_track_dirs(self, deck_input_file_path,
                                        deck_file_path, storm_month):
        """! Set up the adeck or bdeck file paths.  If these
             correspond to a tropical storm, then perform additional
             processing via read_modify_write_file to conform to
             ATCF format.

             Args:
                   @param deck_input_file_path: the adeck or bdeck input
                                               filepath
                   @param deck_file_path:  the adeck or bdeck filepath to be
                                          created
                   @param storm_month:  Month of the storm
        """

        # pylint:disable=protected-access
        # sys._getframe is a legitimate way to access the current
        # filename and method.
        # Used for logging information
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name

        self.logger.debug("DEBUG|" + cur_filename + "|" + cur_function)

        # Check to see if the output file exists already.  If it
        # does exist either check a force overwrite option
        # (add) or log a message telling the user to delete the
        # existing data if they want a fresh run
        # Read in the adeck/bdeck file, modify it, and
        # write a new adeck/bdeck file
        # Check for existence of data and overwrite if desired
        if os.path.exists(deck_file_path):
            if self.config.getbool('config', 'TRACK_DATA_MOD_FORCE_OVERWRITE'):
                self.logger.debug("DEBUG | [" + cur_filename +
                                  ":" + cur_function + "] | " +
                                  "Writing modified csv file: " +
                                  deck_file_path +
                                  ", replacing " +
                                  "existing data because " +
                                  "TRACK_DATA_MOD_FORCE_" +
                                  "OVERWRITE is set to True")
                self.read_modify_write_file(deck_input_file_path,
                                            storm_month,
                                            deck_file_path)
            else:
                self.logger.debug("DEBUG | [" + cur_filename +
                                  ":" + cur_function + "] | " +
                                  "Using existing modified csv"
                                  "file: " + deck_file_path +
                                  ", because " +
                                  "track_data_mod_force_" +
                                  "overwrite is set to False")
        else:
            self.logger.debug("DEBUG | [" + cur_filename + ":" +
                              cur_function + "] | " +
                              "Writing modified csv file: " +
                              deck_file_path)
            self.read_modify_write_file(deck_input_file_path,
                                        storm_month,
                                        deck_file_path)

    def build_tc_pairs(self, pairs_output_dir, date_file, adeck_file_path,
                       bdeck_file_path, req_year_month_list):
        """! Build up the command that is used to run the MET tool,
             tc_pairs.
             Args:
                 @param pairs_output_dir: output directory of paired track data
                 @param date_file: the current date file from a list of all
                                   possible date files in the input directory.
                 @param adeck_file_path: the location of the adeck track output
                 @param bdeck_file_path: the location of the bdeck track output
                 @param req_year_month_list:  list of requested time
            Returns:

        """

        # pylint:disable=protected-access
        # sys._getframe is a legitimate way to access the current
        # filename and method.
        # Used for logging information
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name

        pairs_out_file = os.path.join(pairs_output_dir, date_file)
        pairs_out_file_with_suffix = pairs_out_file + ".tcst"

        # Set up the environment variable to be used in the TCPairs Config
        # file (TC_PAIRS_CONFIG_PATH)
        # Used to set init_inc in "TC_PAIRS_CONFIG_PATH"
        # Need to do some pre-processing so that Python will use " and not '
        # because currently MET
        # doesn't support single-quotes
        tmp_init_string = str(req_year_month_list)
        tmp_init_string = tmp_init_string.replace("\'", "\"")
        os.environ['INIT_INC'] = tmp_init_string

        self.add_env_var('INIT_INC', tmp_init_string)
        self.app_path = self.config.getexe('TC_PAIRS')
        self.app_name = os.path.basename(self.app_path)
        self.add_arg(" -adeck ")
        self.add_arg(adeck_file_path)
        self.add_arg(" -bdeck ")
        self.add_arg(bdeck_file_path)
        self.add_arg(" -config ")
        self.add_arg(self.config.getstr('config', 'TC_PAIRS_CONFIG_PATH'))
        self.add_arg(" -out ")
        self.add_arg(pairs_out_file_with_suffix)
        # This info is necessary in order to create a command, even
        # though you've defined this information in the -out args above
        self.set_output_filename(date_file)
        self.set_output_dir(pairs_output_dir)
        cmd = self.get_command()
        self.logger.debug("cmd = " + str(cmd))

        # Log appropriate message, based on whether we did a force overwrite
        # on existing data.
        if os.path.exists(pairs_out_file_with_suffix):
            if self.config.getbool('config', 'TC_PAIRS_FORCE_OVERWRITE'):
                self.logger.debug("DEBUG | [" + cur_filename +
                                  ":" + cur_function + "] | " +
                                  "Writing tc_pairs output file: " +
                                  pairs_out_file + ", replacing" +
                                  " existing " +
                                  " data because TC_PAIRS_FORCE" +
                                  "_OVERWRITE is set to True")
        else:
            self.logger.debug("DEBUG | [" + cur_filename + ":" +
                              cur_function + "] | " +
                              "Running tc_pairs with command: " +
                              cmd)

    def read_modify_write_file(self, in_csvfile, storm_month, out_csvfile):
        """! Reads, modifies and writes file
              Args:
                @param in_csvfile input csv file that is being parsed
                @param storm_month The storm month
                @param out_csvfile the output csv file
        """

        self.logger.debug("DEBUG|run_tc_pairs.py|read_modify_write_file")

        # pylint:disable=protected-access
        # sys._getframe is a legitimate way to access the current
        # filename and method.
        # Used for logging
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name
        self.logger.debug("DEBUG|" + cur_filename + "|" + cur_function)

        # Open the output csv file
        out_file = open(out_csvfile, "wb")

        # These are the missing values used in the data file to indicate
        # missing values.  Commonly, -9999 is used.
        missing_values = \
            (self.config.getstr('config', 'MISSING_VAL_TO_REPLACE'),
             self.config.getstr('config', 'MISSING_VAL'))

        # Tell the write to use the line separator
        # "\n" instead of the DOS "\r\n"
        writer = csv.writer(out_file, lineterminator="\n")

        with open(in_csvfile) as csvfile:

            in_file_reader = csv.reader(csvfile)
            # pylint:disable=unused-variable
            # enumerate returns a tuple but only the row is useful
            # for this application.  Ignoring 'index' is reasonable.
            for index, row in enumerate(in_file_reader):
                # Create a list for the modified lines
                row_list = []

                # Replace the second column (storm number) with
                # the month followed by the storm number
                # e.g. Replace 0006 with 010006
                row[1] = " " + storm_month + (row[1]).strip()

                # Iterate over the items, deleting or modifying the columns
                for item in row:
                    # Delete the third column
                    if item == row[2]:
                        continue
                    # Replace MISSING_VAL_TO_REPLACE=missing_values[0] with
                    # MISSING_VAL=missing_values[1]
                    elif item.strip() == missing_values[0]:
                        item = " " + missing_values[1]
                    # Create a new row to write
                    row_list.append(item)

                # Write the modified file
                writer.writerow(row_list)

        csvfile.close()
        out_file.close()
        self.logger.debug("DEBUG|" + cur_function + "|" + cur_filename +
                          " finished")


if __name__ == "__main__":
    try:
        if 'JLOGFILE' in os.environ:
            produtil.setup.setup(send_dbn=False,
                                 jobname='run_tc_pairs',
                                 jlogfile=os.environ['JLOGFILE'])
        else:
            produtil.setup.setup(send_dbn=False, jobname='run_tc_pairs')
        produtil.log.postmsg('run_tc_pairs is starting')

        CONFIG_INST = config_metplus.setup()
        if 'MET_BASE' not in os.environ:
            os.environ['MET_BASE'] = CONFIG_INST.getdir('MET_BASE')
        INIT_LIST = util.gen_init_list(
            CONFIG_INST.getstr('config', 'INIT_DATE_BEG'),
            CONFIG_INST.getstr('config', 'INIT_DATE_END'),
            CONFIG_INST.getint('config', 'INIT_HOUR_INC'),
            CONFIG_INST.getstr('config', 'INIT_HOUR_END'))
        TCP = TcPairsWrapper(CONFIG_INST)
        REQUEST_TIME = INIT_LIST[0]
        TCP.run_at_time(REQUEST_TIME)
        produtil.log.postmsg('run_tc_pairs completed')
    except Exception as exc:
        produtil.log.jlogger.critical(
            'run_tc_pairs failed: %s' % (str(exc),), exc_info=True)
        sys.exit(2)
