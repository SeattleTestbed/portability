"""
<Program Name>
  repyhelper.py

<Started>
  November 2008

<Author>
  Andreas Sekine
  Heavily revised by: Justin Cappos

<Purpose>
  Make porting Repy code to regular python easier. The main interface
  is through repyhelper.translate and repyhelper.translate_and_import


  JAC Note:   I wanted to add an interface that allowed a user to specify
  a repyhelper path that is separate from the Python path.   This seems to
  be impossible because you can't always use absolute names when importing
  Python modules and because you can't prevent other imports from happening.
  This prevent me from writing modules in a location other than the python
  path.   As jsamuel pointed out, it's not clear how this interacts with
  non-relative path names (#291).   My solution is to write these files into
  the first item in the Python path.

"""


import os # for file checks
import inspect # for fiddling with callstack/module namespaces

# JAC / JS: to get the Python path
import sys


TRANSLATION_TAGLINE = "### Automatically generated by repyhelper.py ###"


WARNING_LABEL = """
### THIS FILE WILL BE OVERWRITTEN!
### DO NOT MAKE CHANGES HERE, INSTEAD EDIT THE ORIGINAL SOURCE FILE
###
### If changes to the src aren't propagating here, try manually deleting this file. 
### Deleting this file forces regeneration of a repy translation

"""

ENCODING_STRING = """# -*- coding: utf-8 -*-"""

class TranslationError(Exception):
  """ An error occurred during translation """



#For keeping a truly shared context between translated files
shared_context = {}
def get_shared_context():
  """ Ensure all imported repy code has a common 'mycontext' dict """
  global shared_context
  return shared_context
  

# this specifies where the preprocessed files should end up.   By default, they
# will be written to the same directory as they are in.   If there is
# a relative path name, it will be written in sys.path[0]
_importcachedir = None

def set_importcachedir(newimportcachedir):
  """
  <Purpose>
    Repyhelper creates Python versions of repy files.   This function sets
    the location where those all files will be stored.   By default, files are 
    stored wherever they are found in the python path.   If a relative path
    name is specified, by default, files are instead stored in the first 
    directory in the Python path sys.path[0] (usually the current directory)
  
  <Arguments>
    newimportcachedir:
       The location where all files should be stored.   Use None to restore
       the default behavior

  <Exceptions>
    TypeError if the path is invalid.
    ValueError is thrown if the newimportcachedir isn't in the path
  
  <Side Effects>
    None.
  
  <Returns>
    None.
  """
  global _importcachedir

  # handle None...
  if newimportcachedir == None:
    _importcachedir = None
    return

  # else, is this a valid path?
  if type(newimportcachedir) != str:
    raise TypeError("Type of newimportcachedir '"+str(newimportcachedir)+"' is not a string")

  # If it's an empty string, assume it's '.'
  if newimportcachedir == '':
    newimportcachedir = '.'

  if not os.path.isdir(newimportcachedir):
    raise TypeError("Path given for newimportcachedir '"+str(newimportcachedir)+"' is not a directory")
    

  if newimportcachedir not in sys.path:
    raise ValueError, "The import cache dir '"+newimportcachedir+"' isn't in the Python path"

  # set the path...   We're done.
  _importcachedir = newimportcachedir





  
def set_shared_context(context):
  """
  <Purpose>
    Set the shared mycontext dictionary
  
  <Arguments>
    context:
      A dict to use as the new mycontext
  
  <Exceptions>
    TypeError if context is none
  
  <Side Effects>
    Creates a python file correspond to the repy file, overwriting previously 
    generated files that exists with that name
  
  <Returns>
    The name of the Python module that was created in the current directory. This
    string can be used with __import__ to import the translated module.  
  
  """
  global shared_context
  if context is None:
    raise TypeError("Context can't be none")
  shared_context = context
  
  
#Ensure the generated module has a safe name
# Can't use . in the name because import uses it for scope, so convert to _
def _get_module_name(repyfilename):
  head,tail = os.path.split(repyfilename)
  tail = tail.replace('.', '_')
  return os.path.join(head, tail)


def _translation_is_needed(repyfilename, generatedfile):
  """ Checks if generatedfile needs to be regenerated. Does several checks to 
  decide if generating generatedfilename based on repyfilename is a good idea.
    --does file already exist?
    --was it automatically generated?
    --was it generated from the same source file?
    --was the original modified since the last translation?
    
  """
  
  if not os.path.isfile(repyfilename):
    raise TranslationError("no such file:", repyfilename)
    
  if not os.path.isfile(generatedfile):
    return True
  
  #Read the first line
  try:
    fh = open(generatedfile, "r")
    first_line = fh.readline().rstrip()
    second_line = fh.readline().rstrip()
    current_line = ''
    for line in fh:
      current_line = line
    last_line = current_line
    fh.close()
  except IOError, e:
    raise TranslationError("Error opening old generated file: " + generatedfile + ": " + str(e))
  
  #Check to see if the file was generated by repyhelper, to prevent
  #clobbering a file that we didn't create
  if not first_line.startswith(ENCODING_STRING) or not second_line.startswith(TRANSLATION_TAGLINE):
    # it also could have been created by an earlier version of repyhelper.
    if not first_line.startswith(TRANSLATION_TAGLINE):
      raise TranslationError("File name exists but wasn't automatically generated: " + generatedfile)

  if not last_line.startswith(TRANSLATION_TAGLINE):
    # The file generation wasn't completed...   I think this means we should
    # silently regenerate (#617)
    return True
  
  #Check to see if the generated file has the same original source
  old_translation_path = first_line[len(TRANSLATION_TAGLINE):].strip()
  generated_abs_path = os.path.abspath(repyfilename)
  if old_translation_path != generated_abs_path:
    #It doesn't match, but the other file was also a translation! Regen then...
    return True
  
  #If we get here and modification time of orig is older than gen, this is still
  #a valid generation
  repystat = os.stat(repyfilename)
  genstat = os.stat(generatedfile)
  if repystat.st_mtime < genstat.st_mtime:
    return False
    
  return True


def _generate_python_file_from_repy(repyfilename, generatedfilename, shared_mycontext, callfunc, callargs):
  """ Generate a python module from a repy file so it can be imported
  The first line is TRANSLATION_TAGLINE, so it's easy to detect that
  the file was automatically generated
  
  """
    
  #Start the generation! Print out the header and portability stuff, then include
  #the original data and translations
  try:
    # Create path if it doesn't exist.
    # JAC: due to #814, we check for the empty directory too...
    if os.path.dirname(generatedfilename) != '' and not os.path.isdir(os.path.dirname(generatedfilename)):
      os.makedirs(os.path.dirname(generatedfilename))
    fh = open(generatedfilename, "w")
  except IOError, e:
    # this is likely a directory permissions error
    raise TranslationError("Cannot open file for translation '" + repyfilename + "': " + str(e))

  # always close the file
  try:
    print >> fh, ENCODING_STRING
    print >> fh, TRANSLATION_TAGLINE, os.path.abspath(repyfilename)
    print >> fh, WARNING_LABEL
    print >> fh, "from repyportability import *"
    print >> fh, "from repyportability import _context"
    print >> fh, "import repyhelper"
    if shared_mycontext:
      print >> fh, "mycontext = repyhelper.get_shared_context()"
    else:
      print >> fh, "mycontext = {}"
    print >> fh, "callfunc =", repr(callfunc)
    #Properly format the callargs list. Assume it only contains python strings
    print >> fh, "callargs =", repr(callargs) 
    print >> fh 
    _process_output_file(fh, repyfilename, generatedfilename)
    # append the TRANSLATION_TAGLINE so that we can see if the operation was
    # interrupted (#617)
    print >> fh 
    print >> fh, TRANSLATION_TAGLINE, os.path.abspath(repyfilename) 
  except IOError, e:
    raise TranslationError("Error translating file " + repyfilename + ": " + str(e))
  finally:
    fh.close()

def _process_output_file(outfh, filename, generatedfilename):
  """ Read filename and print it to outfh, except convert includes into calls to
  repyhelper.translate
  """
  try:
    repyfh = open(filename, "r")
    repyfiledata = repyfh.readlines()
    repyfh.close()
  except IOError, e:
    #Delete the partially translated file, to ensure this partial translation
    #doesn't get used
    try:
      os.remove(generatedfilename)
    except (IOError, OSError):
      pass
    raise TranslationError("Error opening " + filename + ": " + str(e))
  
  #Having read all the data, lets output it again, performing translations 
  #as needed
  for line in repyfiledata:
    #look for includes, and substitute them with calls to translate
    if line.startswith('include '):
      includename = line[len('include '):].strip()
      modulename = _get_module_name(includename)
      print >> outfh, "repyhelper.translate_and_import('" + includename + "')"
    else:      
      print >> outfh, line, #line includes a newline, so dont add another
  
  
def translate(filename, shared_mycontext=True, callfunc="import", callargs=None, force_overwrite=False):
  """
  <Purpose>
    Translate a Repy file into a valid python module that can be imported by
    the standard "import" statement. 
    
    Creates a python file correspond to the repy file in the current directory, 
    with all '.' in the name replaced with "_", and ".py" appended to it to 
    make it a valid python module name.
      Performs several checks to only perform a translation when necessary, and 
    to prevent accidentally clobbering other files.    
      The repyhelper and repyportability modules must be in the Python path for
    the translated files
      Note that the optional arguments used to set variables are only used 
    if the file is retranslated--otherwise they are ignored. To ensure they're 
    used, manually delete the translation to force regeneration
  
  <Arguments>
    repyfilename:
      A valid repy file name that exists in the Python path (sys.path).  If the 
      filename contains a directory separator, it is used instead of the path.
    shared_mycontext:
      Optional parameter whether or not the mycontext of this translation 
      should be shared, or the translation should have it's own. Default True
    callfunc:
      Optional parameter for what the callfunc of this translation should be.
      Should be valid python string. Default "import"
    callargs:
      A list of strings to use as the repy's "callargs" variable. Default empty
      list.
    force_overwrite:
      If set to True, will skip all file checks and just overwrite any file 
      with the same name as the generated file. Dangerous, so use cautiously. 
      Default False
      
  <Exceptions>
    TranslationError if there was an error during file generation
    ValueError if the file can't be found or directory is invalid
  
  <Side Effects>
    Creates a python file correspond to the repy file, overwriting previously 
    generated files that exists with that name
  
  <Returns>
    The name of the Python module that was created in the current directory. This
    string can be used with __import__ to import the translated module.
  """

  global _importcachedir

  filedir = None     # The directory the file is in.
  filenamewithpath = None    # The full path to the file including the filename.
  destdir = None     # where the file should be written when generated

  # If the file name contains a directory, honor that exactly...
  if filename != os.path.basename(filename): 
    # since the name contains a directory, that's the filename + path
    filenamewithpath = filename

    # I need to use the absolute path because python doesn't handle '..' in 
    # directory / module names
    filedir = os.path.abspath(os.path.dirname(filename))

    # write it to the first directory in the python path (by default)
    destdir = sys.path[0]

    # Let's verify these exist and if not exit...
    if not os.path.isdir(filedir):
      raise ValueError("In repyhelper, the directory '" + filedir + "' does not exist for file '"+filename+"'")
    if not os.path.isfile(filename):
      raise ValueError("In repyhelper, the file '" + filename + "' does not exist.")
    
  else:
    # Determine in which directory in the file is located (using the 
    # Python path)
    for pathdir in sys.path:
      possiblefilenamewithpath = os.path.join(pathdir, filename)
      if os.path.isfile(possiblefilenamewithpath):
        filenamewithpath = possiblefilenamewithpath
        filedir = pathdir
        break

    # make sure we found something.
    if filenamewithpath is None:
      raise ValueError("File " + filename + " does not exist in the Python path.")
    # write it where it was (by default)
    destdir = filedir

 
  if callargs is None:
    callargs = []

  # expand the name from foo.repy to foo_repy (change '.' to '_')
  modulenameonly = _get_module_name(os.path.basename(filename))
  generatedfilenameonly = modulenameonly + ".py"

  # if it shouldn't be in the default location, put it in the correct dir
  if _importcachedir != None:
    destdir = _importcachedir

  # let's generate it
  generatedfilenamewithpath = os.path.join(destdir, generatedfilenameonly)
  
  if force_overwrite or _translation_is_needed(filenamewithpath, generatedfilenamewithpath):
    _generate_python_file_from_repy(filenamewithpath, generatedfilenamewithpath, shared_mycontext, callfunc, callargs)

  # return the name so that we can import it
  return modulenameonly



def translate_and_import(filename, shared_mycontext=True, callfunc="import", callargs=None, 
                         force_overwrite=False, preserve_globals=False):
  """
  <Purpose>
    Translate a repy file to python (see repyhelper.translate), but also import
    it to the current global namespace. This import behaves similarly to python's 
    "from <module> import *", to mimic repy's include semantics, in which
    included files are in-lined. Globals starting with "_" aren't imported. 
    
  <Arguments>
    filename:
      The name of the repy filename to translate and import
    shared_mycontext:
      Whether or not the mycontext of this translation should be shared, or
      the translation should have it's own. Default True
    callfunc:
      Optional parameter for what the callfunc of this translation should be.
      Should be valid python string. Deafault "import"
    callargs:
      A list of strings to use as the repy's "callargs" variable. Default empty list.
    force_overwrite:
      If set to True, will skip all file checks and just overwrite any file with
      the same name as the generated file. Dangerous, so use cautiously. 
      Default False
    preserve_globals:
      Whether or not to preserve globals in the current namespace.
      False means globals in current context will get overwritten by globals
      in filename if the names clash, True means to keep current globals in the
      event of a collision. Default False
  
  <Exceptions>
    TranslationError if there was an error during translation
  
  <Side Effects>
    Creates/updates a python module corresponding to the repy file argument,
    and places references to that module in the current global namespace 
  
  <Returns>
    None
  
  """
  
  modulename = translate(filename, shared_mycontext, callfunc, callargs, force_overwrite)
  _import_file_contents_to_caller_namespace(modulename, preserve_globals)


#List of globals to skip; we want to make sure to ignore these when
#inserting the imported module's vars into the caller's namespace
# Could also blacklist the repyportability things here....
GLOBAL_VARS_BLACKLIST = set(['mycontext', 'callfunc', 'callargs', 'repyhelper'])

def _import_file_contents_to_caller_namespace(modulename, preserve_globals):
  """
    Responsible for importing modulename, and taking the contents and 
  injecting them into the caller's namespace. If overwrite_globals is set to 
  false, then globals that are already defined in the callers namespace get 
  skipped.
  
  Doesn't include objects that start with "_"
  
  BIG HACK WARNING:
    The idea here is to use inspect to get a handle to the caller's module, and 
  start inserting elements from the imported module into the caller's global 
  namespace. This is to simulate the repy behavior of inlining includes, which
  puts everything in the same namespace.

  """
  #DEBUG
  #caller_file = os.path.basename(inspect.currentframe().f_back.f_back.f_code.co_filename)
  #print "*** IMPORTNG", modulename, "INTO FILE", caller_file, "***"
  

  #Let python handle the initial import
  import_module = __import__(modulename)
  
  #To get a handle on the caller's module navigate back up the stack:
  #Go back 2 frames: back to translate_and_import, and another to
  #whoever called that
  caller_globals = inspect.currentframe().f_back.f_back.f_globals
  

  #Now iterate over the import's members, and insert them into the
  #caller's namespace
  for name,definition in inspect.getmembers(import_module):
    
    #like normal python from imports, don't import names starting with "_"
    if name.startswith('_'):
      continue
    
    #Skip blacklisted items
    if name in GLOBAL_VARS_BLACKLIST:
      continue
    
    #skip already defined vars if told to do so
    if name in caller_globals and preserve_globals:
      continue
      
    caller_globals[name] = definition

