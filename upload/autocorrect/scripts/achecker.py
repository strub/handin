#! /usr/bin/env python3

# --------------------------------------------------------------------
import sys, os, re, subprocess as sp, logging, tempfile, shutil

# --------------------------------------------------------------------
class TestSuiteError(Exception):
    pass

# --------------------------------------------------------------------
class TestSuiteRunner(object):
    RUNNER     = 'edu.polytechnique.TestSuiteRunner'

    def __init__(self, workdir, entry):
        self._entry   = entry
        self._workdir = os.path.realpath(workdir)
        self._clazz   = tempfile.mkdtemp()
        self._lib     = os.path.join(workdir, 'lib' )
        self._src     = os.path.join(workdir, 'src' )
        self._test    = os.path.join(workdir, 'test')

    entry   = property(lambda self : self._entry)
    workdir = property(lambda self : self._workdir)

    def _compile_lib(self):
        logging.info('compiling libsupport...')
        try:
            lib = [os.path.join(dp, f) \
                       for dp, dn, filenames in os.walk(self._lib) \
                       for f in filenames if os.path.splitext(f)[1] == '.java']
            if not lib:
                return
            cmd = ['javac', '-sourcepath', self._lib, '-d', self._clazz] + lib
            sp.check_call(cmd, cwd = self.workdir)
        except (OSError, sp.CalledProcessError) as e:
            logging.error('cannot compile libsupport: %s' % (e,))
            raise TestSuiteError
        for filename in os.listdir(self._lib):
            if os.path.splitext(filename)[1] == '.jar':
                shutil.copy(
                    os.path.join(self._lib, filename),
                    os.path.join(self._clazz, filename))
        logging.info('...done')

    def _compile_project(self):
        logging.info('compiling your files (with test-suite)...')
        try:
            java = []
            for root, dirs, files in os.walk(self._src):
                for filename in files:
                    if os.path.splitext(filename)[1].lower() == '.java':
                        java.append(os.path.join(root, filename))
            cmd  = ['javac', '-cp', '%s/*:%s:.' % (self._test, self._clazz),
                    '-d', self._clazz, '-sourcepath', '%s:%s' % (self._src, self._test)]
            cmd += java
            sp.check_call(cmd, cwd = self.workdir)
        except sp.CalledProcessError as e:
            logging.error('cannot compile your project')
            raise TestSuiteError
        logging.info('...done')

    def _run_tests(self):
        logging.info('executing test...')
        try:
            cmd  = ['java', '-cp', '%s/*:%s:.' % (self._test, self._clazz)]
            cmd += [self.RUNNER, self.entry]
            sp.check_call(cmd, cwd = self.workdir)
        except sp.CalledProcessError as e:
            logging.error('failure: %s' % (e,))
            raise TestSuiteError
        logging.info('...done')

    def run(self):
        self._compile_lib()
        self._compile_project()
        self._run_tests()

# --------------------------------------------------------------------
def _main():
    os.environ['JAVA_TOOL_OPTIONS'] = '-Dfile.encoding=UTF8'
    if len(sys.argv)-1 != 2:
        exit(1)
    try:
        TestSuiteRunner(*sys.argv[1:]).run()
    except TestSuiteError:
        exit(1)

# --------------------------------------------------------------------
if __name__ == '__main__':
    _main()
