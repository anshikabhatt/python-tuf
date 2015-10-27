#!/usr/bin/env python

"""
<Program Name>
  test_mix_and_match_attack.py

<Author>
  Konstantin Andrianov.

<Started>
  March 27, 2012.
  
  April 6, 2014.
    Refactored to use the 'unittest' module (test conditions in code, rather
    than verifying text output), use pre-generated repository files, and
    discontinue use of the old repository tools.  Modify the previous scenario
    simulated for the mix-and-match attack.  -vladimir.v.diaz

<Copyright>
  See LICENSE for licensing information.

<Purpose>
  Simulate a mix-and-match attack.  In a mix-and-match attack, an attacker is
  able to trick clients into using a combination of metadata that never existed
  together on the repository at the same time.

  Note: There is no difference between 'updates' and 'target' files.
"""

# Help with Python 3 compatibility, where the print statement is a function, an
# implicit relative import is invalid, and the '/' operator performs true
# division.  Example:  print 'hello world' raises a 'SyntaxError' exception.
from __future__ import print_function
from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import os
import tempfile
import random
import time
import shutil
import json
import subprocess
import logging
import sys

# 'unittest2' required for testing under Python < 2.7.
if sys.version_info >= (2, 7):
  import unittest

else:
  import unittest2 as unittest 

import tuf.formats
import tuf.util
import tuf.log
import tuf.client.updater as updater
import tuf.repository_tool as repo_tool
import tuf.unittest_toolbox as unittest_toolbox

import six

# The repository tool is imported and logs console messages by default.  Disable
# console log messages generated by this unit test.
repo_tool.disable_console_log_messages()

logger = logging.getLogger('tuf.test_mix_and_match_attack')



class TestMixAndMatchAttack(unittest_toolbox.Modified_TestCase):

  @classmethod
  def setUpClass(cls):
    # setUpClass() is called before any of the test cases are executed.
    
    # Create a temporary directory to store the repository, metadata, and target
    # files.  'temporary_directory' must be deleted in TearDownModule() so that
    # temporary files are always removed, even when exceptions occur. 
    cls.temporary_directory = tempfile.mkdtemp(dir=os.getcwd())
    
    # Launch a SimpleHTTPServer (serves files in the current directory).
    # Test cases will request metadata and target files that have been
    # pre-generated in 'tuf/tests/repository_data', which will be served by the
    # SimpleHTTPServer launched here.  The test cases of this unit test assume 
    # the pre-generated metadata files have a specific structure, such
    # as a delegated role 'targets/role1', three target files, five key files,
    # etc.
    cls.SERVER_PORT = random.randint(30000, 45000)
    command = ['python', 'simple_server.py', str(cls.SERVER_PORT)]
    cls.server_process = subprocess.Popen(command, stderr=subprocess.PIPE)
    logger.info('Server process started.')
    logger.info('Server process id: '+str(cls.server_process.pid))
    logger.info('Serving on port: '+str(cls.SERVER_PORT))
    cls.url = 'http://localhost:'+str(cls.SERVER_PORT) + os.path.sep

    # NOTE: Following error is raised if a delay is not applied:
    # <urlopen error [Errno 111] Connection refused>
    time.sleep(.8)



  @classmethod 
  def tearDownClass(cls):
    # tearDownModule() is called after all the test cases have run.
    # http://docs.python.org/2/library/unittest.html#class-and-module-fixtures
   
    # Remove the temporary repository directory, which should contain all the
    # metadata, targets, and key files generated of all the test cases.
    shutil.rmtree(cls.temporary_directory)
   
    # Kill the SimpleHTTPServer process.
    if cls.server_process.returncode is None:
      logger.info('Server process '+str(cls.server_process.pid)+' terminated.')
      cls.server_process.kill()



  def setUp(self):
    # We are inheriting from custom class.
    unittest_toolbox.Modified_TestCase.setUp(self)
  
    # Copy the original repository files provided in the test folder so that
    # any modifications made to repository files are restricted to the copies.
    # The 'repository_data' directory is expected to exist in 'tuf/tests/'.
    original_repository_files = os.path.join(os.getcwd(), 'repository_data') 
    temporary_repository_root = \
      self.make_temp_directory(directory=self.temporary_directory)
  
    # The original repository, keystore, and client directories will be copied
    # for each test case. 
    original_repository = os.path.join(original_repository_files, 'repository')
    original_client = os.path.join(original_repository_files, 'client')
    original_keystore = os.path.join(original_repository_files, 'keystore')
    
    # Save references to the often-needed client repository directories.
    # Test cases need these references to access metadata and target files. 
    self.repository_directory = \
      os.path.join(temporary_repository_root, 'repository')
    self.client_directory = os.path.join(temporary_repository_root, 'client')
    self.keystore_directory = os.path.join(temporary_repository_root, 'keystore')
    
    # Copy the original 'repository', 'client', and 'keystore' directories
    # to the temporary repository the test cases can use.
    shutil.copytree(original_repository, self.repository_directory)
    shutil.copytree(original_client, self.client_directory)
    shutil.copytree(original_keystore, self.keystore_directory)
    
    # Set the url prefix required by the 'tuf/client/updater.py' updater.
    # 'path/to/tmp/repository' -> 'localhost:8001/tmp/repository'. 
    repository_basepath = self.repository_directory[len(os.getcwd()):]
    url_prefix = \
      'http://localhost:' + str(self.SERVER_PORT) + repository_basepath 
    
    # Setting 'tuf.conf.repository_directory' with the temporary client
    # directory copied from the original repository files.
    tuf.conf.repository_directory = self.client_directory 
    self.repository_mirrors = {'mirror1': {'url_prefix': url_prefix,
                                           'metadata_path': 'metadata',
                                           'targets_path': 'targets',
                                           'confined_target_dirs': ['']}}

    # Create the repository instance.  The test cases will use this client
    # updater to refresh metadata, fetch target files, etc.
    self.repository_updater = updater.Updater('test_repository',
                                              self.repository_mirrors)


  def tearDown(self):
    # Modified_TestCase.tearDown() automatically deletes temporary files and
    # directories that may have been created during each test case.
    unittest_toolbox.Modified_TestCase.tearDown(self)



  def test_with_tuf(self):
    # Scenario:
    # An attacker tries to trick the client into installing files indicated by
    # a previous release of its corresponding metatadata.  The outdated metadata
    # is properly named and was previously valid, but is no longer current
    # according to the latest 'snapshot.json' role.  Generate a new snapshot of
    # the repository after modifying a target file of 'role1.json'.
    # Backup 'role1.json' (the delegated role to be updated, and then inserted
    # again for the mix-and-match attack.)
    role1_path = os.path.join(self.repository_directory, 'metadata', 'targets',
                                  'role1.json')
    backup_role1 = os.path.join(self.repository_directory, 'role1.json.backup') 
    shutil.copy(role1_path, backup_role1)

    # Backup 'file3.txt', specified by 'role1.json'.
    file3_path = os.path.join(self.repository_directory, 'targets', 'file3.txt')
    shutil.copy(file3_path, file3_path + '.backup')
    
    # Re-generate the required metadata on the remote repository.  The affected
    # metadata must be properly updated and signed with 'repository_tool.py',
    # otherwise the client will reject them as invalid metadata.  The resulting
    # metadata should be valid metadata.
    repository = repo_tool.load_repository(self.repository_directory)

    # Load the signing keys so that newly generated metadata is properly signed.
    timestamp_keyfile = os.path.join(self.keystore_directory, 'timestamp_key') 
    role1_keyfile = os.path.join(self.keystore_directory, 'delegation_key') 
    snapshot_keyfile = os.path.join(self.keystore_directory, 'snapshot_key') 
    timestamp_private = \
      repo_tool.import_rsa_privatekey_from_file(timestamp_keyfile, 'password')
    role1_private = \
      repo_tool.import_rsa_privatekey_from_file(role1_keyfile, 'password')
    snapshot_private = \
      repo_tool.import_rsa_privatekey_from_file(snapshot_keyfile, 'password')

    repository.targets('role1').load_signing_key(role1_private)
    repository.snapshot.load_signing_key(snapshot_private)
    repository.timestamp.load_signing_key(timestamp_private)
  
    # Modify a 'role1.json' target file, and add it to its metadata so that a
    # new version is generated.
    with open(file3_path, 'wt') as file_object:
      file_object.write('This is role2\'s target file.')
    repository.targets('role1').add_target(file3_path)

    repository.write()
    
    # Move the staged metadata to the "live" metadata.
    shutil.rmtree(os.path.join(self.repository_directory, 'metadata'))
    shutil.copytree(os.path.join(self.repository_directory, 'metadata.staged'),
                    os.path.join(self.repository_directory, 'metadata'))
  
    # Insert the previously valid 'role1.json'.  The TUF client should reject it.
    shutil.move(backup_role1, role1_path)
    
    # Verify that the TUF client detects unexpected metadata (previously valid,
    # but not up-to-date with the latest snapshot of the repository) and refuses
    # to continue the update process.
    # Refresh top-level metadata so that the client is aware of the latest
    # snapshot of the repository.
    self.repository_updater.refresh()

    try:
      self.repository_updater.targets_of_role('targets/role1')
   
    # Verify that the specific 'tuf.BadVersionNumberError' exception is raised
    # by each mirror.
    except tuf.NoWorkingMirrorError as exception:
      for mirror_url, mirror_error in six.iteritems(exception.mirror_errors):
        url_prefix = self.repository_mirrors['mirror1']['url_prefix']
        url_file = os.path.join(url_prefix, 'metadata', 'targets', 'role1.json')
       
        # Verify that 'role1.json' is the culprit.
        self.assertEqual(url_file, mirror_url)
        self.assertTrue(isinstance(mirror_error, tuf.BadVersionNumberError))

    else:
      self.fail('TUF did not prevent a mix-and-match attack.')


if __name__ == '__main__':
  unittest.main()
