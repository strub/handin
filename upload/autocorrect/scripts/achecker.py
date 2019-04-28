#! /usr/bin/env python3

# --------------------------------------------------------------------
import sys, os, re, subprocess as sp, logging, tempfile

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
        self._lib     = os.path.join(workdir, 'lib')
        self._src     = os.path.join(workdir, 'src')
        self._java    = ['java', '-cp', '%s:.' % (self._clazz,)]

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
            print(lib)
            cmd = ['javac', '-sourcepath', self._lib, '-d', self._clazz] + lib
            sp.check_call(cmd, cwd = self.workdir)
        except (OSError, sp.CalledProcessError) as e:
            logging.error('cannot compile libsupport: %s' % (e,))
            raise TestSuiteError
        logging.info('...done')

    def _compile_project(self):
        logging.info('compiling your files (with test-suite)...')
        try:
            java = os.listdir(self._src)
            java = [x for x in java \
                       if os.path.splitext(x)[1].lower() == '.java']
            java = [os.path.join(self._src, x) for x in java]
            cmd  = ['javac', '-cp', self._clazz, '-sourcepath', self._src]
            cmd += java
            sp.check_call(cmd, cwd = self.workdir)
        except sp.CalledProcessError as e:
            logging.error('cannot compile your project')
            raise TestSuiteError
        logging.info('...done')
        
    def _run_tests(self):
        logging.info('executing test...')
        try:
            cmd = self._java + [self.RUNNER, self._test]
            sp.check_call(cmd, cwd = self.workdir)
        except sp.CalledProcessError as e:
            logging.error('failure: %s' % (e,))
            raise TestSuiteError
        logging.info('...done')

    def run(self):
        self._compile_lib()
        os.system('find ' + self._clazz)
        self._compile_project()
        self._run_tests()

# --------------------------------------------------------------------
def _main():
    if len(sys.argv)-1 != 2:
        exit(1)
    try:
        TestSuiteRunner(*sys.argv[1:]).run()
    except TestSuiteError:
        exit(1)

# --------------------------------------------------------------------
if __name__ == '__main__':
    _main()
