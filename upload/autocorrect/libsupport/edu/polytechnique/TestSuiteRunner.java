package edu.polytechnique;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.logging.Logger;

public class TestSuiteRunner {
  private static String getTS() {
    return new SimpleDateFormat("yyyyMMdd_HHmmss")
      .format(Calendar.getInstance().getTime());
  }

  public static void main(String[] args) throws Exception {
    System.setProperty(
        "java.util.logging.SimpleFormatter.format", 
        "[%4$-8s] [%1$tF %1$tT] %5$s%6$s%n");
    
    Logger logger = Logger.getLogger("edu.polytechnique");

    if (args.length != 1) {
      System.err.format("Usage: TestSuiteRunner <class-name>\n");
      System.exit(1);
    }

    final String className = args[0];

    final ClassLoader loader = TestSuiteRunner.class.getClassLoader();
    final Class<?> clazz = loader.loadClass(className);
    final ITestSuite tester = (ITestSuite) clazz.newInstance();

    // Move to log4j at some point...
    boolean failure = false;
    
    logger.info("test-name: " + tester.getTestName());
    logger.info("test-start-time: " + getTS());
    try {
      tester.run();
      logger.info("test-success");
    } catch (TestSuiteError e) {
      logger.severe("test-failure: " + e.getUserError());
      if (e.getUserExn() != null) {
        StringWriter sw = new StringWriter();
        PrintWriter  pw = new PrintWriter(sw);
        e.getUserExn().printStackTrace(pw);
        logger.severe(sw.toString());
      }
      failure = true;
    }
    logger.info("test-end-time: " + getTS());

    System.exit(failure ? 1 : 0);
  }
}
