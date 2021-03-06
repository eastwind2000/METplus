#!/usr/bin/env python
from __future__ import print_function

import logging
import os
import shutil
import sys
import datetime
import errno
import time
import calendar
import re
from collections import namedtuple

import subprocess
from produtil.run import exe
from produtil.run import runstr,alias
from string_template_substitution import StringSub
from string_template_substitution import StringExtract
# TODO Remove the classes and refactor met-util
# met_util needs to be refactored and the functions that
# instantiate the objects(CommandBuilder) refactored in to there
# own respective class OR in there own module, patterned after their
# intended function.
from tc_stat_wrapper import TcStatWrapper
from regrid_data_plane_wrapper import RegridDataPlaneWrapper

"""!@namespace met_util
 @brief Provides  Utility functions for METplus.
"""


def round_0p5(val):
    """! Round to the nearest point five (ie 3.3 rounds to 3.5, 3.1
       rounds to 3.0) Take the input value, multiply by two, round to integer
       (no decimal places) then divide by two.  Expect any input value of n.0,
       n.1, or n.2 to round down to n.0, and any input value of n.5, n.6 or
       n.7 to round to n.5. Finally, any input value of n.8 or n.9 will
       round to (n+1).0
       Args:
          @param val :  The number to be rounded to the nearest .5
       Returns:
          pt_five:  The n.0, n.5, or (n+1).0 value as
                            a result of rounding the input value, val.
    """

    val2 = val * 2
    rval = round_to_int(val2)
    pt_five = round(rval, 0) / 2
    return pt_five


def round_to_int(val):
    """! Round to integer value
         Args:
             @param val:  The value to round up
         Returns:
            rval:  The rounded up value.
    """
    val += 0.5
    rval = int(val)
    return rval


def mkdir_p(path):
    """!
       From stackoverflow.com/questions/600268/mkdir-p-functionality-in-python
       Creates the entire directory path if it doesn't exist (including any
       required intermediate directories).
       Args:
           @param path : The full directory path to be created
       Returns
           None: Creates the full directory path if it doesn't exist,
                 does nothing otherwise.
    """

    try:
        # ***Note***:
        # For Python 3.2 and beyond, os.makedirs has a third optional argument,
        # exist_ok, that when set to True will enable the mkdir -p
        # functionality.
        # The mkdir -p functionality holds unless the mode is provided and the
        # existing directory has different permissions from the intended ones.
        # In this situation the OSError exception is raised.

        # default mode is octal 0777
        os.makedirs(path, mode=0775)
    except OSError as exc:
        # Ignore the error that gets created if the path already exists
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def _rmtree_onerr(function, path, exc_info, logger=None):
    """!Internal function used to log errors.
    This is an internal implementation function called by
    shutil.rmtree when an underlying function call failed.  See
    the Python documentation of shutil.rmtree for details.
    @param function the funciton that failed
    @param path the path to the function that caused problems
    @param exc_info the exception information
    @protected"""
    if logger:
        logger.warning('%s: %s failed: %s' % (
            str(path), str(function), str(exc_info)))


def rmtree(tree, logger=None):
    """!Deletes the tree, if possible.
       @protected
       @param tree the directory tree to delete"
       @param logger the logger, optional
    """
    try:
        # If it is a file, special file or symlink we can just
        # delete it via unlink:
        os.unlink(tree)
        return
    except EnvironmentError:
        pass
    # We get here for directories.
    if logger:
        logger.info('%s: rmtree' % (tree,))
    shutil.rmtree(tree, ignore_errors=False)


def set_logvars(config, logger=None):
    """!Sets and adds the LOG_METPLUS and LOG_TIMESTAMP
       to the config object. If LOG_METPLUS was already defined by the
       user in their conf file. It expands and rewrites it in the conf
       object and the final file.
       conf file.
       Args:
           @param config:   the config instance
           @param logger: the logger, optional

    """

    if logger is None:
        logger = config.log()

    # LOG_TIMESTAMP_TEMPLATE is not required in the conf file,
    # so lets first test for that.
    log_timestamp_template = config.getstr('config','LOG_TIMESTAMP_TEMPLATE','')
    if log_timestamp_template:
        # Note: strftime appears to handle if log_timestamp_template
        # is a string ie. 'blah' and not a valid set of % directives %Y%m%d,
        # it does return the string 'blah', instead of crashing.
        # However, I'm still going to test for a valid % directive and
        # set a default. It probably is ok to remove the if not block pattern
        # test, and not set a default, especially if causing some unintended
        # consequences or the pattern is not capturing a valid directive.
        # The reality is, the user is expected to have entered a correct
        # directive in the conf file.
        # This pattern is meant to test for a repeating set of
        # case insensitive %(AnyAlphabeticCharacter), ie. %Y%m ...
        # The basic pattern is (%+[a-z])+ , %+ allows for 1 or more
        # % characters, ie. %%Y, %% is a valid directive.
        # (?i) case insensitive, \A begin string \Z end of string
        if not re.match('(?i)\A(?:(%+[a-z])+)\Z', log_timestamp_template):
            logger.warning('Your LOG_TIMESTAMP_TEMPLATE is not '
                           'a valid strftime directive: %s' % repr(log_timestamp_template))
            logger.info('Using the following default: %Y%m%d%H')
            log_timestamp_template = '%Y%m%d%H'
        log_filenametimestamp = datetime.datetime.now().strftime(log_timestamp_template)
    else:
        log_filenametimestamp=''

    log_dir = config.getdir('LOG_DIR')

    # NOTE: LOG_METPLUS or metpluslog is meant to include the absolute path
    #       and the metpluslog_filename,
    # so metpluslog = /path/to/metpluslog_filename

    # if LOG_METPLUS =  unset in the conf file, means NO logging.
    # Also, assUmes the user has included the intended path in LOG_METPLUS.
    user_defined_log_file = None
    if config.has_option('config','LOG_METPLUS'):
        user_defined_log_file = True
        # strinterp will set metpluslog to '' if LOG_METPLUS =  is unset.
        metpluslog = config.strinterp('config','{LOG_METPLUS}', \
                                    LOG_TIMESTAMP_TEMPLATE=log_filenametimestamp)

        # test if there is any path information, if there is, assUme it is as intended,
        # if there is not, than add log_dir.
        if metpluslog:
            if os.path.basename(metpluslog) == metpluslog:
                metpluslog = os.path.join(log_dir, metpluslog)
    else:
        # No LOG_METPLUS in conf file, so let the code try to set it,
        # if the user defined the variable LOG_FILENAME_TEMPLATE.
        # LOG_FILENAME_TEMPLATE is an 'unpublished' variable - no one knows
        # about it unless you are reading this. Why does this exist ?
        # It was from my first cycle implementation. I did not want to pull
        # it out, in case the group wanted a stand alone metplus log filename
        # template variable.

        # If metpluslog_filename includes a path, python joins it intelligently.
        # Set the metplus log filename.
        # strinterp will set metpluslog_filename to '' if LOG_FILENAME_TEMPLATE =
        if config.has_option('config', 'LOG_FILENAME_TEMPLATE'):
            metpluslog_filename = config.strinterp('config', '{LOG_FILENAME_TEMPLATE}',
                                                   LOG_TIMESTAMP_TEMPLATE=log_filenametimestamp)
        else:
            metpluslog_filename = ''
        if metpluslog_filename:
            metpluslog = os.path.join(log_dir, metpluslog_filename)
        else:
            metpluslog = ''



    # Adding LOG_TIMESTAMP to the final configuration file.
    logger.info('Adding: config.LOG_TIMESTAMP=%s' % repr(log_filenametimestamp))
    config.set('config','LOG_TIMESTAMP',log_filenametimestamp)

    # Setting LOG_METPLUS in the configuration object
    # At this point LOG_METPLUS will have a value or '' the empty string.
    if user_defined_log_file:
        logger.info('Replace [config] LOG_METPLUS with %s' % repr(metpluslog))
    else:
        logger.info('Adding: config.LOG_METPLUS=%s' % repr(metpluslog))
    # expand LOG_METPLUS to ensure it is available
    config.set('config', 'LOG_METPLUS', metpluslog)


def get_logger(config, sublog=None):
    """!This function will return a logger with a formatted file handler
    for writing to the LOG_METPLUS and it sets the LOG_LEVEL. If LOG_METPLUS is
    not defined, a logger is still returned without adding a file handler,
    but still setting the LOG_LEVEL.

       Args:
           @param config:   the config instance
           @param sublog the logging subdomain, or None
       Returns:
           logger: the logger
    """

    # Retrieve all logging related parameters from the param file
    log_dir = config.getdir('LOG_DIR')
    log_level = config.getstr('config', 'LOG_LEVEL')

    # TODO review, use builtin produtil.fileop vs. mkdir_p ?
    # import produtil.fileop
    # produtil.fileop.makedirs(log_dir,logger=None)

    # Check if the directory path for the log file exists, if
    # not create it.
    if not os.path.exists(log_dir):
        mkdir_p(log_dir)

    if sublog is not None:
        logger = config.log(sublog)
    else:
        logger = config.log()

    # Set the logger level from the config instance.
    logger.setLevel(log_level)

    # Make sure the LOG_METPLUS is defined. In this function,
    # LOG_METPLUS should already be defined in the config object,
    # even if it is empty, LOG_METPLUS =.
    if not config.has_option('config','LOG_METPLUS'):
        set_logvars(config)
    metpluslog = config.getstr('config', 'LOG_METPLUS', '')


    # TODO: Remove LOG_OUTPUT control variable.
    # This was the yes/no control variable from the first cycle logging
    # implementation to turn logging on or off. Instead LOG_METPLUS
    # is being used as the on/off switch, this is not being used.
    # I'm keeping it here until after the group review, in case it comes up
    # that folks want to define such a variable in the conf file.
    # If not used, Delete this comment and commented out code block below
    # and you are done, nothing else needs to be changed elsewhere
    # in the code base.
    #if config.getbool('config','LOG_OUTPUT',default=False,badtypeok=True):
    #    if not metpluslog:
    #        logger.warning('LOG_OUTPUT in conf file is yes, Looks like you want to log your output ?')
    #        logger.warning('However, LOG_METPLUS is not a valid file, I can not log your output.')
    #    else:
    #        logger.info('LOG_OUTPUT in your conf file is set to yes')
    #else:
    #    logger.info('LOG_OUTPUT in your conf file is set to no or not set.')
    #if metpluslog and config.getbool('config', 'LOG_OUTPUT', default=False, badtypeok=True):

    if metpluslog:
        # It is possible that more path, other than just LOG_DIR, was added
        # to the metpluslog, by either a user defining more path in
        # LOG_METPLUS or LOG_FILENAME_TEMPLATE definitions in their conf file.
        # So lets check and make more directory if needed.
        dirname = os.path.dirname(metpluslog)
        if not os.path.exists(dirname):
            mkdir_p(dirname)

        # set up the filehandler and the formatter, etc.
        # This matches the oformat log.py formatter of produtil
        # So terminal output will now match log files.
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03d %(name)s (%(filename)s:%(lineno)d) "
            "%(levelname)s: %(message)s",
            "%m/%d %H:%M:%S")
        #logging.Formatter.converter = time.gmtime
        file_handler = logging.FileHandler(metpluslog, mode='a')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

def file_exists(filename):
    """! Determines if a file exists
        NOTE:  Simply using os.path.isfile() is not a Pythonic way
               to check if a file exists.  You can
               still encounter a TOCTTOU bug
               "time of check to time of use"
               Instead, use the raising of
               exceptions, which is a Pythonic
               approach:
               try:
                   with open(filename) as fileobj:
                      pass # or do something fruitful
               except IOError as e:
                   logger.error("your helpful error message goes here")
        Args:
            @param filename:  the full filename (full path)
        Returns:
            boolean : True if file exists, False otherwise
    """

    try:
        return os.path.isfile(filename)
    except IOError:
        pass


def is_dir_empty(directory):
    """! Determines if a directory exists and is not empty
        Args:
           @param directory:  The directory to check for existence
                                       and for contents.
        Returns:
           True:  If the directory is empty
           False:  If the directory exists and isn't empty
    """
    if not os.listdir(directory):
        return True
    else:
        return False


def grep(pattern, infile):
    """! Python version of grep, searches the file line-by-line
        to find a match to the pattern. Returns upon finding the
        first match.
        Args:
            @param pattern:  The pattern to be matched
            @param infile:     The filename with full filepath in which to
                             search for the pattern
        Returns:
            line (string):  The matching string
    """

    matching_lines = []
    with open(infile, 'r') as file_handle:
        for line in file_handle:
            match = re.search(pattern, line)
            if match:
                matching_lines.append(line)
                # if you got here, you didn't find anything
    return matching_lines


def get_filepaths_for_grbfiles(base_dir):
    """! Generates the grb2 file names in a directory tree
       by walking the tree either top-down or bottom-up.
       For each directory in the tree rooted at
       the directory top (including top itself), it
       produces a tuple: (dirpath, dirnames, filenames).
       This solution was found on Stack Overflow:
       http://stackoverflow.com/questions/3207219/how-to-list-all-files-of-a-
           directory-in-python#3207973
       **scroll down to the section with "Getting Full File Paths From a
       Directory and All Its Subdirectories"
    Args:
        @param base_dir: The base directory from which we
                      begin the search for grib2 filenames.
    Returns:
        file_paths (list): A list of the full filepaths
                           of the data to be processed.
    """

    # Create an empty list which will eventually store
    # all the full filenames
    file_paths = []

    # pylint:disable=unused-variable
    # os.walk returns tuple, we don't need to utilize all the returned
    # values in the tuple.

    # Walk the tree
    for root, directories, files in os.walk(base_dir):
        for filename in files:
            # add it to the list only if it is a grib file
            match = re.match(r'.*(grib|grb|grib2|grb2)$', filename)
            if match:
                # Join the two strings to form the full
                # filepath.
                filepath = os.path.join(root, filename)
                file_paths.append(filepath)
            else:
                continue
    return file_paths


def get_storm_ids(filter_filename, logger):
    """! Get each storm as identified by its STORM_ID in the filter file
        save these in a set so we only save the unique ids and sort them.
        Args:
            @param filter_filename:  The name of the filter file to read
                                       and extract the storm id
            @param logger:  The name of the logger for logging useful info
        Returns:
            sorted_storms (List):  a list of unique, sorted storm ids
    """
    # pylint:disable=protected-access
    # Need to call sys.__getframe() to get the filename and method/func
    # for logging information.

    # For logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name
    logger.debug('DEBUG|' + cur_function + '|' + cur_filename)

    # Initialize a set because we want unique storm ids.
    storm_id_list = set()
    empty_list = []

    # Check if the filter_filename is empty, if it
    # is, then return an empty list.
    if not os.path.isfile(filter_filename):
        return empty_list
    if os.stat(filter_filename).st_size == 0:
        return empty_list
    with open(filter_filename, "r") as fileobj:
        header = fileobj.readline().split()
        header_colnum = header.index('STORM_ID')
        for line in fileobj:
            storm_id_list.add(str(line.split()[header_colnum]))

    # sort the unique storm ids, copy the original
    # set by using sorted rather than sort.
    sorted_storms = sorted(storm_id_list)
    return sorted_storms


def get_files(filedir, filename_regex, logger):
    """! Get all the files (with a particular
        naming format) by walking
        through the directories.
        Args:
          @param filedir:  The topmost directory from which the
                           search begins.
          @param filename_regex:  The regular expression that
                                  defines the naming format
                                  of the files of interest.
       Returns:
          file_paths (string): a list of filenames (with full filepath)
    """
    # pylint:disable=protected-access
    # Need to call sys.__getframe() to get the filename and method/func
    # for logging information.

    # For logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name

    logger.debug("DEBUG|" + cur_filename + "|" + cur_function)
    file_paths = []

    # pylint:disable=unused-variable
    # os.walk returns a tuple. Not all returned values are needed.

    # Walk the tree
    for root, directories, files in os.walk(filedir):
        for filename in files:
            # add it to the list only if it is a match
            # to the specified format
            match = re.match(filename_regex, filename)
            if match:
                # Join the two strings to form the full
                # filepath.
                filepath = os.path.join(root, filename)
                file_paths.append(filepath)
            else:
                continue
    return file_paths


def get_name_level(var_combo, logger):
    """!   Retrieve the variable name and level from a list of
          variable/level combinations.
          Args:
             @param var_combo:  A combination of the variable and the level
                                 separated by '/'
          Returns:
             name,level: A tuple of name and level derived from the
                         name/level combination.
    """

    # pylint:disable=protected-access
    # Need to call sys.__getframe() to get the filename and method/func
    # for logging information.
    # For logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name
    logger.debug("DEBUG|" + cur_function + "|" + cur_filename)

    match = re.match(r'(.*)/(.*)', var_combo)
    name = match.group(1)
    level = match.group(2)

    return name, level


def check_for_tiles(tile_dir, fcst_file_regex, anly_file_regex, logger):
    """! Checks for the presence of forecast and analysis
        tiles that were created by extract_tiles
        Args:
            @param tile_dir:  The directory where the expected
                              tiled files should reside.
            @param fcst_file_regex: The regexp describing the format of the
                                    forecast tile file.
            @param anly_file_regex: The regexp describing the format of the
                                    analysis tile file.
            @param logger:    The logger to which all log messages
                                should be directed.
        Returns:
            None  raises OSError if expected files are missing
    """
    anly_tiles = get_files(tile_dir, anly_file_regex, logger)
    fcst_tiles = get_files(tile_dir, fcst_file_regex, logger)

    num_anly_tiles = len(anly_tiles)
    num_fcst_tiles = len(fcst_tiles)

    # Check that there are analysis and forecast tiles
    # (which were, or should have been created earlier by extract_tiles).
    if not anly_tiles:
        # Cannot proceed, the necessary 30x30 degree analysis tiles are missing
        logger.error("ERROR: No anly tile files were found  " + tile_dir)
        raise OSError("No 30x30 anlysis tiles were found")
    elif not fcst_tiles:
        # Cannot proceed, the necessary 30x30 degree fcst tiles are missing
        logger.error("ERROR: No fcst tile files were found  " + tile_dir)
        raise OSError("No 30x30 fcst tiles were found")

    # Check for same number of fcst and analysis files
    if num_anly_tiles != num_fcst_tiles:
        # Something is wrong, we are missing
        # either an ANLY tile file or a FCST tile
        # file, this indicates a serious problem.
        logger.info("INFO: There are a different number of anly "
                    "and fcst tiles...")


def extract_year_month(init_time, logger):
    """! Retrieve the YYYYMM from the initialization time with format
         YYYYMMDD_hh
        Args:
            @param init_time:  The initialization time of expected format
            YYYYMMDD_hh
            @param logger:  Logger
        Returns:
            year_month (string):  The YYYYMM portion of the initialization time
    """
    # pylint:disable=protected-access
    # Need to call sys.__getframe() to get the filename and method/func
    # for logging information.

    # Useful for logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name

    # Match on anything that starts with 1 or 2 (for the century)
    #  followed by 5 digits for the remainder of the YYYMM
    year_month = re.match(r'^((1|2)[0-9]{5})', init_time)
    if year_month:
        year_month = year_month.group(0)
        return year_month
    else:
        logger.warning("WARNING|" + "[" + cur_filename + ":" + cur_function +
                       "]" + " | Cannot extract YYYYMM from "
                       "initialization time, unexpected format")
        raise Warning("Cannot extract YYYYMM from initialization time,"
                      " unexpected format")


def retrieve_and_regrid(tmp_filename, cur_init, cur_storm, out_dir, logger,
                        config):
    """! Retrieves the data from the MODEL_DATA_DIR (defined in metplus.conf)
         that corresponds to the storms defined in the tmp_filename:
        1) create the analysis tile and forecast file names from the
           tmp_filename file.
        2) perform regridding via MET tool (regrid_data_plane) and store
           results (netCDF files) in the out_dir or via
           Regridding via  regrid_data_plane on the forecast and analysis
           files via a latlon string with the following format:
                latlon Nx Ny lat_ll lon_ll delta_lat delta_lon
                NOTE:  these values are defined in the extract_tiles_parm
                parameter/config file as NLAT, NLON.
        Args:
        @param tmp_filename:   Filename of the temporary filter file in
                               the /tmp directory. Contains rows
                               of data corresponding to a storm id of varying
                               times.
        @param cur_init:       The current init time
        @param cur_storm:      The current storm
        @param out_dir:  The directory where regridded netCDF or grib2 output
                         is saved depending on which regridding methodology is
                         requested.  If the MET tool regrid_data_plane is
                         requested, then netCDF data is produced.  If wgrib2
                         is requested, then grib2 data is produced.
        @param logger:  The name of the logger used in logging.
        @param config:  config instance
        Returns:
           None
    """

    # pylint: disable=protected-access
    # Need to call sys._getframe() to get current function and file for
    # logging information.
    # pylint: disable=too-many-arguments
    # all input is needed to perform task

    #TODO Review this function retrieve_and_regrid
    # This needs to be refactored in to its own wrapper
    # or factored in to the RegridDataPlanWrapper class or subclass.
    # rdp=, was added when logging capability was added to capture
    # all MET output to log files. It is a temporary work around
    # to get logging up and running as needed.
    # It is being used to call the run_cmd method, which runs the cmd
    # and redirects logging based on the conf settings.
    # Instantiate a RegridDataPlaneWrapper
    rdp = RegridDataPlaneWrapper(config,logger)

    # For logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name

    # Get variables, etc. from param/config file.
    model_data_dir = config.getdir('MODEL_DATA_DIR')
    met_install_dir = config.getdir('MET_INSTALL_DIR')
    regrid_data_plane_exe = os.path.join(met_install_dir, 'bin/regrid_data_plane')
    # regrid_data_plane_exe = config.getexe('REGRID_DATA_PLANE_EXE')
    wgrib2_exe = config.getexe('WGRIB2')
    egrep_exe = config.getexe('EGREP_EXE')
    regrid_with_met_tool = config.getbool('config', 'REGRID_USING_MET_TOOL')
    overwrite_flag = config.getbool('config', 'OVERWRITE_TRACK')

    # Extract the columns of interest: init time, lead time,
    # valid time lat and lon of both tropical cyclone tracks, etc.
    # Then calculate the forecast hour and other things.
    with open(tmp_filename, "r") as tf:
        # read header
        header = tf.readline().split()
        # get column number for columns on interest
        # print('header{}:'.format(header))
        header_colnum_init, header_colnum_lead, header_colnum_valid = \
            header.index('INIT'), header.index('LEAD'), header.index('VALID')
        header_colnum_alat, header_colnum_alon =\
            header.index('ALAT'), header.index('ALON')
        header_colnum_blat, header_colnum_blon = \
            header.index('BLAT'), header.index('BLON')
        for line in tf:
            col = line.split()
            init, lead, valid, alat, alon, blat, blon = \
                col[header_colnum_init], col[header_colnum_lead], \
                col[header_colnum_valid], col[header_colnum_alat], \
                col[header_colnum_alon], col[header_colnum_blat], \
                col[header_colnum_blon]

            # integer division for both Python 2 and 3
            lead_time = int(lead)
            fcst_hr = lead_time // 10000

            init_ymd_match = re.match(r'[0-9]{8}', init)
            if init_ymd_match:
                init_ymd = init_ymd_match.group(0)
            else:
                logger.WARN("RuntimeError raised")
                raise RuntimeError('init time has unexpected format for YMD')

            init_ymdh_match = re.match(r'[0-9|_]{11}', init)
            if init_ymdh_match:
                init_ymdh = init_ymdh_match.group(0)
            else:
                logger.WARN("RuntimeError raised")

            valid_ymd_match = re.match(r'[0-9]{8}', valid)
            if valid_ymd_match:
                valid_ymd = valid_ymd_match.group(0)
            else:
                logger.WARN("RuntimeError raised")

            valid_ymdh_match = re.match(r'[0-9|_]{11}', valid)
            if valid_ymdh_match:
                valid_ymdh = valid_ymdh_match.group(0)
            else:
                logger.WARN("RuntimeError raised")

            lead_str = str(fcst_hr).zfill(3)
            fcst_dir = os.path.join(model_data_dir, init_ymd)
            init_ymdh_split = init_ymdh.split("_")
            init_yyyymmddhh = "".join(init_ymdh_split)
            anly_dir = os.path.join(model_data_dir, valid_ymd)
            valid_ymdh_split = valid_ymdh.split("_")
            valid_yyyymmddhh = "".join(valid_ymdh_split)

            # Create output filenames for regridding
            # wgrib2 used to regrid.
            # Create the filename for the regridded file, which is a
            # grib2 file.
            fcst_sts = \
                StringSub(logger, config.getraw('filename_templates',
                                                'GFS_FCST_FILE_TMPL'),
                          init=init_yyyymmddhh, lead=lead_str)

            anly_sts = \
                StringSub(logger, config.getraw('filename_templates',
                                                'GFS_ANLY_FILE_TMPL'),
                          valid=valid_yyyymmddhh, lead=lead_str)

            fcst_file = fcst_sts.doStringSub()
            fcst_filename = os.path.join(fcst_dir, fcst_file)
            anly_file = anly_sts.doStringSub()
            anly_filename = os.path.join(anly_dir, anly_file)

            # Check if the forecast input file exists. If it doesn't
            # exist, just log it
            if file_exists(fcst_filename):
                msg = ("INFO| [" + cur_filename + ":" + cur_function +
                       " ] | Forecast file: " + fcst_filename)
                logger.debug(msg)
            else:
                msg = ("WARNING| [" + cur_filename + ":" +
                       cur_function + " ] | " +
                       "Can't find forecast file, continuing anyway: " +
                       fcst_filename)
                logger.debug(msg)
                continue

            # Check if the analysis input file exists. If it doesn't
            # exist, just log it.
            if file_exists(anly_filename):
                msg = ("INFO| [" + cur_filename + ":" +
                       cur_function + " ] | Analysis file: " +
                       anly_filename)
                logger.debug(msg)

            else:
                msg = ("WARNING| [" + cur_filename + ":" +
                       cur_function + " ] | " +
                       "Can't find analysis file, continuing anyway: " +
                       anly_filename)
                logger.debug(msg)
                continue

            # Create the arguments used to perform regridding.
            # NOTE: the base name
            # is the same for both the fcst and anly filenames,
            # so use either one to derive the base name that will be used to
            # create the fcst_regridded_filename and anly_regridded_filename.
            fcst_anly_base = os.path.basename(fcst_filename)

            fcst_grid_spec = create_grid_specification_string(alat, alon,
                                                              logger, config)
            anly_grid_spec = create_grid_specification_string(blat, blon,
                                                              logger, config)
            if regrid_with_met_tool:
                nc_fcst_anly_base = re.sub("grb2", "nc", fcst_anly_base)
                fcst_anly_base = nc_fcst_anly_base

            tile_dir = os.path.join(out_dir, cur_init, cur_storm)
            fcst_hr_str = str(fcst_hr).zfill(3)

            fcst_regridded_filename = \
                config.getstr('regex_pattern', 'FCST_TILE_PREFIX') + \
                fcst_hr_str + "_" + fcst_anly_base
            fcst_regridded_file = os.path.join(tile_dir,
                                               fcst_regridded_filename)
            anly_regridded_filename = \
                config.getstr('regex_pattern', 'ANLY_TILE_PREFIX') +\
                fcst_hr_str + "_" + fcst_anly_base
            anly_regridded_file = os.path.join(tile_dir,
                                               anly_regridded_filename)

            # Regrid the fcst file only if a fcst tile
            # file does NOT already exist or if the overwrite flag is True.
            # Create new gridded file for fcst tile
            if file_exists(fcst_regridded_file) and not overwrite_flag:
                msg = ("INFO| [" + cur_filename + ":" +
                       cur_function + " ] | Forecast tile file " +
                       fcst_regridded_file + " exists, skip regridding")
                logger.debug(msg)
            else:
                # Perform fcst regridding on the records of interest
                var_level_string = retrieve_var_info(config, logger)
                if regrid_with_met_tool:
                    # Perform regridding using MET Tool regrid_data_plane
                    fcst_cmd_list = [regrid_data_plane_exe, ' ',
                                     fcst_filename, ' ',
                                     fcst_grid_spec, ' ',
                                     fcst_regridded_file, ' ',
                                     var_level_string,
                                     ' -method NEAREST ']
                    regrid_cmd_fcst = ''.join(fcst_cmd_list)

                    #regrid_cmd_fcst = \
                    #    batchexe('sh')['-c', regrid_cmd_fcst].err2out()
                    # run(regrid_cmd_fcst)

                    # Since not using the CommandBuilder to build the cmd,
                    # add the met verbosity level to the MET cmd created before
                    # we run the command.
                    regrid_cmd_fcst = rdp.cmdrunner.insert_metverbosity_opt(regrid_cmd_fcst)
                    (ret, regrid_cmd_fcst) = rdp.cmdrunner.run_cmd(regrid_cmd_fcst,app_name=rdp.app_name)
                    msg = ("INFO|[regrid]| regrid_data_plane regrid command:" +
                           regrid_cmd_fcst.to_shell())
                    logger.debug(msg)


                else:
                    # Perform regridding via wgrib2
                    requested_records = retrieve_var_info(config, logger)
                    fcst_cmd_list = [wgrib2_exe, ' ', fcst_filename, ' | ',
                                     egrep_exe, ' ', requested_records, '|',
                                     wgrib2_exe, ' -i ', fcst_filename,
                                     ' -new_grid ', fcst_grid_spec, ' ',
                                     fcst_regridded_file]
                    wgrb_cmd_fcst = ''.join(fcst_cmd_list)
                    #wgrb_cmd_fcst = \
                    #    batchexe('sh')['-c', wgrb_cmd_fcst].err2out()
                    #run(wgrb_cmd_fcst)

                    (ret, wgrb_cmd_fcst) = rdp.cmdrunner.run_cmd(wgrb_cmd_fcst,ismetcmd=False)
                    msg = ("INFO|[wgrib2]| wgrib2 regrid command:" +
                           wgrb_cmd_fcst.to_shell())
                    logger.debug(msg)

            # Create new gridded file for anly tile
            if file_exists(anly_regridded_file) and not overwrite_flag:
                logger.debug("INFO| [" + cur_filename + ":" +
                             cur_function + " ] |" +
                             " Analysis tile file: " +
                             anly_regridded_file +
                             " exists, skip regridding")
            else:
                # Perform anly regridding on the records of interest
                var_level_string = retrieve_var_info(config, logger)
                if regrid_with_met_tool:
                    anly_cmd_list = [regrid_data_plane_exe, ' ',
                                     anly_filename, ' ',
                                     anly_grid_spec, ' ',
                                     anly_regridded_file, ' ',
                                     var_level_string, ' ',
                                     ' -method NEAREST ']
                    regrid_cmd_anly = ''.join(anly_cmd_list)
                    #regrid_cmd_anly = \
                    #    batchexe('sh')['-c', regrid_cmd_anly].err2out()
                    #run(regrid_cmd_anly)

                    # Since not using the CommandBuilder to build the cmd,
                    # add the met verbosity level to the MET cmd created before
                    # we run the command.
                    regrid_cmd_anly = rdp.cmdrunner.insert_metverbosity_opt(regrid_cmd_anly)
                    (ret, regrid_cmd_anly) = rdp.cmdrunner.run_cmd(regrid_cmd_anly,app_name=rdp.app_name)
                    msg = ("INFO|[regrid]| on anly file:" +
                           anly_regridded_file)
                    logger.debug(msg)
                else:
                    # Regridding via wgrib2.
                    requested_records = retrieve_var_info(config, logger)
                    anly_cmd_list = [wgrib2_exe, ' ', anly_filename, ' | ',
                                     egrep_exe, ' ', requested_records, '|',
                                     wgrib2_exe, ' -i ', anly_filename,
                                     ' -new_grid ', anly_grid_spec, ' ',
                                     anly_regridded_file]
                    wgrb_cmd_anly = ''.join(anly_cmd_list)
                    #wgrb_cmd_anly = \
                    #    batchexe('sh')['-c', wgrb_cmd_anly].err2out()
                    # run(wgrb_cmd_anly)

                    (ret, wgrb_cmd_anly) = rdp.cmdrunner.run_cmd(wgrb_cmd_anly, ismetcmd=False)
                    msg = ("INFO|[wgrib2]| Regridding via wgrib2:" +
                           wgrb_cmd_anly.to_shell())
                    logger.debug(msg)


def retrieve_var_info(config, logger):
    """! Retrieve the variable name and level from the
        EXTRACT_TILES_VAR_FILTER and VAR_LIST.  If the
        EXTRACT_TILES_VAR_FILTER is empty, then retrieve
        the variable information from VAR_LIST.  Both are defined
        in the constants_pdef.py param file.  This will
        be used as part of the command to regrid the grib2 storm track
        files into netCDF.
        Args:
            @param config: The reference to the config/param instance.
            @param logger:  The logger to which all logging is directed.
                            Optional.
        Returns:
            field_level_string (string):  If REGRID_USING_MET_TOOL is True,
                                          A string with format -field
                                          'name="HGT"; level="P500";'
                                          for each variable defined in
                                          VAR_LIST. Otherwise, a string with
                                          format like:
                                          :TMP:2 |:HGT: 500|:PWAT:|:PRMSL:
                                          which will be used to regrid using
                                          wgrib2.
    """

    # pylint: disable=protected-access
    # Need to access sys._getframe() to retrieve the current file and function/
    # method for logging information.

    # For logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name

    logger.debug("DEBUG|" + cur_filename + "|" + cur_function)

    var_list = getlist(config.getstr('config', 'VAR_LIST'))
    extra_var_list = getlist(config.getstr('config', 'EXTRACT_TILES_VAR_LIST'))
    regrid_with_met_tool = config.getbool('config', 'REGRID_USING_MET_TOOL')
    full_list = []

    # Append the extra_var list to the var_list
    # and remove any duplicates. *NOTE, order
    # will be lost.
    full_var_list = var_list + extra_var_list
    unique_var_list = list(set(full_var_list))

    if regrid_with_met_tool:
        name_str = 'name="'
        level_str = 'level="'

        for cur_var in unique_var_list:
            match = re.match(r'(.*)/(.*)', cur_var)
            name = match.group(1)
            level = match.group(2)
            level_val = "_" + level

            # Create the field info string that can be used
            # by the MET Tool regrid_data_plane to perform
            # regridding.
            cur_list = [' -field ', "'", name_str, name, '"; ',
                        level_str, level_val, '";', "'", '\\ ']
            cur_str = ''.join(cur_list)
            full_list.append(cur_str)
        field_level_string = ''.join(full_list)
    else:
        full_list = ['":']
        for cur_var in unique_var_list:
            match = re.match(r'(.*)/(.*)', cur_var)
            name = match.group(1)
            level = match.group(2)
            level_match = re.match(r'([a-zA-Z])([0-9]{1,3})', level)
            level_val = level_match.group(2)

            # Create the field info string that can be used by
            # wgrib2 to perform regridding.
            if int(level_val) > 0:
                level_str = str(level_val) + ' '
            else:
                # For Z0, Z2, etc. just gather all available.
                level_str = ""

            cur_list = [name, ':', level_str, '|']
            tmp_str = ''.join(cur_list)
            full_list.append(tmp_str)

        # Remove the last '|' and add the terminal double quote.
        field_level_string = ''.join(full_list)
        field_level_string = field_level_string[:-1]
        field_level_string += '"'

    return field_level_string


def create_grid_specification_string(lat, lon, logger, config):
    """! Create the grid specification string with the format:
         latlon Nx Ny lat_ll lon_ll delta_lat delta_lon
         used by the MET tool, regrid_data_plane.
         Args:
            @param lat:   The latitude of the grid point
            @param lon:   The longitude of the grid point
            @param logger: The name of the logger
            @param config: config instance
         Returns:
            tile_grid_str (string): the tile grid string for the
                                    input lon and lat
    """

    # pylint: disable=protected-access
    # Need to access sys._getframe to capture current file and function for
    # logging information

    # Useful for logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name
    regrid_by_met = config.getbool('config', 'REGRID_USING_MET_TOOL')

    # Initialize the tile grid string
    # and get the other values from the parameter file
    nlat = config.getstr('config', 'NLAT')
    nlon = config.getstr('config', 'NLON')
    dlat = config.getstr('config', 'DLAT')
    dlon = config.getstr('config', 'DLON')
    lon_subtr = config.getfloat('config', 'LON_ADJ')
    lat_subtr = config.getfloat('config', 'LAT_ADJ')

    # Format for regrid_data_plane:
    # latlon Nx Ny lat_ll lon_ll delta_lat delta_lonadj_lon =
    # float(lon) - lon_subtr
    adj_lon = float(lon) - lon_subtr
    adj_lat = float(lat) - lat_subtr
    lon0 = str(round_0p5(adj_lon))
    lat0 = str(round_0p5(adj_lat))

    msg = ("DEBUG|[" + cur_filename + ":" + cur_function + "]  nlat:" +
           nlat + " nlon: " + nlon + " lat0:" + lat0 + " lon0: " + lon0)
    logger.debug(msg)

    # Create the specification string based on the requested tool.
    if regrid_by_met:
        grid_list = ['"', 'latlon ', nlat, ' ', nlon, ' ', lat0, ' ',
                     lon0, ' ', dlat, ' ', dlon, '"']
    else:
        # regrid via wgrib2
        grid_list = ['latlon ', lon0, ':', nlon, ':', dlon, ' ',
                     lat0, ':', nlat, ':', dlat]

    tile_grid_str = ''.join(grid_list)
    msg = ("INFO|" + cur_filename + ":" + cur_function +
           "| complete grid specification string: " + tile_grid_str)
    logger.debug(msg)
    return tile_grid_str


def gen_date_list(begin_date, end_date):
    """! Generates a list of dates of the form yyyymmdd from a being date to
     end date
    Inputs:
      @param begin_date -- such as "20070101"
      @param end_date -- such as "20070103"
    Returns:
      date_list -- such as ["20070101","20070102","20070103"]
    """

    begin_tm = time.strptime(begin_date, "%Y%m%d")
    end_tm = time.strptime(end_date, "%Y%m%d")
    begin_tv = calendar.timegm(begin_tm)
    end_tv = calendar.timegm(end_tm)
    date_list = []
    for tv in xrange(begin_tv, end_tv + 86400, 86400):
        date_list.append(time.strftime("%Y%m%d", time.gmtime(tv)))
    return date_list


def gen_hour_list(hour_inc, hour_end):
    """! Generates a list of hours of the form hh or hhh
    Inputs:
      @param hour_inc -- increment in integer format such as 6
      @param hour_end -- hh or hhh string indicating the end hour for the
                       increment such as "18"
    Returns:
      hour_list -- such as ["00", "06", "12", "18"]
    """

    int_list = range(0, int(hour_end) + 1, hour_inc)

    zfill_val = 0
    if len(hour_end) == 2:
        zfill_val = 2
    elif len(hour_end) == 3:
        zfill_val = 3

    hour_list = []
    for my_int in int_list:
        hour_string = str(my_int).zfill(zfill_val)
        hour_list.append(hour_string)

    return hour_list


def gen_init_list(init_date_begin, init_date_end, init_hr_inc, init_hr_end):
    """!
    Generates a list of initialization date and times of the form yyyymmdd_hh
    or yyyymmdd_hhh
    Inputs:
      @param init_begin_date -- yyyymmdd string such as "20070101"
      @param init_end_date -- yyyymmdd string such as "20070102"
      @param init_hr_inc -- increment in integer format such as 6
      @param init_hr_end -- hh or hhh string indicating the end hour for the
                           increment such as "18"
    Returns:
      init_list -- such as ["20070101_00", "20070101_06", "20070101_12",
      "20070101_18", "20070102_00", "20070102_06", "20070102_12",
      "20070102_18"]
    """

    my_hour_list = gen_hour_list(init_hr_inc, init_hr_end)

    my_date_list = gen_date_list(init_date_begin, init_date_end)

    date_init_list = []

    # pylint:disable=unused-variable
    # using enumerate on my_date_list returns a tuple, and not all values
    # are needed.

    for index, my_date in enumerate(my_date_list):
        for my_hour in my_hour_list:
            init_string = my_date + "_" + my_hour
            date_init_list.append(init_string)

    return date_init_list


def prune_empty(output_dir, logger):
    """! Start from the output_dir, and recursively check
        all directories and files.  If there are any empty
        files or directories, delete/remove them so they
        don't cause performance degradation or errors
        when performing subsequent tasks.
        Input:
            @param output_dir:  The directory from which searching
                                should begin.
            @param logger: The logger to which all logging is
                           directed.
    """

    # pylint:disable=protected-access
    # Need to call sys.__getframe() to get the filename and method/func
    # for logging information.
    # For logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name

    # Check for empty files.
    for root, dirs, files in os.walk(output_dir):
        # Create a full file path by joining the path
        # and filename.
        for a_file in files:
            a_file = os.path.join(root, a_file)
            if os.stat(a_file).st_size == 0:
                msg = ("INFO|[" + cur_filename + ":" +
                       cur_function + "]|" +
                       "Empty file: " + a_file +
                       "...removing")

                logger.debug(msg)
                os.remove(a_file)

    # Now check for any empty directories, some
    # may have been created when removing
    # empty files.
    for root, dirs, files in os.walk(output_dir):
        for direc in dirs:
            full_dir = os.path.join(root, direc)
            if not os.listdir(full_dir):
                msg = ("INFO|[" + cur_filename + ":" +
                       cur_function + "]|" +
                       "Empty directory: " + full_dir +
                       "...removing")
                logger.debug(msg)
                os.rmdir(full_dir)


def cleanup_temporary_files(list_of_files):
    """! Remove the files indicated in the list_of_files list.  The full
       file path must be indicated.
        Args:
          @param list_of_files: A list of files (full filepath) to be
          removed.
        Returns:
            None:  Removes the requested files.
    """
    for single_file in list_of_files:
        try:
            os.remove(single_file)
        except OSError:
            # Raises exception if this doesn't exist (never created or
            # already removed).  Ignore.
            pass


def apply_series_filters(tile_dir, init_times, series_output_dir, filter_opts,
                         temporary_dir, logger, config):
    """! Apply filter options, as specified in the
        param/config file.
        Args:
           @param tile_dir:  Directory where input data files reside.
                             e.g. data which we will be applying our filter
                             criteria.
           @param init_times:  List of init times that define the input data.
           @param series_output_dir:  The directory where the filter results
                                      will be stored.
           @param filter_opts:  The filter options to apply
           @param temporary_dir:  The temporary directory where intermediate
                                  files are saved.
           @param logger:  The logger to which all logging is directed.
           @param config:  The config/param instance
        Returns:
            None
    """
    # pylint: disable=too-many-arguments
    # Seven input arguments are needed to perform filtering.

    # pylint:disable=protected-access
    # Need to call sys.__getframe() to get the filename and method/func
    # for logging information.

    # Useful for logging
    cur_filename = sys._getframe().f_code.co_filename
    cur_function = sys._getframe().f_code.co_name

    # Create temporary directory where intermediate files are saved.
    cur_pid = str(os.getpid())
    tmp_dir = os.path.join(temporary_dir, cur_pid)
    logger.debug("DEBUG|" + cur_filename + "|" + cur_function +
                 " creating tmp dir: " + tmp_dir)

    for cur_init in init_times:
        # Call the tc_stat wrapper to build up the command and invoke
        # the MET tool tc_stat.
        filter_file = "filter_" + cur_init + ".tcst"
        filter_filename = os.path.join(series_output_dir,
                                       cur_init, filter_file)

        #TODO Review this function apply_series_filters
        # should this be in its own wrapper or subclass of tc_stat
        tcs = TcStatWrapper(config,logger)
        tcs.build_tc_stat(series_output_dir, cur_init, tile_dir, filter_opts)

        # Check that the filter.tcst file isn't empty. If
        # it is, then use the files from extract_tiles as
        # input (tile_dir = extract_out_dir)
        if not file_exists(filter_filename):
            msg = ("WARN| " + cur_filename + ":" + cur_function +
                   "]| Non-existent filter file, filter " +
                   " Never created by MET Tool tc_stat.")
            logger.debug(msg)
            continue
        elif os.stat(filter_filename).st_size == 0:
            msg = ("WARN| " + cur_filename + ":" + cur_function +
                   "]| Empty filter file, filter " +
                   " options yield nothing.")
            logger.debug(msg)
            continue
        else:
            # Now retrieve the files corresponding to these
            # storm ids that resulted from filtering.
            sorted_storm_ids = get_storm_ids(filter_filename, logger)

            # Retrieve the header from filter_filename to be used in
            # creating the temporary files.
            with open(filter_filename, 'r') as filter_file:
                header = filter_file.readline()

            for cur_storm in sorted_storm_ids:
                msg = ("INFO| [" + cur_filename + ":" +
                       cur_function + " ] | Processing storm: " + cur_storm +
                       " for file: " + filter_filename)
                logger.debug(msg)
                storm_output_dir = os.path.join(series_output_dir,
                                                cur_init, cur_storm)
                mkdir_p(storm_output_dir)
                mkdir_p(tmp_dir)
                tmp_file = "filter_" + cur_init + "_" + cur_storm
                tmp_filename = os.path.join(tmp_dir, tmp_file)
                storm_match_list = grep(cur_storm, filter_filename)
                with open(tmp_filename, "a+") as tmp_file:
                    tmp_file.write(header)
                    for storm_match in storm_match_list:
                        tmp_file.write(storm_match)

                # Create the analysis and forecast files based
                # on the storms (defined in the tmp_filename created above)
                # Store the analysis and forecast files in the
                # series_output_dir.
                retrieve_and_regrid(tmp_filename, cur_init, cur_storm,
                                    series_output_dir, logger, config)

    # Check for any empty files and directories and remove them to avoid
    # any errors or performance degradation when performing
    # series analysis.
    prune_empty(series_output_dir, logger)

    # Clean up the tmp dir
    rmtree(tmp_dir)


def create_filter_tmp_files(filtered_files_list, filter_output_dir, logger=None):
    """! Creates the tmp_fcst and tmp_anly ASCII files that contain the full
        filepath of files that correspond to the filter criteria.  Useful for
        validating that filtering returns the expected results/troubleshooting.
        Args:
            @param filtered_files_list:  A list of the netCDF or grb2 files
                                          that result from applying filter
                                          options and running the MET tool
                                          tc_stat.
            @param filter_output_dir:  The directory where the filtered data is
                                       stored
            @param logger a logging.Logger for log messages
        Returns:
            None: Creates two ASCII files
    """

    # Useful for logging
    # cur_filename = sys._getframe().f_code.co_filename
    # cur_function = sys._getframe().f_code.co_name

    # Create the filenames for the tmp_fcst and tmp_anly files.
    tmp_fcst_filename = os.path.join(filter_output_dir,
                                     "tmp_fcst_regridded.txt")
    tmp_anly_filename = os.path.join(filter_output_dir,
                                     "tmp_anly_regridded.txt")

    fcst_list = []
    anly_list = []

    for filter_file in filtered_files_list:
        fcst_match = re.match(r'(.*/FCST_TILE_F.*.[grb2|nc])', filter_file)
        if fcst_match:
            fcst_list.append(fcst_match.group(1))

        anly_match = re.match(r'(.*/ANLY_TILE_F.*.[grb2|nc])', filter_file)
        if anly_match:
            anly_list.append(anly_match.group(1))

    # Write to the appropriate tmp file
    with open(tmp_fcst_filename, "a+") as fcst_tmpfile:
        for fcst in fcst_list:
            fcst_tmpfile.write(fcst + "\n")

    with open(tmp_anly_filename, "a+") as anly_tmpfile:
        for anly in anly_list:
            anly_tmpfile.write(anly + "\n")


def get_updated_init_times(input_dir, config=None):
    """ Get a list of init times, derived by the .tcst files in the
        input_dir (and below).
        Args:
            @param input_dir:  The topmost directory from which our search for
                               filter.tcst files begins.
            @param config:  Reference to metplus.conf configuration instance.
        Returns:
            updated_init_times_list : A list of the init times represented by
                                      the forecast.tcst files found in the
                                      input_dir.
    """

    # For logging
    # cur_filename = sys._getframe().f_code.co_filename
    # cur_function = sys._getframe().f_code.co_name

    updated_init_times_list = []
    init_times_list = []
    filter_list = get_files(input_dir, ".*.tcst", config)
    if filter_list:
        for filter_file in filter_list:
            match = re.match(r'.*/filter_([0-9]{8}_[0-9]{2,3})', filter_file)
            init_times_list.append(match.group(1))
        updated_init_times_list = sorted(init_times_list)

    return updated_init_times_list


def get_dirs(base_dir):
    """! Get a list of directories under a base directory.
        Args:
            @param base_dir:  The base directory from where search begins
       Returns:
           dir_list:  A list of directories under the base_dir
    """

    dir_list = []

    # pylint:disable=unused-variable
    # os.walk returns a tuple, not all returned values are needed.

    for dirname, dirs, filenames in os.walk(base_dir):
        for direc in dirs:
            dir_list.append(os.path.join(dirname, direc))

    return dir_list


def getlist(s, logger=None):
    """! Returns a list of string elements from a comma or space
         separated string of values.

         This function MUST also return an empty list [] if s is '' empty.

         This function is meant to handle these possible or similar inputs:
         AND return a clean list with no surrounding spaces or trailing
         commas in the elements.

         '4,4,2,4,2,4,2, ' or '4,4,2,4,2,4,2 ' or
         '4, 4, 4, 4, ' or '4, 4, 4, 4 '

         Note: getstr on an empty variable (EMPTY_VAR = ) in 
         a conf file returns '' an empty string.
        
        @param s the string being converted to a list.  
    """

    # Developer NOTE: we could just force this to only operate
    # on comma seperated lists, not space seperated.

    # FIRST remove surrounding comma, and spaces, form the string.
    s = s.strip().strip(',').strip()

    # splitting an empty string, s with ',', creates a 1 element
    # list with an empty string element, we dont want to create or 
    # retrun that, ie. NEVER RETURN THIS [''], If s is '', an
    # empty string, then return an empty list [].
    # Doing so allows for proper boolean testing of your
    # list elsewhere in the code, ie. bool([]) is False.

    # if s is not an empty string, split it on
    # commas or spaces
    if s:
        if ',' in s:
            s = s.split(',')
            s = [item.strip() for item in s]
        else:
            s = s.split()
    else:
        # create an empty list []
        s = list()

    return s


def getlistfloat(s):
    s = getlist(s)
    s = [float(i) for i in s]
    return s


def getlistint(s):
    s = getlist(s)
    s = [int(i) for i in s]
    return s


# minutes
def shift_time(time, shift):
    return (datetime.datetime.strptime(time, "%Y%m%d%H%M") +
            datetime.timedelta(hours=shift)).strftime("%Y%m%d%H%M")

def shift_time_minutes(time, shift):
    return (datetime.datetime.strptime(time, "%Y%m%d%H%M") +
            datetime.timedelta(minutes=shift)).strftime("%Y%m%d%H%M")

def shift_time_seconds(time, shift):
    return (datetime.datetime.strptime(time, "%Y%m%d%H%M") +
            datetime.timedelta(seconds=shift)).strftime("%Y%m%d%H%M")


class FieldObj(object):
    __slots__ = 'fcst_name', 'fcst_level', 'fcst_extra',\
                'obs_name', 'obs_level', 'obs_extra'

def parse_var_list(p):
    # var_list is a list containing an list of FieldObj
    var_list = []

    # find all FCST_VARn_NAME keys in the conf files
    all_conf = p.keys('config')
    fcst_indices = []
    regex = re.compile("FCST_VAR(\d+)_NAME")
    for conf in all_conf:
        result = regex.match(conf)
        if result is not None:
          fcst_indices.append(result.group(1))

    # loop over all possible variables and add them to list
    for n in fcst_indices:
        # get fcst var info if available
        if p.has_option('config', "FCST_VAR"+n+"_NAME"):
            fcst_name = p.getstr('config', "FCST_VAR"+n+"_NAME")

            fcst_extra = ""
            if p.has_option('config', "FCST_VAR"+n+"_OPTIONS"):
                fcst_extra = p.getraw('config', "FCST_VAR"+n+"_OPTIONS")

            # if OBS_VARn_X does not exist, use FCST_VARn_X
            if p.has_option('config', "OBS_VAR"+n+"_NAME"):
                obs_name = p.getstr('config', "OBS_VAR"+n+"_NAME")
            else:
                obs_name = fcst_name

            obs_extra = ""
            if p.has_option('config', "OBS_VAR"+n+"_OPTIONS"):
                obs_extra = p.getraw('config', "OBS_VAR"+n+"_OPTIONS")

            fcst_levels = getlist(p.getstr('config', "FCST_VAR"+n+"_LEVELS"))
            if p.has_option('config', "OBS_VAR"+n+"_LEVELS"):
                obs_levels = getlist(p.getstr('config', "OBS_VAR"+n+"_LEVELS"))
            else:
                obs_levels = fcst_levels

            if len(fcst_levels) != len(obs_levels):
                print("ERROR: FCST_VAR"+n+"_LEVELS and OBS_VAR"+n+\
                          "_LEVELS do not have the same number of elements")
                exit(1)

            for f,o in zip(fcst_levels, obs_levels):
                fo = FieldObj()
                fo.fcst_name = fcst_name
                fo.obs_name = obs_name
                fo.fcst_extra = fcst_extra
                fo.obs_extra = obs_extra
                fo.fcst_level = f
                fo.obs_level = o
                var_list.append(fo)

    '''
    count = 0
    for v in var_list:
        print(" fcst_name:"+v.fcst_name)
        print(" fcst_level:"+v.fcst_level)
        print(" fcst_extra:"+v.fcst_extra)
        print(" obs_name:"+v.obs_name)
        print(" obs_level:"+v.obs_level)
        print(" obs_extra:"+v.obs_extra)
        print("")
        count += 1
    '''
    return var_list


def reformat_fields_for_met(all_vars_list, logger):
        """! Reformat the fcst or obs field values defined in the
             MET+ config file to the MET field dictionary.

             Args:
                 all_vars_list - The list of all variables/fields retrieved
                                 from the MET+ configuration file

                 logger        - The log to which any logging is directed.

             Returns:
                 met_fields - a named tuple containing the fcst field and
                              obs field key-value pairs needed by MET.


        """
        # pylint:disable=protected-access
        # Need to call sys.__getframe() to get the filename and method/func
        # for logging information.

        # Used for logging.
        cur_filename = sys._getframe().f_code.co_filename
        cur_function = sys._getframe().f_code.co_name
        logger.info("INFO|:" + cur_function + '|' + cur_filename + '| ' +
                    "Reformatting field dictionary ...")

        # Named tuple (so we don't have to remember the order of the fields)
        # containing the string corresponding to the fcst or obs field
        # key-values for the MET config file.
        MetFields = namedtuple("MetFields", "fcst_field, obs_field")

        # Two types of fields in the MET fields dictionary, fcst and obs. Use
        # this to create the key-value pairs.
        field_list = ['fcst', 'obs']
        fcst_field = ''
        obs_field = ''
        for var in all_vars_list:
            # Create the key-value pairs in the fcst field and obs field
            # dictionaries as defined in the MET configuration file:
            # fcst = {
            #    field = [
            #       {
            #         name = "TMP";
            #         level = ["P500", "P400", "P300"];
            #         cat_thresh = [ > 80.0];
            #         GRIB_lvl_typ = 202;
            #       },
            #       {
            #         name = "HGT";
            #         level = ["P500"];
            #         cat_thresh = [ > 0.0];
            #         GRIB_lvl_typ = 202;
            #       },
            #    ]
            # }
            # obs = fcst;
            #
            # The reformatting involves creating the field key-value pairs in
            # the fcst and obs dictionaries.

            # Iterate over the field types fcst and obs
            for field in field_list:
                if field == 'fcst':
                    name = var.fcst_name
                    level = var.fcst_level.zfill(2)
                    extra = var.fcst_extra
                elif field == 'obs':
                    name = var.obs_name
                    level = var.obs_level
                    extra = var.obs_extra

                name_level_extra_list = ['{ name = "', name,
                                         '"; level = [ "', level, '" ]; ']
                if extra:
                    extra_str = extra + '; },'
                    name_level_extra_list.append(extra_str)
                else:
                    # End the text for this field.  If this is the last field,
                    # end the dictionary appropriately.
                    if var == all_vars_list[-1]:
                        # This is the last field, terminate it appropriately.
                        name_level_extra_list.append('}')
                    else:
                        # More field(s) to go
                        name_level_extra_list.append('}, ')

                # Create the long string that will comprise the dictionary in
                # the MET point_stat config file.
                if field == 'fcst':
                    fcst_field += ''.join(name_level_extra_list)
                elif field == 'obs':
                    obs_field += ''.join(name_level_extra_list)

        met_fields = MetFields(fcst_field, obs_field)

        return met_fields

def get_filetype(config, filepath):
    ncdump_exe = config.getexe('NCDUMP_EXE')
    try:
        result = subprocess.check_output([ncdump_exe, filepath])
    except subprocess.CalledProcessError:
        return "GRIB"

    regex = re.search("netcdf", result)
    if regex is not None:
        return "NETCDF"
    else:
        return None


def get_time_from_file(logger, filepath, template):
    if os.path.isdir(filepath):
        return None

    # Check number of / in template, get same number from file path
    num_slashes = template.count('/')
    path_split = filepath.split('/')
    f = ""
    for n in range(num_slashes, -1, -1):
        f = os.path.join(f,path_split[-(n+1)])
#    print(f+" and "+template)
    se = StringExtract(logger, template, f)

    if se.parseTemplate():
        return se
    else:
        return None


if __name__ == "__main__":
    gen_init_list("20141201", "20150331", 6, "18")
