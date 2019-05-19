package edu.polytechnique;

public class TestSuiteError extends Exception {
  private static final long serialVersionUID = -153258057745895163L;

  private final String    error;
  private final Throwable exn;

  public TestSuiteError(String message, Object... args) {
    super(message);
    this.error = String.format(message, args);
    this.exn   = null;
  }

  public TestSuiteError(String message, Throwable exn) {
    super(message, exn);
    this.error = message;
    this.exn   = exn;
  }

  public String getUserError() {
    return this.error;
  }
  
  public Throwable getUserExn() {
    return this.exn;
  }
}
