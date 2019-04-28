package edu.polytechnique;

import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

public class TestSuiteWrapper {
  public final static int DEFAULT_TIMEOUT = 5;
  
  public static interface UserCode<T, U> {
    public T run(U data) throws Exception;
  }

  public static abstract class UserProc implements UserCode<Void, Void> {
    @Override
    final public Void run(Void v) throws Exception {
      this.run();
      return null;
    }
    
    public abstract void run() throws Exception;
  }
  
  public static <T, U> T run(UserCode<T, U> code, U data, int timeout)
      throws TestSuiteError
  {
    ExecutorService executor = Executors.newSingleThreadExecutor();
    Future<T> future = executor.submit(new Callable<T>() {
      @Override
      public T call() throws Exception {
        return code.run(data);
      }
    });

    try {
      return future.get(timeout, TimeUnit.SECONDS);
    } catch (TimeoutException e) {
      throw new TestSuiteError("your code reached the time limit", e);
    } catch (ExecutionException e) {
      throw new TestSuiteError("your code raised an exception", e.getCause());
    } catch (Exception e) {
      throw new TestSuiteError("internal error. report.", e.getCause());
    } finally {
      executor.shutdown();
    }
  }

  public static <T, U> T run(UserCode<T, U> code, U data)
      throws TestSuiteError
  {
    return run(code, data, DEFAULT_TIMEOUT);
  }

  public static <T> T run(UserCode<T, Void> code, int timeout)
      throws TestSuiteError
  {
    return run(code, null, timeout);
  }

  public static <T> T run(UserCode<T, Void> code)
      throws TestSuiteError
  {
    return run(code, null);
  }

  public static void run(UserProc proc, int timeout)
      throws TestSuiteError
  {
    run(proc, null, timeout);
  }

  public static void run(UserProc proc)
      throws TestSuiteError
  {
    run(proc, null);
  }
}
