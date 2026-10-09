import io.brunnodev.ledger.Journal;
import java.nio.file.*;
import java.time.Instant;
import java.util.List;

public class JournalCheck {
  public static void main(String[] args) throws Exception {
    Path file = Files.createTempFile("journal", ".log");
    try {
      var journal = new Journal(file);
      var entry =
          new Journal.Entry(
              "one",
              Instant.now(),
              List.of(new Journal.Line("a", "BRL", -123), new Journal.Line("b", "BRL", 123)));
      assert journal.append(entry);
      assert !journal.append(entry);
      assert journal.balances().get("b:BRL") == 123;
      boolean blocked = false;
      try {
        new Journal.Entry(
            "bad",
            Instant.now(),
            List.of(new Journal.Line("a", "BRL", 1), new Journal.Line("b", "BRL", 1)));
      } catch (IllegalArgumentException e) {
        blocked = true;
      }
      assert blocked;
      Files.writeString(file, Files.readString(file).replace("b,BRL,123", "b,BRL,124"));
      blocked = false;
      try {
        journal.balances();
      } catch (IllegalStateException e) {
        blocked = true;
      }
      assert blocked;
    } finally {
      Files.deleteIfExists(file);
    }
  }
}
