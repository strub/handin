package edu.polytechnique;

import java.util.concurrent.ExecutionException;

public interface ITestSuite {
  public String getTestName();

  public void run() throws TestSuiteError, ExecutionException;
}
