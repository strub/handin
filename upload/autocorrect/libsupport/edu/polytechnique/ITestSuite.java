package edu.polytechnique;

public interface ITestSuite {
  public String getTestName();

  public void run() throws TestSuiteError;
}
