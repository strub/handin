package edu.polytechnique;

import java.util.Objects;
import java.util.concurrent.ExecutionException;

public abstract class AbstractTestSuite implements ITestSuite {
  @Override
  public String getTestName() {
    return this.getClass().getName().replace('_', ' ');
  }

  public <T> void check_eq(T submitted, T expected) throws TestSuiteError, ExecutionException {
    final boolean success = Objects.equals(expected, submitted);

    if (!success) {
      final String s_submitted = String.valueOf(submitted);
      final String s_expected  = String.valueOf(expected);

      throw new TestSuiteError(String.format(
              "%s: expecting [%s], got [%s]",
              this.getTestName(), s_expected, s_submitted));
    }
  }
}
